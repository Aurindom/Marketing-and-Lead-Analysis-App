import contextlib
import os
import re
import threading
import yaml
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
from src.models.prospect import ProspectState, ErrorRecord

_playwright_disabled = False
_playwright_lock = threading.Lock()


class CrossDomainRedirectError(Exception):
    pass


class PlaywrightTimeoutError(Exception):
    pass


def _load_enrichment_config() -> dict:
    path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "..", "config", "pipeline_config.yaml"
    ))
    with open(path) as f:
        return yaml.safe_load(f)["enrichment"]


HEADERS = {"User-Agent": _load_enrichment_config()["user_agent"]}

TIMEOUT = 15
CONTACT_FORM_PATH_TIMEOUT = 10
MAX_CONTACT_FORM_PATHS = 4
MIN_CONTENT_CHARS = 200
JS_SHELL_WORD_FLOOR = 120
ACCESS_DENIED_STATUS_CODES = {403, 429, 503}
JS_FRAMEWORK_HINTS = (
    "react", "next", "nuxt", "vue", "angular", "vite", "webpack",
    "gatsby", "svelte", "astro", "chunk", "hydrate", "__next",
)

BUILDER_FORM_SELECTORS = (
    ".wpforms-form",
    ".wpcf7",
    ".gform_wrapper",
    ".nf-form-cont",
    ".fluentform",
    ".elementor-form",
    ".hs-form",
)
EMBED_FORM_PROVIDERS = (
    "typeform.com",
    "jotform.com",
    "jotformpro.com",
    "wufoo.com",
    "formstack.com",
    "hubspot.com/meetings",
    "hs-scripts.com",
    "hsforms.net",
)
DIVI_FORM_CLASS_PATTERN = re.compile(r"\bet_pb_contact(?:_form(?:_\d+)?)?(?:_container)?\b", re.IGNORECASE)
GRAVITY_FORM_CLASS_PATTERN = re.compile(r"\bgform_wrapper(?:_\d+)?\b", re.IGNORECASE)
CONTACT_FORM_FALLBACK_PATHS = (
    "/contact-us",
    "/contact",
    "/request-an-appointment",
    "/book",
)
NAV_LINK_CONTACT_KEYWORDS = ("contact", "appointment", "schedule", "book", "request", "new-patient", "reach-us")
MAX_NAV_LINK_PATHS = 3
INTERNAL_JS_SHELL_WORD_FLOOR = 30
PLUGIN_FORM_SCRIPT_HINTS = ("contact-form-7", "metform", "caldera-forms", "formidable", "quform")
PLUGIN_FORM_WAIT_SELECTOR = "form, " + ", ".join(BUILDER_FORM_SELECTORS)


def run(state: ProspectState) -> ProspectState:
    if not state.candidate.website:
        state.errors.append(ErrorRecord(
            node="enrichment",
            error_type="no_website",
            message=f"No website for {state.candidate.name}"
        ))
        return state

    url = _normalize_url(state.candidate.website)
    final_url = url
    fetched_with_playwright = False
    state.playwright_attempted = False
    state.playwright_used = False
    state.blocked_http_status = None
    state.contact_form_page = None
    state.contact_page_url = None

    try:
        html, final_url = _fetch_homepage(url)
    except Exception as fetch_exc:
        status_code = _status_code_from_fetch_error(fetch_exc)
        if status_code:
            state.blocked_http_status = status_code
        if _should_try_playwright_on_fetch_error(fetch_exc):
            try:
                state.playwright_attempted = True
                html = _fetch_with_playwright(url)
                fetched_with_playwright = True
                state.playwright_used = True
            except Exception as browser_exc:
                state.errors.append(ErrorRecord(
                    node="enrichment",
                    error_type=type(fetch_exc).__name__,
                    message=str(fetch_exc),
                ))
                state.errors.append(ErrorRecord(
                    node="enrichment",
                    error_type="playwright_fallback_failed",
                    message=str(browser_exc),
                ))
                return state
        else:
            state.errors.append(ErrorRecord(
                node="enrichment",
                error_type=type(fetch_exc).__name__,
                message=str(fetch_exc),
            ))
            return state

    try:
        soup = BeautifulSoup(html, "lxml")
        _apply_soup_to_state(state, soup)
        if state.has_form_tag:
            state.contact_form_page = "homepage"
    except Exception as parse_exc:
        state.errors.append(ErrorRecord(
            node="enrichment",
            error_type=type(parse_exc).__name__,
            message=str(parse_exc),
        ))
        return state

    if (
        not fetched_with_playwright
        and _needs_browser_fallback(
            state.raw_text,
            state.detected_scripts,
            state.page_title,
            state.meta_description,
        )
    ):
        try:
            state.playwright_attempted = True
            html_browser = _fetch_with_playwright(url)
            soup_browser = BeautifulSoup(html_browser, "lxml")
            _apply_soup_to_state(state, soup_browser)
            state.playwright_used = True
            if state.has_form_tag:
                state.contact_form_page = "homepage"
        except Exception as browser_exc:
            state.errors.append(ErrorRecord(
                node="enrichment",
                error_type="playwright_fallback_failed",
                message=str(browser_exc),
            ))

    if not state.has_form_tag:
        _enrich_contact_form_from_internal_paths(state, final_url)

    if state.has_form_tag:
        state.contact_form_status = "found"
    elif state.contact_form_check_had_errors:
        state.contact_form_status = "unknown"
    else:
        state.contact_form_status = "missing"

    return state


def _normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def _fetch(url: str) -> str:
    return _fetch_response(url).text


def _fetch_homepage(url: str) -> tuple[str, str]:
    response = _fetch_response(url)
    return response.text, str(response.url)


def _fetch_response(url: str, timeout: int = TIMEOUT) -> httpx.Response:
    url = _normalize_url(url)

    with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response


def _fetch_with_playwright(url: str) -> str:
    global _playwright_disabled
    with _playwright_lock:
        if not _is_playwright_enabled():
            _playwright_disabled = True
            raise RuntimeError("Playwright disabled by PLAYWRIGHT_ENABLED=false")

        if _playwright_disabled:
            raise RuntimeError("Playwright disabled after previous launch failure")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            _playwright_disabled = True
            raise RuntimeError("Playwright is not installed in this environment") from exc

        try:
            with open(os.devnull, "w", encoding="utf-8") as devnull, contextlib.redirect_stderr(devnull):
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    try:
                        page = browser.new_page()
                        page.goto(url, wait_until="networkidle", timeout=25000)
                        return page.content()
                    finally:
                        browser.close()
        except (PermissionError, OSError) as exc:
            _playwright_disabled = True
            raise RuntimeError(f"Playwright launch failed: {exc}") from exc


def _playwright_fetch_checked(url: str, base_hostname: str) -> str | None:
    global _playwright_disabled
    with _playwright_lock:
        if not _is_playwright_enabled():
            _playwright_disabled = True
            raise RuntimeError("Playwright disabled by PLAYWRIGHT_ENABLED=false")

        if _playwright_disabled:
            raise RuntimeError("Playwright disabled after previous launch failure")

        try:
            from playwright.sync_api import sync_playwright, TimeoutError as _PWTimeout
        except ImportError as exc:
            _playwright_disabled = True
            raise RuntimeError("Playwright is not installed in this environment") from exc

        try:
            with open(os.devnull, "w", encoding="utf-8") as devnull, contextlib.redirect_stderr(devnull):
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    try:
                        page = browser.new_page()
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        except _PWTimeout as exc:
                            raise PlaywrightTimeoutError("domcontentloaded timed out") from exc
                        if not _is_same_domain(page.url, base_hostname):
                            raise CrossDomainRedirectError(page.url)
                        stage1_html = page.content()
                        stage1_soup = BeautifulSoup(stage1_html, "lxml")
                        if _is_internal_js_shell(stage1_soup):
                            try:
                                page.goto(url, wait_until="networkidle", timeout=25000)
                                if not _is_same_domain(page.url, base_hostname):
                                    raise CrossDomainRedirectError(page.url)
                                return page.content()
                            except _PWTimeout:
                                return stage1_html
                        return stage1_html
                    finally:
                        browser.close()
        except (CrossDomainRedirectError, PlaywrightTimeoutError):
            raise
        except (PermissionError, OSError) as exc:
            _playwright_disabled = True
            raise RuntimeError(f"Playwright launch failed: {exc}") from exc


def _playwright_fetch_plugin_targeted(url: str, base_hostname: str) -> str:
    global _playwright_disabled
    with _playwright_lock:
        if not _is_playwright_enabled():
            _playwright_disabled = True
            raise RuntimeError("Playwright disabled by PLAYWRIGHT_ENABLED=false")

        if _playwright_disabled:
            raise RuntimeError("Playwright disabled after previous launch failure")

        try:
            from playwright.sync_api import sync_playwright, TimeoutError as _PWTimeout
        except ImportError as exc:
            _playwright_disabled = True
            raise RuntimeError("Playwright is not installed in this environment") from exc

        try:
            with open(os.devnull, "w", encoding="utf-8") as devnull, contextlib.redirect_stderr(devnull):
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    try:
                        page = browser.new_page()
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=15000)
                        except _PWTimeout as exc:
                            raise PlaywrightTimeoutError("domcontentloaded timed out") from exc
                        if not _is_same_domain(page.url, base_hostname):
                            raise CrossDomainRedirectError(page.url)
                        try:
                            page.wait_for_selector(PLUGIN_FORM_WAIT_SELECTOR, timeout=5000)
                        except _PWTimeout:
                            pass
                        return page.content()
                    finally:
                        browser.close()
        except (CrossDomainRedirectError, PlaywrightTimeoutError):
            raise
        except (PermissionError, OSError) as exc:
            _playwright_disabled = True
            raise RuntimeError(f"Playwright launch failed: {exc}") from exc


def _is_playwright_enabled() -> bool:
    value = (os.getenv("PLAYWRIGHT_ENABLED") or "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _apply_soup_to_state(state: ProspectState, soup: BeautifulSoup) -> None:
    state.detected_scripts = _extract_scripts(soup)
    state.detected_hrefs = _extract_hrefs(soup)
    state.page_title = _extract_title(soup)
    state.meta_description = _extract_meta_description(soup)
    state.has_form_tag = _has_form_tag(soup)
    state.has_email_input = _has_email_input(soup)
    state.has_submit_control = _has_submit_control(soup)
    state.raw_text = _extract_text(soup)


def _enrich_contact_form_from_internal_paths(state: ProspectState, homepage_url: str) -> None:
    origin = _origin_from_url(homepage_url)
    if origin is None:
        return
    base_hostname = urlparse(origin).hostname
    if not base_hostname:
        return

    checked: set[str] = set()
    homepage_used_playwright = state.playwright_used

    def _set_reason(reason: str) -> None:
        if state.internal_contact_check_reason is None:
            state.internal_contact_check_reason = reason

    def _try_path(path: str, allow_playwright_escalation: bool) -> bool:
        target_url = f"{origin.rstrip('/')}{path}"
        resolved_url = target_url
        http_blocked = False
        html = None

        if homepage_used_playwright:
            try:
                html = _playwright_fetch_checked(target_url, base_hostname)
            except CrossDomainRedirectError:
                _set_reason("cross_domain_redirect")
                return False
            except PlaywrightTimeoutError:
                _set_reason("playwright_timeout")
                state.contact_form_check_had_errors = True
                return False
            except RuntimeError:
                _set_reason("playwright_error")
                state.contact_form_check_had_errors = True
                return False
            except Exception:
                _set_reason("playwright_error")
                state.contact_form_check_had_errors = True
                return False
            if html is None:
                return False
        else:
            try:
                response = _fetch_response(target_url, timeout=CONTACT_FORM_PATH_TIMEOUT)
                if not _is_same_domain(str(response.url), base_hostname):
                    return False
                resolved_url = str(response.url)
                html = response.text
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {404, 410}:
                    return False
                http_blocked = True
            except httpx.ConnectError:
                http_blocked = True
            except Exception:
                state.contact_form_check_had_errors = True
                return False

            if http_blocked:
                if not allow_playwright_escalation:
                    _set_reason("blocked")
                    state.contact_form_check_had_errors = True
                    return False
                try:
                    html = _playwright_fetch_checked(target_url, base_hostname)
                except CrossDomainRedirectError:
                    _set_reason("cross_domain_redirect")
                    return False
                except PlaywrightTimeoutError:
                    _set_reason("playwright_timeout")
                    state.contact_form_check_had_errors = True
                    return False
                except RuntimeError:
                    _set_reason("playwright_error")
                    state.contact_form_check_had_errors = True
                    return False
                except Exception:
                    _set_reason("playwright_error")
                    state.contact_form_check_had_errors = True
                    return False
                if html is None:
                    _set_reason("cross_domain_redirect")
                    return False
                state.internal_playwright_used = True

        if state.contact_page_url is None:
            state.contact_page_url = resolved_url

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            state.contact_form_check_had_errors = True
            return False

        _merge_internal_evidence(state, soup)

        if not _has_form_tag(soup):
            if (
                not homepage_used_playwright
                and not http_blocked
                and allow_playwright_escalation
                and _is_internal_js_shell(soup)
            ):
                state.internal_js_shell_detected = True
                try:
                    html_pw = _playwright_fetch_checked(target_url, base_hostname)
                except CrossDomainRedirectError:
                    _set_reason("cross_domain_redirect")
                    return False
                except PlaywrightTimeoutError:
                    _set_reason("playwright_timeout")
                    state.contact_form_check_had_errors = True
                    return False
                except RuntimeError:
                    _set_reason("playwright_error")
                    state.contact_form_check_had_errors = True
                    return False
                except Exception:
                    _set_reason("playwright_error")
                    state.contact_form_check_had_errors = True
                    return False
                if html_pw is None:
                    return False
                try:
                    soup = BeautifulSoup(html_pw, "lxml")
                except Exception:
                    state.contact_form_check_had_errors = True
                    return False
                if not _has_form_tag(soup):
                    return False
                state.internal_playwright_used = True
                _merge_internal_evidence(state, soup)
            elif (
                not homepage_used_playwright
                and not http_blocked
                and allow_playwright_escalation
                and _has_plugin_markers(soup)
            ):
                state.internal_plugin_playwright_attempted = True
                try:
                    html_pw = _playwright_fetch_plugin_targeted(target_url, base_hostname)
                except CrossDomainRedirectError:
                    _set_reason("cross_domain_redirect")
                    return False
                except PlaywrightTimeoutError:
                    _set_reason("plugin_markers_only")
                    return False
                except RuntimeError:
                    _set_reason("plugin_markers_only")
                    return False
                except Exception:
                    _set_reason("plugin_markers_only")
                    return False
                try:
                    soup = BeautifulSoup(html_pw, "lxml")
                except Exception:
                    _set_reason("plugin_markers_only")
                    return False
                if not _has_form_tag(soup):
                    _set_reason("plugin_markers_only")
                    return False
                state.internal_plugin_playwright_used = True
                _merge_internal_evidence(state, soup)
            else:
                if _has_plugin_markers(soup):
                    _set_reason("plugin_markers_only")
                else:
                    _set_reason("no_form_static")
                return False

        state.has_form_tag = True
        state.has_email_input = state.has_email_input or _has_email_input(soup)
        state.has_submit_control = state.has_submit_control or _has_submit_control(soup)
        state.contact_form_page = path
        return True

    for path in CONTACT_FORM_FALLBACK_PATHS[:MAX_CONTACT_FORM_PATHS]:
        checked.add(path)
        if _try_path(path, allow_playwright_escalation=True):
            return

    for path in _extract_contact_nav_paths(state.detected_hrefs, origin, checked)[:MAX_NAV_LINK_PATHS]:
        if _try_path(path, allow_playwright_escalation=False):
            return


def _merge_internal_evidence(state: ProspectState, soup: BeautifulSoup) -> None:
    new_scripts = _extract_scripts(soup)
    existing = set(state.detected_scripts)
    for s in new_scripts:
        if s not in existing:
            state.detected_scripts.append(s)
            existing.add(s)

    new_hrefs = _extract_hrefs(soup)
    existing_hrefs = set(state.detected_hrefs.split())
    additions = [h for h in new_hrefs.split() if h not in existing_hrefs]
    if additions:
        state.detected_hrefs = (state.detected_hrefs + " " + " ".join(additions)).strip()

    new_text = _extract_text(soup)
    if new_text:
        state.raw_text = ((state.raw_text or "") + " " + new_text).strip()


def _extract_contact_nav_paths(hrefs_str: str, origin: str, already_checked: set[str]) -> list[str]:
    base_hostname = (urlparse(origin).hostname or "").lower()
    paths: list[str] = []
    seen: set[str] = set()
    for href in hrefs_str.split():
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        if href.startswith("http"):
            parsed = urlparse(href)
            if (parsed.hostname or "").lower() != base_hostname:
                continue
            path = parsed.path.rstrip("/") or "/"
        elif href.startswith("/"):
            path = href.split("?")[0].split("#")[0].rstrip("/") or "/"
        else:
            clean = href.split("?")[0].split("#")[0].strip()
            if not clean:
                continue
            path = "/" + clean.lstrip("/").rstrip("/")
            if not path:
                path = "/"
        if not path or path in already_checked or path in seen:
            continue
        if any(kw in path.lower() for kw in NAV_LINK_CONTACT_KEYWORDS):
            seen.add(path)
            paths.append(path)
        if len(paths) >= MAX_NAV_LINK_PATHS:
            break
    return paths


def _is_internal_js_shell(soup: BeautifulSoup) -> bool:
    text = " ".join(soup.get_text(separator=" ").split())
    if len(text.split()) >= INTERNAL_JS_SHELL_WORD_FLOOR:
        return False
    scripts = " ".join(tag.get("src", "") for tag in soup.find_all("script")).lower()
    return any(hint in scripts for hint in JS_FRAMEWORK_HINTS)


def _origin_from_url(url: str) -> str | None:
    parsed = urlparse(_normalize_url(url))
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_same_domain(url: str, base_hostname: str) -> bool:
    candidate_hostname = urlparse(url).hostname
    if not candidate_hostname:
        return False

    candidate = candidate_hostname.lower()
    base = base_hostname.lower()
    return candidate == base or candidate.endswith(f".{base}") or base.endswith(f".{candidate}")


def _should_try_playwright_on_fetch_error(error: Exception) -> bool:
    status_code = _status_code_from_fetch_error(error)
    return bool(status_code and status_code in ACCESS_DENIED_STATUS_CODES)


def _status_code_from_fetch_error(error: Exception) -> int | None:
    if not isinstance(error, httpx.HTTPStatusError):
        return None
    if error.response is None:
        return None
    return error.response.status_code


def _needs_browser_fallback(
    raw_text: str | None,
    scripts: list[str],
    title: str | None,
    meta_description: str | None,
) -> bool:
    text = raw_text or ""
    if len(text) < MIN_CONTENT_CHARS:
        return True

    word_count = len(text.split())
    if word_count >= JS_SHELL_WORD_FLOOR:
        return False

    js_text = " ".join(scripts).lower()
    shell_context = " ".join([js_text, (title or "").lower(), (meta_description or "").lower()])
    return any(hint in shell_context for hint in JS_FRAMEWORK_HINTS)


def _extract_text(soup: BeautifulSoup) -> str:
    # Work on a copy so callers can continue using the original DOM for
    # form/shell detection and script extraction.
    soup_copy = BeautifulSoup(str(soup), "lxml")
    for tag in soup_copy(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup_copy.get_text(separator=" ").split())


def _extract_scripts(soup: BeautifulSoup) -> list[str]:
    sources = []
    for tag in soup.find_all("script"):
        src = tag.get("src", "")
        if src:
            sources.append(src)
        inline = tag.string or ""
        if inline.strip():
            sources.append(inline.strip()[:300])
    return sources


def _extract_hrefs(soup: BeautifulSoup) -> str:
    hrefs = []
    for tag in soup.find_all("a", href=True):
        hrefs.append(tag["href"])
    for tag in soup.find_all("iframe", src=True):
        hrefs.append(tag["src"])
    return " ".join(hrefs)


def _has_form_tag(soup: BeautifulSoup) -> bool:
    if soup.find("form") is not None:
        return True
    if _has_divi_form_marker(soup):
        return True
    if _has_gravityform_marker(soup):
        return True
    if any(soup.select_one(selector) is not None for selector in BUILDER_FORM_SELECTORS):
        return True
    return _has_embed_form_provider(soup)


def _has_embed_form_provider(soup: BeautifulSoup) -> bool:
    for tag in soup.find_all("iframe", src=True):
        src = tag["src"].lower()
        if any(provider in src for provider in EMBED_FORM_PROVIDERS):
            return True
    for tag in soup.find_all("script", src=True):
        src = tag["src"].lower()
        if any(provider in src for provider in EMBED_FORM_PROVIDERS):
            return True
    return False


def _has_divi_form_marker(soup: BeautifulSoup) -> bool:
    for tag in soup.find_all(class_=True):
        classes = tag.get("class", [])
        if not classes:
            continue
        if DIVI_FORM_CLASS_PATTERN.search(" ".join(classes)):
            return True
    return False


def _has_gravityform_marker(soup: BeautifulSoup) -> bool:
    for tag in soup.find_all(class_=True):
        classes = tag.get("class", [])
        if not classes:
            continue
        if GRAVITY_FORM_CLASS_PATTERN.search(" ".join(classes)):
            return True
    return False


def _has_plugin_markers(soup: BeautifulSoup) -> bool:
    for tag in soup.find_all("script", src=True):
        src = tag["src"].lower()
        if any(hint in src for hint in PLUGIN_FORM_SCRIPT_HINTS):
            return True
    return False


def _has_email_input(soup: BeautifulSoup) -> bool:
    if soup.select_one("input[type='email']"):
        return True
    if soup.select_one("input[name*='email' i]"):
        return True
    if soup.select_one("input[id*='email' i]"):
        return True
    return False


def _has_submit_control(soup: BeautifulSoup) -> bool:
    return soup.select_one(
        "button[type='submit'], input[type='submit'], input[name*='submit' i], "
        "button[class*='submit' i], input[class*='submit' i], button[class*='contact' i]"
    ) is not None


def _extract_title(soup: BeautifulSoup) -> str | None:
    tag = soup.find("title")
    return tag.get_text(strip=True) if tag else None


def _extract_meta_description(soup: BeautifulSoup) -> str | None:
    tag = soup.find("meta", attrs={"name": "description"})
    if tag:
        return tag.get("content", "").strip() or None
    return None

import os
import httpx
import pytest
from unittest.mock import patch
from bs4 import BeautifulSoup

from src.models.prospect import ErrorRecord, ProspectCandidate, ProspectState
from src.nodes import enrichment, output, pre_score_filter, sourcing


def test_enrichment_preserves_scripts_while_extracting_text():
    state = ProspectState(
        candidate=ProspectCandidate(name="Biz", website="https://example.com"),
    )
    html = """
    <html>
      <head>
        <title>Example</title>
        <script src="https://widget.intercom.io/widget/abc123"></script>
      </head>
      <body>
        <h1>Welcome</h1>
      </body>
    </html>
    """

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=RuntimeError("skip internal path crawl")),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=html),
        patch("src.nodes.enrichment._playwright_fetch_checked", return_value=None),
    ):
        result = enrichment.run(state)

    assert any("intercom" in s.lower() for s in result.detected_scripts)
    assert "welcome" in (result.raw_text or "").lower()


def test_enrichment_uses_browser_fallback_on_js_shell():
    state = ProspectState(
        candidate=ProspectCandidate(name="JS Shell", website="https://example.com"),
    )
    thin_html = """
    <html>
      <head>
        <script src="https://cdn.example.com/react-app.js"></script>
      </head>
      <body><div id="root"></div></body>
    </html>
    """
    hydrated_html = """
    <html>
      <body>
        <h1>Rendered content</h1>
        <p>Book now with our team and contact us via the form.</p>
      </body>
    </html>
    """

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(thin_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=RuntimeError("skip internal path crawl")),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=hydrated_html) as mocked_browser,
        patch("src.nodes.enrichment._playwright_fetch_checked", return_value=None),
    ):
        result = enrichment.run(state)

    assert mocked_browser.called
    assert "rendered content" in (result.raw_text or "").lower()


def test_enrichment_detects_divi_style_form_markers():
    state = ProspectState(
        candidate=ProspectCandidate(name="Divi Biz", website="https://example.com"),
    )
    html = """
    <html>
      <body>
        <div class="et_pb_contact_form_0">
          <button class="et_pb_contact_submit">Send</button>
        </div>
      </body>
    </html>
    """

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=RuntimeError("skip internal path crawl")),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=html),
    ):
        result = enrichment.run(state)

    assert result.has_form_tag is True
    assert result.has_submit_control is True


def test_enrichment_uses_playwright_when_http_fetch_is_blocked():
    state = ProspectState(
        candidate=ProspectCandidate(name="Blocked Biz", website="https://example.com"),
    )
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(403, request=req)
    blocked_error = httpx.HTTPStatusError("403 Forbidden", request=req, response=resp)
    hydrated_html = """
    <html>
      <body>
        <h1>Recovered content</h1>
      </body>
    </html>
    """

    with (
        patch("src.nodes.enrichment._fetch_homepage", side_effect=blocked_error),
        patch("src.nodes.enrichment._fetch_response", side_effect=RuntimeError("skip internal path crawl")),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=hydrated_html) as mocked_browser,
        patch("src.nodes.enrichment._playwright_fetch_checked", return_value=None),
    ):
        result = enrichment.run(state)

    assert mocked_browser.called
    assert "recovered content" in (result.raw_text or "").lower()
    assert result.errors == []


def test_enrichment_finds_contact_form_on_internal_contact_page():
    from src.nodes.analysis import run as analysis_run

    state = ProspectState(
        candidate=ProspectCandidate(name="Internal Contact Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          Welcome to our office. We provide preventive care and restorative services for local families.
          Our team focuses on patient comfort, long-term dental health, and clear communication.
          Learn more about our team and our approach to modern care in Test City.
          This content is intentionally verbose to avoid JS-shell fallback in the regression test.
        </p>
        <a href="/contact-us/">Contact Us</a>
      </body>
    </html>
    """
    contact_html = """
    <html>
      <body>
        <form action="/contact-submit" method="post">
          <input type="email" name="email" />
          <button type="submit">Send</button>
        </form>
      </body>
    </html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/contact-us":
            return httpx.Response(200, request=req, text=contact_html)
        raise httpx.ConnectError("not reachable in test", request=req)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
    ):
        enriched = enrichment.run(state)

    analyzed = analysis_run(enriched)
    assert analyzed.has_form_tag is True
    assert analyzed.has_email_input is True
    assert analyzed.has_submit_control is True
    assert analyzed.contact_form_page == "/contact-us"
    assert analyzed.analysis is not None
    assert "No contact form" not in analyzed.analysis.identified_gaps


def test_enrichment_detects_gravityform_wrapper_with_id_suffix():
    state = ProspectState(
        candidate=ProspectCandidate(name="GravityForm Biz", website="https://example.com"),
    )
    html = """
    <html>
      <body>
        <div class="gform_wrapper_6 gform_legacy_markup_wrapper">
          <div class="gfield">Name</div>
        </div>
      </body>
    </html>
    """
    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=RuntimeError("skip internal path crawl")),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=html),
    ):
        result = enrichment.run(state)

    assert result.has_form_tag is True
    assert result.contact_form_page == "homepage"


def test_enrichment_nav_link_fallback_finds_form_on_non_standard_path():
    state = ProspectState(
        candidate=ProspectCandidate(name="Nav Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          Welcome to our office. We provide preventive care and restorative services for local families.
          Our team focuses on patient comfort, long-term dental health, and clear communication.
          Learn more about our team and our approach to modern care in Test City.
          This content is intentionally verbose to avoid JS-shell fallback in the regression test.
        </p>
        <nav>
          <a href="/schedule-appointment">Schedule</a>
        </nav>
      </body>
    </html>
    """
    form_html = """
    <html>
      <body>
        <form action="/submit" method="post">
          <input type="email" name="email" />
          <button type="submit">Book</button>
        </form>
      </body>
    </html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/schedule-appointment":
            return httpx.Response(200, request=req, text=form_html)
        raise httpx.ConnectError("not reachable", request=req)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
    ):
        result = enrichment.run(state)

    assert result.has_form_tag is True
    assert result.contact_form_page == "/schedule-appointment"


def test_enrichment_nav_link_fallback_handles_relative_href_without_leading_slash():
    state = ProspectState(
        candidate=ProspectCandidate(name="Relative Nav Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          Welcome to our office. We provide preventive care and restorative services for local families.
          Our team focuses on patient comfort, long-term dental health, and clear communication.
          Learn more about our team and our approach to modern care in Test City.
          This content is intentionally verbose to avoid JS-shell fallback in the regression test.
        </p>
        <nav>
          <a href="schedule-appointment">Schedule</a>
        </nav>
      </body>
    </html>
    """
    form_html = """
    <html>
      <body>
        <form action="/submit" method="post">
          <input type="email" name="email" />
          <button type="submit">Book</button>
        </form>
      </body>
    </html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/schedule-appointment":
            return httpx.Response(200, request=req, text=form_html)
        raise httpx.ConnectError("not reachable", request=req)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
    ):
        result = enrichment.run(state)

    assert result.has_form_tag is True
    assert result.contact_form_page == "/schedule-appointment"


def test_enrichment_internal_crawl_uses_playwright_when_homepage_was_js_rendered():
    state = ProspectState(
        candidate=ProspectCandidate(name="JS Site Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>Welcome to our dental office.</p>
        <a href="/contact-us">Contact Us</a>
      </body>
    </html>
    """
    contact_html = """
    <html>
      <body>
        <form action="/submit" method="post">
          <input type="email" name="email" />
          <button type="submit">Send</button>
        </form>
      </body>
    </html>
    """

    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(403, request=req)
    blocked_error = httpx.HTTPStatusError("403 Forbidden", request=req, response=resp)

    def fake_playwright_checked(url: str, base_hostname: str) -> str:
        return contact_html

    with (
        patch("src.nodes.enrichment._fetch_homepage", side_effect=blocked_error),
        patch("src.nodes.enrichment._fetch_response", side_effect=RuntimeError("skip http crawl")),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_checked", side_effect=fake_playwright_checked),
    ):
        result = enrichment.run(state)

    assert result.playwright_used is True
    assert result.has_form_tag is True
    assert result.contact_form_page == "/contact-us"


def test_enrichment_internal_playwright_ignores_cross_domain_redirect():
    state = ProspectState(
        candidate=ProspectCandidate(name="Redirect Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>Welcome to our dental office.</p>
        <a href="/contact-us">Contact Us</a>
      </body>
    </html>
    """

    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(403, request=req)
    blocked_error = httpx.HTTPStatusError("403 Forbidden", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", side_effect=blocked_error),
        patch("src.nodes.enrichment._fetch_response", side_effect=RuntimeError("skip http crawl")),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_checked", return_value=None),
    ):
        result = enrichment.run(state)

    assert result.contact_form_page is None
    assert result.has_form_tag is False


def test_enrichment_internal_js_shell_escalates_to_playwright_and_finds_form():
    state = ProspectState(
        candidate=ProspectCandidate(name="JS Contact Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          Welcome to our office. We provide preventive care and restorative services for local families.
          Our team focuses on patient comfort, long-term dental health, and clear communication.
          Learn more about our team and our approach to modern care in Test City.
          This content is intentionally verbose to avoid JS-shell fallback in the regression test.
        </p>
        <a href="/contact-us">Contact Us</a>
      </body>
    </html>
    """
    js_shell_html = """
    <html>
      <head><script src="https://cdn.example.com/react-app.js"></script></head>
      <body><div id="root"></div></body>
    </html>
    """
    contact_html = """
    <html>
      <body>
        <form action="/submit" method="post">
          <input type="email" name="email" />
          <button type="submit">Send</button>
        </form>
      </body>
    </html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/contact-us":
            return httpx.Response(200, request=req, text=js_shell_html)
        raise httpx.ConnectError("not reachable", request=req)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_checked", return_value=contact_html),
    ):
        result = enrichment.run(state)

    assert result.has_form_tag is True
    assert result.contact_form_page == "/contact-us"
    assert result.internal_js_shell_detected is True
    assert result.internal_playwright_used is True


def test_enrichment_static_internal_page_without_form_does_not_trigger_playwright():
    state = ProspectState(
        candidate=ProspectCandidate(name="No Form Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          Welcome to our office. We provide preventive care and restorative services for local families.
          Our team focuses on patient comfort, long-term dental health, and clear communication.
          Learn more about our team and our approach to modern care in Test City.
          This content is intentionally verbose to avoid JS-shell fallback in the regression test.
        </p>
        <a href="/contact-us">Contact Us</a>
      </body>
    </html>
    """
    no_form_html = """
    <html>
      <body>
        <p>Call us at (555) 000-0000 or email us at test@example.com. We are located at 123 Test St.</p>
      </body>
    </html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/contact-us":
            return httpx.Response(200, request=req, text=no_form_html)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404 Not Found", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_checked", side_effect=AssertionError("Playwright must not fire on static page")) as mock_pw_checked,
    ):
        result = enrichment.run(state)

    mock_pw_checked.assert_not_called()
    assert result.contact_form_status == "missing"
    assert result.contact_form_check_had_errors is False
    assert result.internal_contact_check_reason == "no_form_static"
    assert result.internal_playwright_used is False
    assert result.has_form_tag is False
    assert result.contact_form_status == "missing"


def test_enrichment_nav_link_fallback_does_not_trigger_playwright():
    state = ProspectState(
        candidate=ProspectCandidate(name="Nav No PW Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          Welcome to our office. We provide preventive care and restorative services for local families.
          Our team focuses on patient comfort, long-term dental health, and clear communication.
          Learn more about our team and our approach to modern care in Test City.
          This content is intentionally verbose to avoid JS-shell fallback in the regression test.
        </p>
        <nav><a href="/reach-us">Reach Us</a></nav>
      </body>
    </html>
    """
    no_form_html = """
    <html>
      <body>
        <p>Call us at (555) 000-0000 or email us at test@example.com.</p>
      </body>
    </html>
    """

    pw_called_for = []

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if "/contact" in url or "/book" in url or "/request" in url:
            raise httpx.ConnectError("not reachable", request=req)
        if url == "https://example.com/reach-us":
            return httpx.Response(200, request=req, text=no_form_html)
        raise httpx.ConnectError("not reachable", request=req)

    def fake_pw_checked(url: str, base_hostname: str) -> str:
        pw_called_for.append(url)
        return no_form_html

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_checked", side_effect=fake_pw_checked),
    ):
        result = enrichment.run(state)

    nav_pw_calls = [u for u in pw_called_for if "/reach-us" in u]
    assert nav_pw_calls == [], "Playwright must not be called for nav-link fallback paths"
    assert result.has_form_tag is False


def test_sourcing_skips_lookup_when_candidate_already_resolved():
    state = ProspectState(
        candidate=ProspectCandidate(
            name="Known Business",
            website="https://known.example.com",
            location="Test City, TS",
            category="Test Category",
        )
    )

    with patch("src.nodes.sourcing.get_sourcing_provider") as mocked_factory:
        result = sourcing.run(state)

    mocked_factory.assert_not_called()
    assert result.candidate.name == "Known Business"
    assert result.candidate.website == "https://known.example.com"


def test_analysis_contact_form_detected_from_dom_signals():
    from src.nodes.analysis import run as analysis_run

    state = ProspectState(
        candidate=ProspectCandidate(name="Form Biz", website="https://example.com"),
        raw_text="welcome to our office",
        has_form_tag=True,
        has_email_input=True,
        has_submit_control=True,
    )

    result = analysis_run(state)
    assert result.analysis.has_contact_form is True
    assert "No contact form" not in result.analysis.identified_gaps


def test_pre_score_filter_marks_data_blocked():
    state = ProspectState(
        candidate=ProspectCandidate(name="Blocked", website="https://example.com"),
        errors=[
            ErrorRecord(
                node="enrichment",
                error_type="HTTPStatusError",
                message="Client error '403 Forbidden' for url 'https://example.com'",
            ),
            ErrorRecord(
                node="enrichment",
                error_type="playwright_fallback_failed",
                message="Playwright disabled after previous launch failure",
            ),
        ],
    )

    result = pre_score_filter.run(state)
    assert result.skip_scoring is True
    assert result.tier == "COLD"
    assert any(
        flag.startswith("Data blocked (HTTP 403/Playwright unavailable)")
        for flag in result.quality_flags
    )


def test_playwright_kill_switch_disables_launch_attempt():
    with (
        patch.object(enrichment, "_playwright_disabled", False),
        patch.dict(os.environ, {"PLAYWRIGHT_ENABLED": "false"}),
    ):
        with pytest.raises(RuntimeError, match="PLAYWRIGHT_ENABLED=false"):
            enrichment._fetch_with_playwright("https://example.com")


def test_output_record_contains_output_category():
    state = ProspectState(candidate=ProspectCandidate(name="Output Biz"))
    state.tier = "WARM"
    state.raw_text = "abc"
    state.contact_form_page = "homepage"
    state.playwright_attempted = True
    state.playwright_used = False
    state.blocked_http_status = 403

    with patch("src.nodes.output._write_record"):
        result = output.run(state)

    record = output._build_record(result)
    assert record["meta"]["output_category"] == "WARM"
    assert record["diagnostics"]["raw_text_length"] == 3
    assert record["website_signals"]["contact_form_page"] == "homepage"
    assert record["diagnostics"]["playwright_attempted"] is True
    assert record["diagnostics"]["playwright_used"] is False
    assert record["diagnostics"]["blocked_by_403_family"] is True


def test_pre_score_filter_no_website_becomes_no_website_tier():
    state = ProspectState(
        candidate=ProspectCandidate(
            name="No Website Barber",
            website=None,
            rating=4.8,
            review_count=120,
        )
    )
    result = pre_score_filter.run(state)
    assert result.tier == "NO_WEBSITE"
    assert result.skip_scoring is True
    assert result.no_website_opportunity == "HIGH"
    assert any("direct outreach candidate" in f.lower() for f in result.quality_flags)


def test_pre_score_filter_no_website_medium_band():
    state = ProspectState(
        candidate=ProspectCandidate(
            name="Small Shop",
            website=None,
            rating=4.0,
            review_count=25,
        )
    )
    result = pre_score_filter.run(state)
    assert result.tier == "NO_WEBSITE"
    assert result.no_website_opportunity == "MEDIUM"


def test_pre_score_filter_no_website_low_band():
    state = ProspectState(
        candidate=ProspectCandidate(
            name="Brand New Place",
            website=None,
            rating=3.2,
            review_count=4,
        )
    )
    result = pre_score_filter.run(state)
    assert result.tier == "NO_WEBSITE"
    assert result.no_website_opportunity == "LOW"


def test_quality_gate_no_scores_flag_suppressed_when_skip_scoring():
    from src.nodes import quality_gate

    state = ProspectState(
        candidate=ProspectCandidate(name="Skip Biz", website=None),
        skip_scoring=True,
        tier="NO_WEBSITE",
    )
    result = quality_gate.run(state)
    assert not any("pipeline may have failed" in f for f in result.quality_flags)


def test_enrichment_content_rich_internal_page_with_js_form_found_via_playwright():
    from src.nodes.analysis import run as analysis_run

    state = ProspectState(
        candidate=ProspectCandidate(name="Rich JS Form Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          Welcome to our plumbing company. We serve Test City and surrounding areas.
          Our licensed plumbers handle emergency repairs, drain cleaning, and water heater installs.
          Call us anytime — we have technicians available across the region seven days a week.
          Customer satisfaction is our top priority and we back every job with a satisfaction guarantee.
        </p>
        <nav><a href="/contact-us">Contact Us</a></nav>
      </body>
    </html>
    """
    content_rich_no_form_html = """
    <html>
      <head><script src="https://cdn.example.com/react-app.chunk.js"></script></head>
      <body><div id="root"></div></body>
    </html>
    """
    playwright_form_html = """
    <html>
      <body>
        <h1>Contact Us</h1>
        <form action="/submit" method="post">
          <input type="email" name="email" placeholder="Your email" />
          <textarea name="message"></textarea>
          <button type="submit">Send Message</button>
        </form>
      </body>
    </html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/contact-us":
            return httpx.Response(200, request=req, text=content_rich_no_form_html)
        raise httpx.ConnectError("not reachable", request=req)

    def fake_pw_checked(url: str, base_hostname: str) -> str:
        if "contact-us" in url:
            return playwright_form_html
        return None

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_checked", side_effect=fake_pw_checked),
    ):
        enriched = enrichment.run(state)

    analyzed = analysis_run(enriched)
    assert enriched.has_form_tag is True
    assert enriched.contact_form_status == "found"
    assert enriched.contact_form_page == "/contact-us"
    assert analyzed.analysis is not None
    assert "No contact form" not in analyzed.analysis.identified_gaps


def test_enrichment_detects_iframe_embed_form():
    state = ProspectState(
        candidate=ProspectCandidate(name="Typeform Biz", website="https://example.com"),
    )
    html = """
    <html>
      <body>
        <h1>Book a Consultation</h1>
        <iframe src="https://example.typeform.com/to/abc123" width="100%" height="500"></iframe>
      </body>
    </html>
    """
    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=RuntimeError("skip internal")),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=html),
    ):
        result = enrichment.run(state)

    assert result.has_form_tag is True
    assert result.contact_form_status == "found"
    assert result.contact_form_page == "homepage"


def test_internal_page_booking_signal_merges_into_analysis():
    from src.nodes.analysis import run as analysis_run

    state = ProspectState(
        candidate=ProspectCandidate(name="Booking Internal Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          We provide quality dental care in Test City. Our team is accepting new patients.
          We offer cleanings, fillings, crowns and cosmetic procedures. Call us today.
          Our staff has over 20 years of combined experience in restorative dentistry.
          We accept most major insurance plans and offer flexible payment options.
        </p>
        <nav><a href="/contact-us">Contact Us</a></nav>
      </body>
    </html>
    """
    contact_html = """
    <html>
      <body>
        <h1>Book Appointment</h1>
        <script src="https://embed.acuityscheduling.com/js/embed.js"></script>
        <form action="/book" method="post">
          <input type="email" name="email" />
          <button type="submit">Book Now</button>
        </form>
      </body>
    </html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/contact-us":
            return httpx.Response(200, request=req, text=contact_html)
        raise httpx.ConnectError("not reachable", request=req)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
    ):
        enriched = enrichment.run(state)

    analyzed = analysis_run(enriched)
    assert any("acuityscheduling" in s.lower() for s in enriched.detected_scripts)
    assert analyzed.analysis is not None
    assert analyzed.analysis.has_booking_link is True
    assert "No online booking" not in analyzed.analysis.identified_gaps


def test_merge_internal_evidence_does_not_mutate_soup_and_preserves_embed_detection():
    state = ProspectState(
        candidate=ProspectCandidate(name="Embed Guardrail Biz", website="https://example.com"),
    )
    html = """
    <html>
      <body>
        <iframe src="https://example.typeform.com/to/abc123"></iframe>
        <script src="https://js.hsforms.net/forms/embed/v2.js"></script>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")

    assert enrichment._has_form_tag(soup) is True
    enrichment._merge_internal_evidence(state, soup)

    # Ensure evidence merge did not strip scripts from the original soup.
    assert soup.find("script", src=True) is not None
    assert enrichment._has_form_tag(soup) is True
    assert any("hsforms.net" in s.lower() for s in state.detected_scripts)
    assert "typeform.com" in state.detected_hrefs.lower()


def test_contact_form_status_unknown_suppresses_gap_and_raises_flag():
    from src.nodes.analysis import run as analysis_run
    from src.nodes import quality_gate

    state = ProspectState(
        candidate=ProspectCandidate(name="Unknown Form Biz", website="https://example.com"),
        raw_text="Welcome to our office. We serve families in the local area.",
        contact_form_status="unknown",
    )

    analyzed = analysis_run(state)
    assert "No contact form" not in (analyzed.analysis.identified_gaps if analyzed.analysis else [])

    gate_result = quality_gate.run(analyzed)
    assert any("contact form status uncertain" in f.lower() for f in gate_result.quality_flags)


def test_enrichment_404_on_all_fallback_paths_is_clean_missing():
    state = ProspectState(
        candidate=ProspectCandidate(name="404 Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          Welcome to our plumbing company. We serve Test City and surrounding areas.
          Our licensed plumbers handle emergency repairs, drain cleaning, and water heater installs.
          Call us anytime — we have technicians available across the region seven days a week.
          Customer satisfaction is our top priority and we back every job with a satisfaction guarantee.
        </p>
      </body>
    </html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404 Not Found", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_checked", return_value=None),
    ):
        result = enrichment.run(state)

    assert result.contact_form_check_had_errors is False
    assert result.contact_form_status == "missing"


def test_enrichment_403_on_internal_path_cross_domain_via_playwright():
    state = ProspectState(
        candidate=ProspectCandidate(name="403 Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          Welcome to our plumbing company. We serve Test City and surrounding areas.
          Our licensed plumbers handle emergency repairs, drain cleaning, and water heater installs.
          Call us anytime — we have technicians available across the region seven days a week.
          Customer satisfaction is our top priority and we back every job with a satisfaction guarantee.
        </p>
      </body>
    </html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if "/contact-us" in url:
            resp = httpx.Response(403, request=req)
            raise httpx.HTTPStatusError("403 Forbidden", request=req, response=resp)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404 Not Found", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_checked", return_value=None),
    ):
        result = enrichment.run(state)

    assert result.contact_form_check_had_errors is False
    assert result.contact_form_status == "missing"
    assert result.internal_contact_check_reason == "cross_domain_redirect"


def test_enrichment_connect_error_on_internal_path_cross_domain_via_playwright():
    state = ProspectState(
        candidate=ProspectCandidate(name="ConnectErr Biz", website="https://example.com"),
    )
    homepage_html = """
    <html>
      <body>
        <p>
          Welcome to our plumbing company. We serve Test City and surrounding areas.
          Our licensed plumbers handle emergency repairs, drain cleaning, and water heater installs.
          Call us anytime — we have technicians available across the region seven days a week.
          Customer satisfaction is our top priority and we back every job with a satisfaction guarantee.
        </p>
      </body>
    </html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if "/contact-us" in url:
            raise httpx.ConnectError("Connection refused", request=req)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404 Not Found", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_checked", return_value=None),
    ):
        result = enrichment.run(state)

    assert result.contact_form_check_had_errors is False
    assert result.contact_form_status == "missing"
    assert result.internal_contact_check_reason == "cross_domain_redirect"


def test_no_website_output_includes_outreach_angle():
    state = ProspectState(
        candidate=ProspectCandidate(
            name="Barber No Site",
            website=None,
            rating=4.8,
            review_count=240,
        )
    )
    state.tier = "NO_WEBSITE"
    state.no_website_opportunity = "HIGH"
    state.skip_scoring = True

    with patch("src.nodes.output._write_record"):
        result = output.run(state)

    record = output._build_record(result)
    assert record["outreach"]["tier"] == "NO_WEBSITE"
    assert record["outreach"]["no_website_opportunity"] == "HIGH"
    assert "4.8 stars" in record["outreach"]["suggested_angle"]
    assert "240 reviews" in record["outreach"]["suggested_angle"]


def test_static_internal_page_no_form_sets_reason_not_unknown():
    state = ProspectState(
        candidate=ProspectCandidate(name="Static Biz", website="https://example.com"),
    )
    homepage_html = "<html><body>" + ("word " * 200) + "</body></html>"
    contact_html = "<html><body><p>Contact us by phone.</p></body></html>"

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if "contact" in url:
            return httpx.Response(200, request=req, text=contact_html, headers={"content-type": "text/html"})
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404 Not Found", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._playwright_fetch_checked", side_effect=AssertionError("should not escalate to Playwright for static page")),
    ):
        result = enrichment.run(state)

    assert result.contact_form_status == "missing"
    assert result.contact_form_check_had_errors is False
    assert result.internal_contact_check_reason == "no_form_static"


def test_playwright_timeout_on_internal_page_sets_reason_and_unknown():
    state = ProspectState(
        candidate=ProspectCandidate(name="Timeout Biz", website="https://example.com"),
    )
    homepage_html = "<html><body>" + ("word " * 200) + "</body></html>"
    js_shell_html = "<html><head><script src='/app.chunk.js'></script></head><body><div id='root'></div></body></html>"

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if "contact" in url:
            return httpx.Response(200, request=req, text=js_shell_html, headers={"content-type": "text/html"})
        raise httpx.ConnectError("not reachable", request=req)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._playwright_fetch_checked", side_effect=enrichment.PlaywrightTimeoutError("domcontentloaded timed out")),
    ):
        result = enrichment.run(state)

    assert result.contact_form_status == "unknown"
    assert result.contact_form_check_had_errors is True
    assert result.internal_contact_check_reason == "playwright_timeout"


def test_internal_contact_check_reason_in_output_diagnostics():
    state = ProspectState(candidate=ProspectCandidate(name="Reason Biz"))
    state.tier = "COLD"
    state.raw_text = "some text"
    state.internal_contact_check_reason = "no_form_static"

    with patch("src.nodes.output._write_record"):
        result = output.run(state)

    record = output._build_record(result)
    assert record["diagnostics"]["internal_contact_check_reason"] == "no_form_static"


def test_plugin_marker_targeted_playwright_finds_form():
    state = ProspectState(
        candidate=ProspectCandidate(name="Plugin PW Found Biz", website="https://example.com"),
    )
    homepage_html = "<html><body>" + ("word " * 200) + "</body></html>"
    contact_static_html = """
    <html><head>
    <script src="/wp-content/plugins/contact-form-7/js/scripts.js"></script>
    </head><body><p>Contact us page.</p></body></html>
    """
    contact_rendered_html = """
    <html><body>
    <form class="wpcf7-form">
      <input type="email" name="email"/>
      <button type="submit">Send</button>
    </form>
    </body></html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/contact-us":
            return httpx.Response(200, request=req, text=contact_static_html)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404 Not Found", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_plugin_targeted", return_value=contact_rendered_html),
    ):
        result = enrichment.run(state)

    assert result.has_form_tag is True
    assert result.contact_form_status == "found"
    assert result.contact_form_page == "/contact-us"
    assert result.internal_plugin_playwright_attempted is True
    assert result.internal_plugin_playwright_used is True


def test_plugin_marker_targeted_playwright_no_form_stays_missing():
    state = ProspectState(
        candidate=ProspectCandidate(name="Plugin PW No Form Biz", website="https://example.com"),
    )
    homepage_html = "<html><body>" + ("word " * 200) + "</body></html>"
    contact_static_html = """
    <html><head>
    <script src="/wp-content/plugins/contact-form-7/js/scripts.js"></script>
    </head><body><p>Call us instead.</p></body></html>
    """
    contact_rendered_html = "<html><body><p>Still no form after rendering.</p></body></html>"

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/contact-us":
            return httpx.Response(200, request=req, text=contact_static_html)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404 Not Found", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_plugin_targeted", return_value=contact_rendered_html),
    ):
        result = enrichment.run(state)

    assert result.has_form_tag is False
    assert result.contact_form_status == "missing"
    assert result.internal_contact_check_reason == "plugin_markers_only"
    assert result.contact_form_check_had_errors is False
    assert result.internal_plugin_playwright_attempted is True
    assert result.internal_plugin_playwright_used is False


def test_plugin_marker_playwright_timeout_stays_missing_not_unknown():
    state = ProspectState(
        candidate=ProspectCandidate(name="Plugin PW Timeout Biz", website="https://example.com"),
    )
    homepage_html = "<html><body>" + ("word " * 200) + "</body></html>"
    contact_static_html = """
    <html><head>
    <script src="/wp-content/plugins/contact-form-7/js/scripts.js"></script>
    </head><body><p>Contact page loading...</p></body></html>
    """

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/contact-us":
            return httpx.Response(200, request=req, text=contact_static_html)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404 Not Found", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_plugin_targeted", side_effect=enrichment.PlaywrightTimeoutError("domcontentloaded timed out")),
    ):
        result = enrichment.run(state)

    assert result.contact_form_status == "missing"
    assert result.contact_form_check_had_errors is False
    assert result.internal_contact_check_reason == "plugin_markers_only"


def test_no_plugin_markers_does_not_trigger_plugin_playwright():
    state = ProspectState(
        candidate=ProspectCandidate(name="Plain Static Biz", website="https://example.com"),
    )
    homepage_html = "<html><body>" + ("word " * 200) + "</body></html>"
    contact_html = "<html><body><p>Call us at any time.</p></body></html>"

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/contact-us":
            return httpx.Response(200, request=req, text=contact_html)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404 Not Found", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
        patch("src.nodes.enrichment._playwright_fetch_plugin_targeted", side_effect=AssertionError("plugin targeted PW must not fire on plain static page")) as mock_plugin_pw,
    ):
        result = enrichment.run(state)

    mock_plugin_pw.assert_not_called()
    assert result.contact_form_status == "missing"
    assert result.internal_contact_check_reason == "no_form_static"
    assert result.internal_plugin_playwright_attempted is False


def test_plugin_playwright_diagnostics_in_output():
    state = ProspectState(candidate=ProspectCandidate(name="Plugin Diag Biz"))
    state.tier = "COLD"
    state.raw_text = "some text"
    state.internal_plugin_playwright_attempted = True
    state.internal_plugin_playwright_used = False
    state.internal_contact_check_reason = "plugin_markers_only"

    with patch("src.nodes.output._write_record"):
        result = output.run(state)

    record = output._build_record(result)
    assert record["diagnostics"]["internal_plugin_playwright_attempted"] is True
    assert record["diagnostics"]["internal_plugin_playwright_used"] is False
    assert record["diagnostics"]["internal_contact_check_reason"] == "plugin_markers_only"


def test_scoring_penalties_skipped_when_contact_page_exists():
    from src.nodes.scoring import _score_lead_capture_maturity, _score_booking_intake_friction
    from src.models.prospect import AnalysisResult

    analysis = AnalysisResult(
        has_booking_link=False,
        has_email_capture=False,
        cta_strength="absent",
        trust_badges_present=False,
    )

    with_page = _score_lead_capture_maturity(analysis, contact_form_status="missing", contact_page_url="https://example.com/contact")
    without_page = _score_lead_capture_maturity(analysis, contact_form_status="missing", contact_page_url=None)
    assert with_page.score < without_page.score

    friction_with = _score_booking_intake_friction(analysis, contact_form_status="missing", contact_page_url="https://example.com/contact")
    friction_without = _score_booking_intake_friction(analysis, contact_form_status="missing", contact_page_url=None)
    assert friction_with.score < friction_without.score
    assert not any("phone-only intake" in e for e in friction_with.evidence)
    assert any("phone-only intake" in e for e in friction_without.evidence)


def test_contact_page_url_reset_on_new_run():
    state = ProspectState(
        candidate=ProspectCandidate(name="Stale State Biz", website="https://example.com"),
    )
    state.contact_page_url = "https://example.com/old-contact"

    homepage_html = "<html><body>" + ("word " * 200) + "</body></html>"

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
    ):
        result = enrichment.run(state)

    assert result.contact_page_url is None


def test_contact_page_url_set_when_contact_path_exists_without_form():
    state = ProspectState(
        candidate=ProspectCandidate(name="Phone First Biz", website="https://example.com"),
    )
    homepage_html = "<html><body>" + ("word " * 200) + "</body></html>"
    contact_html = "<html><body><p>Call us at 555-1234. Address: 1 Main St.</p></body></html>"

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if url == "https://example.com/contact":
            return httpx.Response(200, request=req, text=contact_html)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
    ):
        result = enrichment.run(state)

    assert result.contact_form_status == "missing"
    assert result.contact_page_url is not None
    assert "example.com" in result.contact_page_url


def test_contact_page_url_uses_canonical_resolved_url():
    state = ProspectState(
        candidate=ProspectCandidate(name="Redirect Biz", website="https://example.com"),
    )
    homepage_html = "<html><body>" + ("word " * 200) + "</body></html>"
    contact_html = "<html><body><p>Reach us here.</p></body></html>"

    def fake_fetch_response(url: str, timeout: int = 15):
        req = httpx.Request("GET", url)
        if "contact" in url:
            canonical = "https://example.com/contact-us/"
            return httpx.Response(200, request=req, text=contact_html, headers={"content-type": "text/html"})
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404", request=req, response=resp)

    class FakeResponse:
        def __init__(self, text, url):
            self.text = text
            self.url = url

        def raise_for_status(self):
            pass

    def fake_fetch_response_canonical(url: str, timeout: int = 15):
        if "contact" in url:
            return FakeResponse(contact_html, "https://example.com/contact-us/")
        req = httpx.Request("GET", url)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404", request=req, response=resp)

    with (
        patch("src.nodes.enrichment._fetch_homepage", return_value=(homepage_html, "https://example.com")),
        patch("src.nodes.enrichment._fetch_response", side_effect=fake_fetch_response_canonical),
        patch("src.nodes.enrichment._fetch_with_playwright", return_value=homepage_html),
    ):
        result = enrichment.run(state)

    assert result.contact_page_url == "https://example.com/contact-us/"


def test_no_hard_gap_when_contact_page_exists_without_form():
    from src.nodes.analysis import _identify_gaps
    gaps = _identify_gaps(
        text="call us",
        all_text="call us",
        contact_form_status="missing",
        contact_page_url="https://example.com/contact",
    )
    assert "No contact form or contact page detected" not in gaps
    assert any("contact page exists" in g for g in gaps)


def test_hard_gap_when_no_form_and_no_contact_page():
    from src.nodes.analysis import _identify_gaps
    gaps = _identify_gaps(
        text="call us",
        all_text="call us",
        contact_form_status="missing",
        contact_page_url=None,
    )
    assert "No contact form or contact page detected" in gaps


def test_contact_page_url_in_output_format_analysis_both_branches():
    state_with_analysis = ProspectState(
        candidate=ProspectCandidate(name="Analysis Biz"),
    )
    state_with_analysis.tier = "WARM"
    state_with_analysis.contact_page_url = "https://example.com/contact"
    from src.models.prospect import AnalysisResult
    state_with_analysis.analysis = AnalysisResult()

    with patch("src.nodes.output._write_record"):
        output.run(state_with_analysis)

    record_with = output._build_record(state_with_analysis)
    assert record_with["website_signals"]["contact_page_url"] == "https://example.com/contact"

    state_no_analysis = ProspectState(
        candidate=ProspectCandidate(name="No Analysis Biz"),
    )
    state_no_analysis.tier = "COLD"
    state_no_analysis.contact_page_url = "https://example.com/reach-us"

    with patch("src.nodes.output._write_record"):
        output.run(state_no_analysis)

    record_without = output._build_record(state_no_analysis)
    assert record_without["website_signals"]["contact_page_url"] == "https://example.com/reach-us"


def _make_local_result(name, website, place_id, city="Test City"):
    return {
        "title": name,
        "website": website,
        "place_id": place_id,
        "address": f"1 Test St, {city}, TS",
        "phone": "555-0000",
        "rating": 4.5,
        "reviews": 10,
        "type": "Plumber",
    }


def _make_paged_search(*pages):
    it = iter(pages)

    class FakeSearch:
        def get_dict(self):
            return {"local_results": next(it, [])}

    return FakeSearch()


def test_sourcing_dedup_by_place_id():
    page1 = [_make_local_result("Alpha Plumbing LLC", "https://example-alpha.test/", "PLACE_001")]
    page2 = [_make_local_result("Alpha Plumbing LLC", "https://example-alpha.test/", "PLACE_001")]

    with patch("src.providers.serpapi_provider.GoogleSearch", return_value=_make_paged_search(page1, page2)):
        results = sourcing.search_businesses("plumbing", "Test City, TS", max_results=10)

    names = [r.name for r in results]
    assert names.count("Alpha Plumbing LLC") == 1


def test_sourcing_dedup_by_name_website_fallback():
    page1 = [_make_local_result("Beta Plumbing", "https://example-beta.test/", None)]
    page2 = [_make_local_result("Beta Plumbing", "https://example-beta.test/", None)]

    with patch("src.providers.serpapi_provider.GoogleSearch", return_value=_make_paged_search(page1, page2)):
        results = sourcing.search_businesses("plumbing", "Test City, TS", max_results=10)

    names = [r.name for r in results]
    assert names.count("Beta Plumbing") == 1

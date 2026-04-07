# Ascent Intelligence — Changelog

**Project:** Prospect Intelligence Engine
**Format:** Newest entries at the top. Each entry notes what changed, why it mattered, and what it fixed or unlocked.

---

## 2026-04-05 — Phase C3: Live Contact Form Regression Samples

### What was added

Added a sample-based QA layer for contact form detection. Previously there was no way to quickly verify that enrichment changes hadn't broken form detection across different site patterns.

Two new files:

**`tests/contact_form_samples.yaml`** — fixture file with categorized real-world URLs:
- `homepage_form` — form is present on the homepage
- `internal_page_form` — form is on `/contact` or similar, not the homepage
- `no_form` — site has no contact form anywhere
- `js_rendered_form` — Elementor/Divi WordPress form, requires Playwright

Currently 3 verified entries (httpbin POST form, example.com, Wikipedia dentist article). Placeholder slots for the remaining categories — populated from real pipeline test runs as they're confirmed.

**`tests/test_contact_form_samples.py`** — parametrized test runner. Reads only `verified: true` entries from the YAML. Runs enrichment + analysis on each URL and asserts `has_contact_form` and `contact_form_page` match expected values.

Gated by `LIVE_SAMPLES=1` environment variable — not included in standard CI since each sample makes live HTTP requests. Run manually after any enrichment or analysis change.

```
LIVE_SAMPLES=1 pytest tests/test_contact_form_samples.py -v
```

**Test count after: 116 standard + 3 skipped (live samples)**

---

## 2026-04-05 — NO_WEBSITE Tier + Opportunity Bands

### What was added

Leads with no website were being classified as COLD and buried in the pipeline. This was wrong — a business with 200 Google reviews, a 4.9 rating, and a phone number is a strong outreach target. They just need a different approach: direct phone/email rather than digital gap analysis.

Introduced a dedicated `NO_WEBSITE` tier that catches these leads before scoring runs, preserves all their Google data, and routes them to a direct-outreach workflow.

### New: Opportunity bands (HIGH / MEDIUM / LOW)

Not all no-website leads are equal. Implemented automatic band classification based on Google signals:

- `HIGH`: 50+ reviews AND 4.0+ rating — proven business, strong phone close opportunity
- `MEDIUM`: 10+ reviews AND 3.5+ rating — established, worth a call
- `LOW`: everything else — low confidence without more data

### Files changed

| File | What changed |
|------|-------------|
| `src/models/prospect.py` | Added `NO_WEBSITE` to tier type. Added `no_website_opportunity` field. |
| `src/nodes/pre_score_filter.py` | NO_WEBSITE check runs first, before data-blocked and insufficient-content checks. Classifies band. |
| `src/graph/pipeline.py` | `no_website_opportunity` explicitly passed through the delta dict (LangGraph silently drops fields not listed). |
| `src/nodes/quality_gate.py` | Suppressed false "No scores computed" warning for intentional skips. |
| `src/nodes/output.py` | NO_WEBSITE leads get a Google-data-only outreach angle in their output JSON. |
| `api.py` | `no_website_opportunity` exposed in API response. NO_WEBSITE sorted after COLD, sub-sorted by band then review count. |
| `run_pipeline.py` | Separate CLI summary block for NO_WEBSITE leads showing phone, stars, review count, band. |
| `static/index.html` | Direct Outreach filter tab, green-bordered cards, opportunity band badge, outreach angle display, CSV export column. |

### Tests added (test_regressions.py)

- NO_WEBSITE lead → HIGH band (50 reviews, 4.5 stars)
- NO_WEBSITE lead → MEDIUM band (20 reviews, 3.8 stars)
- NO_WEBSITE lead → LOW band (3 reviews, 3.0 stars)
- `skip_scoring=True` does not trigger "pipeline failed" quality flag
- Output record for NO_WEBSITE lead includes correct outreach angle

**Test count after: 116 (was 111)**

---

## 2026-04-03 — Phase C2: Contact Form False Negative Fixes

### Problem

The pipeline was reporting "No contact form" for businesses that had one — just not on the homepage. This produced incorrect COLD/WARM tier assignments and misleading gap reports.

### What was found and fixed

Four separate root causes, each fixed independently:

1. **Internal-page crawl** — If no form is found on the homepage, the enrichment node now fetches up to 4 high-signal paths (`/contact`, `/contact-us`, `/request-appointment`, `/book`). Stops on first detected form.

2. **Redirect-safe base URL** — After a redirect (e.g., HTTP → HTTPS, or `www` to bare domain), internal paths were being built from the original URL. Fixed by capturing the final URL after redirect and using that as the base.

3. **Nav-link fallback** — If none of the 4 fixed paths yield a form, the enrichment node now parses the homepage nav links for contact-pattern keywords (`/schedule-appointment`, `/reach-us`, `/new-patient`, etc.) and tries those too.

4. **GravityForms detection** — Sites using GravityForms generate CSS class names like `gform_wrapper_6` (numbered). The old regex only matched `gform_wrapper`. Fixed with `\bgform_wrapper(?:_\d+)?\b`.

5. **Relative href normalization** — Hrefs like `schedule-appointment` (no leading `/`) were being skipped by the keyword check. Now normalized to `/schedule-appointment` before comparison.

### Playwright propagation to internal pages

When the homepage was fetched via Playwright (due to 403 block or JS shell), the internal-page crawl now also uses Playwright. Previously it would fall back to plain HTTP and miss JS-rendered forms.

### Cross-domain redirect guard

Added a check after Playwright navigation — if the page redirected to a different domain (e.g., the site redirects `/contact` to a third-party booking tool), the result is discarded. Prevents false positives from booking platform pages being treated as the business's own contact form.

### Files changed

`src/nodes/enrichment.py` (primary). `src/models/prospect.py` (two new fields: `internal_js_shell_detected`, `internal_playwright_used`). `src/nodes/output.py` (diagnostics block). `src/graph/pipeline.py` (delta dict updated).

**Test count after: ~110**

---

## 2026-04-03 — Phase C1: Tavily External Review Mining

### What was added

Inbound detection previously relied only on website signals. Added Tavily search integration to pull external review signals (Google, Yelp, third-party mentions) for each business.

- `_fetch_tavily_reviews()` calls Tavily with `search_depth="basic"`, returns up to 5 results
- Review signals from Tavily are merged with website signals, deduplicated, capped at 10
- Data coverage upgrades from "partial" to at minimum "partial" even when no regex patterns match — presence of any external content is itself a signal
- `TAVILY_API_KEY` must be set; gracefully skips if missing

### Files changed

`src/nodes/inbound_detection.py`. Tests updated with `NO_TAVILY` patch constant to keep test suite hermetic.

---

## 2026-04-03 — Phase B: Web UI (static/index.html)

### What was added

Full single-page dashboard for the `/analyze` API endpoint.

- Tier filter buttons (HOT / WARM / COLD) with live counts
- Per-lead cards showing tier, gaps, inbound classification, fit score, outreach angle
- Contact form page link when detected
- CSV export of filtered results
- Diagnostics section (raw text length, Playwright used, blocked status)

### Bugs fixed in the same pass

- CSV export was pulling from `_allResults` instead of the filtered/sorted list — exported leads the user had filtered out
- Unicode rendering issues (em-dashes, arrow characters, bullet dots) replaced with ASCII equivalents to prevent garbled output on Windows consoles

---

## 2026-04-02 — FastAPI Server (api.py)

### What was added

REST API wrapping the full pipeline.

- `GET /health` — liveness check
- `POST /analyze` — takes niche, location, max_results (1-20). Runs pipeline concurrently, returns structured results per business.
- Pipeline built once at startup, reused across all requests (no cold start per request)
- 503 guard if pipeline failed during startup
- Results sorted: HOT first, then WARM, COLD. Within tier, sorted by weighted fit score descending.
- Gaps omitted for `data_blocked` and `skip_scoring` leads

### Docker

`Dockerfile` updated to serve via `uvicorn`. Port 8000 exposed in `docker-compose.yml`.

---

## 2026-04-01 — Playwright Circuit Breaker + DATA_BLOCKED Tier Separation

### Problem

On Windows, Playwright was throwing `PermissionError [WinError 5]` on every business — 15 errors per run, cluttering output and causing thread noise. DATA_BLOCKED businesses were being labeled COLD, hiding them in the main tier results.

### What was fixed

**Playwright circuit breaker** — On first launch failure (`PermissionError` or `OSError`), a module-level flag disables all further Playwright attempts for the process lifetime. Eliminates repeated WinError spam. `PLAYWRIGHT_ENABLED=false` env var also added as a manual kill switch.

**DATA_BLOCKED separation** — Businesses blocked by HTTP 403/429/503 where Playwright also failed are now flagged distinctly as `DATA_BLOCKED` and shown in their own CLI section. Previously they silently fell into COLD with no explanation.

**Tracking fields added to ProspectState** — `playwright_attempted`, `playwright_used`, `blocked_http_status`. Visible in API response diagnostics and output JSON.

**Diagnostics block in output JSON** — Every output record now includes a `diagnostics` section: raw text length, whether Playwright was attempted/used, HTTP status code, and whether the record is data-blocked.

---

## 2026-04-01 — Full Delta-Dict Conversion (pipeline.py)

### Problem

Duplicate errors were appearing in output records (e.g., 16 alternating identical entries). LangGraph's `Annotated[list, operator.add]` reducer was re-adding errors every time a node returned a full `ProspectState` object with the accumulated `errors` list already on it.

### Fix

All 5 remaining node wrappers converted from returning full state to delta dicts (only the fields they actually write). Every node in the pipeline now returns a partial dict. Root cause of the duplication eliminated permanently.

---

## 2026-04-01 — 403 Blocked Sites Now Route to Playwright

### Problem

Sites returning HTTP 403, 429, or 503 were being logged as fetch failures and left with empty `raw_text`. They never reached the Playwright fallback, even though Playwright can often bypass these blocks.

### Fix

`enrichment.py` now catches `HTTPStatusError` separately from general fetch failures. If the status is 403/429/503, Playwright fires before the node gives up. If Playwright also fails, both errors are logged.

---

## 2026-04-01 — Threshold Recalibration + Proxy Detection

### Threshold recalibration

After fixing DOM form detection and script extraction ordering (see below), the test set was scoring correctly but still producing 0 HOT results. The top-scoring business (Gottfried Dental) scored 5.289, just below the HOT threshold of 5.5. Recalibrated against real data:

- HOT threshold: 5.5 → 5.0
- WARM threshold: 4.0 → 3.8

### Proxy detection

If `HTTP_PROXY`, `HTTPS_PROXY`, or `ALL_PROXY` were set in the environment, all SerpAPI requests silently timed out or failed — returning 0 businesses with no error. Added `_check_proxy_env()` to `run_pipeline.py`: detects and clears proxy vars at startup with a printed warning.

---

## 2026-04-01 — DOM-Based Contact Form Detection

### Problem

Contact form detection was text-only. If the page said "contact us" but didn't have the word "form", the gap would fire. If it had a form but no matching keywords, it would be missed. This caused "No contact form" to appear as a gap on roughly every business.

### Fix

Enrichment now extracts three DOM signals before text parsing:
- `has_form_tag` — `<form>` element present
- `has_email_input` — `<input type="email">` or email-named input
- `has_submit_control` — submit button or input

Analysis uses DOM signals first. Text-only keyword matching is a fallback only. Gap logic updated to use the same signals — "No contact form" now fires only when DOM signals confirm no form exists.

---

## 2026-04-01 — Playwright Selective Fallback for JS-Rendered Sites

### Problem

~27% of businesses in the test set had JS-rendered sites returning under 200 characters of raw text via plain HTTP. The pipeline was scoring these with empty data, producing noise results.

### Fix

Playwright (headless Chromium) added as a fallback in `enrichment.py`. Triggers when:
- `raw_text < 200 characters`, OR
- Word count < 120 AND JS framework hints detected in scripts/title/meta

If Playwright fails (not installed, permission error, timeout), enrichment keeps the httpx data and logs a non-fatal warning. Node never crashes.

---

## 2026-04-01 — Script Extraction Order Bug

### Problem

`_extract_text()` called `tag.decompose()` on `<script>` tags to strip them from the DOM. But this mutated the BeautifulSoup tree. If scripts were extracted after this, the script list would be empty — all JS framework signals, booking tool fingerprints, and chat provider detections were lost.

### Fix

Reordered extraction: scripts and hrefs are extracted before `_extract_text()` runs. Tree mutation no longer affects signal extraction.

---

## 2026-04-01 — Sourcing Duplicate Maps Lookup Guard

### Problem

`run_pipeline.py` pre-resolves candidates via `search_businesses()` before passing them to the pipeline. The pipeline also had a `sourcing` node that would re-run the Google Maps lookup — overwriting the already-resolved candidate data and burning API credits.

### Fix

`sourcing_node` now returns immediately if `state.candidate.website` or `state.candidate.place_id` is already set. API call skipped entirely for pre-resolved candidates.

---

## 2026-03-31 — Initial Build Complete (Week 1)

### What was built

Full 6-node LangGraph pipeline from scratch.

| Node | What it does |
|------|-------------|
| Sourcing | SerpAPI Google Maps search. Returns up to N businesses matching niche + location. Filters by city and review count. |
| Enrichment | Fetches business website via httpx + BeautifulSoup. Extracts raw text, scripts, hrefs, DOM signals. |
| Analysis | 18-field deterministic signal extraction: contact form, booking tool, live chat, CTA strength, mobile UX, trust badges, gaps. |
| Inbound Detection | Provider fingerprinting + bucket scoring. Classifies inbound handling as AUTOMATED / PARTIAL / MANUAL. |
| Pre-Score Filter | Feedback node. Routes around scoring for: (a) insufficient web data, (b) already fully automated businesses. Prevents LLM hallucination on empty inputs. |
| Scoring | 7-dimension scoring. Dims 1-6 deterministic, Dim 7 (Ascent Fit) via Claude Haiku. Confidence-weighted tier assignment (HOT / WARM / COLD). |
| Quality Gate | Post-scoring sanity flags: HOT with thin data, low average confidence, missing scores. |
| Output | Formats full record to JSON. Writes to `output/` with timestamped filename. |

### Tech stack

Python 3.11, LangGraph, FastAPI, httpx, BeautifulSoup/lxml, Playwright (optional), SerpAPI, Tavily, Anthropic Claude Haiku, Docker.

### Test coverage at launch

91 tests across 5 test files covering all nodes, pipeline wrappers, and regression guardrails.

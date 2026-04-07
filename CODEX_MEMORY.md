# CODEX Memory - Marketing and Lead Generation System

Last updated: 2026-04-03 (America/New_York)  
Maintainer: Codex

## Purpose
Codex-maintained running memory of what has been implemented, validated behavior, active caveats, and high-priority next steps.

## Current System Snapshot
- End-to-end pipeline is operational (sourcing -> enrichment -> analysis/inbound -> scoring -> quality gate -> output).
- FastAPI app is operational:
  - `GET /health`
  - `POST /analyze`
- Docker artifacts are in place (Playwright-based image + compose).
- Tier thresholds currently active:
  - `HOT >= 5.0`
  - `WARM >= 3.8`
  - else `COLD`

## Implemented and Verified Changes

### A) Pipeline state safety and error handling
- Added reducer-safe `errors` handling and delta wrapper behavior to prevent duplication.
- `pipeline.invoke()` dict-return handling is implemented in callers by reconstructing `ProspectState` when needed.
- Sequential wrapper behavior standardized:
  - `scoring`, `quality_gate`, `output` return `errors[errors_before:]`
  - `pre_score_filter`, `merge` return `errors: []`

### B) Enrichment and analysis quality fixes
- Script extraction order fixed (scripts/hrefs extracted before text mutation).
- External booking/chat signals now include href/iframe corpus (`detected_hrefs` + combined analysis text).
- DOM contact-form detection introduced (`has_form_tag`, `has_email_input`, `has_submit_control`).
- Divi builder class variants supported via regex (`et_pb_contact...`).
- Internal-page contact-form fallback implemented (bounded):
  - Attempts up to 4 same-domain paths: `/contact-us`, `/contact`, `/request-an-appointment`, `/book`
  - 10s timeout per path, no recursion, best-effort
  - Sets contact signals from fallback page when found
- `contact_form_page` added to state/output.
- `contact_form_page` propagation bug in `enrichment_node` wrapper fixed.
- Text fallback for contact form tightened to avoid false positives from generic phrases (for example `your name`).

### C) Playwright and blocked-site behavior
- Thin-content/JS-shell fallback logic implemented.
- 403/429/503 fetch errors now route to Playwright fallback path.
- Playwright stabilization:
  - lock around launch path
  - kill switch via `PLAYWRIGHT_ENABLED`
  - scoped stderr suppression for noisy launch failures
- Data-blocked classification added:
  - quality flag: `Data blocked (HTTP 403/Playwright unavailable) - manual review needed`
  - skip scoring + separate handling downstream

### D) Output and operator UX fixes
- `output_category` now set before record build/write.
- UTC timestamps made timezone-aware.
- Diagnostics block added to output records (`raw_text_length`, Playwright flags/status, blocked indicators, `data_blocked`).
- CLI summary display fixed:
  - `skip_scoring` -> `Gaps: N/A (insufficient web data)`
  - `data_blocked` -> `Gaps: N/A (no web data retrieved)`

### E) Sourcing reliability and volume fixes
- Sourcing skip when candidate already resolved (`website` or `place_id`).
- Proxy pre-check/clear at CLI startup to avoid silent 0-result runs.
- Sourcing exception logging improved.
- Google Maps pagination added in sourcing:
  - up to 3 pages via `start` offsets (`0`, `20`, `40`)
  - `num: 40` removed (non-actionable/no-op in this path)
- Review-cap filter made configurable:
  - `max_review_count` parameter in sourcing (default `500`)
  - exposed in API request model
- Verified effect: previously under-delivering query (`max_results=8`) now returns 8 for Austin dental under current constraints.

### F) FastAPI + Docker scope
- FastAPI lifespan initializes pipeline once and reuses it.
- Docker/compose assets present and aligned for API + output mount flow.
- Playwright smoke script present.

## Current Bug Log Sync Status
- `INTERNAL_NOTES.md` bug-fix section was revalidated and corrected for:
  - BF-22 (`contact_form_page` wrapper propagation)
  - BF-23 (over-broad contact-form text fallback)
  - BF-24 (sourcing pagination + review-cap configurability)
- Regression test name references were corrected to match actual tests.

## Tests and Validation
- Full test suite currently passing: **103 passed**.
- Key recent validations performed:
  - live check confirmed internal-page form detection for South Austin Dentist
  - false-positive scenario (The Local Dentist) corrected after fallback tightening
  - API `/analyze` end-to-end run executed successfully with requested payloads

## Interpretation Rules for Ops
- `HOT/WARM`: action candidates.
- `COLD` (scored): lower priority but data-backed.
- `DATA_BLOCKED`: manual review required (not a true low-fit signal).
- `skip_scoring` non-blocked: insufficient data; treat cautiously.
- Note: tier is based on weighted composite final score, not solely the dim-7 `ascent_fit_score`.

## Known Caveats
- Windows environments can still show Playwright launch constraints depending on permissions/runtime.
- Some sites remain inaccessible due to hard anti-bot controls even with fallback.
- Google Maps result quality/volume remains sensitive to filter policy (`max_review_count`) and provider behavior.

## Next High-Value Steps
1. Sourcing backend abstraction and feature flag (`SerpAPI` vs `Google Places`) with parity mapping.
2. Batch processing (multi niche/location), dedup, and cross-batch ranking.
3. Lightweight operator UI (FastAPI-served static page) for internal testing/demo.
4. Recalibrate thresholds on a larger clean sample once batch sourcing stabilizes.

## Useful Commands
- Run tests:
  - `venv\Scripts\python -m pytest -q`
- Run CLI pipeline:
  - `venv\Scripts\python run_pipeline.py`
- Run API:
  - `venv\Scripts\python -m uvicorn api:app --host 0.0.0.0 --port 8001`
- Docker compose:
  - `docker compose up`

## Core Files Touched Most
- `src/nodes/enrichment.py`
- `src/nodes/analysis.py`
- `src/nodes/sourcing.py`
- `src/graph/pipeline.py`
- `src/models/prospect.py`
- `src/nodes/pre_score_filter.py`
- `src/nodes/output.py`
- `api.py`
- `run_pipeline.py`
- `config/scoring_weights.yaml`
- `tests/test_regressions.py`
- `tests/test_analysis.py`
- `tests/test_pipeline_wrappers.py`

## Checkpoint 2026-04-03 (latest)

### Newly verified and completed
- C2 contact-form hardening is in place and validated:
  - relative nav href normalization (`href="schedule-appointment"` support)
  - internal Playwright crawl when homepage already required Playwright
  - domain-checked internal Playwright fetch via `_playwright_fetch_checked` (ignore cross-domain redirect)
- Bounded internal JS-shell escalation is implemented:
  - `INTERNAL_JS_SHELL_WORD_FLOOR = 30`
  - `_is_internal_js_shell()` check on internal pages
  - one bounded Playwright retry per internal path only when internal page is JS-shell-like
- New internal diagnostics fields exist and are wired:
  - `internal_js_shell_detected`
  - `internal_playwright_used`
- Enrichment wrapper propagation fixed in graph:
  - `src/graph/pipeline.py` now returns both new internal diagnostics fields in `enrichment_node` delta dict
- Test hermeticity fix completed:
  - legacy regression tests now patch `_playwright_fetch_checked` where needed
  - removed noisy real Playwright launches during regression runs on Windows

### Bug-log and documentation sync
- `INTERNAL_NOTES.md` bug-fix log re-audited and updated.
- Added/updated:
  - BF-25 (internal JS-rendered contact pages + redirect-safe Playwright internal crawl)
  - BF-26 (internal diagnostics dropped by enrichment wrapper)
  - BF-27 (regression tests launching real Playwright unexpectedly)
- Regression guardrails table updated with new tests:
  - cross-domain redirect guard
  - internal JS-shell escalation positive case
  - non-JS no-form no-escalation case
  - wrapper propagation guard
- Open False Negatives section updated:
  - contact-form internal-page false negative marked resolved (with guardrails listed)

### Current validation baseline
- Full test suite: `111 passed`
- Key focused suites:
  - `tests/test_regressions.py`: passing
  - `tests/test_pipeline_wrappers.py`: passing

## Checkpoint 2026-04-05 (latest)

### NO_WEBSITE pipeline path implemented and verified
- Added dedicated no-website routing so `website=None` leads are no longer auto-bucketed as `COLD`.
- New tier: `NO_WEBSITE`.
- New field: `no_website_opportunity` with bands:
  - `HIGH`: review_count >= 50 and rating >= 4.0
  - `MEDIUM`: review_count >= 10 and rating >= 3.5 (not HIGH)
  - `LOW`: otherwise
- `pre_score_filter` now catches no-website leads before insufficient-web-content logic and sets:
  - `tier="NO_WEBSITE"`
  - `skip_scoring=True`
  - quality flag: direct outreach candidate
- `quality_gate` now suppresses `"No scores computed - pipeline may have failed upstream"` when skip is intentional (`skip_scoring=True`).
- `pipeline` wrapper propagates `no_website_opportunity` in `pre_score_filter_node` delta dict.

### Output/API/CLI/UI integration
- Output record now includes no-website outreach payload:
  - `outreach.tier = NO_WEBSITE`
  - `outreach.no_website_opportunity`
  - generated outreach angle from rating + review count.
- API response now includes `no_website_opportunity` and generated direct-outreach angle for `NO_WEBSITE`.
- API sorting includes no-website sub-ranking by band -> review_count -> rating -> name.
- CLI summary includes dedicated section:
  - `NO_WEBSITE - Direct Outreach`
  - phone, rating, review_count shown for call-first workflow.
- UI (`static/index.html`) includes:
  - NO_WEBSITE badge/style/filter
  - direct-outreach labeling
  - opportunity band display
  - CSV export includes `no_website_opportunity`.

### Regression coverage added
- New regression tests cover:
  - `NO_WEBSITE` tier routing
  - HIGH/MEDIUM/LOW opportunity bands
  - quality gate suppression for intentional skip-scoring
  - output outreach record fields for no-website path.

### Validation status
- `tests/test_regressions.py`: `22 passed`
- full suite: `116 passed`

### Strategic notes captured
- `HOT` vs `Direct Outreach HIGH` distinction documented:
  - `HOT` = full 7-dim scored web/inbound lead.
  - `Direct Outreach HIGH` = no-website, Google-only direct call priority.
- Post-demo neutralization brief updated in `generic - no bias. txt`:
  - feature-flagged (`GENERIC_NEUTRAL_MODE=false` by default),
  - conservative category matcher guidance,
  - no global `_assign_tier` math change in this phase.

## Checkpoint 2026-04-06 (latest)

### Accuracy work completed
- Internal contact-path handling hardened for real-site failures:
  - status-aware path handling for internal fetches (`404/410` clean negative, blocked/connect failure -> uncertainty path).
  - bounded Playwright escalation behavior retained for fixed fallback paths only.
- Internal evidence merge expanded:
  - scripts + hrefs + visible text from internal pages now merged into state corpus.
  - this fixed booking false negatives where CTA text existed only on `/contact-us`.
- Contact-form uncertainty model active:
  - `contact_form_status` now drives output behavior:
    - `found` => normal
    - `missing` => explicit gap
    - `unknown` => gap suppressed + quality flag

### Critical bug fixed
- `_extract_text()` mutation bug fixed in enrichment:
  - now operates on a copied soup object, so original DOM/scripts remain available for downstream checks.
  - added guardrail test to ensure `_merge_internal_evidence()` does not mutate soup and does not break embed-form detection.

### Real-site findings (important)
- **Righttime Plumbing**:
  - still can produce `contact_form_status=unknown` and `contact_form_page=None` on local Windows due Playwright launch failure (`WinError 5`), not because suppression logic is hardcoded.
  - diagnostic trace confirmed `contact_form_check_had_errors=True` in this local runtime.
- **United Service Specialists**:
  - booking false negative corrected after internal text merge.
  - local trace showed `contact_form_status=found`, `contact_form_page=/contact-us`, and `has_booking_link=True`.

### Test status
- full suite after latest fixes: `125 passed, 3 skipped`.
- targeted guardrails for contact-path/Playwright behavior are passing.

### Docker/runtime notes
- Verified inside running compose service:
  - `PLAYWRIGHT_ENABLED=true`
  - Playwright smoke test passes in container.
- Confirmed Docker can lag behind local code if image is not rebuilt (compose mounts `output` only, not source).
- Added planning document:
  - `Next phases demo.md` with:
    - Docker sync-to-current-code requirement
    - do-now scope for D/E/F for demo
    - post-demo patch split

### Current recommendation baseline
- For demo accuracy: use Docker as source-of-truth runtime.
- Rebuild image before validation runs to avoid stale-container results.

## Checkpoint 2026-04-06 (Simple Build fallback)

### User-requested fallback baseline created
- Created local code/config snapshot folder:
  - `checkpoints/Simple Build/`
- Created compressed snapshot archive:
  - `checkpoints/Simple Build.zip`
- Added checkpoint metadata file:
  - `checkpoints/Simple Build/CHECKPOINT_INFO.txt`
- Tagged current Docker runtime image for rollback:
  - `marketingandleadgenerationsystem-pipeline:simple-build`

### Rollback options
1. Code rollback:
   - Copy contents from `checkpoints/Simple Build/` back to project root.
2. Runtime rollback:
   - Run Docker using image tag `marketingandleadgenerationsystem-pipeline:simple-build`.

### Why this exists
- Acts as pre-Phase-D/E/F recovery point so any future refactor can be fully reverted.

## Checkpoint 2026-04-06 (Pre-demo final validation baseline)

### Completed and verified
- Phase D implemented and verified in Docker:
  - provider abstraction + SerpAPI provider + provider factory
  - backend switch via `SOURCING_BACKEND` (default `serpapi`)
- Phase E implemented and verified in Docker:
  - `/batch` endpoint
  - cross-target dedup (`place_id` -> website -> name+city)
  - global ranking + batch summary
  - `place_id` exposed in API result model
- Phase F3 implemented and verified in Docker:
  - JSONL audit logger (`src/utils/audit_logger.py`)
  - record logs from output node
  - summary logs from CLI and API (`/analyze`, `/batch`)
  - gated by `AUDIT_LOG_ENABLED=true` (default off)
- Minor Phase D gap closed:
  - `AnalyzeRequest.source_backend` optional per-request override added

### Final pre-demo runtime validation completed
- Clean image bake done:
  - `docker compose down`
  - `docker compose build --no-cache`
  - `docker compose up -d`
- Playwright smoke test (in container): PASS  
  - `docker compose exec -T pipeline python scripts/playwright_smoke_test.py`
- Full test suite (in container): `179 passed, 3 skipped`
- Real `/analyze` run validated with payload:
  - `{"niche":"plumbing","location":"Phoenix, AZ","max_results":5,"max_review_count":500}`
  - returned ranked 5 results successfully

### Docs/status
- `DEMO_LIMITATIONS.md` present.
- `Next phases demo.md` updated to keep audit logging off for demo and enable post-demo.

### Next action
- Run one final test pass tomorrow, then submit.

## Checkpoint 2026-04-06 (Pre-demo final validation baseline)

### Completed and verified
- Phase D implemented and verified in Docker:
  - provider abstraction + SerpAPI provider + provider factory
  - backend switch via `SOURCING_BACKEND` (default `serpapi`)
- Phase E implemented and verified in Docker:
  - `/batch` endpoint
  - cross-target dedup (`place_id` -> website -> name+city)
  - global ranking + batch summary
  - `place_id` exposed in API result model
- Phase F3 implemented and verified in Docker:
  - JSONL audit logger (`src/utils/audit_logger.py`)
  - record logs from output node
  - summary logs from CLI and API (`/analyze`, `/batch`)
  - gated by `AUDIT_LOG_ENABLED=true` (default off)
- Minor Phase D gap closed:
  - `AnalyzeRequest.source_backend` optional per-request override added

### Final pre-demo runtime validation completed
- Clean image bake done:
  - `docker compose down`
  - `docker compose build --no-cache`
  - `docker compose up -d`
- Playwright smoke test (in container): PASS  
  - `docker compose exec -T pipeline python scripts/playwright_smoke_test.py`
- Full test suite (in container): `179 passed, 3 skipped`
- Real `/analyze` run validated with payload:
  - `{"niche":"plumbing","location":"Phoenix, AZ","max_results":5,"max_review_count":500}`
  - returned ranked 5 results successfully

### Docs/status
- `DEMO_LIMITATIONS.md` present.
- `Next phases demo.md` updated to keep audit logging off for demo and enable post-demo.

### Next action
- Run one final test pass tomorrow, then submit.

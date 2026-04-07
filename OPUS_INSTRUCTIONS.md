---
name: Opus Week 2 Execution Plan
description: Comprehensive phased build plan for remaining Week 2 work. API enrichment, Web UI, Tavily, Google Places, batch processing, polish. Merges Opus assessment + Codex recommendations.
type: project
---

# Opus Week 2 Execution Plan

**Created:** 2026-04-03
**Last updated:** 2026-04-03
**Context:** All 6 pipeline nodes complete, 103+ tests, 24 bug fixes, Docker + FastAPI live. Contact-form internal-page crawl implemented and confirmed (BF-20). This plan covers everything remaining to hit the Week 2 demo target (50+ businesses, usable output, full signal quality).

**CEO priorities (in order):** Strong logic > Strong signal extraction > Useful scoring > Usable output > Good prioritization.

---

## Execution Protocol

- Each phase is executed one subphase at a time (A1, A2, A3, etc.).
- After each subphase is coded, stop and wait for the user to check and verify.
- Do not proceed to the next subphase until the user explicitly gives the go-ahead.
- No exceptions — this applies to every phase (A through F).

---

## Phase A. Complete the API Data Contract

*Everything downstream (UI, CSV, batch) consumes the API. Fix the shape first.*
**Timebox:** ~2 hours

### A1. Enrich API response model
- Add to `ProspectResult` in `api.py`:
  - `suggested_outreach_angle: Optional[str]`
  - `output_category: Optional[str]`
  - All 7 dimension scores (nested model or flat dict per dimension with score + confidence + evidence)
  - `diagnostics` block (raw_text_length, playwright_attempted, playwright_used, blocked_http_status, data_blocked)
  - `contact_form_page: Optional[str]`
  - `priority_rank: int`
- Update `_run_single()` to extract these from pipeline result.

### A2. Add priority ranking
- After all futures complete in `/analyze`, sort results:
  1. Tier order: HOT > WARM > COLD
  2. Within tier: weighted score descending
- Assign `priority_rank` 1..N.
- Also set `priority_rank` on `ProspectState` if persisting to JSON output.

### A3. Verify contact_form_page propagation
- Contact-form internal-page crawl is already implemented (BF-20, enrichment.py lines 207-237).
- Verify `contact_form_page` appears correctly in the enriched API response when an internal-page hit occurs.
- Run against a known business with form on `/contact` (not homepage).
- If missing from API response, trace through enrichment_node delta dict in pipeline.py.

### Definition of Done
- `curl POST /analyze` returns all 7 dimension scores, outreach angle, output_category, diagnostics, contact_form_page, and priority_rank.
- Results sorted by tier then score; priority_rank assigned 1..N with no gaps.
- contact_form_page populated in response when internal-page form is detected.
- All 103+ existing tests still pass.

---

## Phase B. Web UI

*Depends on Phase A being complete (UI consumes the enriched API).*
**Timebox:** ~4 hours

### B1. Build Option A: FastAPI-served static HTML page
- Create `static/index.html`, single file, vanilla JS, no build step.
- FastAPI serves it via `StaticFiles` mount at `/`.
- Input form: niche, location, max_results, max_review_count.
- Submit hits `POST /analyze`, shows loading spinner during pipeline run.

### B2. Results display
- Cards per business, color-coded by tier:
  - HOT = red/orange
  - WARM = yellow/amber
  - COLD = blue/gray
- Each card shows: business name, location, website, rating, tier badge, priority rank.
- Gaps section: list gaps. Show "N/A (insufficient web data)" for skip_scoring, "N/A (site blocked)" for data_blocked.
- Outreach angle displayed prominently on HOT/WARM cards.
- Scores: expandable section per card showing all 7 dimensions with score bars and confidence.
- Error panel: collapsible, shows any pipeline errors per business.

### B3. Quick filters and sort
- Tier filter (checkbox: HOT / WARM / COLD / DATA_BLOCKED).
- Sort by: priority rank (default), score descending, name A-Z.
- Search/filter by business name.

### B4. CSV export button
- Client-side: JS generates CSV from current results and triggers download.
- OR server-side: `GET /export?niche=...&location=...&format=csv` endpoint.
- Columns: rank, tier, name, location, website, phone, rating, review_count, inbound_classification, top_3_gaps, outreach_angle, fit_score, fit_confidence.

### Definition of Done
- Browser at `localhost:8001/` loads the UI with a working input form.
- Submitting a query returns color-coded tier cards with all enriched fields from Phase A.
- CSV export downloads a valid file with all specified columns.
- Tier filter, sort by rank/score/name, and name search all functional.
- CEO can demo the pipeline without touching curl or Swagger.

---

## Phase C. Raise Signal Quality

**Timebox:** ~3 hours

### C1. Tavily review mining for inbound detection
- **Why this matters:** Review signals are the strongest evidence for dims 1, 2, and 6 (AI receptionist likelihood, inbound automation maturity, revenue leakage). Currently `_mine_reviews()` only searches the business's own website text. Real signals ("went to voicemail", "couldn't reach them", "no one answered") live on Google Reviews and Yelp. Without external reviews, `review_signals` is almost always empty, `data_coverage` returns "insufficient", and quality gate flags fire on every HOT lead.
- Add Tavily search in `inbound_detection.py`: query `"{business_name} {location} reviews"`.
- Extract negative/positive review patterns from Tavily results.
- Merge with existing `_mine_reviews()` output.
- Requires `TAVILY_API_KEY` in `.env`.
- Guard: if Tavily key missing or call fails, fall back to current behavior (website-only mining). Non-fatal.
- Update `_assess_coverage()` to reflect external review data availability.

### C2. Debug South Austin Dental contact form false negative
- The internal-page crawl is implemented and confirmed working (BF-20). However, the South Austin Dental output still shows `has_contact_form: false`, `contact_form_page: null`.
- This is a site-specific false negative, not a missing feature. Investigate: (a) Do the fallback paths match what the site uses? (b) Is the form on the internal page JS-rendered (Divi)? (c) Does the page redirect away from the base domain?
- If the form is JS-rendered on internal pages too, consider running Playwright on the first internal-page hit that returns < 200 chars visible text. Bounded: one Playwright call only, only if httpx parse found no form.

### C3. Add live regression sample set
- Create `tests/contact_form_samples.yaml` (or similar) with 5-10 known URLs:
  - 2-3 with form on homepage
  - 2-3 with form on internal page only
  - 1-2 with no form anywhere
  - 1 JS-rendered form (Elementor/Divi)
- Use in CI or manual QA to verify contact form detection accuracy after any enrichment/analysis change.

### Definition of Done
- Tavily review mining returns `review_signals` for businesses with external reviews available.
- `data_coverage` upgrades from "insufficient" to "partial" or "good" when external reviews are found.
- South Austin Dental false negative root cause identified and fixed (or documented as site-specific edge case with workaround).
- Regression sample set passes with < 20% false negative rate on contact form detection.
- Pipeline still falls back gracefully when `TAVILY_API_KEY` is missing.

---

## Phase D. Sourcing Provider Abstraction + Google Places

**Timebox:** ~3 hours

### D1. Define SourcingProvider interface
- Abstract base class or Protocol:
  ```python
  class SourcingProvider(Protocol):
      def search(self, niche: str, location: str, max_results: int, max_review_count: int) -> list[ProspectCandidate]: ...
  ```
- All providers return the same `ProspectCandidate` fields. Parity mapping enforced at the interface level.

### D2. Implement SerpApiProvider
- Refactor current `_search_google_maps()` into a class implementing `SourcingProvider`.
- No behavior change. Existing tests must still pass.

### D3. Implement GooglePlacesProvider
- Google Places Text Search, Nearby Search, Place Details.
- Map Places API fields to `ProspectCandidate`: name, formatted_address, phone, website, rating, user_ratings_total, place_id.
- Bonus fields available from Places: `opening_hours`, `price_level`, `business_status` (OPERATIONAL / CLOSED_TEMPORARILY). Store these on ProspectCandidate if useful for scoring.
- Requires `GOOGLE_PLACES_API_KEY` in `.env`.

### D4. Backend switch flag
- Env var: `SOURCE_BACKEND=serpapi|google_places` (default: `serpapi`).
- `search_businesses()` reads the flag and instantiates the correct provider.
- API request can optionally override: `source_backend: Optional[str]` on `AnalyzeRequest`.

### D5. Provider-level logging and metrics
- Each provider logs per-call: result count before filters, result count after filters, API errors, latency.
- Print to console (like current sourcing debug output).
- Later: structured JSONL logging if audit trail is built.

### D6. Tests for backend switching and response parity
- Test that both providers return valid `list[ProspectCandidate]` with required fields populated.
- Test that switching `SOURCE_BACKEND` env var routes to the correct provider.
- Mock-based: don't require live API keys in CI.

### Definition of Done
- `SOURCE_BACKEND=serpapi` routes to SerpApiProvider; `SOURCE_BACKEND=google_places` routes to GooglePlacesProvider.
- Both providers return valid `list[ProspectCandidate]` with all required fields populated.
- Switching providers does not break any existing tests.
- Provider logging shows result counts (before/after filters) and latency per call.
- All 103+ existing tests still pass, plus new provider-switching tests.

---

## Phase E. Batch Processing

*Depends on Phase D (sourcing should be stable before building batch on top).*
**Timebox:** ~4 hours

### E1. Batch input model
- `POST /batch` endpoint accepting:
  ```json
  {
    "targets": [
      {"niche": "dental clinic", "location": "Austin, TX"},
      {"niche": "HVAC contractor", "location": "Austin, TX"}
    ],
    "max_results_per_target": 10,
    "max_review_count": 500
  }
  ```
- Runs all targets, collects all results into one response.

### E2. Cross-batch deduplication
- Dedup strategy (in priority order):
  1. `place_id` match (strongest, Google's canonical ID)
  2. Normalized `website` match (strip www, trailing slash, protocol)
  3. Fuzzy `name + address` match (fallback for businesses without place_id or website)
- When duplicate found: keep the result with the higher score / more complete data. Log the dedup event.

### E3. Cross-batch ranking
- Global rank across all targets (1..N by tier then score).
- Per-batch rank within each (niche, location) group.
- Both included in response.

### E4. Batch summary stats
- Response includes summary block:
  ```json
  {
    "total": 47,
    "hot": 8,
    "warm": 19,
    "cold": 15,
    "data_blocked": 3,
    "skipped": 2,
    "deduplicated": 4
  }
  ```

### E5. Batch in Web UI
- Add "Batch Mode" toggle in the UI.
- Allow adding multiple niche+location rows.
- Display unified results with batch grouping and global ranking.

### Definition of Done
- `POST /batch` accepts multiple targets and returns unified, deduplicated results.
- Cross-batch dedup correctly merges by place_id, then website, then fuzzy name+address.
- Global ranking (1..N) and per-batch ranking both present in response.
- Summary stats (hot/warm/cold/blocked/skipped/deduplicated counts) included.
- Batch mode in UI allows adding multiple rows and displays grouped results.
- 50+ businesses processed in a single batch run without errors.

---

## Phase F. Polish

| # | Task | Notes |
|---|------|-------|
| F1 | Rate limiting (asyncio.Semaphore per API) | Not needed until batch runs 50+ concurrent. Add before production scale. |
| F2 | SQLite dedup cache | Cache enrichment + scoring by place_id/website. Saves API costs on repeat runs. |
| F3 | JSONL audit trail logger | Deferred per original plan. Self-contained. |
| F4 | Static YAML industry priors | Deferred per original plan. Needs data to calibrate. |
| F5 | Resumable batch execution | Checkpoint/progress file for long runs. Only needed at 500+ businesses. |
| F6 | Streamlit dashboard (Option B) | Only if Option A proves insufficient for internal use. Do not build two UIs. |

### Definition of Done
- Each F-item has its own acceptance criteria defined at implementation time. These are post-launch patches and should not block any earlier phase.

---

## Execution Notes

- **Do Phase A before Phase B.** The UI consumes the API. If the API shape is wrong, you rework the UI.
- **Do Phase C (Tavily) before Phase D (Google Places).** Tavily has a bigger quality impact. It fills the review signal gap that affects 3 of 7 scoring dimensions. Google Places improves upstream data but the current SerpAPI data is adequate.
- **Do Phase D before Phase E (batch).** Batch processing built on SerpAPI inherits its limitations. Better to stabilize sourcing first.
- **Phase F items are post-launch patches.** Do not let them creep into the critical path.

## Guardrail Rule

Before merging any change that touches enrichment, analysis, sourcing, or pipeline:
1. Run the full test suite (103+ tests).
2. If a guardrail fails, stop and diagnose.
3. New behavior touching a guarded code path requires updating or adding a guardrail.
4. Bug fix entries: draft and present for approval before adding to INTERNAL_NOTES.md.

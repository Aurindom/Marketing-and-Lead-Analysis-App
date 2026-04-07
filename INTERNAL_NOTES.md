# Ascent Intelligence â€” Internal Build Notes
**Project:** Prospect Intelligence Engine
**Last Updated:** 2026-03-31
**Status:** Pre-build â€” architecture finalized, awaiting build start

---

## Table of Contents
1. [Architecture Overview](#1-architecture-overview)
2. [Tech Stack](#2-tech-stack)
3. [Node Definitions](#3-node-definitions)
4. [ProspectState Schema](#4-prospectstate-schema)
5. [Scoring Design](#5-scoring-design)
6. [Inbound Detection Layer](#6-inbound-detection-layer)
7. [Directory Structure](#7-directory-structure)
8. [Build Sequence](#8-build-sequence)
9. [Rate Limiting & Cost](#9-rate-limiting--cost)
10. [Risk Register](#10-risk-register)
11. [CEO Requirements Reference](#11-ceo-requirements-reference)
12. [Architecture Decisions Log](#12-architecture-decisions-log)

---

## 1. Architecture Overview

**Pipeline Type:** LangGraph DAG â€” 6 nodes, static graph (no cycles in Week 1)

**Execution Flow:**
```
[Input: niche + location]
        |
        v
  NODE 1: SOURCING
  SerpAPI + Google Places API + Tavily
        |
        v
  NODE 2: ENRICHMENT
  httpx + BeautifulSoup (lxml)
        |
        |â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
        v                          v
  NODE 3: ANALYSIS          NODE 4: INBOUND DETECTION
  (parallel)                (parallel)
  Claude tool-use           Fingerprinting + Claude + Tavily reviews
  30+ signals + gaps        InboundHandlingProfile
        |                          |
        â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                   v
           NODE 5: SCORING ENGINE
           Deterministic (dims 1â€“6) + LLM (dim 7)
           scoring_weights.yaml
                   |
                   v
           NODE 6: RANKING + OUTPUT
           Tier classification + JSON/CSV
```

**Key design choices:**
- Nodes 3+4 run **in parallel** (no dependency between them)
- Scoring dims 1â€“6 are **deterministic** (not LLM-based)
- `ProspectState` is the single shared state model â€” built first
- FastAPI and Docker are **Week 2 only**

---

## 2. Tech Stack

### Core
| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11 | Runtime |
| LangGraph | latest | Pipeline orchestration |
| FastAPI | latest | API endpoint (Week 2) |
| Pydantic v2 | latest | Schema validation at every node |

### LLM
| Tool | Purpose |
|------|---------|
| Claude Sonnet 4.6 | Analysis node, Inbound reasoning, Dim 7 scoring |
| langchain-anthropic | LangChain integration |
| Anthropic Tool Use mode | Structured output (replaces raw JSON parsing) |

### Sourcing
| Tool | Purpose |
|------|---------|
| SerpAPI | Google Maps local business search |
| Google Places API | Structured business data (hours, phone, reviews) |
| Tavily | Supplementary search + review mining |

### Enrichment
| Tool | Purpose |
|------|---------|
| httpx | Async HTTP client (website crawling) |
| BeautifulSoup + lxml | HTML parsing and signal extraction |
| playwright | JS-rendered site fallback (Week 2) |

### Infrastructure
| Tool | Purpose |
|------|---------|
| asyncio.Semaphore | Rate limiting (all external APIs) |
| SQLite / JSON file | Deduplication cache (Week 2) |
| Docker | Containerization (Week 2) |
| YAML config | Externalized scoring weights |

### Output
| Format | Week |
|--------|------|
| JSON file | Week 1 |
| CSV file | Week 1 |
| FastAPI REST endpoint | Week 2 |

---

## 3. Node Definitions

### Node 1 â€” Sourcing
**Input:** niche (str), location (str), max_results (int)
**Tools:** SerpAPI, Google Places API, Tavily (fallback)
**Output:** `list[ProspectCandidate]`
**Fields per candidate:** name, address, phone, website_url, category, rating, review_count, place_id

**Notes:**
- SerpAPI queries Google Maps (local pack results)
- Google Places API fetches structured data for each result
- Tavily used if SerpAPI quota exhausted
- Deduplicate by name + address before passing to Node 2

---

### Node 2 â€” Enrichment
**Input:** `ProspectCandidate`
**Tools:** httpx, BeautifulSoup (lxml parser)
**Output:** `EnrichedProspect` (raw signals appended to ProspectState)
**Fields extracted:**
- Full page text (truncated to ~8K chars for LLM calls)
- All `<script>` src attributes (for fingerprinting)
- All form elements (type, action, placeholder text)
- Booking/CTA links detected
- Chat widget iframes or script embeds
- Operating hours copy
- Contact page presence
- Mobile responsiveness signals (meta viewport)

**Failure handling:**
- HTTP 404/503 â†’ status = "failed", log error
- Empty body (likely JS-rendered) â†’ status = "partial", log, playwright fallback in Week 2
- Cloudflare/CAPTCHA block â†’ status = "partial", log

---

### Node 3 â€” Analysis *(runs parallel with Node 4)*
**Input:** Enriched raw content from Node 2
**Tools:** Claude Sonnet 4.6 (tool-use mode)
**Output:** `AnalysisResult` (Pydantic model, 30+ fields)

**Single Claude call outputs both:**
1. Structured signals (30+ binary/categorical fields)
2. Identified revenue/operational gaps

**Key signal fields (partial list):**
- `has_online_booking: bool`
- `booking_tool: Optional[str]` (Calendly, Acuity, etc.)
- `has_contact_form: bool`
- `has_live_chat: bool`
- `chat_provider: Optional[str]`
- `cta_strength: Literal["strong", "weak", "absent"]`
- `after_hours_handling_visible: bool`
- `mobile_ux_quality: Literal["good", "poor", "unknown"]`
- `website_age_signal: Literal["modern", "outdated", "unknown"]`
- `identified_gaps: list[str]`

**Failure handling:**
- Pydantic validation fail â†’ retry with error feedback (max 2 retries)
- Still fails â†’ status = "partial", score with available data

---

### Node 4 â€” Inbound Detection *(runs parallel with Node 3)*
**Input:** Enriched raw content from Node 2
**Tools:** BeautifulSoup (fingerprinting), Claude (probabilistic), Tavily (reviews)
**Output:** `InboundHandlingProfile` (Pydantic model)

**Three-method approach:**
1. Deterministic fingerprinting (known provider script/widget patterns)
2. Claude probabilistic classification (7 possible classes)
3. Tavily review mining (voicemail/hold time signals)

**Classification classes:**
- `likely_manual_receptionist`
- `likely_voicemail_dependent`
- `likely_basic_IVR`
- `likely_AI_assisted`
- `likely_after_hours_automation`
- `likely_no_meaningful_automation`
- `unknown_insufficient_evidence`

**Fields:** detected_providers, classification, confidence (0.0â€“1.0), evidence (list), review_signals, data_coverage

---

### Node 5 â€” Scoring Engine
**Input:** `AnalysisResult` + `InboundHandlingProfile`
**Tools:** Deterministic scorer (Python) + Claude (dim 7 only)
**Output:** `ScoredProspect` with 7 dimension scores

**Scoring logic:**
- Dims 1â€“6: weighted sum of structured signals, weights from `config/scoring_weights.yaml`
- Confidence per dim = signals_found / total_possible_signals
- Dim 7 (Ascent Fit Score): Claude computes as composite judgment
- Each dimension: `{score: float, confidence: float, evidence: list[str]}`

**The 7 Dimensions:**
1. AI Receptionist Likelihood
2. Inbound Automation Maturity
3. Lead Capture Maturity
4. Booking / Intake Friction
5. Follow-Up Weakness
6. Revenue Leakage Opportunity
7. Ascent Fit Score (composite)

---

### Node 6 â€” Ranking + Output
**Input:** list of `ScoredProspect`
**Output:** Ranked JSON + CSV

**Tier classification:**
- **HOT:** Ascent Fit Score >= 7.5
- **WARM:** 5.0 <= score < 7.5
- **COLD:** score < 5.0

**Required categories:**
- High opportunity, weak inbound handling
- High opportunity, partial automation but weak conversion
- Moderate opportunity, unclear inbound handling
- Lower opportunity, stronger visible intake
- Insufficient evidence

**Output fields per record:** (see schema section below)

---

## 4. ProspectState Schema

This is built FIRST before any node. Every node reads/writes to this.

```python
from pydantic import BaseModel
from typing import Optional, Literal

class ErrorRecord(BaseModel):
    node: str
    error_type: str
    message: str

class ProspectState(BaseModel):
    # Identity
    name: str
    website: Optional[str]
    category: Optional[str]
    location: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]

    # Pipeline status
    status: Literal["pending", "enriched", "partial", "failed"] = "pending"
    errors: list[ErrorRecord] = []

    # Enrichment (raw)
    raw_text: Optional[str] = None
    detected_scripts: list[str] = []
    detected_forms: list[dict] = []

    # Analysis output (Node 3)
    signals: Optional[AnalysisResult] = None

    # Inbound detection output (Node 4)
    inbound_profile: Optional[InboundHandlingProfile] = None

    # Scoring output (Node 5)
    scores: Optional[ScoredProspect] = None

    # Output fields (Node 6)
    tier: Optional[Literal["HOT", "WARM", "COLD"]] = None
    output_category: Optional[str] = None
    suggested_outreach_angle: Optional[str] = None
```

---

## 5. Scoring Design

### Why deterministic (not LLM) for dims 1â€“6:
- LLM scoring is non-deterministic â€” same input, different score on reruns
- Cannot be calibrated based on sales feedback
- Cannot be audited ("why did this get a 6?")
- Deterministic: same inputs always produce same score
- Weights in YAML = adjustable without touching code

### Config structure (scoring_weights.yaml):
```yaml
dimensions:
  ai_receptionist_likelihood:
    weight_total: 10
    signals:
      has_ai_chat_widget: 3.0
      detected_ai_provider: 4.0
      after_hours_copy_present: 1.5
      review_mentions_ai: 1.5

  lead_capture_maturity:
    weight_total: 10
    signals:
      has_contact_form: 2.0
      has_booking_link: 3.0
      has_live_chat: 2.5
      cta_strength_strong: 2.5
  # ... etc
```

### Confidence formula:
```
confidence = signals_with_data / total_signals_in_dimension
```
Low confidence â†’ score is flagged in output but not hidden.

---

## 6. Inbound Detection Layer

### Known provider fingerprints to detect:
**AI / Chat:**
- Dialogflow: `dialogflow.com` in scripts
- Drift: `js.driftt.com`
- Intercom: `widget.intercom.io`
- Tidio: `code.tidio.co`
- LiveChat: `cdn.livechatinc.com`

**Scheduling / Booking:**
- Calendly: `calendly.com` in scripts or iframes
- Acuity: `acuityscheduling.com`
- Setmore: `setmore.com`
- Square Appointments: `squareup.com`

**Phone / Virtual Receptionist:**
- Smith.ai: text mention or widget
- Ruby Receptionists: text mention
- RingCentral: metadata or script patterns
- Grasshopper: metadata or text patterns
- Vonage: metadata patterns

**Review mining keywords (Tavily):**
- Negative signals: "voicemail", "no answer", "on hold", "wait", "missed call", "never called back"
- Positive signals: "always available", "answered right away", "24/7", "quick response", "bot"

---

## 7. Directory Structure

```
E:\Marketing and Lead Generation system\
â”œâ”€â”€ INTERNAL_NOTES.md              â† This file
â”œâ”€â”€ ascent_response_to_ceo.txt     â† CEO reply document
â”‚
â”œâ”€â”€ src/
â”‚   â”œâ”€â”€ models/
â”‚   â”‚   â””â”€â”€ prospect.py            â† ProspectState + all sub-models (BUILD FIRST)
â”‚   â”‚
â”‚   â”œâ”€â”€ graph/
â”‚   â”‚   â””â”€â”€ pipeline.py            â† LangGraph graph definition + edges
â”‚   â”‚
â”‚   â”œâ”€â”€ nodes/
â”‚   â”‚   â”œâ”€â”€ sourcing.py            â† Node 1
â”‚   â”‚   â”œâ”€â”€ enrichment.py          â† Node 2
â”‚   â”‚   â”œâ”€â”€ analysis.py            â† Node 3 (merged signal + gap analysis)
â”‚   â”‚   â”œâ”€â”€ inbound_detection.py   â† Node 4
â”‚   â”‚   â”œâ”€â”€ scoring.py             â† Node 5
â”‚   â”‚   â””â”€â”€ output.py              â† Node 6
â”‚   â”‚
â”‚   â”œâ”€â”€ scoring/
â”‚   â”‚   â””â”€â”€ engine.py              â† Deterministic weighted scorer (pure function)
â”‚   â”‚
â”‚   â””â”€â”€ utils/
â”‚       â”œâ”€â”€ rate_limiter.py        â† asyncio.Semaphore wrappers
â”‚       â”œâ”€â”€ cache.py               â† SQLite cache (Week 2)
â”‚       â””â”€â”€ output_formatter.py    â† JSON/CSV writer
â”‚
â”œâ”€â”€ config/
â”‚   â””â”€â”€ scoring_weights.yaml       â† Externalized scoring weights
â”‚
â”œâ”€â”€ output/                        â† Demo output files (JSON, CSV)
â”‚
â”œâ”€â”€ tests/                         â† (Week 2)
â”‚
â”œâ”€â”€ .env                           â† API keys (never commit)
â”œâ”€â”€ requirements.txt
â””â”€â”€ Dockerfile                     â† Week 2
```

---

## 8. Build Sequence

### Week 1 (core pipeline)
| Step | File | Description |
|------|------|-------------|
| 1 | `src/models/prospect.py` | ProspectState + all Pydantic models |
| 2 | `src/graph/pipeline.py` | LangGraph graph skeleton |
| 3 | `src/nodes/sourcing.py` | Node 1 â€” SerpAPI + Places API |
| 4 | `src/nodes/enrichment.py` | Node 2 â€” httpx + BeautifulSoup |
| 5 | `src/nodes/analysis.py` | Node 3 â€” Claude tool-use analysis |
| 6 | `src/nodes/inbound_detection.py` | Node 4 â€” fingerprinting + Claude |
| 7 | `config/scoring_weights.yaml` | Scoring weights (freeze on Day 1 of scoring) |
| 8 | `src/scoring/engine.py` | Deterministic scorer |
| 9 | `src/nodes/scoring.py` | Node 5 â€” calls engine |
| 10 | `src/nodes/output.py` | Node 6 â€” ranking + JSON/CSV |
| 11 | End-to-end run | Test with 10â€“15 real businesses |

### Week 2 (production-ready)
| Step | Description |
|------|-------------|
| 12 | playwright fallback (enrichment.py update) |
| 13 | asyncio batch processing (50+ concurrent) |
| 14 | SQLite cache (utils/cache.py) |
| 15 | FastAPI endpoint (api.py) |
| 16 | Docker container |
| 17 | Documentation + final demo |

---

## 9. Rate Limiting & Cost

### Rate Limits
| Service | Limit | Implementation |
|---------|-------|---------------|
| SerpAPI | 1 req/sec | asyncio.Semaphore(1) + 1s delay |
| Tavily | 1 req/sec | asyncio.Semaphore(1) + 1s delay |
| httpx crawling | 5 concurrent | asyncio.Semaphore(5) + 1â€“2s per domain |
| Claude API | ~40â€“60 RPM (tier 1) | asyncio.Semaphore(10) |

### Token Cost Estimate
| Item | Estimate |
|------|---------|
| Tokens per prospect (analysis) | 3Kâ€“10K input |
| Claude calls per prospect | 2 (analysis + inbound + dim 7) |
| 50 prospects per batch | ~300Kâ€“1M input tokens |
| Cost at Sonnet rate ($3/M) | $1â€“3 per batch run |
| Development iteration budget | $50â€“100 for 2 weeks |

---

## 10. Risk Register

| Risk | Severity | Mitigation |
|------|---------|-----------|
| JS-rendered sites return empty HTML | CRITICAL | Test crawl rate on Day 1 against 20 real businesses. If <70% success, add playwright immediately |
| Claude Pydantic validation failures | HIGH | Use tool-use mode. Retry with error feedback (max 2). Mark partial if still failing |
| Scoring scope creep | HIGH | Freeze weights on scoring day. Calibration is Week 3+ |
| SerpAPI sparse results in small markets | MEDIUM | Demo in major metro (Austin, NYC, Chicago). 2â€“3 verticals max |
| API token costs exceed budget | MEDIUM | Track from Day 1. Cache aggressively in Week 2 |

---

## 11. CEO Requirements Reference

**What CEO cares about most (in order):**
1. Strong logic
2. Strong signal extraction
3. Useful scoring
4. Usable output
5. Good prioritization

**NOT:** polished UI, dashboards, fancy front-end

**Output record must include at minimum:**
- business name, website, category/niche, location
- contact info found
- key visible issues
- inbound automation / AI likelihood assessment
- revenue leakage notes
- opportunity score
- confidence score or notes
- priority ranking
- suggested outreach angle

**Week 1 demo:** 10â€“15 real processed + ranked businesses
**Week 2 demo:** 50+ businesses, FastAPI, Docker, full docs

---

## 12. Architecture Decisions Log

> Record all significant design choices here with reasoning.

| Date | Decision | Reason | Decided By |
|------|---------|--------|-----------|
| 2026-03-31 | Merge Signal Extraction + Gap Analysis into one node | Both called Claude on identical input â€” redundant LLM call, doubled latency | Opus architecture review |
| 2026-03-31 | Run Analysis + Inbound Detection in parallel | No dependency between them â€” cuts per-prospect time 30â€“40% | Opus architecture review |
| 2026-03-31 | Deterministic scoring for dims 1â€“6, LLM only for dim 7 | LLM scoring is non-deterministic, non-auditable, non-calibratable | Opus architecture review |
| 2026-03-31 | FastAPI + Docker deferred to Week 2 | Premature infrastructure wastes Week 1 iteration time | Opus architecture review |
| 2026-03-31 | Google Places API added alongside SerpAPI | Structured data (hours, phone, review count) is cleaner than scraping | Opus architecture review |
| 2026-03-31 | ProspectState includes status + errors from Day 1 | Partial data must be handled gracefully â€” not crash or silently skip | Opus architecture review |
| 2026-03-31 | lxml parser for BeautifulSoup | 5â€“10x faster than default html.parser for large pages | Opus architecture review |

---

## Working Rules (added 2026-03-31)

1. Keep the software clean â€” do not over-complicate the idea
2. Human in loop â€” Claude writes code, Aurin reviews/verifies before next step
3. Brief step explanations only â€” no long write-ups, preserve context
4. Every 6â€“8 steps: save progress to memory (compacted, no bloat)
5. Follow CLAUDE.md standards at all times (strict typing, fail-fast, high-contrast UI, no dynamic Tailwind classes)
6. More rules to be added

5. Remove comment lines from all code. Code should not look AI generated.
6. Workflow: write code, ask for review, wait for approval, strip comments from that file, then move to next step.
7. Bug fixes log: when a bug is fixed, draft the full entry (root cause, file, fix) and present it to Aurin for approval before adding it to INTERNAL_NOTES.md. Only add it after explicit approval. Fill it in completely before moving to the next Week 2 step.
8. Always validate before answering. Run a sanity check on any diagnosis, recommendation, or finding before stating it. If a tool has known limitations (e.g. WebFetch doesn't execute JS), account for that before drawing conclusions. Do not present an answer and correct it after â€” get it right the first time.

## Humanizing

When asked to humanize any content:

- No em-dashes. Replace with a comma, a period, or rewrite so it flows naturally.
- No unnecessary semicolons. Two thoughts that can be two sentences should be two sentences.
- Write like someone is speaking. If it sounds stiff or corporate, rewrite it.

---

## Bug Fixes Log (added 2026-04-02)

All major bugs found during build, what caused them, and how they were fixed.

---

### BF-01 â€” LangGraph parallel fan-out error duplication
**File:** `pipeline.py`, `prospect.py`
**Plain terms:** When two parts of the pipeline ran at the same time and both hit errors, each error got added twice. The output showed duplicate error messages for every business.
**Bug:** Nodes 3 (analysis) and 4 (inbound_detection) run in parallel. Both wrote to `state.errors`. LangGraph's state merge re-applied every error from both nodes, doubling the error list on every run.
**Fix:** Added `Annotated[list, operator.add]` reducer to the `errors` field in `ProspectState`. Changed all node wrappers to return delta dicts containing only the fields they wrote, not the full state object. The reducer then safely appends only new errors.

---

### BF-02 â€” `pipeline.invoke()` returns a raw dict when reducers are present
**File:** `run_pipeline.py`
**Plain terms:** After fixing BF-01, the pipeline started returning a raw dictionary instead of the expected object. Code that read fields directly then crashed.
**Bug:** Adding a LangGraph reducer (`Annotated[list, operator.add]`) causes `graph.invoke()` to return a plain `dict` instead of a `ProspectState` object. Downstream code that accessed fields directly crashed.
**Fix:** Added `isinstance(raw, dict)` check in `run_pipeline.py`. If the return is a dict, reconstruct with `ProspectState(**raw)` before accessing fields.

---

### BF-03 â€” Confidence-adjusted tier scoring miscalculated
**File:** `src/nodes/scoring.py`, `config/scoring_weights.yaml`
**Plain terms:** The math for calculating a business's score was wrong. High-confidence signals were being amplified too much, pushing scores off-target and assigning the wrong tier.
**Bug:** `weighted_sum` was dividing by the confidence-adjusted weight instead of the raw weight. This made high-confidence scores larger and low-confidence scores smaller than intended, distorting tier assignment.
**Fix:** Changed denominator to raw weight sum only. Tier thresholds recalibrated: HOT 5.5 â†’ 5.0, WARM 4.0 â†’ 3.8, anchored on real E2E run data.

---

### BF-04 â€” Windows console crash on Unicode emoji
**File:** `run_pipeline.py`
**Plain terms:** The summary output used emoji characters. Windows terminals can't display them, so the whole CLI crashed at the end of every run.
**Bug:** Summary print included flag emoji. Windows console (cp1252 encoding) threw `UnicodeEncodeError` and crashed the CLI output.
**Fix:** Removed emoji from all summary print statements.

---

### BF-05 â€” External booking links invisible to analysis
**File:** `src/nodes/enrichment.py`, `src/models/prospect.py`, `src/nodes/analysis.py`
**Plain terms:** When a business used Calendly or ZocDoc for booking, those links lived in href attributes, not visible text. The system never saw them and said "No online booking" incorrectly.
**Bug:** Booking providers like Calendly and ZocDoc appear in `<a href>` and `<iframe src>` attributes, not in visible page text. `raw_text` only contains visible text, so `_has_booking()` and `_detect_booking_tool()` never matched them.
**Fix:** Added `_extract_hrefs()` in enrichment to collect all `href` and `iframe src` values into a single string. Added `detected_hrefs: str = ""` to `ProspectState`. Analysis now builds `all_text = raw_text + scripts + hrefs` and runs all booking/chat checks against that combined corpus.

---

### BF-06 â€” Geographic filter applied after result slicing
**File:** `src/nodes/sourcing.py`
**Plain terms:** The city filter was running after results were already cut to the requested count. If the first 5 results were all from outside Austin, you'd get 0 leads instead of 5.
**Bug:** Code was slicing results to `max_results` first, then filtering by city. If the first N results were from outside the target city, the filtered output was empty or undersized.
**Fix:** Changed to iterate all API results, apply city and size filters inline, and collect into a list with an early break at `max_results`. Filtering now happens before slicing.

---

### BF-07 â€” `quality_gate` overwrote upstream quality flags
**File:** `src/nodes/quality_gate.py`
**Plain terms:** The quality gate was resetting the flag list every time it ran. Any flags set earlier in the pipeline (like DATA_BLOCKED) were wiped out silently.
**Bug:** Quality gate initialized `flags = []` and then appended its own flags. Any flags set by `pre_score_filter` (e.g. DATA_BLOCKED) were silently discarded.
**Fix:** Changed to `flags = list(state.quality_flags)` so the gate preserves upstream flags and only appends new ones.

---

### BF-08 â€” Script tags destroyed before extraction
**File:** `src/nodes/enrichment.py`
**Plain terms:** The code was reading script tags and then deleting them in the wrong order. Scripts got deleted before they were read, so the detected scripts list came back empty.
**Bug:** `_extract_text()` calls `tag.decompose()` on every `<script>` tag to strip them from visible text. If `_extract_text()` ran before `_extract_scripts()`, the script tags were gone and `detected_scripts` came back empty.
**Fix:** Reordered `_apply_soup_to_state()` so scripts and hrefs are extracted first, then text last. `_extract_text()` still decomposes tags â€” it just does it after everything else has read them.

---

### BF-09 â€” Sourcing re-queried Google Maps for already-resolved candidates
**File:** `src/nodes/sourcing.py`
**Plain terms:** The pipeline was re-querying Google Maps for businesses that already had their data. This wasted API credits and could overwrite good data with a fresh (sometimes different) result.
**Bug:** `run_pipeline.py` pre-resolves candidates (website, place_id) before passing them into the pipeline. The sourcing node would re-run the Maps lookup and overwrite the resolved data with a fresh API call.
**Fix:** Added early return guard at the top of `sourcing.run()`: if `state.candidate.website or state.candidate.place_id`, return immediately without querying.

---

### BF-10 â€” `output_category` was null in saved JSON
**File:** `src/nodes/output.py`
**Plain terms:** Every output JSON file had output_category as null. The field was being set after the JSON was already built, so it never made it into the file.
**Bug:** `state.output_category` was set after `_build_record()` was called. The JSON was built from state before the category was assigned, so every output file had `"output_category": null`.
**Fix:** Moved `state.output_category = ...` assignment to before the `_build_record()` call.

---

### BF-11 â€” Deprecated `datetime.utcnow()` usage
**File:** `src/nodes/output.py`
**Plain terms:** A Python function for getting the current time was deprecated. It still worked but would break in a future Python version.
**Bug:** Python 3.12 deprecates `datetime.utcnow()`. It still works but emits a `DeprecationWarning` and will be removed in a future version.
**Fix:** Replaced all `datetime.utcnow()` calls with `datetime.now(timezone.utc)`.

---

### BF-12 â€” JS-rendered sites returned < 200 chars, scored on empty data
**File:** `src/nodes/enrichment.py`
**Plain terms:** Websites built with React or Next.js serve a nearly empty HTML page that loads content via JavaScript. Our scraper only saw the empty shell and scored businesses as COLD based on nothing.
**Bug:** Sites built with React, Next.js, Vue etc. serve a near-empty HTML shell. `raw_text` would be under 200 characters. Analysis ran on this empty text and flagged nearly every signal as absent, producing false COLD scores.
**Fix:** Added `_needs_browser_fallback()`: triggers Playwright if `raw_text < 200 chars`, or `word_count < 120` and JS framework hints detected in scripts/title/meta. Full re-extraction on Playwright soup.

---

### BF-13 â€” Contact form detection was text-only, missed builder forms
**File:** `src/nodes/enrichment.py`, `src/models/prospect.py`, `src/nodes/analysis.py`
**Plain terms:** Contact form detection only looked at visible text. Businesses using Elementor, WPForms, or Gravity Forms had no visible form text â€” their forms are built by plugins. Nearly every business got flagged "No contact form" incorrectly.
**Bug:** `_has_contact_form()` looked for keyword phrases like "contact form" or "your email" in `raw_text`. Page builders (Elementor, WPForms, Gravity Forms) render forms via plugin markup that produces no matching visible text. Nearly every business with a builder-based form got flagged as "No contact form."
**Fix:** Enrichment now extracts three DOM signals before text decomposition: `has_form_tag` (native `<form>` or builder selector match), `has_email_input` (`input[type='email']` or name/id containing "email"), `has_submit_control` (submit button or input). All three stored on `ProspectState`. Analysis checks DOM signals first; text keywords are a fallback only.

---

### BF-14 â€” 403/429/503 blocks never reached Playwright
**File:** `src/nodes/enrichment.py`
**Plain terms:** When a website blocked our scraper with a 403 error, we gave up immediately. We never tried the browser fallback for blocked sites â€” only for empty ones.
**Bug:** If httpx got a 403/429/503 response, the exception was logged and the node returned immediately. Playwright was only triggered for thin-content fallback after a successful httpx fetch â€” never for blocked fetches.
**Fix:** Added `_should_try_playwright_on_fetch_error()`: if the exception is `httpx.HTTPStatusError` with status in `{403, 429, 503}`, Playwright fires immediately before returning. Added `fetched_with_playwright` flag to prevent double-Playwright (httpx 403 â†’ Playwright â†’ skip thin-content check). Both errors logged if Playwright also fails.

---

### BF-15 â€” Error duplication across all sequential nodes
**File:** `pipeline.py`
**Plain terms:** The fix for BF-01 only covered the two parallel nodes. The other five nodes were still returning full state, so errors kept accumulating and repeating with each step.
**Bug:** Initial fix (BF-01) converted only parallel nodes (analysis, inbound) to delta dicts. The 5 sequential nodes (pre_score_filter, merge, scoring, quality_gate, output) still returned full `ProspectState`. Because the `Annotated[list, operator.add]` reducer applies to every node, returning full state caused the accumulated error list to be re-added on every pass â€” errors would appear 2Ã—, 4Ã—, 8Ã— depending on how many nodes had run.
**Fix:** Converted all 5 remaining wrappers to delta dicts. `scoring`, `quality_gate`, and `output` return `errors[errors_before:]`, while `pre_score_filter` and `merge` explicitly return `errors: []` (they do not append errors).

---

### BF-16 â€” Proxy env vars causing silent 0-result failures
**File:** `run_pipeline.py`, `src/nodes/sourcing.py`
**Plain terms:** Old proxy settings in the shell were silently routing API requests through a dead proxy. Every sourcing request timed out quietly and returned zero businesses with no error printed.
**Bug:** Shell proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`) were set from a prior session. httpx routed SerpAPI requests through the dead proxy, timing out silently. `search_businesses()` caught the exception and returned `[]` without printing anything. The pipeline ran cleanly but found zero businesses.
**Fix:** Added `_check_proxy_env()` in `run_pipeline.py`: detects and clears proxy env vars at startup with a printed warning. `search_businesses()` now prints the error type and message before returning `[]`.

---

### BF-17 â€” Playwright WinError 5 spam on Windows
**File:** `src/nodes/enrichment.py`
**Plain terms:** Every time Playwright tried to launch on Windows, it crashed with a permission error. Multiple threads kept retrying in parallel, flooding the console with noise.
**Bug:** Chromium requires sandbox privileges it doesn't have on Windows without admin rights. Every Playwright attempt raised `PermissionError: [WinError 5] Access is denied`, filling the console with noise. The circuit breaker (`_playwright_disabled`) didn't prevent retries across threads â€” a second thread could attempt launch while the first was failing.
**Fix:** Added `threading.Lock` around the entire flag-check + launch block. Only one thread ever attempts Playwright. Added `PLAYWRIGHT_ENABLED` env kill switch (`_is_playwright_enabled()`). Set to `false` locally â€” Playwright never attempted, WinError 5 fully gone. Also added `contextlib.redirect_stderr(devnull)` inside the lock to suppress async noise on first blocked launch.

---

### BF-18 â€” DATA_BLOCKED businesses mixed with COLD in output
**File:** `src/nodes/pre_score_filter.py`, `run_pipeline.py`
**Plain terms:** Businesses whose websites blocked our crawler looked identical to genuinely cold leads. Sales reps had no way to tell if COLD meant "bad lead" or "we couldn't reach the site."
**Bug:** Businesses that were HTTP 403-blocked and couldn't be recovered by Playwright were scored COLD because their `raw_text` was empty. They looked identical to genuinely cold leads in the output. Sales reps couldn't distinguish "bad lead" from "website blocked our crawler."
**Fix:** Added `_is_data_blocked()` in `pre_score_filter.py`: checks for HTTP 403/429/503 error AND `playwright_fallback_failed` both present. Runs before the insufficient-content check. Sets flag `"Data blocked (HTTP 403/Playwright unavailable) - manual review needed"`, tier COLD, skip_scoring True. CLI summary shows DATA_BLOCKED as a separate section.

---

### BF-19 â€” Trust signals false negative (credentials and schema markup)
**File:** `src/nodes/analysis.py`
**Plain terms:** Dentists with "DDS" in their name or attorneys with "Esq." were being flagged "No trust signals." The system only knew basic keywords â€” professional credentials weren't on the list.
**Bug:** `TRUST_SIGNALS` was a flat keyword list (`bbb`, `accredited`, `licensed` etc). Businesses with professional credentials (DDS, DMD, Esq, JD) or structured data schema markup (`@type: Dentist`) were flagged "No trust signals" even though strong trust evidence existed.
**Fix:** Added `CREDENTIAL_PATTERNS` (regex matching DDS, DMD, Esq, JD, board-certified, state-licensed) and `SCHEMA_TRUST_HINTS` (JSON-LD type strings for dentist, physician, attorney etc). `_has_trust_badges()` now checks all three: keyword list, schema hints, credential patterns.

---

### BF-20 â€” Contact form false negative (form on internal page, not homepage)
**File:** `src/nodes/enrichment.py`, `tests/test_regressions.py`
**Plain terms:** The system only checked the homepage for a contact form. Many businesses put their form on /contact. The homepage had no form, so the gap was flagged incorrectly.
**Bug:** Enrichment fetches only the homepage URL. Some businesses (South Austin Dentist, Divi theme) place their contact form on `/contact` or `/contact-us`. Homepage parse returns `has_form_tag=False`, so the gap "No contact form" is a false negative even though a form clearly exists on the site.
**Fix:** Added bounded internal-page form fallback. If homepage has no form, enrichment checks up to 4 same-domain paths (`/contact-us`, `/contact`, `/request-an-appointment`, `/book`) with 10s timeout each, best-effort, no recursion, and stops at first form hit. When found, enrichment sets `has_form_tag`, `has_email_input`, and `has_submit_control` from that internal page so analysis no longer emits a false "No contact form" gap.

---

### BF-21 â€” Misleading gap display for skipped leads in CLI summary
**File:** `run_pipeline.py`
**Plain terms:** Businesses skipped due to bad data still showed gap lists in the CLI â€” gaps derived from empty defaults, not real analysis. Looked like they had been fully scored.
**Bug:** When `skip_scoring=True`, summary still printed default gap values from insufficient-content paths, making skipped leads look fully analyzed.
**Fix:** CLI summary now prints `Gaps: N/A (insufficient web data)` for skipped leads and `Gaps: N/A (no web data retrieved)` for `DATA_BLOCKED` leads.

---

### BF-22 â€” `contact_form_page` dropped in enrichment pipeline wrapper
**Files:** `src/graph/pipeline.py`
**Plain terms:** We added a field to track which page a contact form was found on, but forgot to pass it through the pipeline. It was always null in the output regardless of what enrichment found.
**Bug:** `contact_form_page` was added to `ProspectState` to record which page a form was found on (homepage vs `/contact` etc.), but the `enrichment_node` delta dict in `pipeline.py` did not include it. LangGraph merge never wrote the field downstream, so every business had `contact_form_page=None` regardless of what enrichment found.
**Fix:** Added `"contact_form_page": result.contact_form_page` to the `enrichment_node` return dict (pipeline.py line 60). Field now propagates correctly through the graph.
**Regression coverage:** `test_enrichment_wrapper_returns_only_new_errors` in `tests/test_pipeline_wrappers.py` now asserts `contact_form_page` is propagated in the enrichment wrapper delta.

---

### BF-23 â€” Text fallback in `_has_contact_form()` too broad, caused false positives
**Files:** `src/nodes/analysis.py`
**Plain terms:** Phrases like "your name" and "your email" were used to detect contact forms. Those phrases appear everywhere on a website â€” testimonials, about pages, newsletters. Businesses with no real form had their "No contact form" gap suppressed incorrectly.
**Bug:** The text-only fallback in `_has_contact_form()` included phrases like `"your name"` and `"your email"`. These appear on testimonial sections, about pages, and general page copy â€” not just contact forms. Businesses with no real form (e.g. The Local Dentist) triggered the fallback, suppressing the "No contact form" gap incorrectly.
**Fix:** Removed `"your name"`, `"your email"`, and `"send message"` from the fallback keyword list. Kept only high-specificity phrases: `"contact form"`, `"contact us form"`, `"fill out the form below"`, `"submit the form below"`, `"request an appointment form"`. DOM signals remain the primary path; text fallback is now a last resort only.
**Regression test:** `test_contact_form_not_detected_from_generic_name_phrase` in `tests/test_analysis.py`.

---

### BF-24 â€” Sourcing under-delivers on max_results due to missing pagination
**Files:** `src/nodes/sourcing.py`, `api.py`
**Plain terms:** When you requested 8 leads, you consistently got 6. The API only returns 20 results per page and our size/city filters reduced that pool further. We never fetched a second page, so real qualifying businesses were silently missed.
**Bug:** SerpAPI Google Maps returns at most 20 results per request regardless of the `num` parameter. The code sent `num: 40` which was silently ignored. After geographic and review-count filters ran on ~20 raw results, the pool was too thin to satisfy the requested `max_results`. Requesting 8 leads consistently returned 6 â€” real qualifying businesses on page 2 of Maps results were never seen.
**Fix:** Added pagination loop in `_search_google_maps()`. Fetches up to 3 pages using `start: page * 20` offset. Stops when `max_results` is satisfied or a page returns no results. Removed the no-op `num: 40` param. Made the review cap configurable via `max_review_count: int = 500` on both `search_businesses()` and `_search_google_maps()`. Exposed `max_review_count` as an optional field on `AnalyzeRequest` in `api.py` (default 500).
**Known behavior:** Early stop only triggers on an empty page, not a short page (< 20 results). A short final page may still fire one extra API call. Not breaking.
**Verified:** `search_businesses("dental clinic", "Austin, TX", max_results=8)` now returns 8 leads.

---

### BF-25 - JS-rendered internal contact pages missed after homepage fallback
**Files:** `src/nodes/enrichment.py`, `tests/test_regressions.py`
**Plain terms:** Even after adding internal-page contact checks, some sites still showed "No contact form" because internal pages were JS-rendered and the crawler only used plain HTTP for those paths.
**Bug:** Internal-page fallback (`/contact-us`, `/contact`, etc.) originally used `_fetch_response()` only. If homepage required Playwright (403 or JS shell), internal pages could still be JS-rendered and return formless HTML shells via httpx, causing false "No contact form" gaps.
**Fix:** Internal-page crawl now propagates Playwright mode from homepage fetch and uses `_playwright_fetch_checked()` so domain redirects are validated before trusting page content. Also fixed nav-link fallback to normalize relative hrefs like `href="schedule-appointment"` into `/schedule-appointment` so those paths are not skipped.
**Regression coverage:** Added `test_enrichment_nav_link_fallback_handles_relative_href_without_leading_slash`, `test_enrichment_internal_crawl_uses_playwright_when_homepage_was_js_rendered`, and `test_enrichment_internal_playwright_ignores_cross_domain_redirect`.

---

### BF-26 - Internal JS diagnostics dropped by enrichment wrapper
**Files:** `src/graph/pipeline.py`, `tests/test_pipeline_wrappers.py`
**Plain terms:** The enrichment node correctly detected internal JS-shell escalation, but those diagnostics were not included in the LangGraph delta return. They disappeared before output.
**Bug:** `internal_js_shell_detected` and `internal_playwright_used` existed on `ProspectState` and were set by enrichment, but `enrichment_node` did not return them in its delta dict. Real pipeline runs dropped both values.
**Fix:** Added both fields to `enrichment_node` return dict. Updated `test_enrichment_wrapper_returns_only_new_errors` to assert both keys are propagated.

---

### BF-27 - Regression tests launched real Playwright unexpectedly
**Files:** `tests/test_regressions.py`
**Plain terms:** Some older regression tests started triggering internal contact-page Playwright calls after C2 changes. On Windows this produced noisy `WinError 5` traces during otherwise passing test runs.
**Bug:** Tests mocking `_fetch_with_playwright` but not `_playwright_fetch_checked` were no longer hermetic once internal-page crawl began using checked Playwright fetches.
**Fix:** Patched legacy tests to mock `_playwright_fetch_checked` (`return_value=None`) where internal paths are intentionally out of scope. Regression suite now runs without background Playwright launch noise.

---

### BF-28 - Internal contact-path fetch failures skipped browser recovery
**Files:** `src/nodes/enrichment.py`, `tests/test_regressions.py`
**Plain terms:** On sites like Righttime Plumbing, the contact page exists, but when plain HTTP fetch to `/contact-us` failed (blocked/connection error), the code returned early and never tried Playwright as the fetcher for that path. Output then showed `contact_form_status="unknown"` and `contact_form_page=null`.
**Bug:** `_try_path()` treated blocked/internal fetch errors as terminal for the path in the wrong branch. This prevented Playwright recovery on fixed fallback paths when HTTP failed before HTML parse.
**Fix:** Restructured `_try_path()` to use status-aware flow: `404/410` = clean negative, blocked/connect errors on fixed fallback paths = attempt `_playwright_fetch_checked()` before giving up, nav-link paths remain bounded with no Playwright escalation. Added regression coverage for `404 -> missing`, `403 -> unknown`, and `ConnectError -> unknown`.
**Known runtime limitation:** On local Windows, if Playwright launch itself fails (`WinError 5`), status remains `unknown` by design. Docker/Linux runtime is the reliable path for deterministic browser fallback.

---

### BF-29 - Internal-page booking text not merged, causing false "No online booking"
**Files:** `src/nodes/enrichment.py`, `tests/test_regressions.py`
**Plain terms:** United Service Specialists showed "No online booking" even though `/contact-us` visibly had "Schedule an Appointment Online / Schedule Now". The system was seeing internal scripts/links but not that internal visible text.
**Bug:** `_merge_internal_evidence()` merged internal scripts and hrefs only. Internal page visible text was not appended to `state.raw_text`, so phrase-based booking detection could miss booking CTAs that exist only on `/contact-us`.
**Fix:** Extended `_merge_internal_evidence()` to append extracted internal page text to `state.raw_text` (combined evidence corpus). Analysis then sees internal booking language and no longer emits false booking gaps for this pattern.
**Regression coverage:** `test_internal_page_booking_signal_merges_into_analysis` verifies internal booking evidence is reflected in analysis and suppresses "No online booking".

---

### BF-30 - Over-eager internal Playwright escalation caused false `unknown` contact status
**Files:** `src/nodes/enrichment.py`, `src/models/prospect.py`, `src/graph/pipeline.py`, `src/nodes/output.py`, `api.py`, `tests/test_regressions.py`
**Plain terms:** Internal contact pages that returned normal static HTML with no `<form>` still triggered Playwright. On sites like Righttime, browser wait mode timed out and incorrectly converted a clean "missing form" case into `contact_form_status="unknown"`.
**Bug:** In `_try_path()`, the `_is_internal_js_shell()` check was diagnostic-only and did not gate the internal Playwright call. Any internal 200 page without a detected form could escalate to Playwright and fail on `networkidle`, setting `contact_form_check_had_errors=True` unnecessarily.
**Fix:** Tightened escalation rules and diagnostics:
- Internal Playwright escalation now runs only on bounded conditions (blocked fetch path or JS-shell-like internal pages).
- `_playwright_fetch_checked()` now uses two-stage navigation: `domcontentloaded` first, then `networkidle` only when stage-1 content still looks like a JS shell.
- If stage-2 (`networkidle`) times out, stage-1 HTML is returned (graceful degradation) instead of forcing uncertainty.
- Cross-domain internal redirects now raise a dedicated `CrossDomainRedirectError` for explicit reason attribution.
- Added `internal_contact_check_reason` with precedence-safe writes (do not overwrite first meaningful reason), including reason codes like `no_form_static`, `plugin_markers_only`, `playwright_timeout`, `playwright_error`, `cross_domain_redirect`, `blocked`.
- Propagated `internal_contact_check_reason` through pipeline delta, output diagnostics, and API diagnostics.
**Regression coverage:** Added/updated `test_static_internal_page_no_form_sets_reason_not_unknown`, `test_playwright_timeout_on_internal_page_sets_reason_and_unknown`, and `test_internal_contact_check_reason_in_output_diagnostics`.
**Runtime validation:** Docker rebuild + live `/analyze` recheck confirms Righttime now returns `contact_form_status="missing"` with reason `plugin_markers_only` (no timeout-driven `unknown`).

### BF-31 - 503 test swallowed unrelated exceptions and used a redundant app instance
**Files:** `tests/test_batch_api.py`
**Plain terms:** The test for the 503 "pipeline not ready" guard was written with a `try/except Exception: pass` block, which would silently pass even if the test failed for an unrelated reason. It also created a second app/client instance instead of reusing the shared `client` fixture.
**Bug:** `test_batch_pipeline_not_ready_returns_503` patched `build_pipeline` to raise and wrapped the whole assertion in a bare `except Exception: pass`. Any unrelated failure (import error, assertion error, framework error) would be swallowed and the test would appear to pass.
**Fix:** Reused the `client` fixture; replaced `build_pipeline` side-effect approach with a direct `patch("api._pipeline", None)` during the request. Added explicit assertions on both `status_code == 503` and the exact `detail` message.
**Regression coverage:** `test_batch_pipeline_not_ready_returns_503` — 5 passed in `tests/test_batch_api.py`.

---

## Regression Guardrails (added 2026-04-02)

These tests act as safety rails. They must pass before any enrichment, analysis, or pipeline change is merged.

| Test | Plain terms | Technical detail |
|------|-------------|-----------------|
| `test_enrichment_preserves_scripts_while_extracting_text` | Scripts must be read before text cleanup destroys them. | `_extract_text()` calls `tag.decompose()` on script tags, mutating the tree. Ensures extraction order is correct. |
| `test_enrichment_uses_browser_fallback_on_js_shell` | If a page barely has any content, launch the browser to get the real version. | Thin JS-rendered pages (< 200 chars or < 120 words with JS framework hints) must trigger Playwright fallback. |
| `test_enrichment_detects_divi_style_form_markers` | Divi form classes have numbers appended â€” make sure we still detect them. | Divi generates `et_pb_contact_form_0`. CSS selectors like `.et_pb_contact_form` don't match. Ensures regex matching catches all variants. |
| `test_enrichment_uses_playwright_when_http_fetch_is_blocked` | If a site blocks our regular fetch, try the browser before giving up. | 403/429/503 HTTP errors must route to Playwright before returning. Guards against the status-code check being broken. |
| `test_sourcing_skips_lookup_when_candidate_already_resolved` | Don't re-query Google Maps if we already have the business data. | If a candidate already has `website` or `place_id`, sourcing must return immediately. Guards against duplicate API calls. |
| `test_analysis_contact_form_detected_from_dom_signals` | A real form in the HTML must clear the "No contact form" gap. | DOM signals (`has_form_tag`, `has_email_input`, `has_submit_control`) must suppress the gap. Guards against reverting to text-only detection. |
| `test_pre_score_filter_marks_data_blocked` | Blocked sites must be labeled DATA_BLOCKED, not just COLD. | HTTP 403 + Playwright failure together must set the DATA_BLOCKED flag and skip scoring. |
| `test_playwright_kill_switch_disables_launch_attempt` | Setting PLAYWRIGHT_ENABLED=false must completely stop any browser launch attempt. | Guards against the env kill switch being bypassed and causing WinError 5 noise on Windows. |
| `test_output_record_contains_output_category` | Every saved JSON must have an output category and a diagnostics block. | Guards against null output_category, which was a real bug where it was set after `_build_record()`. |
| `test_enrichment_finds_contact_form_on_internal_contact_page` | If the homepage has no form but /contact does, we should still detect it. | Guards the internal-path fallback so "No contact form" is not emitted when the form is on an internal page. |
| `test_enrichment_nav_link_fallback_handles_relative_href_without_leading_slash` | Contact links without a leading slash should still be crawled. | Guards nav parsing for `href="schedule-appointment"` so relative paths are normalized and checked. |
| `test_enrichment_internal_crawl_uses_playwright_when_homepage_was_js_rendered` | If homepage needed Playwright, internal contact-page crawl must use it too. | Guards against false negatives where internal pages are JS-rendered and httpx sees no form. |
| `test_enrichment_internal_playwright_ignores_cross_domain_redirect` | Internal Playwright crawl must not trust redirected off-domain pages. | Guards against false positives from cross-domain redirects during internal contact-page checks. |
| `test_enrichment_internal_js_shell_escalates_to_playwright_and_finds_form` | If an internal page is a JS shell, do one bounded Playwright escalation. | Guards the internal JS-shell escalation path and confirms form detection is recovered. |
| `test_enrichment_non_js_internal_page_without_form_does_not_trigger_playwright` | Non-JS internal pages with no form should not trigger Playwright. | Guards bounded behavior and prevents unnecessary browser escalation. |
| `test_static_internal_page_no_form_sets_reason_not_unknown` | Static no-form internal pages should be treated as missing, not uncertain. | Guards that internal Playwright does not fire on non-JS 200 pages and reason is `no_form_static`. |
| `test_playwright_timeout_on_internal_page_sets_reason_and_unknown` | True Playwright timeout should still be explicit uncertainty. | Guards timeout classification path with `internal_contact_check_reason="playwright_timeout"` and `contact_form_status="unknown"`. |
| `test_internal_contact_check_reason_in_output_diagnostics` | Internal contact-check reason must be visible to operators. | Guards diagnostics propagation of `internal_contact_check_reason` into output JSON. |
| `test_enrichment_wrapper_returns_only_new_errors` | Enrichment wrapper must propagate new diagnostics fields through LangGraph. | Guards delta propagation for `contact_form_page`, `internal_js_shell_detected`, and `internal_playwright_used`. |

### What guardrails are for

Guardrails are regression tests added after a real bug was found and fixed. They exist so the same class of bug can't silently reappear. Before changing any node in enrichment, analysis, or pipeline:

1. Run the full test suite.
2. If a guardrail fails, the change broke a previously fixed behavior â€” stop and diagnose before continuing.
3. Adding new behavior that touches a guarded code path requires either updating the existing guardrail or adding a new one.

---

## Open False Negatives (as of 2026-04-03)

### Contact form on internal page, not homepage

**Status:** Resolved.

**Resolved by:** BF-20, BF-25, and BF-26.

**What changed:**
- Internal-path fallback checks bounded same-domain paths when homepage has no form.
- Nav-link fallback supports both absolute and relative href paths.
- Playwright internal crawl uses domain-checked fetch (`_playwright_fetch_checked`) and ignores off-domain redirects.
- Internal JS-shell escalation performs one bounded Playwright retry only when needed.
- New diagnostics fields (`internal_js_shell_detected`, `internal_playwright_used`) propagate through pipeline and output.

**Guardrails now covering this area:**
- `test_enrichment_finds_contact_form_on_internal_contact_page`
- `test_enrichment_nav_link_fallback_handles_relative_href_without_leading_slash`
- `test_enrichment_internal_crawl_uses_playwright_when_homepage_was_js_rendered`
- `test_enrichment_internal_playwright_ignores_cross_domain_redirect`
- `test_enrichment_internal_js_shell_escalates_to_playwright_and_finds_form`
- `test_enrichment_non_js_internal_page_without_form_does_not_trigger_playwright`

---

## Post-Demo Patches (do not build before demo)

### P1 â€” Replace regex review mining with LLM extraction

**File:** `src/nodes/inbound_detection.py` â€” `_mine_reviews()`

**Problem:** Hardcoded regex patterns miss the majority of real review language. Phrases like "I've been trying to get someone on the phone for three days" or "front desk never picks up" don't match any pattern. Recall is low even when Tavily returns good content.

**Recommended fix:** When external review content is available (Tavily returned results), pass the combined snippet text to Claude with a structured prompt asking it to extract quotes that indicate poor or strong inbound handling. Keep the existing regex as a zero-cost fallback when no external content exists.

**Why deferred:** Adds a Claude API call per business. Fine at demo scale, needs cost/latency measurement before setting as default at batch scale (50+ businesses).

**Expected impact:** `review_signals` populates for most businesses with external reviews, `data_coverage` upgrades to "sufficient" more often, scoring dimensions 1/2/6 get real evidence instead of empty arrays.

---

## Accuracy + Performance Fix Pack (Parts 1-5) - 2026-04-06

This section records the 5-part fix set implemented for contact-form accuracy and sourcing quality, with performance-safe behavior.

### Part 1 - Capture contact page existence (done)

- Added `contact_page_url` to `ProspectState` and reset it at the start of enrichment runs.
- In enrichment internal path checks, set `contact_page_url` when a contact-relevant page fetch succeeds, even when no `<form>` is found.
- Prefer canonical resolved URL (`response.url`) over the raw target path.
- Wired through pipeline delta, API response, and output record.

**Accuracy impact:** distinguishes "no form on contact page" from "no contact page exists".  
**Performance impact:** no extra crawl stage required; reuses existing path checks.

### Part 2 - Fix gap wording semantics (done)

- Analysis gap logic now branches for `contact_form_status == "missing"`:
  - with `contact_page_url`: `No web contact form detected (contact page exists)`
  - without `contact_page_url`: `No contact form or contact page detected`

**Accuracy impact:** removes hard false-negative wording for phone-first sites.  
**Performance impact:** string/logic change only.

### Part 3 - Prevent scoring distortion (done)

- In scoring, missing-form penalties are applied only when `contact_page_url is None`:
  - `lead_capture_maturity` +2.5 missing-form penalty gated by absence of contact page.
  - `booking_intake_friction` +2.0 "No form or booking - phone-only intake" penalty gated by absence of contact page.

**Accuracy impact:** reduces unfair penalties for businesses with reachable contact pages but no web form.  
**Performance impact:** deterministic branch logic only (no added external calls).

### Part 4 - Deduplicate sourcing results (done)

- Added `seen` set in sourcing before pagination loop.
- Dedup key:
  - primary: `place_id`
  - fallback: `(normalized_name, normalized_website)` when `place_id` missing
- Duplicate candidates are skipped before append.

**Accuracy impact:** prevents duplicate businesses from inflating output and rankings.  
**Performance impact:** fewer downstream enrich/analyze/score operations for duplicate entries.

### Part 5 - Regression coverage (done)

Added regression tests for:
1. `contact_page_url` set when contact path exists without form.
2. Hard gap suppression when contact page exists.
3. Hard gap emission when neither form nor contact page exists.
4. Scoring penalties softened when contact page exists.
5. Sourcing dedup by `place_id` and by name+website fallback.

Runtime validation:
- Docker rebuild + tests completed successfully.
- Full suite status: `142 passed, 3 skipped`.

### Implementation rules reaffirmed

- No business-name, niche, location, or URL hardcoding in production logic.
- Conditions are state-driven (`contact_form_status`, `contact_page_url`, `place_id`, normalized name/website).
- Test fixtures remain synthetic and isolated from production branches.


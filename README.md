# Ascent Intelligence — Prospect Intelligence Engine

An AI pipeline that finds local businesses, analyzes their digital presence, and ranks them by how ready they are to buy. Sales reps get a prioritized list of leads — HOT, WARM, or COLD — with the reasoning behind every score.

---

## What It Does

You give it a niche and a location. It searches Google Maps, crawls each business's website, runs AI analysis, and returns a ranked list of prospects with scores across 7 dimensions. Each result tells you not just who to call, but why.

**Input:**
```json
{ "niche": "plumbing", "location": "Phoenix, AZ", "max_results": 10 }
```

**Output:** Ranked JSON with tier, score breakdown, identified gaps, and a suggested outreach angle per business.

---

## Lead Tiers

| Tier | Composite Score | What It Means |
|------|----------------|---------------|
| HOT  | >= 5.0         | High opportunity. Weak or missing inbound automation. Ready to hear a pitch. |
| WARM | 3.8 – 4.99     | Moderate fit. Partial automation but visible gaps. Worth outreach with context. |
| COLD | < 3.8          | Either well-covered already or insufficient evidence to justify a call. |

Tier is a confidence-weighted composite across all 7 scoring dimensions. A single missing signal does not make a lead COLD — the pipeline weighs everything together.

### Special States

| State | Meaning |
|-------|---------|
| `NO_WEBSITE` | Business exists on Google Maps but has no website. Not scored. Ranked by review count and rating (HIGH / MEDIUM / LOW opportunity bands). Call-first workflow. |
| `DATA_BLOCKED` | Both HTTP and Playwright fetches failed. Site is behind anti-bot protection. Not scored or tiered. Requires manual visit. |

---

## Architecture

The pipeline is a **LangGraph DAG** — 6 nodes, executed in sequence with Nodes 3 and 4 running in parallel.

```
[niche + location]
        |
        v
  NODE 1: SOURCING
  SerpAPI → Google Maps local results
  Dedup by place_id → website → name + city
        |
        v
  NODE 2: ENRICHMENT
  httpx + BeautifulSoup → full page text, scripts, forms
  Playwright fallback for JS-rendered or blocked sites
        |
        |─────────────────────────────────┐
        v                                 v
  NODE 3: ANALYSIS              NODE 4: INBOUND DETECTION
  (parallel)                    (parallel)
  LLM agent tool-use            Fingerprinting + LLM agent + Tavily reviews
  30+ binary/categorical        Classifies how the business handles
  signals + gap identification  inbound calls and leads
        |                                 |
        └──────────────┬──────────────────┘
                       v
             NODE 5: SCORING ENGINE
             7 dimensions, deterministic (dims 1-6) + LLM agent (dim 7)
             Weights loaded from scoring_weights.yaml
                       |
                       v
             NODE 6: RANKING + OUTPUT
             Tier classification, priority rank, outreach angle
             JSONL audit log written per record
```

---

## The 6 Pipeline Nodes

### Node 1 — Sourcing
Searches Google Maps via SerpAPI. Up to 3 pages (60 candidates) per query. Results are deduplicated using a 3-tier key hierarchy: `place_id` first, then normalized website URL, then normalized name + city. Candidates with review counts above `max_review_count` are filtered out to avoid surfacing established chains.

### Node 2 — Enrichment
Fetches each business website using `httpx`. Extracts page text, `<script>` sources, form elements, booking/CTA links, and chat widget embeds. If the site is JS-rendered or returns a block response (403/429/503), it falls back to Playwright (headless Chromium) to retrieve the rendered DOM. Sites that fail both paths are marked `DATA_BLOCKED`.

### Node 3 — Analysis
A single LLM agent call in tool-use mode. Outputs 30+ structured signals from the enriched page content — booking tool presence, contact form status, CTA strength, mobile UX quality, after-hours copy, and a list of identified revenue/operational gaps. Pydantic validates the output; failed validation triggers one retry before falling back to partial scoring.

### Node 4 — Inbound Detection
Runs in parallel with Node 3. Three-method approach:

1. **Deterministic fingerprinting** — matches known provider script patterns (Calendly, Acuity, Drift, Intercom, Tidio, Smith.ai, RingCentral, etc.)
2. **LLM probabilistic classification** — classifies the inbound setup into one of 7 categories
3. **Tavily review mining** — searches for review signals like "voicemail", "no answer", "wait time", "answered right away"

**Inbound classification categories:**
- `likely_manual_receptionist`
- `likely_voicemail_dependent`
- `likely_basic_IVR`
- `likely_AI_assisted`
- `likely_after_hours_automation`
- `likely_no_meaningful_automation`
- `unknown_insufficient_evidence`

### Node 5 — Scoring Engine
Scores across 7 dimensions. Dimensions 1–6 are fully deterministic — same input always produces the same score. Dimension 7 (Ascent Fit) is a composite LLM judgment. All weights are externalized in `config/scoring_weights.yaml` and can be tuned without touching code.

**The 7 Dimensions:**

| # | Dimension | Weight | What It Measures |
|---|-----------|--------|-----------------|
| 1 | AI Receptionist Likelihood | 20% | How likely the business would benefit from an AI receptionist |
| 2 | Inbound Automation Maturity | 15% | How automated (or not) their current inbound flow is |
| 3 | Lead Capture Maturity | 15% | Forms, booking links, CTA strength, email capture |
| 4 | Booking / Intake Friction | 15% | How hard it is for a customer to book or inquire |
| 5 | Follow-Up Weakness | 10% | Missing email capture, review widgets, social presence |
| 6 | Revenue Leakage Opportunity | 15% | Identified gaps that cost the business money |
| 7 | Ascent Fit Score | 10% | LLM composite judgment of overall fit |

Each dimension returns `{ score, confidence, evidence[] }`. Confidence reflects data quality — how many signals were actually found versus expected. Low-confidence dimensions (below 0.3) are automatically down-weighted.

### Node 6 — Ranking + Output
Assigns a final tier (HOT/WARM/COLD), a priority rank across all results, and generates a suggested outreach angle. Writes each record to a JSONL audit log (when `AUDIT_LOG_ENABLED=true`). For batch requests, cross-target dedup runs before ranking so the same business appearing in multiple searches is only ranked once.

---

## Playwright's Role

Playwright (headless Chromium) serves as a fallback enrichment layer. It is not the primary fetch method — `httpx` runs first because it is faster. Playwright steps in when:

- The site requires JavaScript to render meaningful content
- The server returns a 403, 429, or 503 to the HTTP client
- A contact form is embedded in a JS-rendered iframe that static parsing cannot reach

Playwright also powers a `contact_form_status` tri-state: `present`, `absent`, or `unknown`. If Playwright times out or is unavailable, the status is `unknown` rather than `absent` — the pipeline does not treat an incomplete check as a "no form" finding.

A smoke test runs Playwright against `https://example.com` at container startup to verify Chromium is operational.

---

## Guardrails

### Why deterministic scoring for dims 1–6
LLM scoring is non-deterministic. The same business could score differently on two runs, which makes calibration impossible and output unauditable. Deterministic scoring means: same inputs, same score, every time. Sales feedback can be used to tune weights in `scoring_weights.yaml` directly.

### Pre-score quality gate
Before scoring, a quality gate checks whether there is enough data to produce a reliable result. Records that fail the gate are flagged with a quality warning but still scored with available data — they are never silently dropped.

### Review count cap (`max_review_count`)
SerpAPI results are filtered to exclude businesses above a review count threshold (default 500). This prevents large chains and franchises from crowding out true independent SMBs, which are the actual target.

### Rate limiting
All external API calls are wrapped with `asyncio.Semaphore` to prevent quota exhaustion. Concurrent pipeline runs are capped via `max_workers` in `config/pipeline_config.yaml`.

### Contact form tri-state
Contact form detection returns `present`, `absent`, or `unknown` — never a false negative. If the check could not be completed (Playwright unavailable, timeout), the gap is suppressed from output rather than falsely reported as missing. A `contact_form_check_had_errors` flag is set on the record.

### Proxy removal on startup
Any system-level HTTP proxy environment variables are stripped on API startup to prevent proxy interference with direct API calls to external services.

---

## API Endpoints

### `POST /analyze`
Analyze a single niche + location combination. Returns ranked results with full score breakdown.

```json
{
  "niche": "dental",
  "location": "Austin, TX",
  "max_results": 5,
  "max_review_count": 500,
  "source_backend": "serpapi"
}
```

### `POST /batch`
Analyze multiple niche + location targets in one call. Cross-target deduplication runs before ranking — the same business will not appear twice even if it matches multiple targets. Returns a unified ranked list with a summary of tier distribution.

```json
{
  "targets": [
    { "niche": "plumbing", "location": "Phoenix, AZ" },
    { "niche": "plumbing", "location": "Scottsdale, AZ" }
  ]
}
```

---

## Running with Docker

```bash
cp .env.example .env
# fill in API keys

docker compose build
docker compose up -d

# single analyze
curl -X POST http://localhost:8001/analyze \
  -H "Content-Type: application/json" \
  -d '{"niche":"plumbing","location":"Phoenix, AZ","max_results":5}'

# batch
curl -X POST http://localhost:8001/batch \
  -H "Content-Type: application/json" \
  -d '{"targets":[{"niche":"dental","location":"Austin, TX"}]}'
```

---

## Configuration

| File | Purpose |
|------|---------|
| `config/pipeline_config.yaml` | API concurrency, max workers, HTTP timeouts |
| `config/scoring_weights.yaml` | All scoring coefficients and tier thresholds |
| `.env` | API keys (never commit) |

Key environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SOURCING_BACKEND` | `serpapi` | Sourcing provider. Swap without code changes. |
| `AUDIT_LOG_ENABLED` | `false` | Write JSONL audit log per record + batch summary |
| `AUDIT_LOG_PATH` | `output/audit.jsonl` | Audit log file path |

---

## Tech Stack

| Layer | Tools |
|-------|-------|
| Pipeline orchestration | LangGraph |
| API | FastAPI + Pydantic v2 |
| LLM | Large language model agent — tool-use mode |
| Sourcing | SerpAPI (Google Maps) |
| Enrichment | httpx, BeautifulSoup, Playwright |
| Supplementary search | Tavily |
| Infrastructure | Docker, asyncio, ThreadPoolExecutor |
| Config | YAML (scoring weights, pipeline config) |
| Testing | pytest — 179 tests, 3 skipped |

---

## Known Limitations

- Sites behind Cloudflare or DataDome will block even Playwright. Records land in `DATA_BLOCKED` and require manual review.
- The LLM-generated Ascent Fit Score (dim-7) defaults to 5.0 with 0.0 confidence if the LLM API is unreachable. The other 6 dimensions still score normally.
- Inbound classification returns `unknown_insufficient_evidence` when neither reviews nor website content contain enough signals. Scores default to mid-range (5.0) — treat these cautiously.
- Sourcing caps at 3 pages (~60 candidates) per query. High-competition markets may surface fewer true independents.
- `NO_WEBSITE` leads use opportunity bands (HIGH/MEDIUM/LOW) based purely on Google data, not the 7-dimension scoring model.

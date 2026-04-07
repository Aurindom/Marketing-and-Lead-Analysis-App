## 1. Proposed Stack

### Core Framework
| Tool | Role |
|------|------|
| **Python 3.11** | Runtime |
| **LangGraph** | Pipeline orchestration. 6-node DAG with parallel execution. |
| **FastAPI** | Structured output API endpoint *(Week 2)* |

### Sourcing
| Tool | Role |
|------|------|
| **SerpAPI (Google Maps)** | Primary local business sourcing |
| **Google Places API** | Structured business data: hours, phone, category, review count. Cleaner than scraping search results. |
| **Tavily** | Supplementary web search and review language mining |

### Enrichment and Crawling
| Tool | Role |
|------|------|
| **httpx** | Async HTTP client for website crawling |
| **BeautifulSoup (lxml)** | HTML parsing, signal extraction, provider fingerprinting |
| **Playwright** | Fallback for JavaScript-rendered sites *(Week 2)* |

### Data and Output
| Tool | Role |
|------|------|
| **Pydantic v2** | Strict schema enforcement at every pipeline node. 30+ structured signal fields per prospect. |
| **JSON + CSV** | Week 1 output format |
| **SQLite cache** | Deduplication across batch runs *(Week 2)* |

### Infrastructure
| Tool | Role |
|------|------|
| **asyncio** | Concurrent processing with rate limiting across all external APIs |
| **scoring_weights.yaml** | Externalized scoring configuration. Weights adjustable without touching code. |
| **Docker** | Containerisation for delivery *(Week 2)* |

---

## 2. Architecture

The system runs as a **6-node pipeline**. Two of the nodes run in parallel to cut per-prospect processing time.

```
Input: Industry + Location + Niche
             │
             ▼
┌────────────────────────┐
│    NODE 1: SOURCING    │
│  SerpAPI + Places API  │
│  Tavily fallback       │
└───────────┬────────────┘
            │  Candidate list
            │  name · address · phone · website · category · rating
            ▼
┌────────────────────────┐
│   NODE 2: ENRICHMENT   │
│  httpx + BeautifulSoup │
│  Website crawl         │
│  Widget & script scan  │
└───────────┬────────────┘
            │  Raw HTML · extracted text · detected widgets · meta signals
            │
     ┌──────┴──────┐
     │             │  runs in parallel
     ▼             ▼
┌─────────────┐  ┌──────────────────────┐
│   NODE 3:   │  │       NODE 4:        │
│  ANALYSIS   │  │  INBOUND DETECTION   │
│             │  │                      │
│ 30+ struc-  │  │ Deterministic scan:  │
│ tured       │  │ Dialogflow · Drift   │
│ signals     │  │ Intercom · Smith.ai  │
│             │  │ Calendly · Acuity    │
│ Revenue and │  │ RingCentral · etc.   │
│ op. gaps    │  │                      │
│             │  │ Probabilistic        │
│ Schema      │  │ classification       │
│ validated   │  │                      │
│             │  │ Tavily review mining │
│             │  │ voicemail · hold     │
│             │  │ time signals         │
└──────┬──────┘  └──────────┬───────────┘
       │                    │
       └────────┬───────────┘
                │  Merged signals + InboundHandlingProfile
                ▼
┌───────────────────────────────┐
│      NODE 5: SCORING ENGINE   │
│                               │
│  Dims 1-6: Deterministic      │
│  Weighted sum of signals      │
│  Weights from YAML config     │
│  Confidence = signals found   │
│              / total possible │
│                               │
│  Dim 7: Composite fit score   │
│                               │
│  1. AI Receptionist Likelihood│
│  2. Inbound Automation Maturity│
│  3. Lead Capture Maturity     │
│  4. Booking / Intake Friction │
│  5. Follow-Up Weakness        │
│  6. Revenue Leakage Opportunity│
│  7. Ascent Fit Score          │
└───────────────┬───────────────┘
                │  7 dimensions · confidence · evidence
                ▼
┌───────────────────────────────┐
│    NODE 6: RANKING + OUTPUT   │
│                               │
│  Ranked by Ascent Fit Score   │
│  Tiered: HOT · WARM · COLD    │
│                               │
│  Categories:                  │
│  · High opp, weak inbound     │
│  · High opp, partial auto     │
│  · Moderate opp, unclear      │
│  · Lower opp, stronger intake │
│  · Insufficient evidence      │
│                               │
│  Week 1: JSON + CSV           │
│  Week 2: FastAPI endpoint     │
└───────────────────────────────┘
```

### A note on scoring design

For dimensions 1 through 6, scoring is fully deterministic. The system extracts 30+ structured signals per business and a weighted function turns those into scores. The weights live in a config file and can be tuned in minutes without touching code. Every score is explainable and reproducible.

Dimension 7, the Ascent Fit Score, is the composite judgment across all dimensions. That one is computed as a reasoned combination of everything the system has found.

---

## 3. Build Sequence

### Foundation (before Week 1 starts)

| Step | Deliverable |
|------|-------------|
| 1 | `ProspectState` — the data model every node reads and writes. Status tracking, error handling, all signal and score fields. Built first, before any node. |
| 2 | Pipeline skeleton — node registration, parallel execution setup for Nodes 3 and 4, state schema binding. |

### Week 1

| Step | Node | Deliverable |
|------|------|-------------|
| 3 | Node 1 | Sourcing. SerpAPI + Google Places API producing a candidate list. |
| 4 | Node 2 | Enrichment. httpx + BeautifulSoup pulling raw signals from each website. |
| 5 | Node 3 | Analysis. 30+ structured signals and gap identification per business. |
| 6 | Node 4 | Inbound Detection. Provider fingerprinting combined with probabilistic classification. |
| 7 | Node 5 | Scoring Engine. Deterministic scorer with configurable YAML weights. |
| 8 | Node 6 | Ranking and Output. Tier classification with JSON and CSV export. |
| 9 | | End-to-end test on 10-15 real businesses. Output review and tuning. |

### Week 2

| Step | Deliverable |
|------|-------------|
| 10 | Playwright fallback for JS-rendered websites |
| 11 | Async batch processing for 50+ businesses |
| 12 | SQLite cache to skip re-processing known businesses |
| 13 | FastAPI endpoints with structured API output |
| 14 | Docker container |
| 15 | Documentation and final demo |

---

## 4. Week 1 Deliverables

By end of Week 1, the following will be working and demonstrable:

- Full end-to-end pipeline from input to ranked output
- All 6 nodes functional
- All 7 scoring dimensions operational
- Inbound handling detection that is probabilistic, not binary
- `ProspectState` schema enforced at every node
- JSON and CSV structured output
- Demo on 10-15 real businesses in a chosen vertical and city
- Scoring weights configured and documented
- Confidence and evidence visible in output for every record
- Honest limitations writeup

**Not in Week 1:** FastAPI endpoint, Docker, batch processing at 50+, Playwright fallback, SQLite cache.

---

## 5. Week 2 Additions

- FastAPI endpoint serving structured prospect records
- Docker container, single container, deployable
- Async batch processing for 50+ businesses per run with concurrency control
- Playwright fallback for JavaScript-heavy websites
- SQLite cache to avoid re-processing known businesses
- Expanded signal coverage across enrichment sources
- Full documentation covering architecture, lead record schema, scoring logic, confidence model, and known limitations
- Final polished demo with ranked sample output

---

## 6. Inbound Handling Detection — How It Works

This runs as Node 4, in parallel with the Analysis node. It does not make a single yes/no call on whether a business has automated inbound handling. It builds a probabilistic picture from three independent methods.

### Method 1 — Deterministic Provider Fingerprinting

The website is scanned for known signatures of specific tools and providers:

- **Chat and widget tools:** Dialogflow, Drift, Intercom, Tidio, LiveChat
- **Scheduling tools:** Calendly, Acuity, Setmore, Square Appointments
- **Phone systems:** RingCentral, Vonage, Grasshopper
- **Virtual receptionists:** Smith.ai, Ruby Receptionists, PATLive
- **Copy signals:** "24/7", "always available", "never miss a call"

When a known provider is matched, confidence is rated high. It's a deterministic match, not a guess.

### Method 2 — Probabilistic Classification

Each business is classified into one of seven inbound handling states:

- `likely_manual_receptionist`
- `likely_voicemail_dependent`
- `likely_basic_IVR`
- `likely_AI_assisted`
- `likely_after_hours_automation`
- `likely_no_meaningful_automation`
- `unknown_insufficient_evidence`

Each classification comes with a confidence score between 0.0 and 1.0, the reasoning behind it, and which signals were used. The word *likely* is intentional. The system never overclaims.

### Method 3 — Review Language Mining (via Tavily)

Public reviews are searched for language that reveals how callers actually experience the business:

- **Weak signals:** "voicemail", "no answer", "on hold", "never called back", "wait time"
- **Stronger signals:** "spoke to a bot", "press 1", "automated"
- **Positive signals:** "answered right away", "always available", "24 hour"

Review signals carry lower weight than Method 1 matches but they're real evidence and they contribute to confidence scores.

### Uncertainty Handling

If fewer than three signals are available, the classification defaults to `unknown_insufficient_evidence`. Confidence is always shown. There is no false certainty. Partial records are flagged and the scoring engine automatically reduces dimension scores when evidence is thin.


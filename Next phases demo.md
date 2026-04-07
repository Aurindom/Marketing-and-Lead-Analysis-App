# Next Phases Demo

## Context (2 days to demo)
- Priority is **data accuracy, reliability, confidence handling, and ranking quality**.
- UI polish is explicitly not the priority for this demo.
- Yes, your statement is correct: **Docker should be brought up to pace because that is the real runtime to ship** (especially for Playwright reliability vs Windows issues).

---

## 1) Bring Docker Up To Pace (Shipping Runtime)

### Why this is required now
- Playwright on Windows is intermittently unstable (`WinError 5`), which directly hurts contact-form and booking accuracy.
- Docker/Linux gives stable browser runtime and deterministic behavior for demo and production.

### Do now
1. Confirm image/runtime parity for Playwright.
2. Ensure API and pipeline run in container with same env/config used for demo.
3. Run smoke test and one full sample batch in Docker as the source-of-truth run.

### Current verified gap (must close first)
- The running Docker container can be **stale vs local code** (old API response shape, missing latest fields/logic).
- Root cause: compose currently mounts only `./output`, not source code. Container updates only after image rebuild.
- Practical impact: Docker test output may not reflect latest local fixes unless rebuilt.

### Docker sync procedure (required before any demo validation)
1. `docker compose down`
2. `docker compose build --no-cache`
3. `docker compose up -d`
4. Verify:
   - `http://localhost:8001/health` returns ok
   - `docker compose exec pipeline python scripts/playwright_smoke_test.py` passes
   - `/analyze` response includes expected latest fields (e.g., diagnostics/contact status fields currently in local API model)

### Files to verify/update
- `Dockerfile`
  - Keep Playwright-compatible base image.
  - Ensure app/test files copied as needed.
  - Confirm all runtime assets required by API routes are copied (not only backend modules).
- `docker-compose.yml`
  - `env_file: .env`
  - Expose API port.
  - Output bind mount `./output:/app/output`
  - Memory/shared memory settings for Chromium (`shm_size`, etc.) as needed.
- `.dockerignore`
  - Exclude `.env`, `venv/`, `.claude/`, `output/`.
  - Keep `tests/` included.
- `requirements.txt`
  - Keep Playwright version aligned with base image.
- `scripts/playwright_smoke_test.py`
  - Must pass in container before demo runs.
- `.env.example`
  - Document `PLAYWRIGHT_ENABLED=true` in container context.

---

## 2) Do-Now Scope For Demo (Phases D to F)

## Phase D (Do now): D1 + D2 + D4 + D5 + D6
### Goal
Stabilize sourcing architecture and observability **without risky source migration** right before demo.

### What to implement
1. Provider abstraction interface.
2. SerpAPI provider class (behavior parity, no logic drift).
3. Backend switch flag (`SOURCE_BACKEND`) with default `serpapi`.
4. Provider-level logs/metrics (before/after filters, latency, errors).
5. Tests for provider switch and response parity.

### Files to change
- `src/nodes/sourcing.py`
  - Refactor to call provider abstraction.
- `api.py`
  - Optional request override for backend selection (safe default remains `serpapi`).
- `run_pipeline.py`
  - Keep default backend stable unless overridden.
- `src/providers/sourcing_provider.py` (new)
  - Protocol/interface.
- `src/providers/serpapi_provider.py` (new)
  - Current logic migrated here.
- `src/providers/provider_factory.py` (new)
  - Instantiate provider from env/request.
- `tests/test_sourcing_provider_switch.py` (new)
  - Backend routing and schema parity tests.
- `tests/test_sourcing.py` (existing/new as needed)
  - Keep current sourcing behaviors green.

---

## Phase E (Do now): E1 + E2 + E3 + E4 (Backend only)
### Goal
Demo sales-ready scale behavior: multi-target runs, dedup, ranking, and summary stats.

### What to implement
1. `POST /batch` input model.
2. Cross-target dedup (`place_id` -> website -> fuzzy name+address).
3. Global and per-batch ranking.
4. Batch summary counters (`hot/warm/cold/data_blocked/skipped/deduplicated`).

### Files to change
- `api.py`
  - Add batch request/response models and `POST /batch`.
- `src/services/batch_runner.py` (new)
  - Run targets, aggregate results, apply dedup/ranking.
- `src/services/dedup.py` (new)
  - Dedup strategy and merge preference rules.
- `src/services/ranking.py` (new)
  - Global and per-group ranking utilities.
- `tests/test_batch_api.py` (new)
  - Contract tests for `/batch`.
- `tests/test_batch_dedup.py` (new)
  - Dedup correctness.
- `tests/test_batch_ranking.py` (new)
  - Rank consistency.

Note:
- Skip UI batch mode for demo (`static/index.html` can remain mostly unchanged).

---

## Phase F (Do now): F3 only (JSONL audit trail logger)
### Goal
Improve demo trust: show evidence/confidence traceability and easy post-run audit.

### What to implement
1. JSONL event logger per business record and per batch summary.
2. Log key diagnostics: status, tier, flags, contact_form_status, evidence snippets, errors.
3. Keep logger disabled for demo runtime (`AUDIT_LOG_ENABLED=false`), then enable post-demo for observability.

### Files to change
- `src/utils/audit_logger.py` (new)
  - JSONL append logger.
- `api.py`
  - Log per-request/per-batch summary events.
- `src/nodes/output.py`
  - Emit record-level audit payload.
- `run_pipeline.py`
  - Emit run summary event.
- `.env.example`
  - Add `AUDIT_LOG_ENABLED`, `AUDIT_LOG_PATH`.
- `tests/test_audit_logger.py` (new)
  - Logger and payload format tests.

---

## 3) Post-Demo Patches (Remaining D to F)

## Phase D (post-demo)
- D3: `GooglePlacesProvider` full implementation + parity tuning.
- Optional per-niche backend selection rules once live data is compared.

## Phase E (post-demo)
- E5: Batch mode in UI (`static/index.html`) with multi-row target builder and grouped display.

## Phase F (post-demo)
- Enable audit logging in deployed env (`AUDIT_LOG_ENABLED=true`) and monitor log volume/path rotation.
- F1: API-level rate limiting/semaphores.
- F2: SQLite cache for sourcing/enrichment/scoring reuse.
- F4: Static YAML industry priors (after enough calibration data).
- F5: Resumable long batch runs/checkpointing.
- F6: Streamlit dashboard only if current API UI becomes insufficient.

---

## Demo Acceptance Checklist (must pass)
1. Docker smoke test passes.
2. Accuracy regression suite passes (including contact/booking guardrails).
3. `/analyze` and `/batch` return ranked, structured, confidence-aware output.
4. Audit logger toggle is documented (`AUDIT_LOG_ENABLED=false` for demo; enable post-demo).
5. Limitations section prepared (unknown states, blocked sites, manual review paths).

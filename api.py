from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import os
import yaml

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.graph.pipeline import build_pipeline
from src.models.prospect import ProspectCandidate, ProspectState
from src.nodes.sourcing import search_businesses
from src.services.batch_runner import run_batch
from src.services.dedup import dedup
from src.services.ranking import rank_globally, build_summary
from src.utils.audit_logger import log_summary

load_dotenv()

for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_proxy_var, None)

_pipeline = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline
    _pipeline = build_pipeline()
    yield


app = FastAPI(title="Ascent Intelligence API", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

def _load_pipeline_config() -> dict:
    path = os.path.normpath(os.path.join(os.path.dirname(__file__), "config", "pipeline_config.yaml"))
    with open(path) as f:
        return yaml.safe_load(f)


def _load_scoring_weights() -> dict:
    path = os.path.normpath(os.path.join(os.path.dirname(__file__), "config", "scoring_weights.yaml"))
    with open(path) as f:
        return yaml.safe_load(f)


MAX_WORKERS = _load_pipeline_config()["api"]["max_workers"]


class AnalyzeRequest(BaseModel):
    niche: str
    location: str
    max_results: int = Field(default=5, ge=1, le=20)
    max_review_count: int = Field(default=500, ge=1)
    source_backend: Optional[str] = None


class DimensionScoreResult(BaseModel):
    score: float
    confidence: float
    evidence: list[str]


class ScoredDimensions(BaseModel):
    ai_receptionist_likelihood: DimensionScoreResult
    inbound_automation_maturity: DimensionScoreResult
    lead_capture_maturity: DimensionScoreResult
    booking_intake_friction: DimensionScoreResult
    follow_up_weakness: DimensionScoreResult
    revenue_leakage_opportunity: DimensionScoreResult
    ascent_fit_score: DimensionScoreResult


class DiagnosticsResult(BaseModel):
    raw_text_length: int
    playwright_attempted: bool
    playwright_used: bool
    blocked_http_status: Optional[int]
    data_blocked: bool
    contact_form_status: str
    internal_contact_check_reason: Optional[str]
    internal_plugin_playwright_attempted: bool
    internal_plugin_playwright_used: bool


class ProspectResult(BaseModel):
    name: str
    tier: Optional[str]
    location: Optional[str]
    website: Optional[str]
    phone: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]
    place_id: Optional[str]
    gaps: list[str]
    flags: list[str]
    skip_scoring: bool
    data_blocked: bool
    inbound: str
    output_category: Optional[str]
    no_website_opportunity: Optional[str]
    suggested_outreach_angle: Optional[str]
    contact_form_page: Optional[str]
    contact_page_url: Optional[str]
    scores: Optional[ScoredDimensions]
    diagnostics: Optional[DiagnosticsResult]
    priority_rank: Optional[int]
    errors: list[str]


class AnalyzeResponse(BaseModel):
    niche: str
    location: str
    total: int
    results: list[ProspectResult]


class BatchTarget(BaseModel):
    niche: str
    location: str
    max_results: int = Field(default=5, ge=1, le=20)
    max_review_count: int = Field(default=500, ge=1)


class BatchRequest(BaseModel):
    targets: list[BatchTarget] = Field(min_length=1)


class BatchSummary(BaseModel):
    total: int
    hot: int
    warm: int
    cold: int
    no_website: int
    data_blocked: int
    skipped: int
    deduplicated: int


class BatchResponse(BaseModel):
    targets: int
    summary: BatchSummary
    results: list[ProspectResult]


def _build_scores(scored) -> Optional[ScoredDimensions]:
    if not scored:
        return None

    def _dim(d) -> DimensionScoreResult:
        return DimensionScoreResult(score=d.score, confidence=d.confidence, evidence=d.evidence)

    return ScoredDimensions(
        ai_receptionist_likelihood=_dim(scored.ai_receptionist_likelihood),
        inbound_automation_maturity=_dim(scored.inbound_automation_maturity),
        lead_capture_maturity=_dim(scored.lead_capture_maturity),
        booking_intake_friction=_dim(scored.booking_intake_friction),
        follow_up_weakness=_dim(scored.follow_up_weakness),
        revenue_leakage_opportunity=_dim(scored.revenue_leakage_opportunity),
        ascent_fit_score=_dim(scored.ascent_fit_score),
    )


def _build_diagnostics(result: ProspectState) -> DiagnosticsResult:
    data_blocked = any(
        f.startswith("Data blocked (HTTP 403/Playwright unavailable)")
        for f in result.quality_flags
    )
    return DiagnosticsResult(
        raw_text_length=len(result.raw_text) if result.raw_text else 0,
        playwright_attempted=result.playwright_attempted,
        playwright_used=result.playwright_used,
        blocked_http_status=result.blocked_http_status,
        data_blocked=data_blocked,
        contact_form_status=result.contact_form_status,
        internal_contact_check_reason=result.internal_contact_check_reason,
        internal_plugin_playwright_attempted=result.internal_plugin_playwright_attempted,
        internal_plugin_playwright_used=result.internal_plugin_playwright_used,
    )


def _run_single(pipeline, business: ProspectCandidate) -> ProspectResult:
    state = ProspectState(candidate=business)
    try:
        raw = pipeline.invoke(state)
        result = ProspectState(**raw) if isinstance(raw, dict) else raw

        diagnostics = _build_diagnostics(result)

        if diagnostics.data_blocked or result.skip_scoring:
            gaps = []
        else:
            gaps = result.analysis.identified_gaps if result.analysis else []

        no_website = result.tier == "NO_WEBSITE"
        if no_website:
            rating = result.candidate.rating or 0.0
            review_count = result.candidate.review_count or 0
            outreach_angle = (
                f"Strong reputation ({rating} stars, {review_count} reviews) "
                "with no web presence. Full digital buildout opportunity."
            )
        else:
            outreach_angle = result.scores.suggested_outreach_angle if result.scores else None

        return ProspectResult(
            name=result.candidate.name,
            tier=result.tier,
            location=result.candidate.location,
            website=result.candidate.website,
            phone=result.candidate.phone,
            rating=result.candidate.rating,
            review_count=result.candidate.review_count,
            place_id=result.candidate.place_id,
            gaps=gaps,
            flags=result.quality_flags,
            skip_scoring=result.skip_scoring,
            data_blocked=diagnostics.data_blocked,
            inbound=result.inbound_profile.classification if result.inbound_profile else "unknown",
            output_category=result.output_category,
            no_website_opportunity=result.no_website_opportunity,
            suggested_outreach_angle=outreach_angle,
            contact_form_page=result.contact_form_page,
            contact_page_url=result.contact_page_url,
            scores=_build_scores(result.scores),
            diagnostics=diagnostics,
            priority_rank=result.priority_rank,
            errors=[e.message for e in result.errors],
        )
    except Exception as e:
        return ProspectResult(
            name=business.name,
            tier=None,
            location=business.location,
            website=business.website,
            phone=business.phone,
            rating=business.rating,
            review_count=business.review_count,
            place_id=business.place_id,
            gaps=[],
            flags=[],
            skip_scoring=False,
            data_blocked=False,
            inbound="unknown",
            output_category=None,
            no_website_opportunity=None,
            suggested_outreach_angle=None,
            contact_form_page=None,
            contact_page_url=None,
            scores=None,
            diagnostics=None,
            priority_rank=None,
            errors=[str(e)],
        )


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


_TIER_ORDER = {"HOT": 0, "WARM": 1, "COLD": 2, "NO_WEBSITE": 3}
_NO_WEBSITE_BAND_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_DIM_WEIGHTS = {
    dim_name: dim_cfg["weight"]
    for dim_name, dim_cfg in _load_scoring_weights()["dimensions"].items()
}


def _weighted_score(result: ProspectResult) -> float:
    if not result.scores:
        return 0.0
    total = 0.0
    for dim, weight in _DIM_WEIGHTS.items():
        dim_score = getattr(result.scores, dim)
        total += dim_score.score * dim_score.confidence * weight
    return total


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not ready. Startup may have failed.")
    if request.source_backend:
        os.environ["SOURCING_BACKEND"] = request.source_backend
    businesses = search_businesses(request.niche, request.location, request.max_results, request.max_review_count)
    if request.source_backend:
        os.environ.pop("SOURCING_BACKEND", None)
    if not businesses:
        raise HTTPException(status_code=404, detail="No businesses found for the given niche and location.")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_run_single, _pipeline, b): b for b in businesses}
        for future in as_completed(futures):
            results.append(future.result())

    def _sort_key(r: ProspectResult):
        tier_rank = _TIER_ORDER.get(r.tier, 4)
        if r.tier == "NO_WEBSITE":
            band_rank = _NO_WEBSITE_BAND_ORDER.get(r.no_website_opportunity or "LOW", 2)
            return (tier_rank, band_rank, -(r.review_count or 0), -(r.rating or 0.0), (r.name or "").lower())
        return (tier_rank, 0, -_weighted_score(r), 0.0, (r.name or "").lower())

    results.sort(key=_sort_key)
    for rank, result in enumerate(results, start=1):
        result.priority_rank = rank

    summary = build_summary(results, deduplicated=0)
    log_summary(
        source="api_analyze",
        targets=[f"{request.niche} / {request.location}"],
        **summary,
    )

    return AnalyzeResponse(
        niche=request.niche,
        location=request.location,
        total=len(results),
        results=results,
    )


def _batch_sort_key(r: ProspectResult):
    tier_rank = _TIER_ORDER.get(r.tier, 4)
    if r.tier == "NO_WEBSITE":
        band_rank = _NO_WEBSITE_BAND_ORDER.get(r.no_website_opportunity or "LOW", 2)
        return (tier_rank, band_rank, -(r.review_count or 0), -(r.rating or 0.0), (r.name or "").lower())
    return (tier_rank, 0, -_weighted_score(r), 0.0, (r.name or "").lower())


@app.post("/batch", response_model=BatchResponse)
def batch(request: BatchRequest):
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not ready. Startup may have failed.")

    raw_results = run_batch(request.targets, _pipeline, _run_single, MAX_WORKERS)
    deduped, removed = dedup(raw_results)
    ranked = rank_globally(deduped, _batch_sort_key)
    summary_data = build_summary(ranked, deduplicated=removed)

    log_summary(
        source="api_batch",
        targets=[f"{t.niche} / {t.location}" for t in request.targets],
        **summary_data,
    )

    return BatchResponse(
        targets=len(request.targets),
        summary=BatchSummary(**summary_data),
        results=ranked,
    )

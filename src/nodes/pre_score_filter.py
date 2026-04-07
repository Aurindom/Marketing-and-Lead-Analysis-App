import os
import re
import yaml
from src.models.prospect import ProspectState

BLOCKED_FLAG = "Data blocked (HTTP 403/Playwright unavailable) - manual review needed"
_HTTP_BLOCKED_PATTERN = re.compile(r"\b(403|429|503)\b")

_cfg = None


def _load_config() -> dict:
    global _cfg
    if _cfg is None:
        path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "pipeline_config.yaml"
        ))
        with open(path) as f:
            _cfg = yaml.safe_load(f)["pre_score_filter"]
    return _cfg


def _c(key):
    return _load_config()[key]


def run(state: ProspectState) -> ProspectState:
    if _is_no_website(state):
        state.no_website_opportunity = _classify_no_website_opportunity(state)
        state.quality_flags = state.quality_flags + [
            "No website found - direct outreach candidate"
        ]
        state.tier = "NO_WEBSITE"
        state.skip_scoring = True
        return state

    if _is_data_blocked(state):
        state.quality_flags = state.quality_flags + [BLOCKED_FLAG]
        state.tier = "COLD"
        state.skip_scoring = True
        return state

    if not state.raw_text or len(state.raw_text) < _c("min_content_length"):
        state.quality_flags = state.quality_flags + [
            "Insufficient web content - Haiku scoring skipped, assigned COLD"
        ]
        state.tier = "COLD"
        state.skip_scoring = True
        return state

    if (
        state.inbound_profile
        and state.inbound_profile.classification == "likely_AI_assisted"
        and state.analysis
        and state.analysis.has_booking_link
        and state.analysis.has_live_chat
    ):
        state.quality_flags = state.quality_flags + [
            "Existing full automation detected - low Ascent fit, assigned COLD"
        ]
        state.tier = "COLD"
        state.skip_scoring = True
        return state

    return state


def _is_no_website(state: ProspectState) -> bool:
    if not state.candidate.website:
        return True
    return any(
        e.node == "enrichment" and e.error_type == "no_website"
        for e in state.errors
    )


def _classify_no_website_opportunity(state: ProspectState) -> str:
    review_count = state.candidate.review_count or 0
    rating = state.candidate.rating or 0.0
    if review_count >= _c("no_website_high_reviews") and rating >= _c("no_website_high_rating"):
        return "HIGH"
    if review_count >= _c("no_website_med_reviews") and rating >= _c("no_website_med_rating"):
        return "MEDIUM"
    return "LOW"


def _is_data_blocked(state: ProspectState) -> bool:
    has_http_block = any(
        e.node == "enrichment" and _HTTP_BLOCKED_PATTERN.search(e.message or "")
        for e in state.errors
    )
    has_playwright_failure = any(
        e.node == "enrichment" and e.error_type == "playwright_fallback_failed"
        for e in state.errors
    )
    return has_http_block and has_playwright_failure

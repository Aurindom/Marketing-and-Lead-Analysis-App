import json
import os
from datetime import datetime, timezone
from src.models.prospect import ProspectState, ErrorRecord
from src.utils.audit_logger import log_record

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")


def run(state: ProspectState) -> ProspectState:
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        state.output_category = state.tier or "UNSCORED"

        record = _build_record(state)
        _write_record(record, state.candidate.name)

        inbound = state.inbound_profile
        evidence = inbound.evidence[:3] if inbound else []
        log_record(
            name=state.candidate.name,
            tier=state.tier,
            contact_form_status=state.contact_form_status,
            flags=state.quality_flags,
            errors=[e.message for e in state.errors],
            evidence=evidence,
            source="output_node",
        )

        return state

    except Exception as e:
        state.errors.append(ErrorRecord(
            node="output",
            error_type=type(e).__name__,
            message=str(e)
        ))
        return state


def _build_record(state: ProspectState) -> dict:
    candidate = state.candidate
    scores = state.scores
    analysis = state.analysis
    inbound = state.inbound_profile

    record = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tier": state.tier,
            "output_category": state.output_category,
            "status": state.status,
            "quality_flags": state.quality_flags,
            "errors": [e.model_dump() for e in state.errors],
        },
        "diagnostics": _format_diagnostics(state),
        "business": {
            "name": candidate.name,
            "category": candidate.category,
            "location": candidate.location,
            "phone": candidate.phone,
            "email": candidate.email,
            "website": candidate.website,
            "rating": candidate.rating,
            "review_count": candidate.review_count,
            "place_id": candidate.place_id,
        },
        "website_signals": _format_analysis(state),
        "inbound_profile": _format_inbound(inbound),
        "scores": _format_scores(scores),
        "outreach": _format_outreach(state),
    }

    return record


def _format_outreach(state: ProspectState) -> dict:
    scores = state.scores
    analysis = state.analysis

    if state.tier == "NO_WEBSITE":
        rating = state.candidate.rating or 0.0
        review_count = state.candidate.review_count or 0
        angle = (
            f"Strong reputation ({rating} stars, {review_count} reviews) "
            "with no web presence. Full digital buildout opportunity."
        )
        return {
            "tier": state.tier,
            "no_website_opportunity": state.no_website_opportunity,
            "suggested_angle": angle,
            "top_gaps": [],
        }

    return {
        "tier": state.tier,
        "no_website_opportunity": None,
        "suggested_angle": scores.suggested_outreach_angle if scores else None,
        "top_gaps": analysis.identified_gaps[:3] if analysis else [],
    }


def _format_diagnostics(state: ProspectState) -> dict:
    data_blocked = any(flag.startswith("Data blocked (HTTP 403/Playwright unavailable)") for flag in state.quality_flags)
    return {
        "raw_text_length": len(state.raw_text or ""),
        "playwright_attempted": state.playwright_attempted,
        "playwright_used": state.playwright_used,
        "blocked_http_status": state.blocked_http_status,
        "blocked_by_403_family": state.blocked_http_status in (403, 429, 503),
        "data_blocked": data_blocked,
        "internal_js_shell_detected": state.internal_js_shell_detected,
        "internal_playwright_used": state.internal_playwright_used,
        "internal_plugin_playwright_attempted": state.internal_plugin_playwright_attempted,
        "internal_plugin_playwright_used": state.internal_plugin_playwright_used,
        "contact_form_status": state.contact_form_status,
        "internal_contact_check_reason": state.internal_contact_check_reason,
    }


def _format_analysis(state: ProspectState) -> dict:
    analysis = state.analysis
    if analysis is None:
        return {
            "available": False,
            "contact_form_page": state.contact_form_page,
            "contact_page_url": state.contact_page_url,
        }
    return {
        "available": True,
        "has_contact_form": analysis.has_contact_form,
        "contact_form_page": state.contact_form_page,
        "contact_page_url": state.contact_page_url,
        "has_booking_link": analysis.has_booking_link,
        "booking_tool": analysis.booking_tool,
        "has_live_chat": analysis.has_live_chat,
        "chat_provider": analysis.chat_provider,
        "has_email_capture": analysis.has_email_capture,
        "cta_strength": analysis.cta_strength,
        "website_quality": analysis.website_quality,
        "mobile_ux": analysis.mobile_ux,
        "after_hours_handling_visible": analysis.after_hours_handling_visible,
        "trust_badges_present": analysis.trust_badges_present,
        "testimonials_present": analysis.testimonials_present,
        "social_links_present": analysis.social_links_present,
        "identified_gaps": analysis.identified_gaps,
    }


def _format_inbound(inbound) -> dict:
    if inbound is None:
        return {"available": False}
    return {
        "available": True,
        "classification": inbound.classification,
        "confidence": inbound.classification_confidence,
        "data_coverage": inbound.data_coverage,
        "detected_providers": inbound.detected_providers,
        "evidence": inbound.evidence,
        "review_signals": inbound.review_signals,
    }


def _format_scores(scores) -> dict:
    if scores is None:
        return {"available": False}

    def fmt(dim):
        return {"score": dim.score, "confidence": dim.confidence, "evidence": dim.evidence}

    return {
        "available": True,
        "ai_receptionist_likelihood": fmt(scores.ai_receptionist_likelihood),
        "inbound_automation_maturity": fmt(scores.inbound_automation_maturity),
        "lead_capture_maturity": fmt(scores.lead_capture_maturity),
        "booking_intake_friction": fmt(scores.booking_intake_friction),
        "follow_up_weakness": fmt(scores.follow_up_weakness),
        "revenue_leakage_opportunity": fmt(scores.revenue_leakage_opportunity),
        "ascent_fit_score": fmt(scores.ascent_fit_score),
    }


def _write_record(record: dict, business_name: str) -> None:
    safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in business_name)
    safe_name = safe_name.strip().replace(" ", "_")[:60]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_name}_{timestamp}.json"
    filepath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

import os
import yaml
from anthropic import Anthropic
from src.models.prospect import (
    ProspectState, ScoredProspect, DimensionScore, ErrorRecord
)

_client = None
_weights: dict = {}


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def _load_weights() -> dict:
    global _weights
    if not _weights:
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "scoring_weights.yaml"
        )
        with open(os.path.normpath(config_path)) as f:
            _weights = yaml.safe_load(f)
    return _weights


def run(state: ProspectState) -> ProspectState:
    try:
        analysis = state.analysis
        inbound = state.inbound_profile

        dim1 = _score_ai_receptionist_likelihood(analysis, inbound)
        dim2 = _score_inbound_automation_maturity(inbound)
        contact_form_status = state.contact_form_status
        contact_page_url = state.contact_page_url
        dim3 = _score_lead_capture_maturity(analysis, contact_form_status, contact_page_url)
        dim4 = _score_booking_intake_friction(analysis, contact_form_status, contact_page_url)
        dim5 = _score_follow_up_weakness(analysis)
        dim6 = _score_revenue_leakage_opportunity(analysis, inbound, state)
        dim7, outreach_angle = _score_ascent_fit(state, dim1, dim2, dim3, dim4, dim5, dim6)

        scores = ScoredProspect(
            ai_receptionist_likelihood=dim1,
            inbound_automation_maturity=dim2,
            lead_capture_maturity=dim3,
            booking_intake_friction=dim4,
            follow_up_weakness=dim5,
            revenue_leakage_opportunity=dim6,
            ascent_fit_score=dim7,
            suggested_outreach_angle=outreach_angle,
        )

        state.scores = scores
        state.tier = _assign_tier(scores)
        return state

    except Exception as e:
        state.errors.append(ErrorRecord(
            node="scoring",
            error_type=type(e).__name__,
            message=str(e)
        ))
        return state


def _score_ai_receptionist_likelihood(analysis, inbound) -> DimensionScore:
    c = _load_weights()["coefficients"]["ai_receptionist"]
    score = c["base"]
    confidence = 0.5
    evidence = []

    if inbound is None:
        return DimensionScore(score=score, confidence=0.2, evidence=["No inbound profile available"])

    classification = inbound.classification
    inbound_conf = inbound.classification_confidence

    if classification == "likely_voicemail_dependent":
        score += c["voicemail_dependent"]
        evidence.append("Voicemail-dependent — high receptionist need")
    elif classification == "likely_no_meaningful_automation":
        score += c["no_meaningful_automation"]
        evidence.append("No automation detected — prime AI receptionist candidate")
    elif classification == "likely_manual_receptionist":
        score += c["manual_receptionist"]
        evidence.append("Manual receptionist — replacement opportunity")
    elif classification == "likely_basic_IVR":
        score += c["basic_ivr"]
        evidence.append("Basic IVR — upgrade candidate")
    elif classification == "likely_after_hours_automation":
        score += c["after_hours_automation"]
        evidence.append("After-hours automation in place — partial coverage")
    elif classification == "likely_AI_assisted":
        score += c["ai_assisted"]
        evidence.append("AI-assisted inbound already detected — low opportunity")

    if analysis and not analysis.after_hours_handling_visible:
        score += c["no_after_hours_bonus"]
        evidence.append("No after-hours coverage visible on site")

    if analysis and not analysis.has_live_chat:
        score += c["no_live_chat_bonus"]
        evidence.append("No live chat")

    score = max(0.0, min(10.0, score))
    confidence = min(1.0, c["confidence_base"] + inbound_conf * c["confidence_inbound_weight"])
    return DimensionScore(score=round(score, 2), confidence=round(confidence, 2), evidence=evidence)


def _score_inbound_automation_maturity(inbound) -> DimensionScore:
    if inbound is None:
        return DimensionScore(score=5.0, confidence=0.1, evidence=["No inbound data"])

    c = _load_weights()["coefficients"]["inbound_automation"]
    maturity_map = {
        "likely_no_meaningful_automation": (c["likely_no_meaningful_automation"], "No automation — maximum opportunity"),
        "likely_voicemail_dependent": (c["likely_voicemail_dependent"], "Voicemail-dependent — high maturity gap"),
        "likely_manual_receptionist": (c["likely_manual_receptionist"], "Manual only — significant upgrade path"),
        "likely_basic_IVR": (c["likely_basic_ivr"], "Basic IVR — partial automation"),
        "likely_after_hours_automation": (c["likely_after_hours_automation"], "After-hours automation — moderate maturity"),
        "likely_AI_assisted": (c["likely_ai_assisted"], "AI-assisted — low opportunity"),
        "unknown_insufficient_evidence": (c["unknown_insufficient_evidence"], "Insufficient evidence — mid-range assumed"),
    }

    score, note = maturity_map.get(
        inbound.classification,
        (c["unknown_insufficient_evidence"], "Unknown classification"),
    )
    confidence = inbound.classification_confidence

    negative = [s for s in inbound.review_signals if s.startswith("[-]")]
    if negative:
        score = min(10.0, score + c["negative_review_bonus_per_signal"] * len(negative))

    score = max(0.0, min(10.0, score))
    return DimensionScore(
        score=round(score, 2),
        confidence=round(confidence, 2),
        evidence=[note] + inbound.evidence[:3]
    )


def _score_lead_capture_maturity(analysis, contact_form_status: str = "missing", contact_page_url: str | None = None) -> DimensionScore:
    if analysis is None:
        return DimensionScore(score=5.0, confidence=0.1, evidence=["No analysis data"])

    c = _load_weights()["coefficients"]["lead_capture"]
    score = 0.0
    evidence = []

    if contact_form_status == "missing" and contact_page_url is None:
        score += c["no_contact_form"]
        evidence.append("No contact form")
    elif contact_form_status == "unknown":
        pass
    if not analysis.has_email_capture:
        score += c["no_email_capture"]
        evidence.append("No email capture / newsletter")
    if analysis.cta_strength == "absent":
        score += c["cta_absent"]
        evidence.append("No CTA detected")
    elif analysis.cta_strength == "weak":
        score += c["cta_weak"]
        evidence.append("Weak CTA only")
    if not analysis.has_booking_link:
        score += c["no_booking"]
        evidence.append("No online booking")
    if not analysis.trust_badges_present:
        score += c["no_trust_badges"]
        evidence.append("No trust signals")

    score = max(0.0, min(10.0, score))
    confidence = 0.8 if analysis else 0.1
    return DimensionScore(score=round(score, 2), confidence=round(confidence, 2), evidence=evidence)


def _score_booking_intake_friction(analysis, contact_form_status: str = "missing", contact_page_url: str | None = None) -> DimensionScore:
    if analysis is None:
        return DimensionScore(score=5.0, confidence=0.1, evidence=["No analysis data"])

    c = _load_weights()["coefficients"]["booking_friction"]
    score = 0.0
    evidence = []

    if not analysis.has_booking_link:
        score += c["no_booking"]
        evidence.append("No online booking available")
    if analysis.website_quality == "outdated":
        score += c["outdated_website"]
        evidence.append("Outdated website")
    if analysis.mobile_ux == "poor":
        score += c["poor_mobile"]
        evidence.append("Poor mobile UX")
    if contact_form_status == "missing" and not analysis.has_booking_link and contact_page_url is None:
        score += c["no_form_or_booking"]
        evidence.append("No form or booking — phone-only intake")
    if analysis.cta_strength == "absent":
        score += c["no_cta"]
        evidence.append("No CTA guiding intake")

    score = max(0.0, min(10.0, score))
    return DimensionScore(score=round(score, 2), confidence=0.8, evidence=evidence)


def _score_follow_up_weakness(analysis) -> DimensionScore:
    if analysis is None:
        return DimensionScore(score=5.0, confidence=0.1, evidence=["No analysis data"])

    c = _load_weights()["coefficients"]["follow_up"]
    score = 0.0
    evidence = []

    if not analysis.has_email_capture:
        score += c["no_email_capture"]
        evidence.append("No email list / lead nurture")
    if not analysis.review_widget_present:
        score += c["no_review_widget"]
        evidence.append("No review collection tool")
    if not analysis.blog_or_content_present:
        score += c["no_blog"]
        evidence.append("No content / blog for re-engagement")
    if not analysis.social_links_present:
        score += c["no_social"]
        evidence.append("No social presence for retargeting")
    if not analysis.testimonials_present:
        score += c["no_testimonials"]
        evidence.append("No testimonials — weak social proof loop")
    if not analysis.team_page_present:
        score += c["no_team_page"]
        evidence.append("No team page — low trust/relationship signals")

    score = max(0.0, min(10.0, score))
    return DimensionScore(score=round(score, 2), confidence=0.75, evidence=evidence)


def _score_revenue_leakage_opportunity(analysis, inbound, state: ProspectState) -> DimensionScore:
    c = _load_weights()["coefficients"]["revenue_leakage"]
    score = 0.0
    evidence = []

    if analysis:
        gap_count = len(analysis.identified_gaps)
        score += min(c["per_gap_cap"], gap_count * c["per_gap"])
        if gap_count > 0:
            evidence.append(f"{gap_count} gaps identified: {', '.join(analysis.identified_gaps[:3])}")

        if not analysis.after_hours_handling_visible:
            score += c["no_after_hours"]
            evidence.append("No after-hours coverage — missed calls = lost revenue")

    if inbound:
        if inbound.classification in ("likely_voicemail_dependent", "likely_no_meaningful_automation"):
            score += c["voicemail_no_automation"]
            evidence.append("Inbound leakage: calls going unanswered or to voicemail")
        negative_reviews = [s for s in inbound.review_signals if s.startswith("[-]")]
        if negative_reviews:
            score += min(c["negative_review_cap"], c["negative_review_per_signal"] * len(negative_reviews))
            evidence.append(f"{len(negative_reviews)} negative call-handling signals in reviews")

    if state.candidate.rating and state.candidate.rating < c["low_rating_threshold"] and state.candidate.review_count and state.candidate.review_count > c["low_rating_min_reviews"]:
        score += c["low_rating_bonus"]
        evidence.append(f"Low rating ({state.candidate.rating}) with high review volume — trust/service gap")

    score = max(0.0, min(10.0, score))
    inbound_conf = inbound.classification_confidence if inbound else 0.0
    confidence = min(c["confidence_cap"], c["confidence_base"] + inbound_conf * c["confidence_inbound_weight"])
    return DimensionScore(score=round(score, 2), confidence=round(confidence, 2), evidence=evidence)


def _score_ascent_fit(
    state: ProspectState,
    *dims: DimensionScore,
) -> tuple[DimensionScore, str | None]:
    try:
        dim_summary = "\n".join([
            f"- AI Receptionist Likelihood: {dims[0].score}/10 (confidence {dims[0].confidence:.0%})",
            f"- Inbound Automation Maturity gap: {dims[1].score}/10",
            f"- Lead Capture Maturity gap: {dims[2].score}/10",
            f"- Booking Intake Friction: {dims[3].score}/10",
            f"- Follow-up Weakness: {dims[4].score}/10",
            f"- Revenue Leakage Opportunity: {dims[5].score}/10",
        ])

        candidate = state.candidate
        context = f"""Business: {candidate.name}
Category: {candidate.category or 'Unknown'}
Location: {candidate.location or 'Unknown'}
Rating: {candidate.rating or 'N/A'} ({candidate.review_count or 0} reviews)
Inbound classification: {state.inbound_profile.classification if state.inbound_profile else 'unknown'}
Identified gaps: {', '.join(state.analysis.identified_gaps) if state.analysis else 'none'}

Dimension scores (higher = more opportunity):
{dim_summary}"""

        prompt = f"""You are a sales intelligence analyst. Given the following business profile, score how strong a fit this business is for an AI-powered inbound communications platform that handles calls, books appointments, and follows up automatically.

{context}

Respond with exactly two lines:
Score: [number 0-10]
Angle: [one sentence — the single most compelling outreach angle for this specific business]"""

        response = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )

        text = response.content[0].text.strip()
        lines = text.splitlines()

        score_val = 5.0
        angle = None

        for line in lines:
            if line.lower().startswith("score:"):
                try:
                    score_val = float(line.split(":", 1)[1].strip())
                    score_val = max(0.0, min(10.0, score_val))
                except ValueError:
                    pass
            elif line.lower().startswith("angle:"):
                angle = line.split(":", 1)[1].strip()

        return DimensionScore(
            score=round(score_val, 2),
            confidence=0.7,
            evidence=[f"LLM fit score: {score_val}/10"]
        ), angle

    except Exception as e:
        return DimensionScore(
            score=5.0,
            confidence=0.0,
            evidence=[f"LLM scoring unavailable: {str(e)}"]
        ), None


def _assign_tier(scores: ScoredProspect) -> str:
    weights = _load_weights()["dimensions"]
    tiers = _load_weights()["tiers"]

    weighted_sum = 0.0
    total_weight = 0.0

    dim_map = {
        "ai_receptionist_likelihood": scores.ai_receptionist_likelihood,
        "inbound_automation_maturity": scores.inbound_automation_maturity,
        "lead_capture_maturity": scores.lead_capture_maturity,
        "booking_intake_friction": scores.booking_intake_friction,
        "follow_up_weakness": scores.follow_up_weakness,
        "revenue_leakage_opportunity": scores.revenue_leakage_opportunity,
        "ascent_fit_score": scores.ascent_fit_score,
    }

    for dim_name, dim_score in dim_map.items():
        w = weights[dim_name]["weight"]
        weighted_sum += dim_score.score * dim_score.confidence * w
        total_weight += w

    final = (weighted_sum / total_weight) if total_weight > 0 else 0.0

    if final >= tiers["HOT"]:
        return "HOT"
    if final >= tiers["WARM"]:
        return "WARM"
    return "COLD"

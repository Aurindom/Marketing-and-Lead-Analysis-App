import pytest
from src.models.prospect import (
    ProspectState, ProspectCandidate, AnalysisResult,
    InboundHandlingProfile, DimensionScore
)
from src.nodes.scoring import (
    _score_ai_receptionist_likelihood,
    _score_inbound_automation_maturity,
    _score_lead_capture_maturity,
    _score_booking_intake_friction,
    _score_follow_up_weakness,
    _score_revenue_leakage_opportunity,
    _assign_tier,
)
from src.nodes.quality_gate import run as quality_gate_run


def make_state(**kwargs) -> ProspectState:
    return ProspectState(
        candidate=ProspectCandidate(name="Test Biz", website="https://example.com"),
        **kwargs
    )


def make_weak_analysis() -> AnalysisResult:
    return AnalysisResult(
        has_contact_form=False,
        has_booking_link=False,
        has_live_chat=False,
        has_email_capture=False,
        cta_strength="absent",
        website_quality="outdated",
        mobile_ux="poor",
        after_hours_handling_visible=False,
        hours_of_operation_listed=False,
        testimonials_present=False,
        review_widget_present=False,
        trust_badges_present=False,
        blog_or_content_present=False,
        social_links_present=False,
        team_page_present=False,
        identified_gaps=[
            "No online booking", "No contact form", "No live chat",
            "No email capture", "No after-hours coverage visible", "No clear CTA"
        ],
    )


def make_strong_analysis() -> AnalysisResult:
    return AnalysisResult(
        has_contact_form=True,
        has_booking_link=True,
        booking_tool="Calendly",
        has_live_chat=True,
        chat_provider="Intercom",
        has_email_capture=True,
        cta_strength="strong",
        website_quality="modern",
        mobile_ux="good",
        after_hours_handling_visible=True,
        hours_of_operation_listed=True,
        testimonials_present=True,
        review_widget_present=True,
        trust_badges_present=True,
        blog_or_content_present=True,
        social_links_present=True,
        team_page_present=True,
        identified_gaps=[],
    )


def make_voicemail_inbound() -> InboundHandlingProfile:
    return InboundHandlingProfile(
        classification="likely_voicemail_dependent",
        classification_confidence=0.75,
        evidence=["Voicemail signal: 'leave a message'"],
        review_signals=["[-] went to voicemail", "[-] never called back"],
        data_coverage="sufficient",
    )


def make_ai_inbound() -> InboundHandlingProfile:
    return InboundHandlingProfile(
        classification="likely_AI_assisted",
        classification_confidence=0.8,
        evidence=["AI provider detected: Smith.ai"],
        review_signals=["[+] answered right away"],
        data_coverage="sufficient",
    )


def make_scored_prospect_from_dims(score_val: float, conf: float):
    from src.models.prospect import ScoredProspect
    d = DimensionScore(score=score_val, confidence=conf, evidence=[])
    return ScoredProspect(
        ai_receptionist_likelihood=d,
        inbound_automation_maturity=d,
        lead_capture_maturity=d,
        booking_intake_friction=d,
        follow_up_weakness=d,
        revenue_leakage_opportunity=d,
        ascent_fit_score=d,
    )


class TestDim1AIReceptionistLikelihood:
    def test_voicemail_scores_high(self):
        result = _score_ai_receptionist_likelihood(None, make_voicemail_inbound())
        assert result.score >= 7.0

    def test_ai_assisted_scores_low(self):
        result = _score_ai_receptionist_likelihood(None, make_ai_inbound())
        assert result.score <= 4.0

    def test_no_inbound_returns_low_confidence(self):
        result = _score_ai_receptionist_likelihood(None, None)
        assert result.confidence <= 0.3

    def test_no_after_hours_adds_to_score(self):
        inbound = make_voicemail_inbound()
        analysis_with_no_after_hours = AnalysisResult(after_hours_handling_visible=False)
        base = _score_ai_receptionist_likelihood(None, inbound)
        with_analysis = _score_ai_receptionist_likelihood(analysis_with_no_after_hours, inbound)
        assert with_analysis.score >= base.score


class TestDim2InboundMaturity:
    def test_no_automation_scores_highest(self):
        inbound = InboundHandlingProfile(
            classification="likely_no_meaningful_automation",
            classification_confidence=0.6,
            data_coverage="sufficient"
        )
        result = _score_inbound_automation_maturity(inbound)
        assert result.score >= 9.0

    def test_ai_assisted_scores_lowest(self):
        result = _score_inbound_automation_maturity(make_ai_inbound())
        assert result.score <= 2.0

    def test_negative_reviews_increase_score(self):
        base = InboundHandlingProfile(
            classification="likely_voicemail_dependent",
            classification_confidence=0.7,
            data_coverage="sufficient"
        )
        with_neg = InboundHandlingProfile(
            classification="likely_voicemail_dependent",
            classification_confidence=0.7,
            review_signals=["[-] went to voicemail", "[-] no one answered"],
            data_coverage="sufficient"
        )
        assert _score_inbound_automation_maturity(with_neg).score >= _score_inbound_automation_maturity(base).score


class TestDim3LeadCapture:
    def test_all_gaps_scores_high(self):
        result = _score_lead_capture_maturity(make_weak_analysis())
        assert result.score >= 8.0

    def test_all_present_scores_low(self):
        result = _score_lead_capture_maturity(make_strong_analysis(), contact_form_status="found")
        assert result.score == 0.0

    def test_none_analysis_low_confidence(self):
        result = _score_lead_capture_maturity(None)
        assert result.confidence <= 0.2


class TestDim4BookingFriction:
    def test_no_booking_outdated_poor_mobile_scores_high(self):
        result = _score_booking_intake_friction(make_weak_analysis())
        assert result.score >= 8.0

    def test_full_booking_setup_scores_low(self):
        result = _score_booking_intake_friction(make_strong_analysis())
        assert result.score == 0.0


class TestDim5FollowUp:
    def test_all_missing_scores_high(self):
        result = _score_follow_up_weakness(make_weak_analysis())
        assert result.score >= 8.0

    def test_all_present_scores_low(self):
        result = _score_follow_up_weakness(make_strong_analysis())
        assert result.score == 0.0


class TestDim6RevenuLeakage:
    def test_many_gaps_plus_voicemail_scores_high(self):
        state = make_state(
            analysis=make_weak_analysis(),
            inbound_profile=make_voicemail_inbound(),
        )
        state.candidate.rating = 3.5
        state.candidate.review_count = 50
        result = _score_revenue_leakage_opportunity(state.analysis, state.inbound_profile, state)
        assert result.score >= 7.0

    def test_no_gaps_ai_inbound_scores_low(self):
        state = make_state(
            analysis=make_strong_analysis(),
            inbound_profile=make_ai_inbound(),
        )
        result = _score_revenue_leakage_opportunity(state.analysis, state.inbound_profile, state)
        assert result.score <= 3.0


class TestTierAssignment:
    def test_high_scores_high_confidence_gives_hot(self):
        scores = make_scored_prospect_from_dims(9.0, 0.9)
        tier = _assign_tier(scores)
        assert tier == "HOT"

    def test_mid_scores_gives_warm(self):
        scores = make_scored_prospect_from_dims(5.5, 0.8)
        tier = _assign_tier(scores)
        assert tier == "WARM"

    def test_low_scores_gives_cold(self):
        scores = make_scored_prospect_from_dims(2.0, 0.8)
        tier = _assign_tier(scores)
        assert tier == "COLD"

    def test_low_confidence_drags_down_tier(self):
        high_score_low_conf = make_scored_prospect_from_dims(9.0, 0.05)
        high_score_high_conf = make_scored_prospect_from_dims(9.0, 0.9)
        tier_low = _assign_tier(high_score_low_conf)
        tier_high = _assign_tier(high_score_high_conf)
        assert tier_high == "HOT"
        assert tier_low != "HOT"


class TestQualityGate:
    def test_hot_with_insufficient_inbound_flagged(self):
        state = make_state(
            scores=make_scored_prospect_from_dims(9.0, 0.9),
            tier="HOT",
            inbound_profile=InboundHandlingProfile(
                classification="likely_voicemail_dependent",
                classification_confidence=0.5,
                data_coverage="insufficient"
            )
        )
        result = quality_gate_run(state)
        assert any("HOT tier" in f for f in result.quality_flags)

    def test_hot_with_no_analysis_flagged(self):
        state = make_state(
            scores=make_scored_prospect_from_dims(9.0, 0.9),
            tier="HOT",
        )
        result = quality_gate_run(state)
        assert any("no website analysis" in f for f in result.quality_flags)

    def test_low_confidence_flagged(self):
        state = make_state(
            scores=make_scored_prospect_from_dims(8.0, 0.1),
            tier="WARM",
        )
        result = quality_gate_run(state)
        assert any("confidence" in f for f in result.quality_flags)

    def test_no_scores_flagged(self):
        state = make_state()
        result = quality_gate_run(state)
        assert any("No scores" in f for f in result.quality_flags)

    def test_clean_prospect_no_flags(self):
        state = make_state(
            scores=make_scored_prospect_from_dims(8.0, 0.85),
            tier="HOT",
            analysis=make_strong_analysis(),
            contact_form_status="found",
            inbound_profile=InboundHandlingProfile(
                classification="likely_voicemail_dependent",
                classification_confidence=0.8,
                data_coverage="sufficient"
            )
        )
        result = quality_gate_run(state)
        assert result.quality_flags == []

import pytest
from unittest.mock import patch
from src.models.prospect import ProspectState, ProspectCandidate
from src.nodes.inbound_detection import run


def make_state(raw_text: str = "", scripts: list[str] = None) -> ProspectState:
    return ProspectState(
        candidate=ProspectCandidate(name="Test Business", website="https://example.com"),
        raw_text=raw_text,
        detected_scripts=scripts or [],
    )


class TestProviderFingerprinting:
    def test_detects_smith_ai(self):
        state = make_state(scripts=["https://smith.ai/widget.js"])
        result = run(state)
        assert "Smith.ai" in result.inbound_profile.detected_providers

    def test_detects_callrail(self):
        state = make_state(scripts=["https://cdn.callrail.com/companies/123/abc.js"])
        result = run(state)
        assert "CallRail" in result.inbound_profile.detected_providers

    def test_detects_twilio(self):
        state = make_state(scripts=["https://media.twiliocdn.com/sdk/js/client/v1.13/twilio.min.js"])
        result = run(state)
        assert "Twilio" in result.inbound_profile.detected_providers

    def test_detects_multiple_providers(self):
        state = make_state(scripts=[
            "https://cdn.callrail.com/companies/123/abc.js",
            "https://aircall.io/widget.js",
        ])
        result = run(state)
        assert "CallRail" in result.inbound_profile.detected_providers
        assert "Aircall" in result.inbound_profile.detected_providers

    def test_no_providers_on_clean_page(self):
        state = make_state(raw_text="Welcome to our business.")
        result = run(state)
        assert result.inbound_profile.detected_providers == []


class TestClassification:
    def test_classifies_ai_assisted_from_provider(self):
        state = make_state(scripts=["https://smith.ai/widget.js"])
        result = run(state)
        assert result.inbound_profile.classification == "likely_AI_assisted"
        assert result.inbound_profile.classification_confidence > 0.0

    def test_classifies_voicemail_dependent(self):
        state = make_state(raw_text="Please leave a message and we will call you back.")
        result = run(state)
        assert result.inbound_profile.classification == "likely_voicemail_dependent"

    def test_classifies_manual_receptionist(self):
        state = make_state(raw_text="Call during business hours and our receptionist will assist you.")
        result = run(state)
        assert result.inbound_profile.classification == "likely_manual_receptionist"

    def test_classifies_after_hours_automation(self):
        state = make_state(raw_text="We offer 24/7 answering so you never miss a call.")
        result = run(state)
        assert result.inbound_profile.classification == "likely_after_hours_automation"

    def test_classifies_basic_ivr(self):
        state = make_state(raw_text="For sales press 1. For support press 2.")
        result = run(state)
        assert result.inbound_profile.classification == "likely_basic_IVR"

    def test_classifies_no_automation_on_empty_page(self):
        state = make_state(raw_text="We are a family business.")
        result = run(state)
        assert result.inbound_profile.classification in [
            "likely_no_meaningful_automation",
            "unknown_insufficient_evidence",
        ]

    def test_ai_outscores_voicemail_when_both_present(self):
        state = make_state(
            raw_text="Leave a message if we miss you.",
            scripts=["https://smith.ai/widget.js", "https://bland.ai/embed.js"]
        )
        result = run(state)
        assert result.inbound_profile.classification == "likely_AI_assisted"

    def test_unknown_when_confidence_too_low(self):
        state = make_state(raw_text="")
        result = run(state)
        assert result.inbound_profile.classification in [
            "unknown_insufficient_evidence",
            "likely_no_meaningful_automation",
        ]


class TestEvidence:
    def test_evidence_populated_for_provider(self):
        state = make_state(scripts=["https://smith.ai/widget.js"])
        result = run(state)
        assert len(result.inbound_profile.evidence) > 0
        assert any("Smith.ai" in e for e in result.inbound_profile.evidence)

    def test_evidence_populated_for_keyword(self):
        state = make_state(raw_text="Please leave a voicemail and we will return your call.")
        result = run(state)
        assert len(result.inbound_profile.evidence) > 0

    def test_evidence_empty_on_blank_page(self):
        state = make_state(raw_text="")
        result = run(state)
        assert isinstance(result.inbound_profile.evidence, list)


class TestReviewMining:
    def test_detects_negative_voicemail_signal(self):
        state = make_state(raw_text="Every time I called it went to voicemail. Very frustrating.")
        result = run(state)
        assert any("[-]" in s for s in result.inbound_profile.review_signals)

    def test_detects_negative_no_answer(self):
        state = make_state(raw_text="Nobody ever answered the phone when I called.")
        result = run(state)
        assert any("[-]" in s for s in result.inbound_profile.review_signals)

    def test_detects_positive_quick_response(self):
        state = make_state(raw_text="They answered right away and were very helpful.")
        result = run(state)
        assert any("[+]" in s for s in result.inbound_profile.review_signals)

    def test_detects_positive_always_available(self):
        state = make_state(raw_text="Someone is always available to take your call.")
        result = run(state)
        assert any("[+]" in s for s in result.inbound_profile.review_signals)

    def test_review_signals_capped_at_8(self):
        repeated = " ".join(["They answered right away."] * 20)
        state = make_state(raw_text=repeated)
        result = run(state)
        assert len(result.inbound_profile.review_signals) <= 8

    def test_no_signals_on_neutral_text(self):
        state = make_state(raw_text="Great service. Very professional. Highly recommend.")
        result = run(state)
        assert result.inbound_profile.review_signals == []


NO_TAVILY = patch("src.nodes.inbound_detection._fetch_tavily_reviews", return_value=([], False))


class TestDataCoverage:
    def test_sufficient_when_provider_detected(self):
        state = make_state(scripts=["https://smith.ai/widget.js"])
        with NO_TAVILY:
            result = run(state)
        assert result.inbound_profile.data_coverage == "sufficient"

    def test_sufficient_when_multiple_signals(self):
        state = make_state(raw_text="Leave a message. Call during business hours. Our receptionist will help.")
        with NO_TAVILY:
            result = run(state)
        assert result.inbound_profile.data_coverage == "sufficient"

    def test_insufficient_on_blank_page(self):
        state = make_state(raw_text="Welcome to our website.")
        with NO_TAVILY:
            result = run(state)
        assert result.inbound_profile.data_coverage == "insufficient"

    def test_partial_when_tavily_returns_content_but_no_regex_match(self):
        state = make_state(raw_text="Welcome to our website.")
        with patch("src.nodes.inbound_detection._fetch_tavily_reviews", return_value=([], True)):
            result = run(state)
        assert result.inbound_profile.data_coverage == "partial"


class TestErrorHandling:
    def test_does_not_crash_on_empty_state(self):
        state = make_state(raw_text="", scripts=[])
        result = run(state)
        assert result.inbound_profile is not None
        assert result.errors == []

    def test_inbound_profile_always_set(self):
        state = make_state(raw_text="Some page content here.")
        result = run(state)
        assert result.inbound_profile is not None
        assert result.inbound_profile.classification is not None

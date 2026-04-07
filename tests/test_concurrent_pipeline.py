import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch
from src.models.prospect import (
    ProspectState, ProspectCandidate, AnalysisResult,
    InboundHandlingProfile, DimensionScore, ScoredProspect
)
from run_pipeline import _run_single, MAX_WORKERS


def make_business(name: str = "Test Biz", website: str = "https://example.com") -> ProspectCandidate:
    return ProspectCandidate(name=name, website=website, location="Test City, TS")


def make_scored_state(business: ProspectCandidate, tier: str = "WARM") -> ProspectState:
    dim = DimensionScore(score=6.0, confidence=0.7, evidence=["test"])
    scores = ScoredProspect(
        ai_receptionist_likelihood=dim,
        inbound_automation_maturity=dim,
        lead_capture_maturity=dim,
        booking_intake_friction=dim,
        follow_up_weakness=dim,
        revenue_leakage_opportunity=dim,
        ascent_fit_score=DimensionScore(score=6.0, confidence=0.7, evidence=["LLM fit score: 6.0/10"]),
        suggested_outreach_angle="Strong outreach angle here.",
    )
    state = ProspectState(candidate=business)
    state.tier = tier
    state.scores = scores
    state.analysis = AnalysisResult(
        has_contact_form=False,
        has_booking_link=False,
        has_live_chat=False,
        has_email_capture=False,
        cta_strength="weak",
        website_quality="unknown",
        mobile_ux="unknown",
        after_hours_handling_visible=False,
        trust_badges_present=False,
        testimonials_present=False,
        social_links_present=False,
        review_widget_present=False,
        blog_or_content_present=False,
        team_page_present=False,
        booking_tool=None,
        chat_provider=None,
        detected_scripts=[],
        identified_gaps=["No contact form", "No booking", "No live chat"],
    )
    state.inbound_profile = InboundHandlingProfile(
        classification="likely_no_meaningful_automation",
        classification_confidence=0.35,
        evidence=["No signals detected"],
        review_signals=[],
        data_coverage="insufficient",
    )
    return state


class TestRunSingle:
    def test_returns_dict_with_expected_keys(self):
        business = make_business()
        state = make_scored_state(business)
        mock_pipeline = MagicMock()
        mock_pipeline.invoke.return_value = state

        result = _run_single(mock_pipeline, business)

        assert isinstance(result, dict)
        for key in ("name", "tier", "website", "location", "inbound", "gaps", "flags", "errors"):
            assert key in result

    def test_correct_values_extracted(self):
        business = make_business("Test Business", "https://example.test")
        state = make_scored_state(business, tier="HOT")
        mock_pipeline = MagicMock()
        mock_pipeline.invoke.return_value = state

        result = _run_single(mock_pipeline, business)

        assert result["name"] == "Test Business"
        assert result["tier"] == "HOT"
        assert result["website"] == "https://example.test"
        assert result["errors"] == []

    def test_handles_dict_output_from_langgraph(self):
        business = make_business()
        state = make_scored_state(business, tier="WARM")
        mock_pipeline = MagicMock()
        mock_pipeline.invoke.return_value = state.model_dump()

        result = _run_single(mock_pipeline, business)

        assert result["tier"] == "WARM"
        assert result["name"] == "Test Biz"

    def test_handles_pipeline_exception_gracefully(self):
        business = make_business("Broken Biz")
        mock_pipeline = MagicMock()
        mock_pipeline.invoke.side_effect = RuntimeError("Pipeline exploded")

        result = _run_single(mock_pipeline, business)

        assert result["tier"] is None
        assert result["name"] == "Broken Biz"
        assert "Pipeline exploded" in result["errors"][0]

    def test_handles_missing_analysis_gracefully(self):
        business = make_business()
        state = make_scored_state(business)
        state.analysis = None
        mock_pipeline = MagicMock()
        mock_pipeline.invoke.return_value = state

        result = _run_single(mock_pipeline, business)

        assert result["gaps"] == []


class TestConcurrentExecution:
    def test_multiple_businesses_run_in_parallel(self):
        call_times = []
        lock = threading.Lock()

        def slow_invoke(state):
            time.sleep(0.2)
            with lock:
                call_times.append(time.time())
            return make_scored_state(state.candidate)

        businesses = [make_business(f"Biz {i}") for i in range(5)]
        mock_pipeline = MagicMock()
        mock_pipeline.invoke.side_effect = slow_invoke

        start = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_run_single, mock_pipeline, b): b for b in businesses}
            results = [f.result() for f in as_completed(futures)]
        elapsed = time.time() - start

        assert len(results) == 5
        assert elapsed < 0.8, f"Expected parallel execution under 0.8s, took {elapsed:.2f}s"

    def test_all_results_collected_despite_partial_failure(self):
        businesses = [make_business(f"Biz {i}") for i in range(4)]

        def flaky_invoke(state):
            if "Biz 2" in state.candidate.name:
                raise ValueError("Simulated failure")
            return make_scored_state(state.candidate)

        mock_pipeline = MagicMock()
        mock_pipeline.invoke.side_effect = flaky_invoke

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_run_single, mock_pipeline, b): b for b in businesses}
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 4
        failed = [r for r in results if r["tier"] is None]
        succeeded = [r for r in results if r["tier"] is not None]
        assert len(failed) == 1
        assert len(succeeded) == 3

    def test_no_shared_state_between_workers(self):
        businesses = [make_business(f"Biz {i}") for i in range(5)]
        seen_names = set()
        lock = threading.Lock()

        def capturing_invoke(state):
            with lock:
                seen_names.add(state.candidate.name)
            return make_scored_state(state.candidate)

        mock_pipeline = MagicMock()
        mock_pipeline.invoke.side_effect = capturing_invoke

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_run_single, mock_pipeline, b): b for b in businesses}
            [f.result() for f in as_completed(futures)]

        assert len(seen_names) == 5, "Each business must be processed exactly once"

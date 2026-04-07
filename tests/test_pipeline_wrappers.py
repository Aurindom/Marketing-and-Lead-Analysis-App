from unittest.mock import patch

from src.graph.pipeline import enrichment_node, sourcing_node
from src.models.prospect import ErrorRecord, ProspectCandidate, ProspectState


def test_sourcing_wrapper_returns_only_new_errors():
    state = ProspectState(
        candidate=ProspectCandidate(name="Seed", location="Test City, TS", category="Test Category"),
        errors=[ErrorRecord(node="seed", error_type="seed_error", message="baseline")],
    )

    def fake_run(s: ProspectState) -> ProspectState:
        s.status = "failed"
        s.errors.append(ErrorRecord(node="sourcing", error_type="no_results", message="none found"))
        return s

    with patch("src.nodes.sourcing.run", side_effect=fake_run):
        delta = sourcing_node(state)

    assert delta["status"] == "failed"
    assert len(delta["errors"]) == 1
    assert delta["errors"][0].node == "sourcing"


def test_enrichment_wrapper_returns_only_new_errors():
    state = ProspectState(
        candidate=ProspectCandidate(name="Seed", website="https://example.com"),
        errors=[ErrorRecord(node="seed", error_type="seed_error", message="baseline")],
    )

    def fake_run(s: ProspectState) -> ProspectState:
        s.raw_text = "content"
        s.page_title = "Title"
        s.contact_form_page = "/contact-us"
        s.internal_js_shell_detected = True
        s.internal_playwright_used = True
        s.errors.append(ErrorRecord(node="enrichment", error_type="timeout", message="timed out"))
        return s

    with patch("src.nodes.enrichment.run", side_effect=fake_run):
        delta = enrichment_node(state)

    assert delta["raw_text"] == "content"
    assert delta["page_title"] == "Title"
    assert delta["contact_form_page"] == "/contact-us"
    assert delta["internal_js_shell_detected"] is True
    assert delta["internal_playwright_used"] is True
    assert len(delta["errors"]) == 1
    assert delta["errors"][0].node == "enrichment"

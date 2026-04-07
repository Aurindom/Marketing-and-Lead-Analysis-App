import os
import pytest
import yaml
from pathlib import Path

from src.models.prospect import ProspectCandidate, ProspectState
from src.nodes import enrichment
from src.nodes import analysis as analysis_node

SAMPLES_FILE = Path(__file__).parent / "contact_form_samples.yaml"


def _load_samples():
    if not SAMPLES_FILE.exists():
        return []
    with open(SAMPLES_FILE) as f:
        data = yaml.safe_load(f)
    return [s for s in data.get("samples", []) if s.get("verified", False)]


def _run_sample(url: str) -> ProspectState:
    candidate = ProspectCandidate(name="live-sample", website=url)
    state = ProspectState(candidate=candidate)
    state = enrichment.run(state)
    state = analysis_node.run(state)
    return state


@pytest.mark.skipif(
    not os.getenv("LIVE_SAMPLES"),
    reason="Set LIVE_SAMPLES=1 to run live network samples",
)
@pytest.mark.parametrize("sample", _load_samples(), ids=lambda s: s["label"])
def test_contact_form_detection(sample):
    state = _run_sample(sample["url"])

    has_form = state.analysis.has_contact_form if state.analysis else False
    form_page = state.contact_form_page
    errors = [e.message for e in state.errors]

    assert has_form == sample["expected_has_form"], (
        f"[{sample['label']}] has_contact_form: "
        f"expected {sample['expected_has_form']}, got {has_form}. "
        f"form_page={form_page!r}, errors={errors}"
    )

    expected_page = sample.get("expected_form_page")
    if expected_page is not None:
        assert form_page is not None and (
            form_page == expected_page or expected_page in form_page
        ), (
            f"[{sample['label']}] form_page: expected {expected_page!r}, got {form_page!r}"
        )
    elif not sample["expected_has_form"]:
        assert form_page is None, (
            f"[{sample['label']}] expected no form, but contact_form_page={form_page!r}"
        )

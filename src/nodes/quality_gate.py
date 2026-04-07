import os
import yaml
from src.models.prospect import ProspectState, ErrorRecord

_cfg = None


def _load_config() -> dict:
    global _cfg
    if _cfg is None:
        path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "pipeline_config.yaml"
        ))
        with open(path) as f:
            _cfg = yaml.safe_load(f)["quality_gate"]
    return _cfg


def _c(key):
    return _load_config()[key]


def run(state: ProspectState) -> ProspectState:
    try:
        flags = list(state.quality_flags)

        flags.extend(_check_hot_with_weak_data(state))
        flags.extend(_check_low_confidence(state))
        flags.extend(_check_no_scores(state))
        flags.extend(_check_contact_form_status(state))

        state.quality_flags = flags
        return state

    except Exception as e:
        state.errors.append(ErrorRecord(
            node="quality_gate",
            error_type=type(e).__name__,
            message=str(e)
        ))
        return state


def _check_hot_with_weak_data(state: ProspectState) -> list[str]:
    flags = []
    if state.tier != "HOT":
        return flags

    if state.inbound_profile and state.inbound_profile.data_coverage == "insufficient":
        avg_confidence = 0.0
        if state.scores:
            dim_scores = [
                state.scores.ai_receptionist_likelihood,
                state.scores.inbound_automation_maturity,
                state.scores.lead_capture_maturity,
                state.scores.booking_intake_friction,
                state.scores.follow_up_weakness,
                state.scores.revenue_leakage_opportunity,
            ]
            avg_confidence = sum(d.confidence for d in dim_scores) / len(dim_scores)

        if avg_confidence < _c("hot_weak_data_threshold"):
            flags.append("Inbound data limited to static HTML — phone handling unverified")

    if state.analysis is None:
        flags.append("HOT tier assigned with no website analysis — enrich manually")

    return flags


def _check_low_confidence(state: ProspectState) -> list[str]:
    if state.scores is None:
        return []

    dim_scores = [
        state.scores.ai_receptionist_likelihood,
        state.scores.inbound_automation_maturity,
        state.scores.lead_capture_maturity,
        state.scores.booking_intake_friction,
        state.scores.follow_up_weakness,
        state.scores.revenue_leakage_opportunity,
    ]

    confidences = [d.confidence for d in dim_scores]
    avg_confidence = sum(confidences) / len(confidences)

    if avg_confidence < _c("confidence_floor"):
        return [f"Low signal quality — average confidence {avg_confidence:.0%} across dims 1-6"]

    return []


def _check_no_scores(state: ProspectState) -> list[str]:
    if state.scores is None and not state.skip_scoring:
        return ["No scores computed - pipeline may have failed upstream"]
    return []


def _check_contact_form_status(state: ProspectState) -> list[str]:
    if state.contact_form_status == "unknown":
        return ["Contact form status uncertain - manual verification needed"]
    return []

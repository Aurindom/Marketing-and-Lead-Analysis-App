from langgraph.graph import StateGraph, END
from src.models.prospect import ProspectState


def build_pipeline() -> StateGraph:
    graph = StateGraph(ProspectState)

    graph.add_node("sourcing", sourcing_node)
    graph.add_node("enrichment", enrichment_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("inbound_detection", inbound_detection_node)
    graph.add_node("merge", merge_node)
    graph.add_node("pre_score_filter", pre_score_filter_node)
    graph.add_node("scoring", scoring_node)
    graph.add_node("quality_gate", quality_gate_node)
    graph.add_node("output", output_node)

    graph.set_entry_point("sourcing")

    graph.add_edge("sourcing", "enrichment")
    graph.add_edge("enrichment", "analysis")
    graph.add_edge("enrichment", "inbound_detection")
    graph.add_edge("analysis", "merge")
    graph.add_edge("inbound_detection", "merge")
    graph.add_edge("merge", "pre_score_filter")
    graph.add_conditional_edges(
        "pre_score_filter",
        lambda state: "quality_gate" if state.skip_scoring else "scoring",
        {"quality_gate": "quality_gate", "scoring": "scoring"},
    )
    graph.add_edge("scoring", "quality_gate")
    graph.add_edge("quality_gate", "output")
    graph.add_edge("output", END)

    return graph.compile()


def sourcing_node(state: ProspectState) -> dict:
    from src.nodes.sourcing import run
    errors_before = len(state.errors)
    result = run(state)
    return {
        "candidate": result.candidate,
        "status": result.status,
        "errors": result.errors[errors_before:],
    }


def enrichment_node(state: ProspectState) -> dict:
    from src.nodes.enrichment import run
    errors_before = len(state.errors)
    result = run(state)
    return {
        "raw_text": result.raw_text,
        "detected_scripts": result.detected_scripts,
        "detected_hrefs": result.detected_hrefs,
        "has_form_tag": result.has_form_tag,
        "has_email_input": result.has_email_input,
        "has_submit_control": result.has_submit_control,
        "contact_form_page": result.contact_form_page,
        "contact_page_url": result.contact_page_url,
        "playwright_attempted": result.playwright_attempted,
        "playwright_used": result.playwright_used,
        "blocked_http_status": result.blocked_http_status,
        "internal_js_shell_detected": result.internal_js_shell_detected,
        "internal_playwright_used": result.internal_playwright_used,
        "internal_plugin_playwright_attempted": result.internal_plugin_playwright_attempted,
        "internal_plugin_playwright_used": result.internal_plugin_playwright_used,
        "contact_form_status": result.contact_form_status,
        "contact_form_check_had_errors": result.contact_form_check_had_errors,
        "internal_contact_check_reason": result.internal_contact_check_reason,
        "page_title": result.page_title,
        "meta_description": result.meta_description,
        "errors": result.errors[errors_before:],
    }


def analysis_node(state: ProspectState) -> dict:
    from src.nodes.analysis import run
    errors_before = len(state.errors)
    result = run(state)
    return {"analysis": result.analysis, "errors": result.errors[errors_before:]}


def inbound_detection_node(state: ProspectState) -> dict:
    from src.nodes.inbound_detection import run
    errors_before = len(state.errors)
    result = run(state)
    return {"inbound_profile": result.inbound_profile, "errors": result.errors[errors_before:]}


def pre_score_filter_node(state: ProspectState) -> dict:
    from src.nodes.pre_score_filter import run
    result = run(state)
    return {
        "quality_flags": result.quality_flags,
        "tier": result.tier,
        "skip_scoring": result.skip_scoring,
        "no_website_opportunity": result.no_website_opportunity,
        "errors": [],
    }


def merge_node(state: ProspectState) -> dict:
    return {
        "status": "enriched" if state.status != "failed" else state.status,
        "errors": [],
    }


def scoring_node(state: ProspectState) -> dict:
    from src.nodes.scoring import run
    errors_before = len(state.errors)
    result = run(state)
    return {
        "scores": result.scores,
        "tier": result.tier,
        "errors": result.errors[errors_before:],
    }


def quality_gate_node(state: ProspectState) -> dict:
    from src.nodes.quality_gate import run
    errors_before = len(state.errors)
    result = run(state)
    return {
        "quality_flags": result.quality_flags,
        "errors": result.errors[errors_before:],
    }


def output_node(state: ProspectState) -> dict:
    from src.nodes.output import run
    errors_before = len(state.errors)
    result = run(state)
    return {
        "output_category": result.output_category,
        "errors": result.errors[errors_before:],
    }

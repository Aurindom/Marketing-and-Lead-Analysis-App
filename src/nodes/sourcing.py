from src.models.prospect import ProspectState, ErrorRecord
from src.providers.provider_factory import get_sourcing_provider


def run(state: ProspectState) -> ProspectState:
    if state.candidate.website or state.candidate.place_id:
        state.status = "pending"
        return state

    try:
        candidates = search_businesses(
            state.candidate.category,
            state.candidate.location,
        )
        if not candidates:
            state.status = "failed"
            state.errors.append(ErrorRecord(
                node="sourcing",
                error_type="no_results",
                message=f"No businesses found for {state.candidate.category} in {state.candidate.location}",
            ))
            return state

        state.candidate = candidates[0]
        state.status = "pending"
        return state

    except Exception as e:
        state.status = "failed"
        state.errors.append(ErrorRecord(
            node="sourcing",
            error_type=type(e).__name__,
            message=str(e),
        ))
        return state


def search_businesses(
    niche: str,
    location: str,
    max_results: int = 15,
    max_review_count: int = 500,
) -> list:
    try:
        provider = get_sourcing_provider()
        return provider.search(niche, location, max_results, max_review_count)
    except Exception as e:
        print(f"  [ERROR] Sourcing failed for '{niche}' in '{location}': {type(e).__name__}: {e}")
        return []

from concurrent.futures import ThreadPoolExecutor, as_completed
from src.nodes.sourcing import search_businesses


def run_batch(targets, pipeline, run_one_fn, max_workers: int = 5) -> list:
    """
    For each target, source businesses and run them through the pipeline.
    Returns a flat list of result objects in completion order.

    Args:
        targets: iterable with .niche, .location, .max_results, .max_review_count
        pipeline: built LangGraph pipeline passed to run_one_fn
        run_one_fn: callable(pipeline, candidate) -> result object
        max_workers: thread pool size
    """
    all_candidates = []
    for target in targets:
        businesses = search_businesses(
            target.niche,
            target.location,
            target.max_results,
            target.max_review_count,
        )
        all_candidates.extend(businesses)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_one_fn, pipeline, candidate): candidate
            for candidate in all_candidates
        }
        for future in as_completed(futures):
            results.append(future.result())

    return results

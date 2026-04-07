from typing import TypeVar, Callable

T = TypeVar("T")

_TIER_ORDER = {"HOT": 0, "WARM": 1, "COLD": 2, "NO_WEBSITE": 3}
_NO_WEBSITE_BAND_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def rank_globally(items: list[T], sort_key_fn: Callable[[T], tuple]) -> list[T]:
    """
    Sort items by sort_key_fn and assign sequential priority_rank values.
    Mutates priority_rank in-place on each item.
    """
    sorted_items = sorted(items, key=sort_key_fn)
    for rank, item in enumerate(sorted_items, start=1):
        if hasattr(item, "priority_rank"):
            item.priority_rank = rank
    return sorted_items


def build_summary(results: list, deduplicated: int) -> dict:
    """
    Build a flat counter summary from a list of result objects.
    Expects objects with: tier, data_blocked, skip_scoring attributes.
    """
    hot = warm = cold = no_website = data_blocked = skipped = 0
    for r in results:
        tier = getattr(r, "tier", None)
        if getattr(r, "data_blocked", False):
            data_blocked += 1
        elif getattr(r, "skip_scoring", False) and tier != "NO_WEBSITE":
            skipped += 1
        elif tier == "HOT":
            hot += 1
        elif tier == "WARM":
            warm += 1
        elif tier == "COLD":
            cold += 1
        elif tier == "NO_WEBSITE":
            no_website += 1

    return {
        "total": len(results),
        "hot": hot,
        "warm": warm,
        "cold": cold,
        "no_website": no_website,
        "data_blocked": data_blocked,
        "skipped": skipped,
        "deduplicated": deduplicated,
    }

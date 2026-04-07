import re
from typing import TypeVar

T = TypeVar("T")


def _norm_website(url: str | None) -> str | None:
    if not url:
        return None
    return (
        url.rstrip("/")
        .lower()
        .removeprefix("https://")
        .removeprefix("http://")
        .removeprefix("www.")
    )


def _norm_name(name: str | None) -> str | None:
    if not name:
        return None
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _city_key(location: str | None) -> str:
    if not location:
        return ""
    return location.split(",")[0].strip().lower()


def dedup(items: list[T]) -> tuple[list[T], int]:
    """
    Remove duplicate items using a three-tier key hierarchy:
      1. place_id  (exact)
      2. website   (normalized URL)
      3. name + city  (normalized strings)

    First occurrence wins. Returns (deduped_list, removed_count).
    """
    seen_place: set[str] = set()
    seen_website: set[str] = set()
    seen_name_city: set[tuple[str, str]] = set()

    kept: list[T] = []
    removed = 0

    for item in items:
        place_id: str | None = getattr(item, "place_id", None)
        website = _norm_website(getattr(item, "website", None))
        name = _norm_name(getattr(item, "name", None))
        city = _city_key(getattr(item, "location", None))

        if place_id and place_id in seen_place:
            removed += 1
            continue
        if website and website in seen_website:
            removed += 1
            continue
        if name and city and (name, city) in seen_name_city:
            removed += 1
            continue

        if place_id:
            seen_place.add(place_id)
        if website:
            seen_website.add(website)
        if name and city:
            seen_name_city.add((name, city))

        kept.append(item)

    return kept, removed

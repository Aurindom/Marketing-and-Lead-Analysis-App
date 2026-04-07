import os
from serpapi import GoogleSearch
from src.models.prospect import ProspectCandidate

_PAGE_SIZE = 20
_MAX_PAGES = 3


class SerpApiProvider:
    def search(
        self,
        niche: str,
        location: str,
        max_results: int = 15,
        max_review_count: int = 500,
    ) -> list[ProspectCandidate]:
        city = location.split(",")[0].strip().lower()
        candidates = []
        seen: set = set()

        for page in range(_MAX_PAGES):
            if len(candidates) >= max_results:
                break

            params = {
                "engine": "google_maps",
                "q": f"{niche} in {location}",
                "type": "search",
                "start": page * _PAGE_SIZE,
                "api_key": os.getenv("SERPAPI_API_KEY"),
            }

            search = GoogleSearch(params)
            results = search.get_dict()
            local_results = results.get("local_results", [])

            if not local_results:
                break

            for r in local_results:
                if len(candidates) >= max_results:
                    break
                address = r.get("address", "") or ""
                if address and city not in address.lower():
                    continue
                reviews = r.get("reviews") or 0
                if reviews > max_review_count:
                    continue
                place_id = r.get("place_id")
                website = (r.get("website") or "").rstrip("/").lower()
                name_norm = (r.get("title") or "").strip().lower()
                dedup_key = place_id if place_id else (name_norm, website)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                candidates.append(ProspectCandidate(
                    name=r.get("title", ""),
                    website=r.get("website"),
                    category=r.get("type"),
                    location=address,
                    phone=r.get("phone"),
                    rating=r.get("rating"),
                    review_count=reviews,
                    place_id=place_id,
                ))

        return candidates

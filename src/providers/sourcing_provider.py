from typing import Protocol
from src.models.prospect import ProspectCandidate


class SourcingProvider(Protocol):
    def search(
        self,
        niche: str,
        location: str,
        max_results: int,
        max_review_count: int,
    ) -> list[ProspectCandidate]:
        ...

import os
from src.providers.serpapi_provider import SerpApiProvider

_SUPPORTED = {"serpapi": SerpApiProvider}


def get_sourcing_provider():
    backend = os.getenv("SOURCING_BACKEND", "serpapi").lower()
    cls = _SUPPORTED.get(backend)
    if cls is None:
        raise ValueError(
            f"Unknown SOURCING_BACKEND '{backend}'. Supported: {list(_SUPPORTED)}"
        )
    return cls()

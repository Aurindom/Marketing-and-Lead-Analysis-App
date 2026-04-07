import pytest
from unittest.mock import MagicMock, patch
from src.providers.provider_factory import get_sourcing_provider
from src.providers.serpapi_provider import SerpApiProvider
from src.nodes.sourcing import search_businesses
from src.models.prospect import ProspectCandidate


def _make_candidate(**kwargs):
    defaults = dict(
        name="Test Biz",
        website="https://example.test",
        category="plumbing",
        location="123 Test St, Test City, TS",
        phone="(555) 000-0000",
        rating=4.5,
        review_count=30,
        place_id="abc123",
    )
    defaults.update(kwargs)
    return ProspectCandidate(**defaults)


def test_factory_returns_serpapi_by_default(monkeypatch):
    monkeypatch.delenv("SOURCING_BACKEND", raising=False)
    provider = get_sourcing_provider()
    assert isinstance(provider, SerpApiProvider)


def test_factory_returns_serpapi_when_set_explicitly(monkeypatch):
    monkeypatch.setenv("SOURCING_BACKEND", "serpapi")
    provider = get_sourcing_provider()
    assert isinstance(provider, SerpApiProvider)


def test_factory_raises_on_unknown_backend(monkeypatch):
    monkeypatch.setenv("SOURCING_BACKEND", "places")
    with pytest.raises(ValueError, match="Unknown SOURCING_BACKEND"):
        get_sourcing_provider()


def test_search_businesses_delegates_to_provider(monkeypatch):
    fake_candidates = [_make_candidate()]
    mock_provider = MagicMock()
    mock_provider.search.return_value = fake_candidates

    monkeypatch.setattr(
        "src.nodes.sourcing.get_sourcing_provider",
        lambda: mock_provider,
    )

    result = search_businesses("plumbing", "Test City, TS", max_results=5)
    mock_provider.search.assert_called_once_with("plumbing", "Test City, TS", 5, 500)
    assert result == fake_candidates


def test_search_businesses_returns_empty_on_provider_error(monkeypatch):
    mock_provider = MagicMock()
    mock_provider.search.side_effect = RuntimeError("API down")

    monkeypatch.setattr(
        "src.nodes.sourcing.get_sourcing_provider",
        lambda: mock_provider,
    )

    result = search_businesses("dental", "Test City, TS")
    assert result == []


def test_serpapi_provider_conforms_to_protocol():
    from src.providers.sourcing_provider import SourcingProvider
    provider = SerpApiProvider()
    assert hasattr(provider, "search")
    assert callable(provider.search)

import pytest
from src.services.dedup import dedup, _norm_website, _norm_name, _city_key


class _Item:
    def __init__(self, name=None, website=None, location=None, place_id=None):
        self.name = name
        self.website = website
        self.location = location
        self.place_id = place_id


def test_norm_website_strips_trailing_slash():
    assert _norm_website("https://example.com/") == "example.com"


def test_norm_website_strips_protocol_and_www():
    assert _norm_website("http://www.example.com") == "example.com"


def test_norm_website_none():
    assert _norm_website(None) is None


def test_norm_name_lowercases_and_strips_punctuation():
    assert _norm_name("Alpha Plumbing, LLC!") == "alpha plumbing llc"


def test_city_key_extracts_first_segment():
    assert _city_key("Test City, TS 12345") == "test city"


def test_dedup_by_place_id_keeps_first():
    a = _Item(name="Biz A", location="Test City, TS", place_id="PLACE_001")
    b = _Item(name="Biz A duplicate", location="Test City, TS", place_id="PLACE_001")
    result, removed = dedup([a, b])
    assert removed == 1
    assert len(result) == 1
    assert result[0] is a


def test_dedup_by_website_keeps_first():
    a = _Item(name="Biz A", website="https://example.com/", location="Test City, TS")
    b = _Item(name="Biz A Alt", website="http://example.com", location="Test City, TS")
    result, removed = dedup([a, b])
    assert removed == 1
    assert result[0] is a


def test_dedup_by_name_city_keeps_first():
    a = _Item(name="Alpha Plumbing", location="Test City, TS")
    b = _Item(name="Alpha Plumbing", location="Test City, TS")
    result, removed = dedup([a, b])
    assert removed == 1
    assert result[0] is a


def test_dedup_different_cities_both_kept():
    a = _Item(name="Alpha Plumbing", location="City One, TS")
    b = _Item(name="Alpha Plumbing", location="City Two, TS")
    result, removed = dedup([a, b])
    assert removed == 0
    assert len(result) == 2


def test_dedup_different_websites_both_kept():
    a = _Item(name="Biz A", website="https://biz-a.test", location="Test City, TS")
    b = _Item(name="Biz B", website="https://biz-b.test", location="Test City, TS")
    result, removed = dedup([a, b])
    assert removed == 0
    assert len(result) == 2


def test_dedup_empty_list():
    result, removed = dedup([])
    assert result == []
    assert removed == 0


def test_dedup_place_id_takes_precedence_over_name_city():
    a = _Item(name="Biz A", location="Test City, TS", place_id="PLACE_001")
    b = _Item(name="Biz A", location="Test City, TS", place_id="PLACE_002")
    result, removed = dedup([a, b])
    assert removed == 1
    assert result[0] is a


def test_dedup_no_place_id_no_website_falls_back_to_name_city():
    a = _Item(name="Biz X", location="Test City, TS")
    b = _Item(name="Biz X", location="Test City, TS")
    c = _Item(name="Biz Y", location="Test City, TS")
    result, removed = dedup([a, b, c])
    assert removed == 1
    assert len(result) == 2

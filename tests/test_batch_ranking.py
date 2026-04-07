import pytest
from src.services.ranking import rank_globally, build_summary


class _Score:
    def __init__(self, score=5.0, confidence=0.8):
        self.score = score
        self.confidence = confidence


class _Scores:
    def __init__(self, val=5.0):
        s = _Score(val)
        self.ai_receptionist_likelihood = s
        self.inbound_automation_maturity = s
        self.lead_capture_maturity = s
        self.booking_intake_friction = s
        self.follow_up_weakness = s
        self.revenue_leakage_opportunity = s
        self.ascent_fit_score = s


class _Result:
    def __init__(self, name, tier, scores=None, no_website_opportunity=None,
                 review_count=0, rating=0.0, data_blocked=False, skip_scoring=False):
        self.name = name
        self.tier = tier
        self.scores = scores
        self.no_website_opportunity = no_website_opportunity
        self.review_count = review_count
        self.rating = rating
        self.data_blocked = data_blocked
        self.skip_scoring = skip_scoring
        self.priority_rank = None
        self.place_id = None
        self.website = None
        self.location = None


def _sort_key(r):
    _TIER_ORDER = {"HOT": 0, "WARM": 1, "COLD": 2, "NO_WEBSITE": 3}
    _BAND_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    tier_rank = _TIER_ORDER.get(r.tier, 4)
    if r.tier == "NO_WEBSITE":
        band_rank = _BAND_ORDER.get(r.no_website_opportunity or "LOW", 2)
        return (tier_rank, band_rank, -(r.review_count or 0), -(r.rating or 0.0), r.name.lower())
    score = sum(
        getattr(r.scores, d).score * getattr(r.scores, d).confidence
        for d in ["ai_receptionist_likelihood", "inbound_automation_maturity",
                  "lead_capture_maturity", "booking_intake_friction",
                  "follow_up_weakness", "revenue_leakage_opportunity", "ascent_fit_score"]
    ) if r.scores else 0.0
    return (tier_rank, 0, -score, 0.0, r.name.lower())


def test_rank_globally_assigns_sequential_ranks():
    items = [
        _Result("B", "WARM", _Scores(4.0)),
        _Result("A", "HOT", _Scores(7.0)),
        _Result("C", "COLD", _Scores(2.0)),
    ]
    ranked = rank_globally(items, _sort_key)
    assert ranked[0].name == "A"
    assert ranked[0].priority_rank == 1
    assert ranked[1].name == "B"
    assert ranked[1].priority_rank == 2
    assert ranked[2].name == "C"
    assert ranked[2].priority_rank == 3


def test_rank_globally_hot_before_warm_before_cold():
    items = [
        _Result("Cold Biz", "COLD", _Scores()),
        _Result("Hot Biz", "HOT", _Scores()),
        _Result("Warm Biz", "WARM", _Scores()),
    ]
    ranked = rank_globally(items, _sort_key)
    tiers = [r.tier for r in ranked]
    assert tiers == ["HOT", "WARM", "COLD"]


def test_rank_globally_no_website_last():
    items = [
        _Result("NW Biz", "NO_WEBSITE", no_website_opportunity="HIGH", review_count=100, rating=4.5),
        _Result("Cold Biz", "COLD", _Scores()),
    ]
    ranked = rank_globally(items, _sort_key)
    assert ranked[0].tier == "COLD"
    assert ranked[1].tier == "NO_WEBSITE"


def test_rank_globally_no_website_band_order():
    items = [
        _Result("NW Low", "NO_WEBSITE", no_website_opportunity="LOW", review_count=5, rating=3.0),
        _Result("NW High", "NO_WEBSITE", no_website_opportunity="HIGH", review_count=80, rating=4.8),
        _Result("NW Med", "NO_WEBSITE", no_website_opportunity="MEDIUM", review_count=20, rating=4.0),
    ]
    ranked = rank_globally(items, _sort_key)
    bands = [r.no_website_opportunity for r in ranked]
    assert bands == ["HIGH", "MEDIUM", "LOW"]


def test_rank_globally_empty_list():
    result = rank_globally([], _sort_key)
    assert result == []


def test_build_summary_counts_correctly():
    items = [
        _Result("H1", "HOT", _Scores()),
        _Result("W1", "WARM", _Scores()),
        _Result("C1", "COLD", _Scores()),
        _Result("NW1", "NO_WEBSITE", no_website_opportunity="HIGH"),
        _Result("DB1", "COLD", data_blocked=True),
        _Result("SK1", "COLD", skip_scoring=True),
    ]
    summary = build_summary(items, deduplicated=3)
    assert summary["total"] == 6
    assert summary["hot"] == 1
    assert summary["warm"] == 1
    assert summary["cold"] == 1
    assert summary["no_website"] == 1
    assert summary["data_blocked"] == 1
    assert summary["skipped"] == 1
    assert summary["deduplicated"] == 3


def test_build_summary_empty():
    summary = build_summary([], deduplicated=0)
    assert summary["total"] == 0
    assert all(v == 0 for k, v in summary.items() if k != "total")

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    mock_pipeline = MagicMock()
    with patch("api.build_pipeline", return_value=mock_pipeline):
        from api import app
        with TestClient(app) as c:
            yield c


def test_batch_missing_targets_returns_422(client):
    resp = client.post("/batch", json={"targets": []})
    assert resp.status_code == 422


def test_batch_returns_correct_structure(client):
    with patch("api.run_batch", return_value=[]):
        with patch("api.dedup", return_value=([], 0)):
            with patch("api.rank_globally", return_value=[]):
                with patch("api.build_summary", return_value={
                    "total": 0, "hot": 0, "warm": 0, "cold": 0,
                    "no_website": 0, "data_blocked": 0, "skipped": 0, "deduplicated": 0,
                }):
                    resp = client.post("/batch", json={
                        "targets": [{"niche": "dental", "location": "Test City, TS"}]
                    })

    assert resp.status_code == 200
    body = resp.json()
    assert "targets" in body
    assert "summary" in body
    assert "results" in body
    assert body["targets"] == 1


def test_batch_summary_keys_present(client):
    with patch("api.run_batch", return_value=[]):
        with patch("api.dedup", return_value=([], 2)):
            with patch("api.rank_globally", return_value=[]):
                with patch("api.build_summary", return_value={
                    "total": 0, "hot": 0, "warm": 0, "cold": 0,
                    "no_website": 0, "data_blocked": 0, "skipped": 0, "deduplicated": 2,
                }):
                    resp = client.post("/batch", json={
                        "targets": [{"niche": "plumbing", "location": "Test City, TS"}]
                    })

    assert resp.status_code == 200
    summary = resp.json()["summary"]
    for key in ["total", "hot", "warm", "cold", "no_website", "data_blocked", "skipped", "deduplicated"]:
        assert key in summary


def test_batch_target_count_matches_request(client):
    with patch("api.run_batch", return_value=[]):
        with patch("api.dedup", return_value=([], 0)):
            with patch("api.rank_globally", return_value=[]):
                with patch("api.build_summary", return_value={
                    "total": 0, "hot": 0, "warm": 0, "cold": 0,
                    "no_website": 0, "data_blocked": 0, "skipped": 0, "deduplicated": 0,
                }):
                    resp = client.post("/batch", json={
                        "targets": [
                            {"niche": "dental", "location": "City A"},
                            {"niche": "plumbing", "location": "City B"},
                        ]
                    })

    assert resp.status_code == 200
    assert resp.json()["targets"] == 2


def test_batch_pipeline_not_ready_returns_503(client):
    with patch("api._pipeline", None):
        resp = client.post("/batch", json={"targets": [{"niche": "dental", "location": "Test City"}]})

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Pipeline not ready. Startup may have failed."

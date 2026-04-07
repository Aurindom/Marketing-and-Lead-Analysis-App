import json
import os
import pytest
import tempfile
from src.utils.audit_logger import log_record, log_summary


@pytest.fixture
def audit_file(tmp_path, monkeypatch):
    path = str(tmp_path / "audit.jsonl")
    monkeypatch.setenv("AUDIT_LOG_ENABLED", "true")
    monkeypatch.setenv("AUDIT_LOG_PATH", path)
    return path


def _read_events(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_log_record_disabled_by_default(tmp_path, monkeypatch):
    path = str(tmp_path / "audit.jsonl")
    monkeypatch.setenv("AUDIT_LOG_ENABLED", "false")
    monkeypatch.setenv("AUDIT_LOG_PATH", path)
    log_record(name="Test Biz", tier="HOT", contact_form_status="found",
               flags=[], errors=[], evidence=[])
    assert not os.path.exists(path)


def test_log_record_writes_event(audit_file):
    log_record(
        name="Alpha Plumbing",
        tier="HOT",
        contact_form_status="found",
        flags=["flag1"],
        errors=[],
        evidence=["evidence1"],
        source="test",
    )
    events = _read_events(audit_file)
    assert len(events) == 1
    e = events[0]
    assert e["event"] == "record"
    assert e["name"] == "Alpha Plumbing"
    assert e["tier"] == "HOT"
    assert e["contact_form_status"] == "found"
    assert e["flags"] == ["flag1"]
    assert e["evidence"] == ["evidence1"]
    assert e["source"] == "test"
    assert "ts" in e


def test_log_summary_writes_event(audit_file):
    log_summary(
        source="test_runner",
        total=10,
        hot=3,
        warm=4,
        cold=2,
        no_website=1,
        data_blocked=0,
        skipped=0,
        deduplicated=2,
        targets=["dental / Austin, TX"],
    )
    events = _read_events(audit_file)
    assert len(events) == 1
    e = events[0]
    assert e["event"] == "summary"
    assert e["source"] == "test_runner"
    assert e["total"] == 10
    assert e["hot"] == 3
    assert e["deduplicated"] == 2
    assert e["targets"] == ["dental / Austin, TX"]
    assert "ts" in e


def test_multiple_events_appended(audit_file):
    log_record(name="Biz A", tier="HOT", contact_form_status="found",
               flags=[], errors=[], evidence=[])
    log_record(name="Biz B", tier="COLD", contact_form_status="missing",
               flags=[], errors=[], evidence=[])
    log_summary(source="test", total=2, hot=1, warm=0, cold=1,
                no_website=0, data_blocked=0, skipped=0)
    events = _read_events(audit_file)
    assert len(events) == 3
    assert events[0]["event"] == "record"
    assert events[1]["event"] == "record"
    assert events[2]["event"] == "summary"


def test_log_record_each_line_is_valid_json(audit_file):
    log_record(name='Biz "quoted"', tier="WARM", contact_form_status="unknown",
               flags=[], errors=["err: something"], evidence=[])
    with open(audit_file, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["name"] == 'Biz "quoted"'


def test_log_summary_no_targets_defaults_empty(audit_file):
    log_summary(source="run_pipeline", total=0, hot=0, warm=0, cold=0,
                no_website=0, data_blocked=0, skipped=0)
    events = _read_events(audit_file)
    assert events[0]["targets"] == []

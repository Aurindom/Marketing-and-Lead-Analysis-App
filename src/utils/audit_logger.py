import json
import os
from datetime import datetime, timezone


def _enabled() -> bool:
    return os.getenv("AUDIT_LOG_ENABLED", "false").lower() == "true"


def _log_path() -> str:
    return os.getenv("AUDIT_LOG_PATH", os.path.join("output", "audit.jsonl"))


def _append(event: dict) -> None:
    path = _log_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def log_record(
    *,
    name: str,
    tier: str | None,
    contact_form_status: str,
    flags: list[str],
    errors: list[str],
    evidence: list[str],
    source: str = "pipeline",
) -> None:
    if not _enabled():
        return
    _append({
        "event": "record",
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "name": name,
        "tier": tier,
        "contact_form_status": contact_form_status,
        "flags": flags,
        "errors": errors,
        "evidence": evidence,
    })


def log_summary(
    *,
    source: str,
    total: int,
    hot: int,
    warm: int,
    cold: int,
    no_website: int,
    data_blocked: int,
    skipped: int,
    deduplicated: int = 0,
    targets: list[str] | None = None,
) -> None:
    if not _enabled():
        return
    _append({
        "event": "summary",
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "targets": targets or [],
        "total": total,
        "hot": hot,
        "warm": warm,
        "cold": cold,
        "no_website": no_website,
        "data_blocked": data_blocked,
        "skipped": skipped,
        "deduplicated": deduplicated,
    })

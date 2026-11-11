"""Publishers without a login route for the configured school, for half an hour.

When a publisher's institution list has no entry for the school (Science's CARSI
list without it; BMJ's federation list without CARSI), every other article there
waits the same login out. The publisher and the school are written to
``<data dir>/login_routes.json``: a later article of that publisher still opens
and takes an open PDF, but ends at once where it would sign in (the user,
2026-11-11). Another school is another key; entries older than ``KEEP_SEC`` are
dropped when the file is read, so a later batch tries again.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .entitlements import _data_dir, _read_json, _write_json

KEEP_SEC = 30 * 60


def ledger_path() -> Path:
    return _data_dir() / "login_routes.json"


def school_key(config: dict[str, Any]) -> str:
    """The configured school: its entityID, else its CARSI name; "" without one."""
    for field in ("idp_entity_id", "carsi_idp_name", "carsi_idp_name_en"):
        value = " ".join(str(config.get(field) or "").split())
        if value:
            return value.lower()
    return ""


def _key(publisher: str, school: str) -> str:
    publisher = " ".join(str(publisher or "").lower().split())
    return f"{publisher}|{school}" if publisher and school else ""


def _recent(now: float) -> dict[str, dict[str, Any]]:
    data = _read_json(ledger_path())
    return {key: entry for key, entry in data.items()
            if isinstance(entry, dict) and isinstance(entry.get("at"), (int, float)) and now - KEEP_SEC < entry["at"] <= now}


def missing_since(publisher: str, school: str, now: float | None = None) -> str:
    """The DOI that found no route for this school at this publisher in the last ``KEEP_SEC``, or ""."""
    key = _key(publisher, school)
    entry = _recent(time.time() if now is None else now).get(key) if key else None
    return str(entry.get("doi") or "") if entry else ""


def remember(publisher: str, school: str, doi: str, now: float | None = None) -> bool:
    """Write the publisher as having no route for the school; False without either."""
    key = _key(publisher, school)
    if not key:
        return False
    now = time.time() if now is None else now
    data = _recent(now)
    data[key] = {"at": now, "doi": doi}
    _write_json(ledger_path(), data)
    return True

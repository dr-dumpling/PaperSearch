"""Publishers without a login route for the configured school, for half an hour.

When a publisher's institution list has no entry for the school (Science's CARSI
list without it; BMJ's federation list without CARSI), every other article there
waits the same login out. The publisher and the school are written to
``<data dir>/login_routes.json``: a later article of that publisher still opens
and takes an open PDF, but ends at once where it would sign in (the user,
2026-11-11). Another school is another key; entries older than ``KEEP_SEC`` are
dropped when the file is read, so a later batch tries again.

A site whose article page showed no way to any school's login at all (no institution
entry, no institution search or list, no federation chooser: an open-access site,
a site with personal accounts only) is written to ``<data dir>/no_school_entry.json``
for the batch that found it: its later papers in the same batch end at once where
they would sign in (user, 2026-11-18). Another batch looks again.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .entitlements import _data_dir, _read_json, _write_json

KEEP_SEC = 30 * 60
# A batch can run for hours; its own id keeps it apart from the next one.
NO_ENTRY_KEEP_SEC = 24 * 3600


def ledger_path() -> Path:
    return _data_dir() / "login_routes.json"


def school_key(config: dict[str, Any]) -> str:
    """The configured school: its entityID and its name, else either; "" without
    one. The name keeps apart schools signing in through one shared entry (a
    national one: Norway's, 2026-11-13), whose entityID is the same for all."""
    entity, name, english = (" ".join(str(config.get(field) or "").split())
                             for field in ("idp_entity_id", "school_name", "school_name_en"))
    return " | ".join(part for part in (entity, name or english) if part).lower()


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


def no_entry_path() -> Path:
    return _data_dir() / "no_school_entry.json"


def _no_entry_key(host: str, batch: str) -> str:
    host = " ".join(str(host or "").lower().split())
    batch = " ".join(str(batch or "").split())
    return f"{batch}|{host}" if host and batch else ""


def no_entry_since(host: str, batch: str, now: float | None = None) -> dict[str, Any]:
    """What an earlier paper of batch ``batch`` found at ``host`` (``{"doi", "reason"}``) when
    its page showed no school login entry; {} otherwise, or without a batch."""
    key = _no_entry_key(host, batch)
    if not key:
        return {}
    now = time.time() if now is None else now
    entry = _read_json(no_entry_path()).get(key)
    if (not isinstance(entry, dict) or not isinstance(entry.get("at"), (int, float))
            or not now - NO_ENTRY_KEEP_SEC < entry["at"] <= now):
        return {}
    return {"doi": str(entry.get("doi") or ""), "reason": str(entry.get("reason") or "")}


def remember_no_entry(host: str, batch: str, doi: str, reason: str, now: float | None = None) -> bool:
    """Write ``host`` as showing no school login entry in batch ``batch``; False without either."""
    key = _no_entry_key(host, batch)
    if not key:
        return False
    now = time.time() if now is None else now
    data = {k: e for k, e in _read_json(no_entry_path()).items()
            if isinstance(e, dict) and isinstance(e.get("at"), (int, float)) and now - NO_ENTRY_KEEP_SEC < e["at"] <= now}
    data[key] = {"at": now, "doi": doi, "reason": reason}
    _write_json(no_entry_path(), data)
    return True

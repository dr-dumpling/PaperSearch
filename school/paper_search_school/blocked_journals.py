"""Journals whose site blocked the current network, for half an hour.

A journal's page that answers with a protection or block page (Cloudflare's
"Sorry, you have been blocked"; ``access_blocked``) is written to
``<data dir>/blocked_journals.json``: the journal's later articles are answered
at once while every other journal goes on. One publisher may license one journal
and not another, and its journals can sit on other sites (the user, 2026-11-02;
BMJ's Cloudflare page came from the exit network). The file, not the process,
keeps it: PaperSearch starts the backend anew for every article. Entries older
than ``KEEP_SEC`` are dropped when the file is read, so a later batch tries again.
Every ``RECHECK_SEC`` one article tries the site again (``skip_for``): the user may
have moved to another network (Windows, 2026-11-16); its site not blocking it any
more ends the journal's entry (``recheck_ended``).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .entitlements import _data_dir, _read_json, _write_json

KEEP_SEC = 30 * 60
RECHECK_SEC = 5 * 60  # the user, 2026-11-16 (two minutes first)


def ledger_path() -> Path:
    return _data_dir() / "blocked_journals.json"


def journal_key(identity: dict[str, Any]) -> str:
    """A journal by its ISSNs, else by its name; "" when neither is known."""
    issns = sorted(str(issn).upper() for issn in identity.get("issn") or () if issn)
    if issns:
        return "issn:" + ",".join(issns)
    name = " ".join(str(identity.get("journal") or "").lower().split())
    return f"journal:{name}" if name else ""


def _recent(now: float) -> dict[str, dict[str, Any]]:
    data = _read_json(ledger_path())
    return {key: entry for key, entry in data.items()
            if isinstance(entry, dict) and isinstance(entry.get("at"), (int, float)) and now - KEEP_SEC < entry["at"] <= now}


def any_recent(now: float | None = None) -> bool:
    """Whether any journal is blocked now (the journal lookup is needed only then)."""
    return bool(_recent(time.time() if now is None else now))


def blocked_by(identity: dict[str, Any], now: float | None = None) -> str:
    """The DOI whose page blocked this journal's site in the last ``KEEP_SEC``, or ""."""
    key = journal_key(identity)
    entry = _recent(time.time() if now is None else now).get(key) if key else None
    return str(entry.get("doi") or "") if entry else ""


def skip_for(identity: dict[str, Any], doi: str, now: float | None = None) -> str:
    """The DOI whose page blocked this journal's site, when this article is answered at
    once; "" when it is tried: the journal is not blocked, or this article re-checks the
    site, once every ``RECHECK_SEC`` (``recheck_ended`` says how that went)."""
    key = journal_key(identity)
    if not key:
        return ""
    now = time.time() if now is None else now
    data = _recent(now)
    entry = data.get(key)
    if not entry:
        return ""
    if now - max(float(entry["at"]), float(entry.get("checked_at") or 0)) >= RECHECK_SEC:
        entry.update(checked_at=now, checked_by=(doi or "").lower())
        _write_json(ledger_path(), data)
        return ""
    return str(entry.get("doi") or "")


def recheck_ended(doi: str, blocked: bool) -> None:
    """The article that re-checked a blocked journal's site ended: unless that site
    blocked it again (``remember`` has written so), the journal is open again."""
    if blocked or not doi:
        return
    data = _read_json(ledger_path())
    if not isinstance(data, dict):
        return
    keys = [key for key, entry in data.items()
            if isinstance(entry, dict) and entry.get("checked_by") == doi.lower()]
    if keys:
        for key in keys:
            del data[key]
        _write_json(ledger_path(), data)


def remember(doi: str, identity: dict[str, Any], now: float | None = None) -> bool:
    """Write the journal as blocked; False when the journal is not known."""
    key = journal_key(identity)
    if not key:
        return False
    now = time.time() if now is None else now
    data = _recent(now)
    data[key] = {"at": now, "doi": doi}
    _write_json(ledger_path(), data)
    return True

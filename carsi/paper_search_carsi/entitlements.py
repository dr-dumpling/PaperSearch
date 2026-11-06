"""Remembered entitlement decisions: which journals/publishers to skip or fetch.

The user marks the current paper in the progress window: "this journal has
access", "no access to this journal" or "no access to this publisher". The
decision is stored in ``<data dir>/entitlements.json`` and applies to every
later download: a journal or publisher marked as having no access is skipped
before any browser opens; an explicit "has access" overrides a publisher-level
skip for that journal.

Journals are identified by ISSN (from Crossref, cached in
``<data dir>/journal_cache.json``); the journal title is the fallback key.
"""
from __future__ import annotations

import html
import json
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .log import get_logger

log = get_logger()

class UserMarkedNoEntitlement(Exception):
    """The user pressed "no access" for this paper's journal or publisher."""


class UserSkippedArticle(UserMarkedNoEntitlement):
    """The user pressed "skip this paper": it ends, nothing is remembered."""


class UserStoppedBatch(UserMarkedNoEntitlement):
    """The user pressed "stop the task": this paper ends and the batch stops."""


# Not an entitlement decision: nothing is recorded, the batch ends.
STOP_BATCH = "stop_batch"
SHOW_BROWSER = "show_browser"


SKIP = "skip"
ALLOW = "allow"
_ACTIONS = {
    "skip_item": ("item", SKIP),
    "allow_journal": ("journal", ALLOW),
    "skip_journal": ("journal", SKIP),
    "skip_publisher": ("publisher", SKIP),
}


def _data_dir() -> Path:
    return Path(os.environ.get("CARSI_DATA_DIR", str(Path.home() / ".local" / "share" / "paper-search-cli" / "carsi")))


def entitlements_path() -> Path:
    return _data_dir() / "entitlements.json"


def control_path() -> Path:
    return _data_dir() / "progress" / "control.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --- journal identity ---------------------------------------------------------

def journal_identity(doi: str, *, lookup: bool = True) -> dict[str, Any]:
    """{"issn": [...], "journal": str, "publisher": str} for a DOI (cached)."""
    doi = (doi or "").strip().lower()
    cache_file = _data_dir() / "journal_cache.json"
    cache = _read_json(cache_file)
    if doi in cache:
        return cache[doi]
    identity: dict[str, Any] = {"issn": [], "journal": "", "publisher": ""}
    if lookup and doi:
        try:
            import requests

            response = requests.get(f"https://api.crossref.org/works/{doi}", timeout=10,
                                    headers={"User-Agent": "paper-search-carsi (entitlement memory)"})
            if response.status_code == 200:
                message = response.json().get("message", {})
                identity = {
                    "issn": sorted({str(i).upper() for i in message.get("ISSN", []) if i}),
                    # Crossref titles can carry HTML entities ("Arthritis &amp; Rheumatology").
                    "journal": html.unescape((message.get("container-title") or [""])[0]),
                    "publisher": message.get("publisher", ""),
                }
                cache[doi] = identity
                try:
                    _write_json(cache_file, cache)
                except Exception:
                    pass
        except Exception as exc:
            log.info("   [Entitlement] journal lookup failed: %s", type(exc).__name__)
    return identity


def _journal_keys(identity: dict[str, Any]) -> list[str]:
    keys = [f"issn:{issn}" for issn in identity.get("issn") or []]
    title = re.sub(r"\s+", " ", str(identity.get("journal") or "")).strip().lower()
    if title:
        keys.append(f"journal:{title}")
    return keys


def _publisher_key(publisher: str) -> str:
    return f"publisher:{(publisher or '').strip().lower()}"


# --- decisions -----------------------------------------------------------------

def load() -> dict[str, Any]:
    return _read_json(entitlements_path())


def decision_for(doi: str, publisher: str, *, identity: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The remembered decision for this paper, or None. Journal beats publisher."""
    entries = load()
    if not entries:
        return None
    identity = identity if identity is not None else journal_identity(doi)
    for key in _journal_keys(identity):
        if key in entries:
            return {**entries[key], "key": key}
    key = _publisher_key(publisher)
    if publisher and key in entries:
        return {**entries[key], "key": key}
    return None


def record(doi: str, publisher: str, action: str, *, identity: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Store the user's decision for this paper's journal or publisher."""
    if action not in _ACTIONS:
        return None
    scope, decision = _ACTIONS[action]
    identity = identity if identity is not None else journal_identity(doi)
    if scope == "journal":
        keys = _journal_keys(identity)
        if not keys:
            return None
        key = keys[0]
    else:
        if not publisher:
            return None
        key = _publisher_key(publisher)
    entry = {
        "decision": decision,
        "scope": scope,
        "journal": identity.get("journal", ""),
        "issn": identity.get("issn", []),
        "publisher": publisher,
        "example_doi": doi,
        "decided_at": datetime.now().isoformat(timespec="seconds"),
    }
    entries = load()
    entries[key] = entry
    _write_json(entitlements_path(), entries)
    log.info("   [Entitlement] %s -> %s (%s)", key, decision, doi)
    return {**entry, "key": key}


def clear(key: str) -> bool:
    entries = load()
    if key not in entries:
        return False
    del entries[key]
    _write_json(entitlements_path(), entries)
    return True


# --- progress-window control channel ---------------------------------------------

def request_action(current: str, action: str, run_id: str = "") -> None:
    """Written by the progress window when the user presses a button."""
    if action not in _ACTIONS and action not in (STOP_BATCH, SHOW_BROWSER):
        raise ValueError("unknown action")
    data = {"current": current, "action": action, "run_id": run_id, "at": time.time()}
    if action == STOP_BATCH and run_id:
        # A batch stop survives both item handoff and later focus requests.
        # A new run has a new identity, so an old stop cannot cancel it.
        _write_json(control_path().with_name("stop.json"), data)
    else:
        _write_json(control_path(), data)


def batch_stop_requested() -> bool:
    """A durable stop for the current run, including the gap between papers."""
    stop = _read_json(control_path().with_name("stop.json"))
    if stop.get("action") != STOP_BATCH or not stop.get("run_id"):
        return False
    state = _read_json(control_path().with_name("current.json"))
    return state.get("status") == "running" and stop["run_id"] == state.get("run_id")


def take_action(doi: str, since: float) -> str | None:
    """The user's pending action for this paper (requested after ``since``), consumed once."""
    if batch_stop_requested():
        return STOP_BATCH
    path = control_path()
    data = _read_json(path)
    if not data or str(data.get("current", "")).lower() != (doi or "").lower():
        return None
    try:
        if float(data.get("at", 0)) < since:
            return None
    except (TypeError, ValueError):
        return None
    try:
        path.unlink()
    except OSError:
        pass
    action = data.get("action")
    return action if action in _ACTIONS or action in (STOP_BATCH, SHOW_BROWSER) else None


def apply_user_decision(doi: str, publisher: str, since: float) -> str | None:
    """Apply a progress-window button for this paper: record it, and raise on skip."""
    action = take_action(doi, since)
    if not action:
        return None
    if action == SHOW_BROWSER:
        return action  # an explicit focus request, never an entitlement decision
    if action == STOP_BATCH:
        raise UserStoppedBatch(action)
    if action == "skip_item":
        raise UserSkippedArticle(action)
    try:
        record(doi, publisher, action)
    except Exception as exc:
        log.info("   [Entitlement] could not record decision: %s", type(exc).__name__)
    if action.startswith("skip"):
        raise UserMarkedNoEntitlement(action)
    return action

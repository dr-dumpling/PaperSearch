"""At most ``publisher_hourly_limit`` articles per publisher in any hour (default 100).

Libraries count more than about a hundred downloads an hour as abuse, and
publishers suspend the school's access for it (dependencies section 6, state L).
Every article about to open a publisher's site is counted in
``<data dir>/publisher_rate.json``. Once a publisher has had its hour's worth,
the next article waits until the oldest of them is an hour old: the backend
answers ``rate_limited`` with the seconds to wait, and psc's batch waits and
tries the same article again.
"""
from __future__ import annotations

import time
from pathlib import Path

from .entitlements import _data_dir, _read_json, _write_json

HOUR = 3600
DEFAULT_LIMIT = 100


def ledger_path() -> Path:
    return _data_dir() / "publisher_rate.json"


def _last_hour(data: dict, key: str, now: float) -> list[float]:
    times = data.get(key)
    return sorted(t for t in times if isinstance(t, (int, float)) and now - HOUR < t <= now) \
        if isinstance(times, list) else []


def wait_seconds(key: str, limit: int, now: float | None = None) -> int:
    """Seconds until ``key`` may open another article; 0 = now (or no limit)."""
    if limit <= 0 or not key:
        return 0
    now = time.time() if now is None else now
    recent = _last_hour(_read_json(ledger_path()), key, now)
    if len(recent) < limit:
        return 0
    return int(recent[-limit] + HOUR - now) + 1


def record(key: str, now: float | None = None) -> None:
    """Count one article opened on ``key``'s site; older entries are dropped."""
    if not key:
        return
    now = time.time() if now is None else now
    data = _read_json(ledger_path())
    kept = {name: times for name in data if (times := _last_hour(data, name, now))}
    kept.setdefault(key, []).append(now)
    _write_json(ledger_path(), kept)

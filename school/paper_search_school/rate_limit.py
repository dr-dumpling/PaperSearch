"""At most ``publisher_hourly_limit`` articles per publisher in each hour (default 100).

Libraries count more than about a hundred downloads an hour as abuse, and
publishers suspend the school's access for it (dependencies section 6, state L).
A publisher's hour starts with the first article opened on its site, and
``<data dir>/publisher_rate.json`` keeps when it started and how many it has
opened. Once the hour has its limit, the next article waits until the hour is
over; the count then starts again with that article. (Counted over any 60
minutes, a batch went on one article at a time as each of the last hour's aged
out, which read as stopping again and again: the user, 2026-11-13.) The backend
answers ``rate_limited`` with the seconds to wait, and psc's batch waits and tries
the same article again.
"""
from __future__ import annotations

import time
from pathlib import Path

from .entitlements import _data_dir, _read_json, _write_json

HOUR = 3600
DEFAULT_LIMIT = 100


def ledger_path() -> Path:
    return _data_dir() / "publisher_rate.json"


def _hour(data: dict, key: str, now: float) -> tuple[float, int] | None:
    """(start, count) of ``key``'s hour still running at ``now``; None when none is."""
    entry = data.get(key)
    if isinstance(entry, list):
        # Written before 0.6.3, the times of the articles opened: their hour starts with the oldest of the last hour.
        times = sorted(t for t in entry if isinstance(t, (int, float)) and now - HOUR < t <= now)
        entry = {"start": times[0], "count": len(times)} if times else None
    if not isinstance(entry, dict):
        return None
    start, count = entry.get("start"), entry.get("count")
    if (not isinstance(start, (int, float)) or isinstance(start, bool)
            or not isinstance(count, int) or isinstance(count, bool) or not now - HOUR < start <= now):
        return None
    return float(start), count


def wait_seconds(key: str, limit: int, now: float | None = None) -> int:
    """Seconds until ``key`` may open another article; 0 = now (or no limit)."""
    if limit <= 0 or not key:
        return 0
    now = time.time() if now is None else now
    hour = _hour(_read_json(ledger_path()), key, now)
    if hour is None or hour[1] < limit:
        return 0
    return int(hour[0] + HOUR - now) + 1


def record(key: str, now: float | None = None) -> None:
    """Count one article opened on ``key``'s site, in its hour or in a new one; hours over are dropped."""
    if not key:
        return
    now = time.time() if now is None else now
    data = _read_json(ledger_path())
    kept = {name: {"start": hour[0], "count": hour[1]} for name in data if (hour := _hour(data, name, now))}
    current = kept.get(key, {"start": now, "count": 0})
    kept[key] = {"start": current["start"], "count": current["count"] + 1}
    _write_json(ledger_path(), kept)

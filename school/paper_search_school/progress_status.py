"""Read-only, allowlisted task snapshots and bounded JSONL monitoring.

Can also run as a standalone script, without importing package startup code:
python paper_search_school/progress_status.py --json --watch --run-id UUID

An unbound snapshot describes the latest file, not a newly requested task.
Bind run_id to distinguish retries of the same DOI. Identifier filtering alone
does not establish freshness. A done task is not product identity verification.
Exit codes: 0 snapshot/done, 1 unknown/unavailable/failed/interrupted/cancelled,
2 invalid arguments, 3 task mismatch, 4 run changed, 124 watch timeout.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

if __package__:
    from . import progress_reporter as reporter
else:
    import progress_reporter as reporter


MIN_INTERVAL = 0.1
MAX_TIMEOUT = 60.0
_STATUSES = frozenset({"running", "done", "failed", "cancelled", "interrupted"})
_TERMINAL_STAGES = frozenset({"saved_pending_verification", "supplements_checked", "failed", "cancelled", "interrupted"})
_EXIT_CODES = {
    "unknown": 1, "unavailable": 1, "failed": 1, "cancelled": 1,
    "interrupted": 1, "task_mismatch": 3, "run_changed": 4, "timeout": 124,
}


def normalize_identifier(value: object) -> str | None:
    """Only DOI identifiers, never arbitrary current/title/URL text."""
    if not isinstance(value, str) or len(value) > 512:
        return None
    doi = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):].strip()
            break
    return doi if re.fullmatch(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", doi) else None


def _run_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _timestamp(value: object) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", value
    ):
        return None
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return None


def validate_options(*, watch: bool, timeout: float, interval: float,
                     run_id: str | None, identifier: str | None) -> tuple[str | None, str | None]:
    if not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT:
        raise ValueError("timeout must be greater than 0 and at most 60 seconds")
    if not math.isfinite(interval) or not MIN_INTERVAL <= interval <= MAX_TIMEOUT:
        raise ValueError("interval must be between 0.1 and 60 seconds")
    if run_id is not None and _run_id(run_id) is None:
        raise ValueError("run-id must be a UUID")
    if identifier is not None and normalize_identifier(identifier) is None:
        raise ValueError("identifier must be a DOI without query parameters")
    return _run_id(run_id), normalize_identifier(identifier)


def snapshot(*, run_id: str | None = None, identifier: str | None = None) -> dict:
    """Return only validated scalar fields; never serialize the source record."""
    run_id, identifier = validate_options(
        watch=False, timeout=MAX_TIMEOUT, interval=0.5, run_id=run_id, identifier=identifier,
    )
    result = {
        "schema_version": 1, "status": "unknown", "stage": "unknown",
        "run_id": None, "revision": None,
        "scope": "run" if run_id else ("identifier" if identifier else "latest"),
    }
    state, reason = reporter.read_snapshot()
    if state is None:
        result.update(status="idle" if reason in {"missing", "stale"} else "unavailable", reason=reason)
        return result
    if "schema_version" not in state:
        result["reason"] = "legacy_state"
        # Preserve the useful dead-owner signal, but never claim a legacy
        # record belongs to the requested run or infer a stage from phase.
        if run_id or identifier:
            result["status"] = "task_mismatch"
        elif state.get("status") == "interrupted":
            result.update(status="interrupted", stage="interrupted")
        return result
    actual_run = _run_id(state.get("run_id"))
    revision = state.get("revision")
    status = state.get("status")
    timestamps = {field: _timestamp(state.get(field)) for field in ("started_at", "updated_at")}
    if "finished_at" in state:
        timestamps["finished_at"] = _timestamp(state["finished_at"])
    if (type(state.get("schema_version")) is not int or state["schema_version"] != 1
            or actual_run is None or type(revision) is not int or not 1 <= revision <= 2**53 - 1
            or not isinstance(status, str) or status not in _STATUSES
            or any(value is None for value in timestamps.values())):
        result.update(status="unavailable", reason="invalid_state")
        return result
    result.update(run_id=actual_run, revision=revision)
    actual_identifier = normalize_identifier(state.get("current"))
    if ((run_id and actual_run != run_id)
            or (identifier and actual_identifier != identifier)):
        result.update(status="task_mismatch", reason="filter_mismatch")
        return result
    stage = state.get("stage")
    result["stage"] = stage if isinstance(stage, str) and stage in reporter.STAGES else "unknown"
    result["status"] = status
    if status in {"failed", "cancelled", "interrupted"}:
        result["stage"] = status
    result["stale"] = state.get("stale") is True
    result.update(timestamps)
    if actual_identifier:
        result["identifier"] = actual_identifier
    for field in ("total", "done", "success", "failed"):
        value = state.get(field)
        if type(value) is int and 0 <= value <= 2**53 - 1:
            result[field] = value
    return result


def iter_status(*, watch: bool = False, timeout: float = MAX_TIMEOUT,
                interval: float = 0.5, run_id: str | None = None,
                identifier: str | None = None) -> Iterator[dict]:
    """Watch a single run; never silently follow its replacement."""
    run_id, identifier = validate_options(
        watch=watch, timeout=timeout, interval=interval, run_id=run_id, identifier=identifier,
    )
    deadline = time.monotonic() + timeout
    bound_run = None
    previous = None
    while True:
        current = snapshot(run_id=run_id, identifier=identifier)
        actual_run = current["run_id"]
        if bound_run and actual_run and actual_run != bound_run:
            yield {
                "schema_version": 1, "status": "run_changed", "stage": "unknown",
                "run_id": actual_run, "revision": current["revision"],
                "scope": "run", "expected_run_id": bound_run,
            }
            return
        if actual_run and current["status"] not in {"task_mismatch", "unavailable"}:
            bound_run = actual_run
        if current != previous:
            yield current
            previous = current
        if (not watch or current["status"] not in {"idle", "running"}
                or current["stage"] in _TERMINAL_STAGES):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            yield {
                "schema_version": 1, "status": "timeout", "stage": "unknown",
                "run_id": bound_run or run_id, "revision": current["revision"],
                "scope": current["scope"],
            }
            return
        time.sleep(min(interval, remaining))


def emit_status(**options) -> int:
    last = {}
    try:
        for last in iter_status(**options):
            print(json.dumps(last, ensure_ascii=True, allow_nan=False), flush=True)
    except KeyboardInterrupt:
        # The watcher stopped; do not mark the download itself interrupted.
        print(json.dumps({"schema_version": 1, "status": "watch_cancelled"}), flush=True)
        return 130
    if last.get("stage") in {"failed", "cancelled", "interrupted"}:
        return 1
    return _EXIT_CODES.get(last.get("status"), 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", required=True, dest="json_output")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--timeout", type=float, default=MAX_TIMEOUT)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--run-id")
    parser.add_argument("--identifier")
    args = vars(parser.parse_args(argv))
    args.pop("json_output")
    try:
        return emit_status(**args)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())

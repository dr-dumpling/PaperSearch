"""Task progress reporting via a well-known JSON file.

Writers (server / batch) report per-paper progress here; readers (the
floating progress window, ``paper-search-carsi progress``) watch the file. The two
are decoupled on purpose: a headless background task stays GUI-free while the
floating bar makes its progress visible on the desktop.

File: <data_dir>/progress/current.json — atomically replaced (tmp + rename)
on every update, so readers never see a torn write.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {}
_STARTED_MONO: float = 0.0
_STAGE_LISTENER: ContextVar[tuple[str, Callable[[str], None]] | None] = ContextVar(
    "carsi_request_stage_listener", default=None)

STAGES = frozenset({
    "starting", "opening_article", "waiting_login", "waiting_verification",
    "checking_access", "fetching_pdf", "pdf_captured",
    "saved_pending_verification", "route_failed", "failed", "cancelled", "interrupted", "unknown",
})
_IDENTITY_FIELDS = frozenset({"schema_version", "run_id", "revision", "owner_pid"})

STALE_SECONDS = 120  # legacy reports expire; a living owner's stalled task stays visible
# Between two items of a serial batch no backend process owns the task; the
# caller is running its own (open-access) stages. Give up after this long.
BATCH_WAIT_STALE_SECONDS = 1800


def _progress_dir() -> Path:
    data_dir = Path(os.environ.get("CARSI_DATA_DIR", str(Path.home() / ".local" / "share" / "paper-search-cli" / "carsi")))
    return data_dir / "progress"


def progress_path() -> Path:
    return _progress_dir() / "current.json"


def _atomic_write(payload: dict[str, Any]) -> None:
    path = progress_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _pid_alive(pid: int) -> bool:
    """Windows-safe liveness probe. NEVER use os.kill(pid, 0) on Windows —
    any signal value there calls TerminateProcess and would murder the bar."""
    if pid <= 0:
        return False
    try:
        if os.name != "nt":
            os.kill(pid, 0)
            return True
        import ctypes

        SYNCHRONIZE = 0x00100000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            return False
        kernel32.CloseHandle(int(handle))
        return True
    except Exception:
        return False


def ensure_progress_bar(config: dict[str, Any] | None = None) -> None:
    """Spawn the floating progress window once (no-op when one is already up).

    Called whenever a download task starts so the user sees progress without
    launching anything by hand; PaperSearch additionally prints the same
    stages to stderr. The window is an independent process guarded by
    ``progress/bar.pid``; a stale lock (dead window) is reclaimed.

    Disabled by config ``progress_bar_auto: false``, env
    ``CARSI_PROGRESS_BAR=0``, and always under pytest so test runs never
    open windows.
    """
    if os.environ.get("CARSI_PROGRESS_BAR") == "0":
        return
    if os.environ.get("CARSI_PROGRESS_BAR_CHILD") == "1":
        return
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    if config is not None and config.get("progress_bar_auto") is False:
        return
    lock = _progress_dir() / "bar.pid"
    try:
        if lock.exists():
            pid = int(lock.read_text(encoding="utf-8").strip() or 0)
            if _pid_alive(pid):
                return  # a window is already up
            # else: stale lock (window died) - reclaim below
    except (ValueError, OSError):
        return
    try:
        import subprocess
        import sys

        kwargs = {"creationflags": 0x08000000} if os.name == "nt" else {}
        env = {**os.environ, "CARSI_PROGRESS_BAR_CHILD": "1"}
        subprocess.Popen(
            [sys.executable, "-m", "paper_search_carsi.progress_bar"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            env=env, start_new_session=(os.name != "nt"), **kwargs,
        )
    except Exception:
        pass


@dataclass(frozen=True)
class BatchContext:
    """Position of one download inside a caller's serial batch.

    The counts are the caller's totals *before* this item, so items the caller
    finished without the backend (open access, Sci-Hub) are still counted.
    """

    batch_id: str
    index: int
    total: int
    done: int | None = None
    succeeded: int | None = None
    failed: int | None = None

    @classmethod
    def from_args(cls, batch_id: Any, index: Any, total: Any, done: Any = None,
                  succeeded: Any = None, failed: Any = None) -> "BatchContext | None":
        """Validated context, or None (then the download is reported on its own)."""
        def count(value: Any) -> int | None:
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

        if not isinstance(batch_id, str) or not batch_id.strip() or len(batch_id) > 128:
            return None
        if count(index) is None or count(total) is None or not 1 <= index <= total <= 100_000:
            return None
        counts = [count(v) for v in (done, succeeded, failed)]
        return cls(batch_id.strip(), index, total, *counts)


def _batch_state(batch_id: str) -> dict[str, Any] | None:
    """The running report of this batch, if the previous item left one."""
    try:
        state = json.loads(progress_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(state, dict) and state.get("batch_id") == batch_id and state.get("status") == "running":
        return state
    return None


def _adopt_batch(batch_id: str, total: int, counts: tuple[int | None, int | None, int | None],
                 **fields: Any) -> None:
    """Continue this batch's report in the current process, or start it."""
    global _STATE, _STARTED_MONO
    try:
        from .config import load_config

        ensure_progress_bar(load_config())
    except Exception:
        try:
            ensure_progress_bar()
        except Exception:
            pass
    previous = _batch_state(batch_id)
    with _LOCK:
        _STARTED_MONO = time.monotonic()
        if previous is None:
            previous = {
                "task": "机构 PDF 批量下载",
                "done": 0, "success": 0, "failed": 0,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "schema_version": 1,
                "run_id": str(uuid.uuid4()),
                "revision": 0,
            }
        done, succeeded, failed = counts
        _STATE = {
            **previous,
            "batch_id": batch_id,
            "total": int(total),
            "status": "running",
            "awaiting_next": False,
            "attention": {},
            "owner_pid": os.getpid(),
            **({"done": done} if done is not None else {}),
            **({"success": succeeded} if succeeded is not None else {}),
            **({"failed": failed} if failed is not None else {}),
            **fields,
        }
        _STATE.pop("finished_at", None)
        _write_state()


def sync_batch(batch_id: str, total: int, done: int, succeeded: int, failed: int, *,
               current: str = "", finished: bool = False) -> bool:
    """Record batch totals for items finished without the backend, or the batch end."""
    ctx = BatchContext.from_args(batch_id, max(1, min(done, total)), total, done, succeeded, failed)
    if ctx is None or done > total:
        return False
    previous = _batch_state(ctx.batch_id)
    if finished and previous is None and done == 0:
        return False
    _adopt_batch(ctx.batch_id, total, (done, succeeded, failed),
                 **({"current": current} if current else {}),
                 stage="saved_pending_verification" if finished else "starting",
                 phase=(f"批量下载结束：成功 {succeeded}，失败 {failed}" if finished
                        else f"已完成 {done}/{total} 篇，等待下一篇"))
    with _LOCK:
        if finished:
            _STATE.update(status="done", awaiting_next=False,
                          finished_at=datetime.now().isoformat(timespec="seconds"))
        else:
            _STATE.update(awaiting_next=True)
        _write_state()
    return True


@contextmanager
def tracked_download(current: str, output_dir: Any = None, batch: BatchContext | None = None,
                     content: str = "main"):
    """One institutional download as a reported task (progress window + live preview).

    Every single-paper entry point (MCP tool, ``publisher-check``) runs inside
    this, so the floating window and the browser preview start the same way.
    The caller stores the result dict under ``outcome["result"]`` and may set
    ``outcome["failure_phase"]``. Inside a serial batch the item continues the
    batch's report (``k / N``) and the window stays open between items.
    ``content`` (main / supplements / both) is shown as a small label.
    ``outcome["paused"]`` (a phase text) means the article has not run yet and
    the batch tries it again later (publisher's hourly limit): nothing is
    counted and the window stays open.
    """
    if batch is None:
        start_task("机构 PDF 下载", total=1, current=current, phase="进入机构访问")
    else:
        done = batch.done if batch.done is not None else (None if _batch_state(batch.batch_id) else batch.index - 1)
        _adopt_batch(batch.batch_id, batch.total, (done, batch.succeeded, batch.failed),
                     current=current, stage="starting",
                     phase=f"第 {batch.index}/{batch.total} 篇：进入机构访问")
        _notify_stage("starting", current)
    update(content=content if content in ("main", "supplements", "both") else "main")
    if output_dir:
        set_output_dir(output_dir)
    outcome: dict[str, Any] = {}
    try:
        yield outcome
    finally:
        if outcome.get("paused") and batch is not None:
            with _LOCK:
                if _STATE:
                    _STATE.update(awaiting_next=True, phase=str(outcome["paused"]))
                    _write_state()
        else:
            _finish_download(outcome, current, batch)


def _finish_download(outcome: dict[str, Any], current: str, batch: BatchContext | None) -> None:
    """Count the download and show how it ended (end of ``tracked_download``)."""
    succeeded = (outcome.get("result") or {}).get("success") is True
    phase = "PDF 已保存，待内容核验" if succeeded else outcome.get("failure_phase", "下载未完成")
    report_stage("saved_pending_verification" if succeeded else "failed", current=current)
    advance(succeeded, current=current, phase=phase)
    if batch is not None and batch.index < batch.total:
        with _LOCK:
            if _STATE:
                _STATE.update(awaiting_next=True,
                              phase=f"第 {batch.index}/{batch.total} 篇{'已保存' if succeeded else '未完成'}，等待下一篇")
                _write_state()
    else:
        finish()


def _write_state() -> None:
    """Called under _LOCK; revisions count successful atomic replacements only."""
    payload = {
        **_STATE,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "revision": _STATE.get("revision", 0) + 1,
    }
    try:
        _atomic_write(payload)
    except Exception:
        # Progress is best-effort; never fail the download because of its UI.
        return
    _STATE.update(payload)


@contextmanager
def listen_for_stages(identifier: str, listener: Callable[[str], None]):
    """Bind live events to this operation, without consulting shared GUI state.

    asyncio.to_thread copies this context. Unbound source-pool threads are
    deliberately excluded; their caller must explicitly propagate the context.
    """
    from .identifiers import normalize_doi

    token = _STAGE_LISTENER.set((normalize_doi(identifier).lower(), listener))
    try:
        yield
    finally:
        _STAGE_LISTENER.reset(token)


def _notify_stage(stage: str, current: str = "") -> None:
    bound = _STAGE_LISTENER.get()
    if bound is None:
        return
    from .identifiers import normalize_doi

    identifier, listener = bound
    if current and normalize_doi(current).lower() != identifier:
        return
    # Optional observers cannot turn a download into a failure. Never log
    # observer exceptions, which may carry transport or authentication data.
    try:
        listener(stage)
    except Exception:
        pass


def report_stage(stage: str, *, current: str = "") -> None:
    """Report an explicit machine stage, independently of GUI prose.

    saved_pending_verification means bytes were saved, not that the product
    verified the article's identity. route_failed leaves the task running for
    other routes. No stage is inferred from phase text.
    """
    if not isinstance(stage, str) or stage not in STAGES:
        raise ValueError("invalid progress stage")
    # Stage-only callers (e.g. a wait on the user's login) must retain the DOI
    # already bound by start_task; otherwise filtered monitors lose the run.
    update(stage=stage, **({"current": current} if current else {}))
    _notify_stage(stage, current)


def start_task(task: str, total: int, **extra: Any) -> None:
    """Begin (or restart) the reported task with a known total."""
    global _STATE, _STARTED_MONO
    try:
        from .config import load_config

        ensure_progress_bar(load_config())
    except Exception:
        try:
            ensure_progress_bar()
        except Exception:
            pass
    with _LOCK:
        _STARTED_MONO = time.monotonic()
        _STATE = {
            "task": task,
            "total": int(total),
            "done": 0,
            "success": 0,
            "failed": 0,
            "current": "",
            "phase": "",
            "status": "running",
            "attention": {},
            "started_at": datetime.now().isoformat(timespec="seconds"),
            **extra,
            "schema_version": 1,
            "run_id": str(uuid.uuid4()),
            "revision": 0,
            "owner_pid": os.getpid(),
            "stage": "starting",
        }
        _write_state()

    _notify_stage("starting", str(extra.get("current", "")))


def update(**kw: Any) -> None:
    """Merge fields into the current report (done/success/failed/current/...)."""
    if _IDENTITY_FIELDS.intersection(kw):
        raise ValueError("progress identity fields are managed by start_task")
    if "stage" in kw and (not isinstance(kw["stage"], str) or kw["stage"] not in STAGES):
        raise ValueError("invalid progress stage")
    with _LOCK:
        if not _STATE:
            return
        _STATE.update(kw)
        _write_state()


def advance(ok: bool, current: str = "", phase: str = "") -> None:
    """Record one finished item (the hot path for per-paper lanes)."""
    with _LOCK:
        if not _STATE:
            return
        _STATE["done"] = int(_STATE.get("done", 0)) + 1
        _STATE["success"] = int(_STATE.get("success", 0)) + (1 if ok else 0)
        _STATE["failed"] = int(_STATE.get("failed", 0)) + (0 if ok else 1)
        if current:
            _STATE["current"] = current
        if phase:
            _STATE["phase"] = phase
        _write_state()


def set_attention(key: str, message: str, *, current: str = "", phase: str = "") -> None:
    """Show a manual-action reminder without stopping other workers."""
    with _LOCK:
        if not _STATE:
            return
        attention = _STATE.setdefault("attention", {})
        if not isinstance(attention, dict):
            attention = {}
            _STATE["attention"] = attention
        attention[str(key)] = {
            "message": str(message),
            "current": str(current or ""),
            "phase": str(phase or ""),
            "since": datetime.now().isoformat(timespec="seconds"),
        }
        _write_state()


def set_output_dir(path) -> None:
    """Record the output folder for task diagnostics; omit it from the widget."""
    with _LOCK:
        if not _STATE:
            return
        _STATE["output_dir"] = str(path)
        _write_state()


def clear_attention(key: str) -> None:
    """Remove one manual-action reminder after its browser page clears."""
    with _LOCK:
        if not _STATE:
            return
        attention = _STATE.get("attention")
        if not isinstance(attention, dict):
            return
        attention.pop(str(key), None)
        _write_state()


def finish() -> None:
    """Mark the task done (the bar keeps the final state briefly, then idles)."""
    with _LOCK:
        if not _STATE:
            return
        _STATE["status"] = "done"
        _STATE["awaiting_next"] = False
        _STATE["attention"] = {}
        _STATE["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _write_state()


def elapsed_sec() -> float:
    return max(0.0, time.monotonic() - _STARTED_MONO)


def read_snapshot() -> tuple[dict[str, Any] | None, str]:
    """Read once without writes/config/GUI; reason codes contain no raw errors."""
    try:
        raw = progress_path().read_text(encoding="utf-8")
        state = json.loads(raw)
    except FileNotFoundError:
        return None, "missing"
    except (ValueError, RecursionError):
        # Includes malformed UTF-8/JSON and Python's oversized-int guard.
        return None, "invalid_json"
    except OSError:
        return None, "unreadable"
    if not isinstance(state, dict):
        return None, "invalid_state"
    if state.get("status") == "running" and state.get("awaiting_next") is True:
        # Between batch items no process owns the task; only time ends the wait.
        try:
            ts = datetime.fromisoformat(str(state.get("updated_at")))
            waited = (datetime.now(ts.tzinfo) - ts).total_seconds()
        except Exception:
            waited = 0.0
        if waited > BATCH_WAIT_STALE_SECONDS:
            return {**state, "status": "interrupted", "stage": "interrupted", "awaiting_next": False,
                    "phase": "批量下载已停止，结果未确认", "attention": {}}, "available"
        return state, "available"
    if state.get("status") == "running" and isinstance(state.get("owner_pid"), int) and not _pid_alive(state["owner_pid"]):
        # The MCP process can be terminated before its finally block runs.
        # Do not claim success, failure, or cancellation without a result.
        return {**state, "status": "interrupted", "stage": "interrupted", "phase": "下载进程已结束，结果未确认", "attention": {}}, "available"
    if state.get("status") in ("done", "cancelled", "interrupted"):
        return state, "available"  # finished states stay visible (reader decides)
    try:
        ts = datetime.fromisoformat(str(state.get("updated_at")))
        age = (datetime.now(ts.tzinfo) - ts).total_seconds()
        if age > STALE_SECONDS:
            if state.get("status") == "running" and isinstance(state.get("owner_pid"), int):
                # The owner was checked above. A long blocking browser call
                # must not make an active download disappear from the bar.
                return {**state, "phase": "等待下载进程响应（暂无新进度）", "stale": True}, "available"
            return None, "stale"
    except Exception:
        pass
    return state, "available"


def read_state() -> dict[str, Any] | None:
    """GUI compatibility: latest report, or None when absent/invalid/stale."""
    return read_snapshot()[0]

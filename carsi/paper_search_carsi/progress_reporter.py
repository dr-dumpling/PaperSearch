"""Task progress reporting via a well-known JSON file.

Writers (server / batch) report per-paper progress here; readers (the
floating progress window, ``paper-search-carsi progress``) watch the file. The two
are decoupled on purpose: a headless background task stays GUI-free while the
floating bar makes its progress visible on the desktop.

File: <data_dir>/progress/current.json — atomically replaced (tmp + rename)
on every update, so readers never see a torn write.
"""

from __future__ import annotations

import html
import json
import os
import re
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
    "saved_pending_verification", "supplements_checked", "route_failed", "failed", "cancelled", "interrupted", "unknown",
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


def _atomic_write(payload: dict[str, Any], path: Path | None = None) -> None:
    path = path or progress_path()
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


def _pid_alive(pid: int, *, created_before: float | None = None) -> bool:
    """Windows-safe liveness probe. NEVER use os.kill(pid, 0) on Windows —
    any signal value there calls TerminateProcess and would murder the bar."""
    if pid <= 0:
        return False
    try:
        if os.name != "nt":
            os.kill(pid, 0)
            return True
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        access = 0x00100000 | (0x1000 if created_before is not None else 0)
        handle = kernel32.OpenProcess(access, False, int(pid))
        if not handle:
            return False
        try:
            # A terminated process can remain openable while another process
            # retains a handle. Only WAIT_TIMEOUT means it is still running.
            if kernel32.WaitForSingleObject(handle, 0) != 258:
                return False
            if created_before is not None:
                kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
                kernel32.GetProcessTimes.restype = wintypes.BOOL
                times = [wintypes.FILETIME() for _ in range(4)]
                if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                    return False
                created = ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) / 10_000_000 - 11644473600
                if created > created_before:
                    return False  # the old window's PID was reused
            return True
        finally:
            kernel32.CloseHandle(handle)
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
    if _window_up() is False:
        _spawn_window()


def _window_up() -> bool | None:
    """Whether a progress window is open; None when its lock cannot be read.
    A stale lock (the window died) counts as none: the next window takes it over."""
    lock = _progress_dir() / "bar.pid"
    try:
        if lock.exists():
            pid = int(lock.read_text(encoding="utf-8").strip() or 0)
            if _pid_alive(pid, created_before=lock.stat().st_mtime + 1):
                return True
        return False
    except (ValueError, OSError):
        return None


def _spawn_window() -> bool:
    try:
        import subprocess
        import sys

        kwargs = {"creationflags": 0x08000000} if os.name == "nt" else {}
        env = {**os.environ, "CARSI_PROGRESS_BAR_CHILD": "1"}
        command = [sys.executable, "-m", "paper_search_carsi.progress_capsule"]
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            env=env, start_new_session=(os.name != "nt"), **kwargs,
        )
        return True
    except Exception:
        return False


SETTINGS_REQUEST_SECONDS = 60  # a request no window has picked up by then is dropped


def _settings_request_path() -> Path:
    return _progress_dir() / "open-settings.json"


def open_settings(page: str = "home", service: str = "") -> str:
    """Show the progress window's settings (``paper-search-carsi settings``).

    An open window switches to them ("existing"). Otherwise a window starts on
    them ("opened"); it closes when they are closed with no download running,
    and a download that starts meanwhile shows in it. RuntimeError when no
    window could start."""
    up = _window_up()
    request = {"page": page, "service": service, "new_window": up is not True, "at": time.time()}
    path = _settings_request_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(request, fh)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    if up is True:
        return "existing"
    if not _spawn_window():
        path.unlink(missing_ok=True)
        raise RuntimeError("进度窗口没能启动")
    return "opened"


def take_settings_request() -> dict[str, Any] | None:
    """The pending request to show the settings, once; None when there is none
    or it is too old (the window it was meant for never came up)."""
    path = _settings_request_path()
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()
        fresh = time.time() - float(request["at"]) <= SETTINGS_REQUEST_SECONDS
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if not fresh:
        return None
    return {"page": str(request.get("page") or "home"), "service": str(request.get("service") or ""),
            "new_window": request.get("new_window") is True}


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
    """This batch's report, if an earlier item or stretch left one.

    A finished stretch counts too: the institutional stretch of a batch ends
    before its supplementary files and the caller's final summary, and the
    batch keeps its start time (and run) across them."""
    try:
        state = json.loads(progress_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(state, dict) and state.get("batch_id") == batch_id and state.get("status") in ("running", "done"):
        return state
    return None


def _adopt_batch(batch_id: str, total: int, counts: tuple[int | None, int | None, int | None],
                 *, beside_download: bool = False, **fields: Any) -> bool | None:
    """Continue this batch's report in the current process, or start it (True).

    ``beside_download``: an update from the caller's other lane. While a download
    of this batch runs here, only the totals and ``lanes`` change (False); while
    one runs in another process, nothing is written (None). Decided under the
    lock a starting download takes too, so neither overwrites the other."""
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
        if beside_download:
            if (_STATE.get("batch_id") == batch_id and _STATE.get("status") == "running"
                    and not _STATE.get("awaiting_next")):
                done, succeeded, failed = counts
                _STATE.update(total=int(total), lanes=fields.get("lanes", ""),
                              **({"done": done} if done is not None else {}),
                              **({"success": succeeded} if succeeded is not None else {}),
                              **({"failed": failed} if failed is not None else {}))
                _write_state()
                return False
            owner = previous.get("owner_pid") if previous else None
            if (previous is not None and previous.get("status") == "running" and not previous.get("awaiting_next")
                    and isinstance(owner, int) and owner != os.getpid() and _pid_alive(owner)):
                return None
        _STARTED_MONO = time.monotonic()
        if previous is None:
            previous = {
                # A lone download comes as a batch of one (its finished card gets the reason).
                "task": "机构 PDF 批量下载" if total > 1 else "机构 PDF 下载",
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
        _STATE.pop("results", None)
        _write_state()
    return True


def sync_batch(batch_id: str, total: int, done: int, succeeded: int, failed: int, *,
               current: str = "", finished: bool = False, results: Any = None,
               phase: str = "", channel: str = "", lanes: str = "") -> bool:
    """Record batch totals for items finished without the backend, or the batch end.

    ``results`` (the batch end only) is the caller's summary of every item,
    for the finished window: see ``_batch_results``. It updates an existing
    report and never opens a window for a batch the backend did not show.
    ``phase`` replaces the waiting line and ``channel`` names where the caller
    fetches from (its open-access stretch, before any publisher); both are
    short single lines and are dropped at the batch end. ``lanes`` is one line on
    what each lane got in a batch whose open-access checks run beside its downloads;
    it may come while a download of the batch runs, which then keeps its paper,
    stage and prompts (``_adopt_batch``)."""
    ctx = BatchContext.from_args(batch_id, max(1, min(done, total)), total, done, succeeded, failed)
    if ctx is None or done > total:
        return False
    summary = _batch_results(results) if finished and results is not None else None
    previous = _batch_state(ctx.batch_id)
    if finished and previous is None and (done == 0 or summary is not None):
        return False
    phase, channel, lanes = _short_line(phase), _short_line(channel), _short_line(lanes)
    adopted = _adopt_batch(ctx.batch_id, total, (done, succeeded, failed),
                           beside_download=bool(lanes) and not finished,
                           **({"current": current} if current else {}),
                           **({"lanes": lanes} if lanes or finished else {}),
                           stage="saved_pending_verification" if finished else "starting",
                           channel="" if finished else channel,
                           phase=(f"批量下载结束：成功 {succeeded}，失败 {failed}" if finished
                                  else phase or f"已完成 {done}/{total} 篇，等待下一篇"))
    if not adopted:
        return adopted is False  # beside a download: written here, or left to its process
    with _LOCK:
        if finished:
            _STATE.update(status="done", awaiting_next=False,
                          finished_at=datetime.now().isoformat(timespec="seconds"))
            if summary is not None:
                started = summary.pop("started", None)
                if started is not None and started < str(_STATE.get("started_at") or "~"):
                    _STATE["started_at"] = started  # the caller's open stages ran before the window
                if summary.pop("stopped", False):
                    _STATE["status"] = "cancelled"
                folder = summary.pop("folder", None)
                if folder:
                    _STATE["output_dir"] = folder  # the whole batch, not the last paper's folder
                _STATE["results"] = summary
        else:
            _STATE.update(awaiting_next=True)
        _write_state()
    return True


def _short_line(value: Any, limit: int = 80) -> str:
    """A caller's display text as one short line (empty when it is not text)."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


FAILURE_CLASSES = ("no_access", "user_or_external", "unsupported", "unexplained")
_RESULT_CONTENTS = ("main", "supplements", "both")
_MAX_RESULT_FAILURES = 1000  # the caller's batch limit
_MAX_RESULT_TEXT = 300


def _display_text(value: Any) -> str:
    """A caller's text for the window: plain, one line, bounded.

    Crossref's titles and journals can keep HTML entities ("Arthritis &amp; Rheumatology")
    and markup ("<i>Glossostemon bruguieri</i>"); the card shows plain text."""
    if not isinstance(value, str):
        return ""
    return " ".join(re.sub(r"<[^<>]{1,40}>", "", html.unescape(value)).split())[:_MAX_RESULT_TEXT]


def _batch_results(raw: Any) -> dict[str, Any] | None:
    """The caller's end-of-batch summary, checked and bounded for the window.

    Wire shape (PaperSearch writes it, the window only lays it out):
    ``content``; ``folder`` (the batch's download folder, absolute);
    ``started`` (epoch seconds the batch began); ``stopped``;
    ``main`` (main texts saved), ``supplements`` (attachment files saved),
    ``no_supplements`` (pages that listed none); ``sources`` ([label, count]);
    ``source_details`` ([label, text]: a label's sources, shown in brackets after its count);
    ``failures`` ([{cls, reason, title, journal, doi, note}]) with ``cls`` one
    of FAILURE_CLASSES and a short ``reason`` text; ``supplement_failures``, the
    same for papers whose main text was saved but not every supplementary file
    (content "both"). Anything else is dropped.
    """
    if not isinstance(raw, dict):
        return None

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1_000_000 else 0

    text = _display_text
    summary: dict[str, Any] = {
        "content": raw.get("content") if raw.get("content") in _RESULT_CONTENTS else "main",
        "main": count(raw.get("main")),
        "supplements": count(raw.get("supplements")),
        "no_supplements": count(raw.get("no_supplements")),
        "sources": [[text(s[0]), count(s[1])] for s in (raw.get("sources") or [])[:8]
                    if isinstance(s, list) and len(s) == 2 and text(s[0]) and count(s[1])]
        if isinstance(raw.get("sources"), list) else [],
        "source_details": {text(s[0]): text(s[1]) for s in (raw.get("source_details") or [])[:8]
                           if isinstance(s, list) and len(s) == 2 and text(s[0]) and text(s[1])}
        if isinstance(raw.get("source_details"), list) else {},
        "failures": [],
        "supplement_failures": [],
        "stopped": raw.get("stopped") is True,
    }
    for key in ("failures", "supplement_failures"):
        listed = raw.get(key)
        for item in (listed if isinstance(listed, list) else [])[:_MAX_RESULT_FAILURES]:
            if not isinstance(item, dict) or not text(item.get("reason")):
                continue
            summary[key].append({
                "cls": item.get("cls") if item.get("cls") in FAILURE_CLASSES else "unexplained",
                **{field: text(item.get(field)) for field in ("reason", "title", "journal", "doi", "note")},
            })
    folder = raw.get("folder")
    if isinstance(folder, str) and 0 < len(folder) <= 4096 and os.path.isabs(folder):
        summary["folder"] = folder
    started = raw.get("started")
    if isinstance(started, (int, float)) and not isinstance(started, bool) and 0 < time.time() - started < 31 * 86400:
        summary["started"] = datetime.fromtimestamp(started).isoformat(timespec="seconds")
    return summary


# A paper's states in the order it moves through them: open access not checked
# yet, waiting for (or in) the institutional download, then its result.
PAPER_STATES = {"open": 0, "school": 1, "ok": 2, "failed": 2}
_PAPERS_LOCK = threading.Lock()


def papers_path() -> Path:
    return _progress_dir() / "papers.json"


def _paper(raw: Any) -> dict[str, Any] | None:
    """One paper as the caller sent it, checked and bounded (see ``sync_papers``)."""
    if not isinstance(raw, dict) or raw.get("state") not in PAPER_STATES:
        return None
    index = raw.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= _MAX_RESULT_FAILURES:
        return None
    paper = {"index": index, "state": raw["state"],
             **{field: _display_text(raw.get(field)) for field in ("doi", "title", "journal")}}
    if paper["state"] == "ok":
        paper.update(via=_display_text(raw.get("via")), detail=_display_text(raw.get("detail")))
        path = raw.get("path")
        if isinstance(path, str) and 0 < len(path) <= 4096 and os.path.isabs(path):
            paper["path"] = path
    elif paper["state"] == "failed":
        paper.update(cls=raw.get("cls") if raw.get("cls") in FAILURE_CLASSES else "unexplained",
                     reason=_display_text(raw.get("reason")))
    return paper


def sync_papers(batch_id: str, folder: str, papers: Any) -> bool:
    """Each paper of a batch, for the lists behind the window's 成功, 失败 and 剩余.

    The caller sends every paper once, then the ones that changed; they are merged
    into ``papers.json`` by ``index`` (1..N), and a paper's state only moves forward
    (``PAPER_STATES``). Another batch starts a new list. Wire shape of a paper:
    ``index``, ``doi``, ``title``, ``journal``, ``state``; a saved one adds ``via``
    (开放下载 or 机构下载), ``detail`` (the open source when not open access: 出版社 API,
    Sci-Hub, 预印本) and ``path`` (the PDF, absolute); a failed one ``cls`` (one of
    FAILURE_CLASSES) and ``reason``. ``folder`` is the batch's download folder: the
    window opens a PDF only from inside it. Kept apart from the progress file, which
    the downloading process rewrites every moment."""
    if not isinstance(batch_id, str) or not 0 < len(batch_id) <= 128 or not isinstance(papers, list):
        return False
    with _PAPERS_LOCK:
        try:
            listed = json.loads(papers_path().read_text(encoding="utf-8"))
        except Exception:
            listed = None
        if not isinstance(listed, dict) or listed.get("batch_id") != batch_id or not isinstance(listed.get("papers"), dict):
            listed = {"batch_id": batch_id, "folder": "", "papers": {}}
        if isinstance(folder, str) and 0 < len(folder) <= 4096 and os.path.isabs(folder):
            listed["folder"] = folder
        known = listed["papers"]
        for raw in papers[:_MAX_RESULT_FAILURES]:
            paper = _paper(raw)
            if paper is None:
                continue
            before = known.get(str(paper["index"]))
            if before and PAPER_STATES.get(before.get("state"), 0) > PAPER_STATES[paper["state"]]:
                continue  # a late report never takes a paper back
            known[str(paper["index"])] = paper
        try:
            _atomic_write(listed, papers_path())
        except Exception:
            return False  # the lists are optional; the download goes on
    return True


def read_papers() -> dict[str, Any] | None:
    try:
        listed = json.loads(papers_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    return listed if isinstance(listed, dict) and isinstance(listed.get("papers"), dict) else None


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
                     current=current, stage="starting", channel="",
                     phase=f"第 {batch.index}/{batch.total} 篇：进入机构访问" if batch.total > 1 else "进入机构访问")
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
            _finish_download(outcome, current, batch, content)


def _finish_download(outcome: dict[str, Any], current: str, batch: BatchContext | None,
                     content: str = "main") -> None:
    """Count the download and show how it ended (end of ``tracked_download``)."""
    succeeded = (outcome.get("result") or {}).get("success") is True
    phase = "PDF 已保存，待内容核验" if succeeded else outcome.get("failure_phase", "下载未完成")
    stage = "saved_pending_verification" if succeeded else "failed"
    files = (outcome.get("result") or {}).get("supplements")
    checked = (content == "supplements" and isinstance(files, list)
               and (files or succeeded or (outcome.get("result") or {}).get("error_type") == "supplements_only")
               and all(isinstance(f, dict) and f.get("status") == "saved" for f in files))
    if checked:
        succeeded = True  # A completed empty check is not a failed download.
        stage = "supplements_checked"
        phase = f"补充材料已保存 {len(files)} 个" if files else "已检查，页面未列出补充材料"
    report_stage(stage, current=current)
    # A saved PDF is the caller's to count once it has checked the article's
    # identity; its totals come with the next item. Counted here, an article
    # left for review showed as a success, then a failure (RSC, Windows 2026-11-08).
    pending = (stage == "saved_pending_verification" and batch is not None
               and batch.succeeded is not None and batch.index < batch.total)
    advance(succeeded, current=current, phase=phase, pending=pending)
    if batch is not None and batch.index < batch.total:
        with _LOCK:
            if _STATE:
                _STATE.update(awaiting_next=True,
                              phase=f"第 {batch.index}/{batch.total} 篇{'已检查' if checked else '已保存' if succeeded else '未完成'}，等待下一篇")
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


def advance(ok: bool, current: str = "", phase: str = "", *, pending: bool = False) -> None:
    """Record one finished item (the hot path for per-paper lanes); ``pending``:
    finished, but whether it succeeded is the caller's to count."""
    with _LOCK:
        if not _STATE:
            return
        _STATE["done"] = int(_STATE.get("done", 0)) + 1
        if not pending:
            _STATE["success"] = int(_STATE.get("success", 0)) + (1 if ok else 0)
            _STATE["failed"] = int(_STATE.get("failed", 0)) + (0 if ok else 1)
        if current:
            _STATE["current"] = current
        if phase:
            _STATE["phase"] = phase
        _write_state()


def has_attention(*, current: str = "", excluding: str = "") -> bool:
    """Whether another reminder already asks this paper's user to act."""
    with _LOCK:
        return any(key != excluding and (not current or value.get("current") == current)
                   for key, value in _STATE.get("attention", {}).items())


def set_attention(key: str, message: str, *, current: str = "", phase: str = "",
                  deadline: float | None = None) -> None:
    """Show a manual-action reminder without stopping other workers; ``deadline``
    (epoch seconds) is when the wait ends, for the window's countdown."""
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
        if deadline is not None:
            attention[str(key)]["deadline"] = float(deadline)
        _write_state()


def update_attention_deadline(key: str, deadline: float | None) -> None:
    """Change only the countdown, keeping the reminder/notification identity."""
    with _LOCK:
        attention = _STATE.get("attention", {}).get(str(key))
        if attention is None or attention.get("deadline") == deadline:
            return
        if deadline is None:
            attention.pop("deadline", None)
        else:
            attention["deadline"] = float(deadline)
        _write_state()


def set_output_dir(path) -> None:
    """Record the actual task folder for diagnostics and the window folder button."""
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

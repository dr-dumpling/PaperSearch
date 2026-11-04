"""End an item whose browser call never returns.

On Camoufox a Playwright call can wait forever for an answer (2026-10-31,
after a Cloudflare check had passed): the backend sits at CPU 0 and the batch
waits for its 20-minute item timeout. Every sync Playwright call is timed
here; one still running after ``LIMIT_SEC`` is logged with its caller and
cancelled, and it and every later browser call of this process raise
:class:`BrowserUnresponsive`. The item ends as ``browser_unresponsive``; the
backend process then exits, which closes the browser it launched.

Stopping the Playwright driver instead does not work: the pending sync call
never learns about it and spins at full CPU.

The same wrapper carries the progress window's buttons into the browser
thread: :func:`interrupt` ends the item at once (the running call is cancelled
and every later call raises the given exception until :func:`clear_interrupt`),
and :func:`run_soon` runs work, such as handling a problem report, on the
browser thread before its next call.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

# The longest legitimate call is a page load (60 s, the engine's longest
# timeout); waits for the user are made of short calls.
LIMIT_SEC = 90

_inflight: dict[int, tuple[float, str, list[str], Any, Any]] = {}
_call_deadlines: dict[int, tuple[float, str]] = {}
_local = threading.local()
_installed = False
# A browser call longer than this is reported to ``on_slow_call(name, seconds,
# ended, caller)``, set by the downloader for the article it runs: a Playwright
# default timeout of 30 s otherwise passes without a trace (Sage, 2026-11-02).
SLOW_CALL_SEC = 10
on_slow_call: Any = None
# The browser calls since the article's previous step (``take_period``): a long
# silence then says whether it was spent in the browser, and on what.
_period: dict[str, Any] = {"calls": 0, "seconds": 0.0, "slowest": "", "slowest_sec": 0.0}


def take_period() -> dict[str, Any]:
    """The browser calls since the last time asked (count, seconds, the slowest), and start again."""
    global _period
    taken, _period = _period, {"calls": 0, "seconds": 0.0, "slowest": "", "slowest_sec": 0.0}
    return taken
fired: dict[str, Any] | None = None
interrupted: BaseException | None = None
_soon: list[Any] = []
_running_soon = False


class BrowserUnresponsive(Exception):
    """A browser call did not return within the watchdog limit."""


class BrowserOperationTimeout(BrowserUnresponsive):
    """The whole page operation exhausted its budget across browser calls."""


@contextmanager
def operation(seconds: float, label: str):
    """One monotonic deadline shared by all calls and retries in this scope."""
    stack = getattr(_local, "budgets", None)
    if stack is None:
        stack = _local.budgets = []
    stack.append([time.monotonic() + seconds, label])
    try:
        yield
    finally:
        stack.pop()


def operation_remaining() -> float | None:
    """Remaining automation time, so a human handoff can happen before expiry."""
    budgets = getattr(_local, "budgets", [])
    return max(0.0, min(b[0] for b in budgets) - time.monotonic()) if budgets else None


@contextmanager
def pause_operation():
    """Explicit human interaction does not spend the enclosing automation budget."""
    stack = getattr(_local, "budgets", [])
    started = time.monotonic()
    _local.budgets = []
    try:
        yield
    finally:
        elapsed = time.monotonic() - started
        for budget in stack:
            budget[0] += elapsed
        _local.budgets = stack


def failure_code() -> str:
    return "browser_operation_timeout" if fired and fired.get("operation") else "browser_unresponsive"


def _timeout_error() -> BrowserUnresponsive:
    if fired and fired.get("operation"):
        return BrowserOperationTimeout(f"{fired['operation']} exceeded its page budget during {fired['call']}")
    return BrowserUnresponsive(f"browser unresponsive since {fired['call']}")


def install(limit_sec: float = LIMIT_SEC) -> None:
    """Time every sync Playwright call of this process (once)."""
    global _installed
    if _installed:
        return
    from playwright._impl import _sync_base

    original = _sync_base.SyncBase._sync

    def timed_sync(self: Any, coro: Any) -> Any:
        name = getattr(coro, "__qualname__", "") or type(coro).__name__
        if fired is not None:
            coro.close()
            raise _timeout_error()
        if interrupted is not None:
            coro.close()
            raise interrupted
        if _soon and not _running_soon:
            try:
                _run_soon_calls()
            except BaseException:
                coro.close()
                raise
        key = id(coro)
        started = time.monotonic()
        _inflight[key] = (started, name, traceback.format_stack(limit=8)[:-1],
                          getattr(self, "_loop", None), coro)
        budgets = getattr(_local, "budgets", [])
        if budgets:
            _call_deadlines[key] = tuple(min(budgets, key=lambda budget: budget[0]))
        ended = "returned"
        try:
            # Refuse to start another candidate after the shared budget expired.
            if key in _call_deadlines and started >= _call_deadlines[key][0]:
                check(limit_sec)
                coro.close()
                raise _timeout_error()
            return original(self, coro)
        except asyncio.CancelledError:
            ended = "cancelled"
            if fired is not None:
                raise _timeout_error() from None
            if interrupted is not None:
                raise interrupted from None
            raise
        except BaseException as exc:
            ended = type(exc).__name__
            raise
        finally:
            _inflight.pop(key, None)
            _call_deadlines.pop(key, None)
            elapsed = time.monotonic() - started
            _period["calls"] += 1
            _period["seconds"] += elapsed
            if elapsed > _period["slowest_sec"]:
                _period["slowest"], _period["slowest_sec"] = name, elapsed
            if elapsed > SLOW_CALL_SEC and on_slow_call is not None:
                _report_slow(name, elapsed, ended)

    _sync_base.SyncBase._sync = timed_sync
    _installed = True
    threading.Thread(target=_watch, args=(limit_sec,), name="browser-watchdog", daemon=True).start()


def _report_slow(name: str, seconds: float, ended: str) -> None:
    """Tell ``on_slow_call`` about a long call, with the engine's line that made it."""
    frames = [f for f in traceback.extract_stack(limit=16)
              if "paper_search_carsi" in f.filename and not f.filename.endswith("watchdog.py")]
    where = f"{frames[-1].filename.rsplit('/', 1)[-1]}:{frames[-1].lineno} {frames[-1].name}" if frames else ""
    try:
        on_slow_call(name, seconds, ended, where)
    except Exception:
        pass  # a record, never the article's end


def _watch(limit_sec: float) -> None:
    while not check(limit_sec):
        time.sleep(0.25)


def check(limit_sec: float) -> bool:
    """Cancel a call that has run past ``limit_sec``; True once fired."""
    global fired
    if fired is not None:
        return True
    now = time.monotonic()
    deadlines = dict(_call_deadlines)
    overdue = [(key, entry) for key, entry in list(_inflight.items())
               if now - entry[0] > limit_sec
               or (key in deadlines and now >= deadlines[key][0])]
    if not overdue:
        return False
    key, entry = min(overdue, key=lambda pair: pair[1][0])
    started, name, stack, loop, coro = entry
    fired = {"call": name, "seconds": int(now - started)}
    deadline = deadlines.get(key)
    if deadline and deadline[0] <= now and deadline[0] <= started + limit_sec:
        fired["operation"] = deadline[1]
    log.warning("%s: %s waited %ss; operation=%s; caller:\n%s", failure_code(), name,
                fired["seconds"], fired.get("operation", ""), "".join(stack))
    # Every thread's stack, for the cause of the hang (still unknown, 2026-11-01).
    from ..log import dump_stacks

    dump_stacks(f"{failure_code()}: {name} waited {fired['seconds']}s")
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(_cancel, coro)
    return True


def interrupt(exc: BaseException) -> None:
    """End the item at once: cancel the running browser call; it and every later
    call raise ``exc`` until :func:`clear_interrupt`."""
    global interrupted
    interrupted = exc
    for _, _, _, loop, coro in list(_inflight.values()):
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(_cancel, coro)


def clear_interrupt() -> None:
    global interrupted
    interrupted = None


def run_soon(work: Any) -> None:
    """Run ``work()`` on the browser thread before its next browser call."""
    _soon.append(work)


def _run_soon_calls() -> None:
    global _running_soon
    _running_soon = True
    try:
        while _soon:
            _soon.pop(0)()
    finally:
        _running_soon = False


def _cancel(coro: Any) -> None:
    """Runs in the event loop: cancel the task driving ``coro``."""
    for task in asyncio.all_tasks():
        if task.get_coro() is coro:
            task.cancel()

"""The Playwright API package both browser backends run on: Patchright.

Patchright is Playwright's code under another package name, with Chromium's
automation traces removed. Its errors are its own classes, and ``evaluate``
runs in an isolated world unless told otherwise.
"""
from __future__ import annotations

from typing import Any

from patchright.sync_api import Error, TimeoutError  # noqa: F401  (``except Error``)


def main_world(_target: Any = None) -> dict[str, Any]:
    """``evaluate`` options for the page's own world, where init scripts run and
    page globals live; Patchright evaluates in an isolated world by default."""
    return {"isolated_context": False}


def is_driver_error(exc: BaseException, name: str = "") -> bool:
    """An error raised by the driver (optionally of class ``name``), not a program bug."""
    return type(exc).__module__.startswith("patchright.") and (not name or type(exc).__name__ == name)


#: What a call says once the driver process is gone: the call it was answering, then
#: every later call of the process (builtin Exception and RuntimeError, not the
#: driver's own classes). Windows, 2026-11-18: after 753 Cell papers the driver and
#: its Chrome were gone, and 88 papers failed within a second each.
_DRIVER_GONE = ("Connection closed while reading from the driver", "no running event loop")


def driver_lost(exc: BaseException) -> bool:
    """The connection to the driver is gone: no call of this process reaches a browser again."""
    return any(words in str(exc) for words in _DRIVER_GONE)


def sync_bases() -> list[type]:
    """The SyncBase classes whose calls the watchdog times."""
    from patchright._impl import _sync_base

    return [_sync_base.SyncBase]

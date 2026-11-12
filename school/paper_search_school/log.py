"""Logging setup for the school subscription download backend. Routes to stderr to avoid corrupting MCP stdio."""

from __future__ import annotations

import logging
import sys
from .data_home import default_data_dir

_logger: logging.Logger | None = None
_stack_file = None


def _file_handler() -> logging.Handler | None:
    """Daily log file under ``<data dir>/logs`` so a run can be traced afterwards."""
    import os
    from datetime import date
    from pathlib import Path

    if os.environ.get("SCHOOL_FILE_LOG") == "0":
        return None
    try:
        data_dir = default_data_dir()
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / f"backend-{date.today().isoformat()}.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [pid %(process)d] %(levelname)s %(message)s"))
        return handler
    except Exception:
        return None


def enable_stack_dump() -> None:
    """Prepare watchdog dumps on every OS; POSIX also supports ``kill -USR1``.
    Stacks go to ``<data dir>/logs/stacks-<date>.txt``."""
    global _stack_file
    import faulthandler
    import os
    import signal
    from datetime import date
    from pathlib import Path

    if _stack_file is not None or os.environ.get("SCHOOL_FILE_LOG") == "0":
        return
    try:
        log_dir = default_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        _stack_file = open(log_dir / f"stacks-{date.today().isoformat()}.txt", "a", encoding="utf-8")
    except OSError:
        get_logger().warning("Could not open the browser watchdog stack log")
        return
    # Windows has no SIGUSR1/register, but dump_traceback works there. A failed
    # optional signal hook must not disable explicit watchdog dumps either.
    if hasattr(signal, "SIGUSR1"):
        try:
            faulthandler.register(signal.SIGUSR1, file=_stack_file, all_threads=True)
        except (OSError, RuntimeError, ValueError):
            get_logger().warning("Stack log ready, but the SIGUSR1 hook is unavailable")


def dump_stacks(reason: str) -> bool:
    """Append every thread's Python stack to the stack file now, as ``kill -USR1``
    would; True when written. The watchdog calls it when a browser call hangs, so
    the hang leaves its stacks without anyone at the machine."""
    import faulthandler
    from datetime import datetime

    if _stack_file is None:
        return False
    try:
        _stack_file.write(f"\n=== {datetime.now().isoformat(timespec='seconds')} {reason}\n")
        _stack_file.flush()
        faulthandler.dump_traceback(file=_stack_file, all_threads=True)
        _stack_file.flush()
        return True
    except (OSError, ValueError):
        return False


def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("paper_search_school")
        if not _logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
            _logger.addHandler(handler)
            file_handler = _file_handler()
            if file_handler is not None:
                _logger.addHandler(file_handler)
            _logger.setLevel(logging.INFO)
    return _logger

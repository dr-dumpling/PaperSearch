"""Persistent browser profile state and ownership, independent of the launcher.

Session cookies use their existing per-profile file and expiry. Native lock
checks never remove another process's lock or change the profile location.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
PROFILE_RELEASE_TIMEOUT_SEC = 20.0


SESSION_COOKIES_FILE = ".paper-search-session-cookies.json"
SESSION_COOKIES_MAX_AGE_SEC = 12 * 3600


def _save_session_cookies(context: Any, profile: Path) -> None:
    """Keep session cookies (IdP and publisher logins) for the next launch.

    Each paper runs in a new backend process and browser; the browser drops
    cookies without an expiry when it closes, so every paper asked for the
    school login again. Only session cookies are kept: persistent ones are in
    the profile already. The file is readable by the user only.
    """
    try:
        cookies = [c for c in context.cookies() if not c.get("expires") or c.get("expires", -1) < 0]
    except Exception:
        return
    path = profile / SESSION_COOKIES_FILE
    try:
        if not cookies:
            path.unlink(missing_ok=True)
            return
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"saved_at": time.time(), "cookies": cookies}),
                       encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception as exc:
        logger.debug("browser_backend: session cookies not saved: %s", type(exc).__name__)


def _restore_session_cookies(context: Any, profile: Path) -> int:
    path = profile / SESSION_COOKIES_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if time.time() - float(data.get("saved_at", 0)) > SESSION_COOKIES_MAX_AGE_SEC:
        return 0
    restored = 0
    for cookie in data.get("cookies") or []:
        try:
            context.add_cookies([{k: v for k, v in cookie.items() if k != "expires" or v not in (None, -1)}])
            restored += 1
        except Exception:
            continue
    return restored


def _profile_owner_pid(user_data_dir: str) -> int | None:
    """PID of the browser holding this profile, if any: Chromium's
    ``SingletonLock`` symlink to ``<host>-<pid>`` (macOS and Linux)."""
    try:
        target = os.readlink(Path(user_data_dir) / "SingletonLock")
    except OSError:
        return None
    match = re.search(r"-(\d+)$", target)
    return int(match.group(1)) if match else None


def _lock_file_held(path: Path) -> bool:
    """Another process holds this lock file: Chromium's ``lockfile`` on Windows,
    which the running browser keeps open without write sharing (an fcntl lock
    elsewhere). The lock is tested, never kept."""
    if not path.exists():
        return False
    try:
        fd = os.open(str(path), os.O_RDWR)
    except PermissionError:
        return True  # Windows: the running browser has it open
    except OSError:
        return False
    try:
        try:
            import fcntl
        except ImportError:
            return False
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.lockf(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def profile_holder(user_data_dir: str) -> str:
    """Who still holds this profile ("" = nobody): a live ``SingletonLock``
    owner, or a ``lockfile`` another process holds (Windows)."""
    pid = _profile_owner_pid(user_data_dir)
    if pid is not None and _pid_alive(pid):
        return f"lock of pid {pid}"
    if _lock_file_held(Path(user_data_dir) / "lockfile"):
        return "lockfile held"
    return ""


def _pid_alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def wait_for_profile_release(user_data_dir: str, timeout: float = PROFILE_RELEASE_TIMEOUT_SEC) -> bool:
    """Wait while a previous browser process still owns this persistent profile.

    Back-to-back downloads reuse one profile; the previous Chrome can take a
    few seconds to exit after its context closed. Launching meanwhile fails,
    and the fallback launcher then reports a misleading "executable doesn't
    exist". Returns True when the profile is free (or never locked).
    """
    import time

    deadline = time.monotonic() + max(0.0, timeout)
    waited = False
    while True:
        if not profile_holder(user_data_dir):
            if waited:
                logger.info("browser_backend: persistent profile released by previous browser")
            return True
        if time.monotonic() >= deadline:
            logger.info("browser_backend: persistent profile still in use by another browser process")
            return False
        if not waited:
            logger.info("browser_backend: waiting for the previous browser to release the profile")
            waited = True
        time.sleep(0.5)

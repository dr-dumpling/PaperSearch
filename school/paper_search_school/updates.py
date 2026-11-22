"""The settings window's one version and one update (user, 2026-11-21: PaperSearch and Pro one thing to them, updated
by one button).

The window checks PaperSearch's newest version (``paper-search update check``: npm's release, or the private
install's own repository) and, with Pro installed, Pro's (``paper-search pro check``). 更新 then runs, one after
another, what is behind: PaperSearch itself (``update install``), the school extension (``school update``) and the
Skills (``skills update``) after it, Pro (``pro install``); each step's outcome is kept for the page. A window holds the
code it started with: once PaperSearch itself is updated it opens again (``reopen``), and one left open while an
update happened elsewhere says so (``installed_version`` beside ``RUNNING``).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

_VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?")


def _version(value: Any) -> str:
    text = str(value or "").strip()
    return text if _VERSION.fullmatch(text) else ""


def installed_version() -> str:
    """The PaperSearch version installed now: the extension's install record, rewritten by each update."""
    try:
        record = json.loads((Path(sys.prefix).parent / "install.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return _version(record.get("paperSearchVersion")) if isinstance(record, dict) else ""


#: The version this window runs: as PaperSearch passed it when it started the window, else as installed then.
RUNNING = _version(os.environ.get("PAPER_SEARCH_VERSION")) or installed_version()

#: The steps of 更新, in order, each with what the page calls it.
STEPS = {"paper_search": "PaperSearch", "school": "学校订阅下载扩展", "skills": "Skill", "pro": "Pro"}


def _quiet_env() -> dict[str, str]:
    # A step updates only what it is for: no Skill update or version reminder alongside.
    return {**os.environ, "PAPER_SEARCH_SKILL_AUTO_UPDATE": "false", "PAPER_SEARCH_UPDATE_NOTIFY": "false"}


def _last_json(text: str) -> dict[str, Any]:
    for line in reversed([line for line in str(text or "").splitlines() if line.strip()]):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _run(argv: list[str], timeout: int) -> tuple[int, str]:
    extra = {"creationflags": 0x08000000} if os.name == "nt" else {}
    done = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace", env=_quiet_env(),
                          timeout=timeout, stdin=subprocess.DEVNULL, **extra)
    return done.returncode, done.stdout


class VersionCheck:
    """PaperSearch's newest version and, with Pro installed, Pro's: {state: idle, running, done (current, latest,
    update, notes, pro_update, pro_latest), failed (message)}; checked again once its answer is an hour old."""

    def __init__(self, command_of: Callable[[], list[str] | None] | None = None,
                 run: Callable[[list[str], int], tuple[int, str]] | None = None,
                 pro_installed: Callable[[], bool] | None = None, now: Callable[[], float] = time.time) -> None:
        from .api_keys import paper_search_command

        self._command_of = command_of or paper_search_command
        self._run = run or _run
        self._pro_installed = pro_installed or _pro_installed
        self._now = now
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"state": "idle"}
        self._at = 0.0

    def state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def start(self, again: bool = False) -> dict[str, Any]:
        with self._lock:
            fresh = self._state.get("state") == "done" and self._now() - self._at < 3600
            if self._state.get("state") == "running" or (fresh and not again):
                return dict(self._state)
            self._state = {"state": "running"}
        threading.Thread(target=self._check, name="version-check", daemon=True).start()
        return {"state": "running"}

    def _check(self) -> None:
        command = self._command_of()
        state: dict[str, Any]
        if command is None:
            state = {"state": "failed", "message": "找不到 paper-search 命令"}
        else:
            try:
                answer = _last_json(self._run([*command, "update", "check", "--format", "json"], 60)[1])
                latest = _version(answer.get("latest") or answer.get("latestVersion"))
                if answer.get("ok") is not True or not latest:
                    state = {"state": "failed", "message": str(answer.get("message") or "检查更新出错")}
                else:
                    update = answer.get("update") if "update" in answer else answer.get("updateAvailable")
                    state = {"state": "done", "current": _version(answer.get("current") or answer.get("currentVersion")) or RUNNING,
                             "latest": latest, "update": update is True, "notes": str(answer.get("releaseNotesUrl") or ""),
                             "pro_update": False, "pro_latest": ""}
                    if self._pro_installed():
                        pro = _last_json(self._run([*command, "pro", "check"], 60)[1])
                        if pro.get("ok") is True:
                            state.update(pro_update=pro.get("update") is True, pro_latest=_version(pro.get("latest")))
            except (OSError, subprocess.SubprocessError):
                state = {"state": "failed", "message": "检查更新出错"}
        with self._lock:
            self._state = state
            self._at = self._now()


def _pro_installed() -> bool:
    try:
        from .pro_status import status

        return bool(status().get("installed"))
    except Exception:
        return False


class UpdateAll:
    """更新: what is behind, one step after another; {state: idle, running (steps, step), done (steps, reopen),
    failed (steps, step, message)}. ``reopen``: PaperSearch itself was updated, the window opens again."""

    def __init__(self, command_of: Callable[[], list[str] | None] | None = None,
                 run: Callable[[list[str], int], tuple[int, str]] | None = None) -> None:
        from .api_keys import paper_search_command

        self._command_of = command_of or paper_search_command
        self._run = run or _run
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"state": "idle"}

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {**self._state, **({"steps": list(self._state["steps"])} if "steps" in self._state else {})}

    def start(self, core: bool, pro: bool, target: str = "") -> dict[str, Any]:
        """``core``: PaperSearch is behind (then the extension and the Skills after it); ``pro``: Pro is."""
        from .progress_reporter import read_state

        steps = (["paper_search", "school", "skills"] if core else []) + (["pro"] if pro else [])
        with self._lock:
            if self._state.get("state") == "running":
                return dict(self._state)
            if not steps:
                return {"state": "idle"}
            if (read_state() or {}).get("status") == "running":
                return {"state": "idle", "error": "正在下载，等这次下载结束再更新"}
            self._state = {"state": "running", "steps": steps, "step": 0, "target": target}
        threading.Thread(target=self._go, args=(steps,), name="update-all", daemon=True).start()
        return self.state()

    def _go(self, steps: list[str]) -> None:
        command = self._command_of()
        if command is None:
            return self._failed(0, "找不到 paper-search 命令")
        argv = {"paper_search": ["update", "install"], "school": ["school", "update"], "skills": ["skills", "update"],
                "pro": ["pro", "install"]}
        for index, step in enumerate(steps):
            with self._lock:
                self._state = {**self._state, "step": index}
            try:
                code, out = self._run([*command, *argv[step]], 900)
            except (OSError, subprocess.SubprocessError):
                return self._failed(index, f"更新{STEPS[step]}出错")
            answer = _last_json(out)
            if code != 0 or answer.get("ok") is False:
                return self._failed(index, str(answer.get("message") or answer.get("error") or f"更新{STEPS[step]}出错"))
        with self._lock:
            self._state = {**self._state, "state": "done", "step": len(steps), "reopen": "paper_search" in steps}

    def _failed(self, index: int, message: str) -> None:
        with self._lock:
            self._state = {**self._state, "state": "failed", "step": index, "message": message}


#: Started by ``reopen``: waits for the window it was started by to close, then opens the settings again with the
#: PaperSearch installed now (its new window).
_REOPEN = """
import json, subprocess, sys, time
from paper_search_school.progress_reporter import _pid_alive
pid, argv = int(sys.argv[1]), json.loads(sys.argv[2])
deadline = time.time() + 60
while _pid_alive(pid) and time.time() < deadline:
    time.sleep(0.3)
extra = {"creationflags": 0x08000000} if sys.platform == "win32" else {"start_new_session": True}
subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
"""


def reopen(page: str = "about", command_of: Callable[[], list[str] | None] | None = None, popen=None) -> bool:
    """The settings opened again at ``page`` once this window has closed (the caller closes it); False when
    PaperSearch's command is not found (the window stays)."""
    from .api_keys import paper_search_command

    command = (command_of or paper_search_command)()
    if command is None:
        return False
    extra = {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
    (popen or subprocess.Popen)([sys.executable, "-c", _REOPEN, str(os.getpid()), json.dumps([*command, "settings", page])],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=_quiet_env(), **extra)
    return True

"""PaperSearch Pro (the Markdown converter) on this computer, as the settings window shows it:
installed or not, and its version. The command line hands
the path it loads Pro from in ``PAPER_SEARCH_PRO_PATH``; without it, Pro's place in PaperSearch's
data, as the command line computes it. ``pro.json`` beside Pro gives its version."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

# The Markdown page's 提交 issue: the public tracker, its title begun (user, 2026-11-18).
ISSUE_URL = "https://github.com/dr-dumpling/PaperSearch/issues/new?title=" + quote("Markdown 全文：")


def data_home(env: Mapping[str, str] | None = None) -> Path:
    """PaperSearch's data folder, as the command line computes it (paperSearchDataHome)."""
    env = os.environ if env is None else env
    data = Path(env["XDG_DATA_HOME"]).resolve() if env.get("XDG_DATA_HOME") else Path.home() / ".local" / "share"
    return data / "paper-search-cli"


def entry(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    given = (env.get("PAPER_SEARCH_PRO_PATH") or "").strip()
    if given:
        return Path(given)
    return data_home(env) / "pro" / "index.js"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Installed or not and its version; installed, what the page shows besides (user, 2026-11-19):
    the sites with rules (pro.json), the Markdown saved on this computer (pro/stats.json, which the
    command line counts) and whether Pro is free now (pro/access.json, which Pro keeps)."""
    path = entry(env)
    if not path.is_file():
        return {"installed": False, "version": "", "activation": activation(env)}
    manifest = _read(path.parent / "pro.json")
    sites = manifest.get("sites")
    stats = _read(data_home(env) / "pro" / "stats.json")
    converted = _count(stats.get("converted"))
    access = _read(data_home(env) / "pro" / "access.json")
    until = access.get("until")
    return {
        "installed": True,
        "version": str(manifest.get("version") or ""),
        "sites": [str(site) for site in sites[:200] if isinstance(site, str)] if isinstance(sites, list) else [],
        "converted": converted,
        "complete": min(converted, _count(stats.get("complete"))),
        "access": {"mode": access.get("mode") if access.get("mode") in ("free", "key") else "free",
                   "until": _day(until)},
        "activation": activation(env),
    }


_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def activation(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Whether this computer is activated (user, 2026-11-21), from ``pro/activation.json``, which
    ``paper-search pro activate`` keeps (src/management/pro/activate.ts): none, active or expired,
    the code's last four characters and the day it ends. The code itself is not handed on."""
    record = _read(data_home(env) / "pro" / "activation.json")
    code = record.get("code")
    if not isinstance(code, str) or not code:
        return {"state": "none", "tail": "", "until": ""}
    until = record.get("until") if isinstance(record.get("until"), str) and _DAY.match(record["until"]) else ""
    import time

    expired = bool(until) and until < time.strftime("%Y-%m-%d", time.localtime())
    return {"state": "expired" if expired else "active", "tail": code[-4:], "until": until}


def _day(ms: Any) -> str:
    """A free setting's end ("2027-03-01"), from Pro's milliseconds; "" for none."""
    import time

    if not isinstance(ms, (int, float)) or isinstance(ms, bool) or ms <= 0:
        return ""
    return time.strftime("%Y-%m-%d", time.localtime(ms / 1000))


class ProInstall:
    """The settings window's 安装: ``paper-search pro install --progress`` in the background, its
    progress lines read as they come; the page asks for ``state()`` until it is done or failed."""

    def __init__(self, command_of=None, popen=None, run=None):
        import subprocess
        import threading

        from .api_keys import paper_search_command

        self._command_of = command_of or paper_search_command
        self._popen = popen or subprocess.Popen
        self._run_command = run or subprocess.run
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"state": "idle"}

    def state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _set(self, **state: Any) -> None:
        with self._lock:
            self._state = state

    def start(self, code: str | None = None) -> dict[str, Any]:
        """安装, or with the code typed on Pro's page 激活并安装: ``paper-search pro activate`` first
        (user, 2026-11-21), the code handed on standard input; the install only once it is active."""
        import threading

        with self._lock:
            if self._state.get("state") == "running":
                return dict(self._state)
            activating = code is not None
            self._state = started = ({"state": "running", "step": "activate"} if activating
                                     else {"state": "running", "step": "install", "done": 0, "total": 0})
        threading.Thread(target=self._run, args=(code,), name="pro-install", daemon=True).start()
        return dict(started)

    def _activate(self, command: list[str], env: dict[str, str], code: str) -> bool:
        try:
            run = self._run_command([*command, "pro", "activate"], input=code, capture_output=True, encoding="utf-8",
                                    errors="replace", env=env, timeout=60)
            lines = [line for line in (run.stdout or "").splitlines() if line.strip()]
            answer = json.loads(lines[-1]) if lines else {}
        except Exception:
            answer = {}
        if isinstance(answer, dict) and answer.get("ok") is True:
            return True
        message = answer.get("message") or answer.get("error") if isinstance(answer, dict) else ""
        self._set(state="failed", step="activate", message=str(message or "激活出错"))
        return False

    def _run(self, code: str | None = None) -> None:
        import subprocess

        command = self._command_of()
        if command is None:
            self._set(state="failed", step="activate" if code is not None else "install", message="找不到 paper-search 命令")
            return
        # An install must not also update the Skill or check for a new version.
        env = {**os.environ, "PAPER_SEARCH_SKILL_AUTO_UPDATE": "false", "PAPER_SEARCH_UPDATE_NOTIFY": "false"}
        if code is not None:
            if not self._activate(command, env, code):
                return
            self._set(state="running", step="install", done=0, total=0)
        last: dict[str, Any] = {}
        try:
            process = self._popen([*command, "pro", "install", "--progress"], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace", env=env)
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict) and message.get("event") == "progress":
                    self._set(state="running", step="install", done=int(message.get("done") or 0),
                              total=int(message.get("total") or 0))
                elif isinstance(message, dict):
                    last = message
            process.wait(timeout=60)
        except Exception:
            self._set(state="failed", step="install", message="安装出错")
            return
        if last.get("ok") is True:
            self._set(state="done", version=str(last.get("version") or ""))
        else:
            self._set(state="failed", step="install", message=str(last.get("message") or last.get("error") or "安装出错"))

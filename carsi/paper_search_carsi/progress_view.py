"""What the download progress windows show, worked out from the progress file.

Shared by the progress capsule (``progress_capsule``) and the classic window
(``progress_bar``): the texts, the steps, the needs-you prompts, when a
finished window closes, the window lock and the OS appearance. No GUI imports,
so tests cover every state without opening a window.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any

CONTENT_LABELS = {"main": "正文", "supplements": "附录", "both": "正文+附录"}
# The step of the main text, as the status line says it ("正文 · 正在获取 PDF").
STAGE_TEXT = {
    "starting": "准备中", "opening_article": "正在打开文章", "checking_access": "正在检查访问权限",
    "waiting_login": "等待机构登录", "waiting_verification": "等待人机验证", "fetching_pdf": "正在获取 PDF",
    "pdf_captured": "已读到 PDF，正在核对", "saved_pending_verification": "已保存",
    "route_failed": "这条路没走通，正在换路",
    "supplements_checked": "附录检查完成",
}
# The capsule's five steps of one paper, and where each stage sits on them.
STEPS = ("打开文章", "权限", "取 PDF", "核对", "附录")
STAGE_STEP = {
    "starting": (0, "准备中"), "opening_article": (0, "打开文章"),
    "checking_access": (1, "检查权限"), "waiting_login": (1, "等待登录"),
    "waiting_verification": (1, "等待验证"), "route_failed": (1, "换一条路"),
    "fetching_pdf": (2, "取 PDF"), "pdf_captured": (3, "核对 PDF"), "saved_pending_verification": (3, "已保存"),
}
# What a needs-you prompt asks, short enough for the collapsed capsule.
ATTENTION_SHORT = {"waiting_login": "请登录学校", "waiting_verification": "请完成验证"}
# The answer a button gets in the window, before the download confirms it.
ACTION_FEEDBACK = {
    "stop_batch": "已终止任务：这一篇结束，剩下的不再下载",
    "skip_item": "已跳过本篇，进入下一篇",
    "skip_journal": "已记住：本刊无权限，以后自动跳过（可用 entitlements 撤销）",
    "skip_publisher": "已记住：该出版社无权限，以后自动跳过",
}

TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled", "interrupted"})
DEFAULT_LINGER_SECONDS = 8.0
NOTICE_SECONDS = 10.0  # how long the download's answer to a click stays on screen


class AutoClose:
    """Decide when an auto-spawned window should close after its task ends.

    A task that saved everything closes ``linger`` seconds after it ends. One
    with failures, or stopped or interrupted, stays until the user closes it
    or a new task starts, so the result is still there when they come back.
    While the pointer is on the window it stays, and the linger starts again
    once it leaves. A new task in the meantime (different run) keeps the window
    open. Windows the user opened by hand (``paper-search-carsi progress``)
    never close.
    """

    def __init__(self, *, enabled: bool, linger: float) -> None:
        self.enabled = enabled
        self.linger = max(0.0, linger)
        self._run: object = None
        self._since: float | None = None

    @classmethod
    def from_env(cls) -> "AutoClose":
        enabled = os.environ.get("CARSI_PROGRESS_BAR_CHILD") == "1"
        try:
            linger = float(os.environ.get("CARSI_PROGRESS_BAR_LINGER", DEFAULT_LINGER_SECONDS))
        except ValueError:
            linger = DEFAULT_LINGER_SECONDS
        return cls(enabled=enabled, linger=linger)

    def should_close(self, state: dict[str, Any] | None, now: float, *, hovering: bool = False) -> bool:
        if not self.enabled:
            return False
        if not state or state.get("status") not in TERMINAL_STATUSES:
            # running (or nothing to show yet): keep the window
            self._run, self._since = None, None
            return False
        if state.get("status") != "done" or _count(state.get("failed")) > 0:
            return False  # failures, a stop or an interruption: the user closes it
        run = state.get("run_id") or state.get("started_at")
        if run != self._run or self._since is None or hovering:
            self._run, self._since = run, now
        return not hovering and now - self._since >= self.linger


def fmt_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_clock(seconds: float) -> str:
    """The capsule's times: 3:12, 2:41, 1:02:03."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def status_text(state: dict[str, Any], running: bool) -> str:
    """The status line: which part of the paper is being fetched and how far,
    "正文 · 正在获取 PDF" or "附录 · 已保存 2/5"; between papers, the phase."""
    phase = str(state.get("phase") or ("处理中" if running else ""))
    part = str(state.get("part") or "")
    if not running or state.get("awaiting_next") or part not in ("main", "supplements"):
        return phase
    if part == "supplements":
        total = state.get("supplements_total")
        if not isinstance(total, int):
            return "附录 · 正在查找附录文件"
        return f"附录 · 已保存 {int(state.get('supplements_saved') or 0)}/{total}"
    return "正文 · " + STAGE_TEXT.get(str(state.get("stage") or ""), phase)


def attention_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    attention = state.get("attention")
    if isinstance(attention, dict):
        if "message" in attention:
            return [attention]
        return [v for v in attention.values() if isinstance(v, dict)]
    if isinstance(attention, list):
        return [v for v in attention if isinstance(v, dict)]
    return []


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _time(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def view(state: dict[str, Any] | None, now: float) -> dict[str, Any]:
    """Everything the capsule shows for one snapshot of the progress file.

    ``now`` is ``time.time()``. ``mode`` is idle, running, attention (a step
    needs the user) or done; ``tone`` colours the capsule."""
    if not state:
        return {"mode": "idle"}
    status = str(state.get("status") or "")
    running = status == "running"
    total = _count(state.get("total"))
    done = _count(state.get("done"))
    done = min(total, done) if total else done
    ok, bad = _count(state.get("success")), _count(state.get("failed"))
    attention = attention_items(state) if running else []

    if attention:
        mode, tone, headline = "attention", "warn", "需要你操作"
    elif running:
        mode, tone, headline = "running", "accent", "下载中"
    elif status == "cancelled":
        mode, tone, headline = "done", "warn", "已终止任务"
    elif status == "interrupted":
        mode, tone, headline = "done", "warn", "下载中断"
    elif ok == 0 and bad > 0:
        mode, tone, headline = "done", "bad", "下载未成功"
    elif bad > 0:
        mode, tone, headline = "done", "warn", "下载结束，部分失败"
    else:
        mode, tone, headline = "done", "ok", "下载完成"

    awaiting = bool(state.get("awaiting_next"))
    part_key = str(state.get("part") or "")
    if running and not awaiting and part_key in ("main", "supplements"):
        part = CONTENT_LABELS[part_key]
    else:
        part = CONTENT_LABELS.get(str(state.get("content") or "main"), CONTENT_LABELS["main"])
    publisher = str(state.get("publisher") or "")
    journal = str(state.get("journal") or "")
    current = str((attention[-1].get("current") if attention else "") or state.get("current") or "")

    step = None
    if running and not attention and not awaiting:
        if part_key == "supplements":
            found = state.get("supplements_total")
            label = (f"附录 {_count(state.get('supplements_saved'))}/{found}"
                     if isinstance(found, int) else "查找附录")
            step = {"index": 4, "label": label}
        elif part_key == "main" and str(state.get("stage") or "") in STAGE_STEP:
            index, label = STAGE_STEP[str(state.get("stage"))]
            step = {"index": index, "label": label}

    started = _time(state.get("started_at"))
    ended = now if running else _time(state.get("finished_at"))
    elapsed = fmt_clock(ended - started) if started is not None and ended is not None else ""

    prompt = None
    if attention:
        item = attention[-1]
        message = str(item.get("message") or "请在浏览器窗口完成安全验证")
        stage = str(state.get("stage") or "")
        short = ATTENTION_SHORT.get(stage) or (
            "请登录学校" if "登录" in message else "请完成验证" if "验证" in message else "需要你处理")
        deadline = item.get("deadline")
        remaining = (max(0, int(deadline - now))
                     if isinstance(deadline, (int, float)) and not isinstance(deadline, bool) else None)
        prompt = {"message": message, "short": short, "more": len(attention) - 1,
                  "remaining": fmt_clock(remaining) if remaining is not None else "",
                  "login": short == "请登录学校"}

    notice = ""
    raw = state.get("notice")
    if isinstance(raw, dict) and str(raw.get("current") or "") == str(state.get("current") or ""):
        try:
            if now - float(raw.get("at") or 0) < NOTICE_SECONDS:
                notice = str(raw.get("text") or "")
        except (TypeError, ValueError):
            pass

    return {
        "mode": mode, "tone": tone, "headline": headline,
        # The collapsed capsule of a finished task: "完成 38/40", "已终止 12/40".
        "finished": {"cancelled": "已终止", "interrupted": "已中断"}.get(status, "完成"),
        "done": done, "total": total, "pct": round(100 * done / total) if total else 0,
        "ok": ok, "bad": bad, "left": max(0, total - done) if running and total else None,
        "part": part, "publisher": publisher,
        "where": " · ".join(v for v in (journal, publisher) if v),
        "title": str(state.get("title") or ""), "current": current,
        "run_id": str(state.get("run_id") or ""),
        "step": step, "steps": list(STEPS), "line": status_text(state, running) if running else "",
        "elapsed": elapsed, "attention": prompt, "notice": notice,
        "completion_detail": str(state.get("phase") or "")
            if not running and state.get("stage") == "supplements_checked" else "",
        "actions": running and bool(current) and not awaiting,
        "stop_left": max(0, total - done - 1),
        "folder": bool(state.get("output_dir")),
    }


# --- window plumbing shared by both windows -------------------------------
def _lock_path():
    from .progress_reporter import progress_path

    return progress_path().parent / "bar.pid"


def write_window_lock() -> None:
    """Mark this process as the open progress window (ensure_progress_bar reads it)."""
    try:
        lock = _lock_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass


def release_window_lock() -> None:
    try:
        lock = _lock_path()
        if lock.exists() and lock.read_text(encoding="utf-8").strip() == str(os.getpid()):
            lock.unlink()
    except Exception:
        pass


def dark_mode() -> bool:
    """Whether the OS uses a dark appearance (macOS / Windows); light otherwise."""
    import subprocess

    try:
        if sys.platform == "darwin":
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                 capture_output=True, text=True, timeout=2).stdout
            return out.strip().lower() == "dark"
        if os.name == "nt":
            import winreg

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except Exception:
        pass
    return False


def open_folder(path: str) -> bool:
    """Open a folder in Finder / Explorer; False when it is missing."""
    if not path or not os.path.isdir(path):
        return False
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            import subprocess

            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

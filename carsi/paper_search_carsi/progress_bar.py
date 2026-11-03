"""Floating download progress window.

A small always-on-top window that watches the task progress file
(``progress_reporter``) and shows: status and done/total, the current phase
and elapsed time, the paper being worked on, a slim progress bar, success /
failure / remaining counters and a link to the output folder. Drag the client
area to move; the native title bar provides minimize and close.

Usage: ``paper-search-carsi progress`` (or ``python -m paper_search_carsi.progress_bar``).
Spawned automatically by ``progress_reporter.ensure_progress_bar`` when a download starts.

Visual stack (no third-party GUI deps):
- Light and dark palettes follow the OS appearance (macOS / Windows).
- Platform fonts: the macOS system font (SF + PingFang), Microsoft YaHei UI
  on Windows, Noto Sans CJK on Linux; DOIs use the platform monospace.
- Windows: per-monitor DPI aware, rounded DWM frame with a matching title bar.
- All text is laid out with measured widths (CJK-safe).
"""

from __future__ import annotations

import os
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Any

import os as _os
import sys as _sys

from .progress_reporter import read_state

# --- Win32 / DWM constants -------------------------------------------------
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_ROUND = 2
DWMSBT_MAINWINDOW = 2  # light Mica

# Palettes: (light, dark). Picked once at start from the OS appearance.
CONTENT_LABELS = {"main": "正文", "supplements": "附录", "both": "正文+附录"}

PALETTES = {
    "light": {
        "bg": "#ffffff", "text": "#111827", "dim": "#6b7280", "faint": "#9ca3af",
        "track": "#e5e7eb", "accent": "#2563eb", "ok": "#16a34a", "bad": "#dc2626",
        "warn": "#b45309", "warn_bg": "#fef3c7", "link": "#2563eb", "btn": "#374151",
    },
    "dark": {
        "bg": "#1f2023", "text": "#f3f4f6", "dim": "#a1a1aa", "faint": "#71717a",
        "track": "#3f3f46", "accent": "#60a5fa", "ok": "#4ade80", "bad": "#f87171",
        "warn": "#fbbf24", "warn_bg": "#3b2f12", "link": "#60a5fa", "btn": "#d4d4d8",
    },
}

# Window, macOS Dock and Windows taskbar icon, rendered from assets/icon.svg.
ICON_FILES = ("icon-512.png", "icon-64.png", "icon-32.png")

TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled", "interrupted"})
DEFAULT_LINGER_SECONDS = 8.0


class AutoClose:
    """Decide when an auto-spawned window should close after its task ends.

    The finished state stays on screen for ``linger`` seconds; a new task in
    the meantime (different run) keeps the window open. Windows the user
    opened by hand (``paper-search-carsi progress``) never close.
    """

    def __init__(self, *, enabled: bool, linger: float) -> None:
        self.enabled = enabled
        self.linger = max(0.0, linger)
        self._run: object = None
        self._since: float | None = None

    @classmethod
    def from_env(cls) -> "AutoClose":
        enabled = _os.environ.get("CARSI_PROGRESS_BAR_CHILD") == "1"
        try:
            linger = float(_os.environ.get("CARSI_PROGRESS_BAR_LINGER", DEFAULT_LINGER_SECONDS))
        except ValueError:
            linger = DEFAULT_LINGER_SECONDS
        return cls(enabled=enabled, linger=linger)

    def should_close(self, state: dict[str, Any] | None, now: float) -> bool:
        if not self.enabled:
            return False
        if not state or state.get("status") not in TERMINAL_STATUSES:
            # running (or nothing to show yet): keep the window
            self._run, self._since = None, None
            return False
        run = state.get("run_id") or state.get("started_at")
        if run != self._run or self._since is None:
            self._run, self._since = run, now
        return now - self._since >= self.linger


# Logical layout (scaled by the real DPI factor at runtime)
W, H, PAD = 420, 172, 18


def _dark_mode() -> bool:
    """Whether the OS uses a dark appearance (macOS / Windows); light otherwise."""
    import subprocess
    import sys as _sys

    try:
        if _sys.platform == "darwin":
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


def _pick_family(candidates: list[str], fallback: str) -> str:
    try:
        available = {f.lower(): f for f in tkfont.families()}
    except Exception:
        return fallback
    for name in candidates:
        if name.lower() in available:
            return available[name.lower()]
    return fallback


def _fmt_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _enable_dpi_awareness() -> None:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _dwm(hwnd: int, attr: int, value: int) -> bool:
    try:
        import ctypes
        import ctypes.wintypes as wt
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [
            wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD,
        ]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        v = ctypes.c_int(value)
        r = dwm.DwmSetWindowAttribute(
            hwnd, attr, ctypes.byref(v), ctypes.sizeof(v),
        )
        return r == 0
    except Exception:
        return False


def _dwm_color(hwnd: int, attr: int, color: int) -> bool:
    """Set a DWM COLORREF attribute when the current Windows build supports it."""
    try:
        import ctypes
        import ctypes.wintypes as wt
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [
            wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD,
        ]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        value = ctypes.c_uint(color)
        return dwm.DwmSetWindowAttribute(
            hwnd, attr, ctypes.byref(value), ctypes.sizeof(value),
        ) == 0
    except Exception:
        return False


def _elide(font: tkfont.Font, text: str, width_px: int) -> str:
    if font.measure(text) <= width_px:
        return text
    while text and font.measure(text + "…") > width_px:
        text = text[:-1]
    return text + "…"


class ProgressWindow:
    def __init__(self) -> None:
        _enable_dpi_awareness()
        self._auto_close = AutoClose.from_env()
        self.root = tk.Tk()
        self._set_icon()
        self.c = PALETTES["dark" if _dark_mode() else "light"]
        # Tk on macOS already renders in points on Retina; Windows needs the
        # explicit per-monitor factor.
        self.s = 1.0 if _sys.platform == "darwin" else max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.W, self.H, self.P = int(W * self.s), int(H * self.s), int(PAD * self.s)
        self.root.title("PaperSearch · 下载进度")
        self.root.geometry(f"{self.W}x{self.H}+{self._anchor_x()}{self._anchor_y()}")
        self.root.minsize(self.W, self.H)
        self.root.resizable(True, False)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=self.c["bg"])

        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H,
                                bg=self.c["bg"], highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        # Map the Tk window before asking Win32 for its top-level handle.
        self.root.update_idletasks()
        self.root.update()
        self._apply_backdrop()
        self._fonts()
        self._bind_mouse()
        self._finished_elapsed: float | None = None
        self._finished_run: object = None
        self._flash: tuple[str, float, str] | None = None  # (text, until, doi)
        self._chosen: tuple[str, str] | None = None  # (doi, action) pressed for the current paper
        self._hover = ""  # the button under the mouse; kept across redraws
        self.root.after(400, self._tick)

    # --- window plumbing ---------------------------------------------------
    def _set_icon(self) -> None:
        """PaperSearch's icon for this window, the macOS Dock and the Windows
        taskbar; a plain Python process shows a blank one."""
        folder = Path(__file__).with_name("assets")
        try:
            # Kept on self: Tk drops an image once Python frees the PhotoImage.
            self._icons = [tk.PhotoImage(master=self.root, file=str(folder / name)) for name in ICON_FILES]
            self.root.iconphoto(True, *self._icons)
        except tk.TclError:
            pass  # a missing icon file must not keep the progress window from opening

    def _hwnd(self) -> int:
        if os.name != "nt":
            return 0
        try:
            import ctypes
            import ctypes.wintypes as wt
            self.root.update_idletasks()
            user32 = ctypes.windll.user32
            # GetParent on Tk's root returns 0; GetAncestor(GA_ROOT) is the frame.
            user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
            user32.GetAncestor.restype = wt.HWND
            hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
            return int(hwnd or self.root.winfo_id())
        except Exception:
            return 0

    def _apply_backdrop(self) -> None:
        """Windows 11: rounded frame and a title bar in the window's palette."""
        hwnd = self._hwnd()
        if not hwnd:
            return
        dark = self.c is PALETTES["dark"]
        _dwm(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
        _dwm(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)

        def colorref(hex_color: str) -> int:  # "#rrggbb" -> 0x00BBGGRR
            r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
            return (b << 16) | (g << 8) | r

        _dwm_color(hwnd, DWMWA_CAPTION_COLOR, colorref(self.c["bg"]))
        _dwm_color(hwnd, DWMWA_BORDER_COLOR, colorref(self.c["track"]))
        _dwm_color(hwnd, DWMWA_TEXT_COLOR, colorref(self.c["text"]))

    def _fonts(self) -> None:
        if _sys.platform == "darwin":
            ui = tkfont.nametofont("TkDefaultFont").actual("family")  # SF + PingFang fallback
            mono = _pick_family(["SF Mono", "Menlo"], "Courier")
        elif os.name == "nt":
            ui = _pick_family(["Microsoft YaHei UI", "Segoe UI"], "TkDefaultFont")
            mono = _pick_family(["Cascadia Mono", "Consolas"], "Courier New")
        else:
            ui = _pick_family(["Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei", "DejaVu Sans"], "TkDefaultFont")
            mono = _pick_family(["DejaVu Sans Mono", "Noto Sans Mono", "Liberation Mono"], "Courier")
        px = lambda n: -int(round(n * self.s))  # negative size = pixels
        self.f_title = tkfont.Font(family=ui, size=px(14), weight="bold")
        self.f_count = tkfont.Font(family=ui, size=px(14), weight="bold")
        self.f_body = tkfont.Font(family=ui, size=px(12))
        self.f_small = tkfont.Font(family=ui, size=px(11))
        self.f_mono = tkfont.Font(family=mono, size=px(11))

    def _anchor_x(self) -> int:
        return max(0, self.root.winfo_screenwidth() - self.W - int(20 * self.s))

    def _anchor_y(self) -> str:
        # macOS: top-right under the menu bar (the Dock owns the bottom edge).
        # Windows/Linux: bottom-right above the taskbar.
        if _sys.platform == "darwin":
            return "+44"
        return f"-{int(56 * self.s)}"

    def _bind_mouse(self) -> None:
        self._drag_dx = self._drag_dy = 0
        c = self.canvas
        c.bind("<Button-1>", self._press)
        c.bind("<B1-Motion>", self._move)

    def _press(self, event: Any) -> None:
        self._drag_dx, self._drag_dy = event.x, event.y

    def _move(self, event: Any) -> None:
        x = self.root.winfo_x() + event.x - self._drag_dx
        y = self.root.winfo_y() + event.y - self._drag_dy
        self.root.geometry(f"+{x}+{y}")

    # --- drawing ------------------------------------------------------------
    def _pill(self, x0: int, y0: int, x1: int, y1: int, fill: str, tags: Any = ()) -> None:
        """Crisp rounded rectangle: two discs plus a rectangle (no polygon smoothing)."""
        r = (y1 - y0) / 2
        c = self.canvas
        if x1 - x0 <= 2 * r:
            c.create_oval(x0, y0, x0 + 2 * r, y1, fill=fill, outline=fill, tags=tags)
            return
        c.create_oval(x0, y0, x0 + 2 * r, y1, fill=fill, outline=fill, tags=tags)
        c.create_oval(x1 - 2 * r, y0, x1, y1, fill=fill, outline=fill, tags=tags)
        c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline=fill, tags=tags)

    def _elapsed(self, state: dict[str, Any], finished: bool) -> str:
        from datetime import datetime

        try:
            started = datetime.fromisoformat(str(state.get("started_at")))
        except (TypeError, ValueError):
            return ""
        if finished:
            try:
                end = datetime.fromisoformat(str(state.get("finished_at")))
            except (TypeError, ValueError):
                run = state.get("run_id")
                if self._finished_run != run or self._finished_elapsed is None:
                    self._finished_run = run
                    self._finished_elapsed = (datetime.now() - started).total_seconds()
                return _fmt_elapsed(self._finished_elapsed)
            return _fmt_elapsed((end - started).total_seconds())
        return _fmt_elapsed((datetime.now() - started).total_seconds())

    @staticmethod
    def _attention_items(state: dict[str, Any]) -> list[dict[str, Any]]:
        attention = state.get("attention")
        if isinstance(attention, dict):
            if "message" in attention:
                return [attention]
            return [v for v in attention.values() if isinstance(v, dict)]
        if isinstance(attention, list):
            return [v for v in attention if isinstance(v, dict)]
        return []

    def _draw(self, state: dict[str, Any] | None) -> None:
        c, col, s = self.canvas, self.c, self.s
        c.delete("all")
        P = self.P
        Wl = max(self.W, c.winfo_width())
        Hl = max(self.H, c.winfo_height())
        u = lambda n: int(round(n * s))

        if not state:
            c.create_text(Wl // 2, Hl // 2 - u(8), text="PaperSearch", fill=col["text"], font=self.f_title)
            c.create_text(Wl // 2, Hl // 2 + u(14), text="暂无下载任务", fill=col["dim"], font=self.f_small)
            return

        status = str(state.get("status") or "")
        running = status == "running"
        total = max(0, int(state.get("total", 0) or 0))
        done = int(state.get("done", 0) or 0)
        done = min(total, done) if total else done
        ok = int(state.get("success", 0) or 0)
        bad = int(state.get("failed", 0) or 0)
        pct = (done / total) if total else 0.0
        attention = self._attention_items(state) if running else []

        if attention:
            tone, headline = col["warn"], "需要你操作"
        elif running:
            tone, headline = col["accent"], str(state.get("task") or "下载中")
        elif ok == 0 and bad > 0:
            tone, headline = col["bad"], "下载未成功"
        elif bad > 0:
            tone, headline = col["warn"], "下载结束，部分失败"
        else:
            tone, headline = col["ok"], "下载完成"

        # Row 1: status dot + headline ......... done / total
        y1 = P + u(9)
        dot = u(8)
        c.create_oval(P, y1 - dot // 2, P + dot, y1 + dot // 2, fill=tone, outline=tone)
        count = f"{done} / {total}" if total else f"{done}"
        c.create_text(Wl - P, y1, text=count, fill=col["text"], font=self.f_count, anchor="e")
        count_w = self.f_count.measure(count)
        # What this download fetches, as a small label left of the count.
        content = CONTENT_LABELS.get(str(state.get("content") or "main"), CONTENT_LABELS["main"])
        chip_h = u(18)
        chip_x1 = Wl - P - count_w - u(8)
        chip_x0 = chip_x1 - self.f_small.measure(content) - u(14)
        self._pill(chip_x0, y1 - chip_h // 2, chip_x1, y1 + chip_h // 2, col["track"])
        c.create_text((chip_x0 + chip_x1) / 2, y1, text=content, fill=col["dim"], font=self.f_small)
        title_x = P + dot + u(8)
        c.create_text(title_x, y1, anchor="w", fill=col["text"], font=self.f_title,
                      text=_elide(self.f_title, headline, chip_x0 - u(8) - title_x))

        # Row 2: phase (or the verification request) ........ elapsed
        y2 = y1 + u(25)
        elapsed = self._elapsed(state, finished=not running)
        elapsed_text = (f"已用 {elapsed}" if running else f"用时 {elapsed}") if elapsed else ""
        if elapsed_text:
            c.create_text(Wl - P, y2, text=elapsed_text, fill=col["faint"], font=self.f_small, anchor="e")
        phase_room = Wl - 2 * P - (self.f_small.measure(elapsed_text) + u(12) if elapsed_text else 0)
        flash = self._flash if self._flash and time.time() < self._flash[1] else None
        # What the download did about a click (batch_user.py), once it is newer than the click.
        notice = state.get("notice") if isinstance(state.get("notice"), dict) else {}
        notice_at = float(notice.get("at") or 0) if notice else 0.0
        if (notice and time.time() - notice_at < 10 and str(notice.get("current") or "") == str(state.get("current") or "")
                and (not flash or notice_at >= flash[1] - 6)):
            flash = (str(notice.get("text") or ""), notice_at + 10, str(notice.get("current") or ""))
        if flash and flash[2] == str(state.get("current") or ""):
            c.create_text(P, y2, anchor="w", fill=col["accent"], font=self.f_body,
                          text=_elide(self.f_body, flash[0], phase_room))
        elif attention:
            item = attention[-1]
            notice = str(item.get("message") or "请在浏览器窗口完成安全验证")
            if len(attention) > 1:
                notice += f"（另有 {len(attention) - 1} 项）"
            text = _elide(self.f_body, notice, phase_room - u(16))
            self._pill(P - u(2), y2 - u(11), P + self.f_body.measure(text) + u(14), y2 + u(11), col["warn_bg"])
            c.create_text(P + u(6), y2, text=text, fill=col["warn"], font=self.f_body, anchor="w")
        else:
            phase = str(state.get("phase") or ("处理中" if running else ""))
            c.create_text(P, y2, anchor="w", fill=col["dim"], font=self.f_body,
                          text=_elide(self.f_body, phase, phase_room))

        # Row 3: the paper being worked on
        y3 = y2 + u(22)
        current = str((attention[-1].get("current") if attention else "") or state.get("current") or "")
        if current:
            c.create_text(P, y3, anchor="w", fill=col["text"] if running else col["dim"], font=self.f_mono,
                          text=_elide(self.f_mono, current, Wl - 2 * P))
            where = " · ".join(v for v in (str(state.get("journal") or ""), str(state.get("publisher") or "")) if v)
            if where:
                doi_w = self.f_mono.measure(current) + u(10)
                if doi_w < Wl - 2 * P - u(60):
                    c.create_text(P + doi_w, y3, anchor="w", fill=col["faint"], font=self.f_small,
                                  text=_elide(self.f_small, where, Wl - 2 * P - doi_w))

        # Row 4: slim progress bar
        y4 = y3 + u(20)
        bar_h = u(6)
        self._pill(P, y4, Wl - P, y4 + bar_h, col["track"])
        fill_w = int((Wl - 2 * P) * pct)
        if fill_w > 0:
            self._pill(P, y4, P + max(bar_h, fill_w), y4 + bar_h, tone)

        # Row 5: counters ........ open folder
        y5 = y4 + bar_h + u(17)
        x = P
        for label, value, color in (("成功", ok, col["ok"]), ("失败", bad, col["bad"]),
                                    ("剩余", max(0, total - done), col["faint"])):
            if label == "剩余" and (not total or not running):
                continue
            d = u(6)
            c.create_oval(x, y5 - d // 2, x + d, y5 + d // 2, fill=color, outline=color)
            text = f"{label} {value}"
            c.create_text(x + d + u(5), y5, text=text, fill=col["dim"], font=self.f_small, anchor="w")
            x += d + u(5) + self.f_small.measure(text) + u(14)
        # Row 6: buttons for the current paper. Neutral until pressed; a pressed one
        # turns amber (the "no access" ones are remembered for later runs).
        y6 = y5 + u(26)
        if running and current and not state.get("awaiting_next"):
            x = P
            chosen = self._chosen[1] if self._chosen and self._chosen[0] == current else ""
            for key, label in (("skip_item", "跳过本篇"), ("skip_journal", "本刊无权限"),
                               ("skip_publisher", "出版社无权限")):
                pressed = key == chosen
                text = ("✓ " + label) if pressed else label
                w = self.f_small.measure(text) + u(18)
                tag = f"btn-{key}"
                self._pill(x, y6 - u(11), x + w, y6 + u(11), col["warn"] if pressed else col["track"], tags=(tag,))
                fill = col["bg"] if pressed else (col["text"] if self._hover == key else col["btn"])
                label_id = c.create_text(x + w / 2, y6, text=text, fill=fill, font=self.f_small, tags=(tag,))
                c.tag_bind(tag, "<Button-1>", lambda e, k=key, d=current, s=state: self._decide(k, d, s))
                if not pressed:
                    c.tag_bind(tag, "<Enter>", lambda e, k=key, i=label_id: self._hover_button(k, i))
                    c.tag_bind(tag, "<Leave>", lambda e, i=label_id: self._hover_button("", i))
                x += w + u(8)
            # Problem report for the agent to review: a small flag icon, right-aligned.
            c.create_text(Wl - P, y6, text="\u2691", fill=col["faint"], font=self.f_body,
                          anchor="e", tags=("report",))
            c.tag_bind("report", "<Button-1>", lambda e, d=current, s=state: self._report_menu(e, d, s))

        output_dir = str(state.get("output_dir") or "")
        if output_dir:
            link = c.create_text(Wl - P, y5, text="打开文件夹", fill=col["link"], font=self.f_small,
                                 anchor="e", tags=("outdir",))
            c.tag_bind("outdir", "<Button-1>", lambda e: self._open_output_dir(state))
            c.tag_bind("outdir", "<Enter>", lambda e: c.itemconfigure(link, font=self._underlined()))
            c.tag_bind("outdir", "<Leave>", lambda e: c.itemconfigure(link, font=self.f_small))

    def _decide(self, action: str, doi: str, state: dict[str, Any]) -> None:
        """Ask the running download to apply the user's entitlement decision."""
        try:
            from .entitlements import request_action

            request_action(doi, action, str(state.get("run_id") or ""))
            text = {"skip_item": "已跳过本篇，进入下一篇",
                    "skip_journal": "已记住：本刊无权限，以后自动跳过（可用 entitlements 撤销）",
                    "skip_publisher": "已记住：该出版社无权限，以后自动跳过"}[action]
        except Exception as exc:
            text = f"记录失败：{type(exc).__name__}"
        self._flash = (text, time.time() + 6, doi)
        self._chosen = (doi, action)
        self._draw(state)

    def _hover_button(self, key: str, label_id: int) -> None:
        self._hover = key
        self.canvas.itemconfigure(label_id, fill=self.c["text"] if key else self.c["btn"])

    def _report_menu(self, event: Any, doi: str, state: dict[str, Any]) -> None:
        """Pick the problem seen in the browser; the running download acts on it at once."""
        from .issues import ISSUE_KINDS

        menu = tk.Menu(self.root, tearoff=0)
        for kind, label in ISSUE_KINDS.items():
            menu.add_command(label=label, command=lambda k=kind: self._report(k, doi, state))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _report(self, kind: str, doi: str, state: dict[str, Any]) -> None:
        try:
            from .issues import ISSUE_KINDS, report

            report(doi, kind, state)
            text = f"已收到：{ISSUE_KINDS[kind]}，正在处理"
        except Exception as exc:
            text = f"记录失败：{type(exc).__name__}"
        self._flash = (text, time.time() + 6, doi)
        self._draw(state)

    def _underlined(self) -> tkfont.Font:
        if not hasattr(self, "_f_link_hover"):
            self._f_link_hover = self.f_small.copy()
            self._f_link_hover.configure(underline=True)
        return self._f_link_hover

    # --- polling ------------------------------------------------------------
    def _open_output_dir(self, state: dict) -> None:
        d = str(state.get("output_dir") or "")
        if d and os.path.isdir(d):
            try:
                if os.name == "nt":
                    os.startfile(d)  # Windows: open Explorer at the folder
                else:
                    import subprocess
                    import sys as _sys

                    opener = "open" if _sys.platform == "darwin" else "xdg-open"
                    subprocess.Popen([opener, d], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def _tick(self) -> None:
        state = None
        try:
            state = read_state()
            self._draw(state)
        except Exception:
            pass
        try:
            import time as _time

            if self._auto_close.should_close(state, _time.monotonic()):
                self._close()
                return
        except Exception:
            pass
        self.root.after(500, self._tick)

    def _report_geom(self) -> None:
        try:
            print(
                f"GEOM {self.root.winfo_x()} {self.root.winfo_y()} "
                f"{self.root.winfo_width()} {self.root.winfo_height()}",
                flush=True,
            )
        except Exception:
            pass

    def _write_lock(self) -> None:
        try:
            from .progress_reporter import progress_path

            lock = progress_path().parent / "bar.pid"
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text(str(_os.getpid()), encoding="utf-8")
        except Exception:
            pass

    def _release_lock(self) -> None:
        try:
            from .progress_reporter import progress_path

            lock = progress_path().parent / "bar.pid"
            if lock.exists():
                lock.unlink()
        except Exception:
            pass

    def run(self) -> None:
        self._write_lock()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(400, self._report_geom)
        self.root.mainloop()

    def _close(self) -> None:
        self._release_lock()
        self.root.destroy()


def main() -> None:
    try:
        ProgressWindow().run()
    except Exception as exc:  # headless / non-Windows fallback: console tail
        print(f"progress bar unavailable ({exc}); watching file…")
        import time as _t
        last = None
        while True:
            s = read_state()
            line = None
            if s:
                line = (f"{s.get('task')} {s.get('done')}/{s.get('total')} "
                        f"ok={s.get('success')} fail={s.get('failed')} {s.get('current')}")
            if line != last:
                print(line or "(idle)", flush=True)
                last = line
            _t.sleep(1)


if __name__ == "__main__":
    main()

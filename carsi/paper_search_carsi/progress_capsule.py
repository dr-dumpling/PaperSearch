"""The download progress capsule: a small always-on-top pill in a screen corner.

Collapsed it shows how far the task is ("12/40  正文 · Wiley"). Hovering opens
a card with the paper, the counts and every action of the classic window
(skip, no access, stop, problem report, settings, output folder). A step that
needs the user (school login, verification) opens the card by itself and
raises one system notification. The page is HTML (``assets/capsule.html``)
drawn by pywebview with the system web engine: WebKit on macOS, WebView2 on
Windows. Without pywebview or a usable engine the classic window
(``progress_bar``) opens instead.

Usage: ``paper-search-carsi progress`` (or ``python -m paper_search_carsi.progress_capsule``).
Spawned automatically by ``progress_reporter.ensure_progress_bar`` when a download starts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import download_directory, progress_view, user_settings
from .progress_reporter import progress_path, read_state

ASSETS = Path(__file__).with_name("assets")
PAGE = ASSETS / "capsule.html"
# PaperSearch's icon (assets/icon.svg) for the Dock and the Windows taskbar.
ICON, TASKBAR_ICON = ASSETS / "icon-512.png", ASSETS / "icon-64.png"
# The first, collapsed frame; the page then reports the size it needs.
START_SIZE = (260, 56)
MIN_SIZE = (60, 30)
EDGE = 20  # distance from the screen's right edge
# macOS: top-right under the menu bar (the Dock owns the bottom edge).
# Windows/Linux: bottom-right above the taskbar, clear of the browser's window buttons.
TOP_GAP, BOTTOM_GAP = 44, 56


def _corner() -> str:
    return "top" if sys.platform == "darwin" else "bottom"


class Placement:
    """Where the capsule sits: its right edge and its top (macOS) or bottom
    edge stay put while it grows and shrinks; dragging it moves them, and the
    spot is remembered for the next window."""

    def __init__(self, path: Path, corner: str) -> None:
        self.path = path
        self.corner = corner
        self.right: float | None = None
        self.edge: float | None = None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("corner") == corner:
                self.right, self.edge = float(data["right"]), float(data["edge"])
        except Exception:
            pass

    def start(self, screen_w: float, screen_h: float, size: tuple[int, int]) -> tuple[int, int]:
        """Top-left corner for the first frame; the default spot when none is
        remembered or the remembered one is off this screen."""
        w, h = size
        right, edge = self.right, self.edge
        if right is None or edge is None or not (w <= right <= screen_w + 1) or not (0 <= edge <= screen_h + 1):
            right = screen_w - EDGE
            edge = TOP_GAP if self.corner == "top" else screen_h - BOTTOM_GAP
        self.right, self.edge = right, edge
        return int(right - w), int(edge if self.corner == "top" else edge - h)

    def moved(self, x: float, y: float, w: float, h: float) -> None:
        self.right = x + w
        self.edge = y if self.corner == "top" else y + h
        try:
            self.path.write_text(json.dumps({"corner": self.corner, "right": self.right, "edge": self.edge}),
                                 encoding="utf-8")
        except Exception:
            pass


def notify(title: str, body: str) -> None:
    """One system notification; silently nothing where none is available."""
    try:
        if sys.platform == "darwin":
            script = f"display notification {json.dumps(body)} with title {json.dumps(title)}"
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        elif os.name == "nt":
            # Windows toast through PowerShell's registered app id; the texts go in by
            # environment so no quoting is needed.
            script = (
                "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;"
                "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                "$t=$x.GetElementsByTagName('text');"
                "$t.Item(0).AppendChild($x.CreateTextNode($env:PSC_TITLE))>$null;"
                "$t.Item(1).AppendChild($x.CreateTextNode($env:PSC_BODY))>$null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
                "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'"
                ").Show([Windows.UI.Notifications.ToastNotification]::new($x))"
            )
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           env={**os.environ, "PSC_TITLE": title, "PSC_BODY": body},
                           capture_output=True, timeout=10, creationflags=0x08000000)
    except Exception:
        pass


class Notifier:
    """A system notification when a step starts to need the user, once per prompt."""

    def __init__(self, send=notify) -> None:
        self._send = send
        self._seen: set[str] = set()

    def observe(self, state: dict[str, Any] | None) -> None:
        attention = state.get("attention") if state and state.get("status") == "running" else None
        prompts = {f"{key}@{value.get('since', '')}": value for key, value in attention.items()
                   if isinstance(value, dict)} if isinstance(attention, dict) else {}
        new = [prompts[key] for key in prompts if key not in self._seen]
        self._seen = set(prompts)
        if not new or not user_settings.notify_enabled():
            return
        message = str(new[-1].get("message") or "需要你在浏览器里处理")
        threading.Thread(target=self._send, args=("PaperSearch", message), daemon=True).start()


class Api:
    """What the page calls (``window.pywebview.api``). Every method returns
    plain values and never raises into the page."""

    def __init__(self, placement: Placement, notifier: Notifier, auto_close: progress_view.AutoClose) -> None:
        self._window: Any = None
        self._placement = placement
        self._notifier = notifier
        self._auto_close = auto_close
        self._size = START_SIZE
        self._hovering = False
        self._closed = False
        self._close_requested: float | None = None

    # --- what to show -----------------------------------------------------
    def platform(self) -> str:
        return sys.platform

    def state(self, hovering: bool = False) -> dict[str, Any]:
        """The capsule's view of the progress file; ``hovering`` keeps a finished window open."""
        self._hovering = bool(hovering)
        try:
            return progress_view.view(read_state(), time.time())
        except Exception:
            return {"mode": "idle"}

    # --- watching the task, also while the capsule is minimized ------------
    def watch(self) -> None:
        """Notifications and closing, off the page: the system slows a minimized
        page's timers down."""
        while not self._closed:
            try:
                snapshot = read_state()
            except Exception:
                snapshot = None
            self.watch_once(snapshot, time.monotonic())
            time.sleep(0.5)

    def watch_once(self, snapshot: dict[str, Any] | None, now: float) -> None:
        if self._close_requested is not None and now >= self._close_requested:
            self.close()
            return
        self._notifier.observe(snapshot)
        if self._auto_close.should_close(snapshot, now, hovering=self._hovering):
            self.close()

    def minimize(self) -> None:
        """Into the Dock / taskbar like a browser window; clicking it there brings it back."""
        try:
            self._window.minimize()
        except Exception:
            pass

    # --- the buttons ------------------------------------------------------
    def act(self, action: str, current: str, run_id: str = "") -> str:
        """Skip, no access (journal / publisher) or stop, for the running download."""
        try:
            from .entitlements import request_action

            request_action(str(current), str(action), str(run_id))
            return progress_view.ACTION_FEEDBACK[str(action)]
        except Exception as exc:
            return f"记录失败：{type(exc).__name__}"

    def issue_kinds(self) -> list[list[str]]:
        from .issues import ISSUE_KINDS

        return [[kind, label] for kind, label in ISSUE_KINDS.items()]

    def report(self, kind: str, current: str) -> str:
        """The problem the user saw in the browser; the running download acts on it at once."""
        try:
            from .issues import ISSUE_KINDS, report

            report(str(current), str(kind), read_state() or {})
            return f"已收到：{ISSUE_KINDS[kind]}，正在处理"
        except Exception as exc:
            return f"记录失败：{type(exc).__name__}"

    def open_folder(self) -> bool:
        return progress_view.open_folder(str((read_state() or {}).get("output_dir") or ""))

    # --- settings ---------------------------------------------------------
    def settings(self) -> dict[str, Any]:
        values = user_settings.current()
        return {
            "fields": [{"name": f.name, "label": f.label, "unit": f.unit, "value": values[f.name],
                        "default": f.default} for f in user_settings.FIELDS],
            "notify": user_settings.notify_enabled(),
            "download_dir": download_directory.current(),
        }

    def save_settings(self, values: dict[str, Any], notify_on: bool, download_dir: str | None = None) -> dict[str, Any]:
        """Check every field, then save them all; nothing is saved when one is wrong."""
        checked, errors = {}, {}
        for field in user_settings.FIELDS:
            value, problem = user_settings.check(field, str((values or {}).get(field.name, "")))
            if problem:
                errors[field.name] = problem
            else:
                checked[field.name] = value
        if download_dir is not None:
            try:
                download_dir = download_directory.validate(download_dir)
            except ValueError as exc:
                errors["download_dir"] = str(exc)
        if errors:
            return {"ok": False, "errors": errors}
        try:
            if download_dir is not None:
                download_directory.save(download_dir)
            user_settings.save(checked)
            user_settings.set_notify(bool(notify_on))
        except Exception as exc:
            return {"ok": False, "errors": {"": f"保存失败：{type(exc).__name__}"}}
        return {"ok": True}

    def choose_download_directory(self) -> str | None:
        """Native directory picker; cancelling leaves the field unchanged."""
        import webview

        selected = self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                                  directory=download_directory.current())
        return str(selected[0]) if selected else None

    # --- the window -------------------------------------------------------
    def resize(self, width: float, height: float) -> None:
        """The page's new size; the capsule's anchored corner stays put."""
        size = (max(MIN_SIZE[0], int(width)), max(MIN_SIZE[1], int(height)))
        if size == self._size or self._window is None:
            return
        self._size = size
        try:
            from webview.window import FixPoint

            vertical = FixPoint.NORTH if self._placement.corner == "top" else FixPoint.SOUTH
            self._window.resize(size[0], size[1], fix_point=vertical | FixPoint.EAST)
        except Exception:
            pass

    def moved(self, x: float, y: float) -> None:
        self._placement.moved(x, y, *self._size)

    def request_close(self) -> None:
        # Let the JS bridge deliver this call's reply before disposing WebView2.
        # The watcher stays alive independently of the page's stopped timers.
        self._close_requested = time.monotonic() + 0.2

    def close(self) -> None:
        self._closed = True
        progress_view.release_window_lock()
        try:
            if self._window is not None:
                self._window.destroy()
        except Exception:
            pass


def _enable_inactive_hover(window: Any) -> None:
    """WKWebView's normal tracking is key-window-only; track our own window always."""
    if sys.platform != "darwin":
        return
    import AppKit
    from PyObjCTools import AppHelper

    class CapsuleTrackingOwner(AppKit.NSObject):
        def mouseEntered_(self, event):
            self.send_(True)

        def mouseExited_(self, event):
            self.send_(False)

        def send_(self, inside):
            # evaluate_js waits for WebKit: never block Cocoa's event thread.
            def send():
                try:
                    window.evaluate_js("setHover(" + ("true" if inside else "false") + ")")
                except Exception:
                    pass  # The window can close while a tracking event is queued.
            threading.Thread(target=send, daemon=True).start()

    def install():
        native = window.native
        native.setAcceptsMouseMovedEvents_(True)
        owner = CapsuleTrackingOwner.alloc().init()
        view = native.contentView()
        options = (AppKit.NSTrackingMouseEnteredAndExited | AppKit.NSTrackingActiveAlways
                   | AppKit.NSTrackingInVisibleRect)
        area = AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            view.bounds(), options, owner, None)
        view.addTrackingArea_(area)
        window._capsule_tracking = (owner, area)  # Retain both while the window lives.
    AppHelper.callAfter(install)


def _windows_taskbar_icon(window: Any) -> None:
    """PaperSearch's icon on the window's taskbar button (WinForms through pythonnet)."""
    try:
        from System.Drawing import Bitmap, Icon

        window.native.Icon = Icon.FromHandle(Bitmap(str(TASKBAR_ICON)).GetHicon())
    except Exception:
        pass


def _round_windows_corners(window: Any) -> None:
    """Windows 11 rounds a frameless window only when asked (DWM corner preference)."""
    try:
        import ctypes

        from ctypes import wintypes

        hwnd = int(window.native.Handle.ToInt64())
        set_attribute = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
        set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        set_attribute.restype = ctypes.c_long
        value = ctypes.c_int(2)  # DWMWCP_ROUND
        set_attribute(hwnd, 33, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def _classic() -> None:
    from .progress_bar import main as classic_window

    classic_window()


def _prepare_nonactivating_start(window: Any) -> None:
    """Show the capsule without taking keyboard focus; clicks can still activate it.

    pywebview's focus=False also disables keyboard entry in Settings, so only
    suppress initial activation, not the window's ability to become active.
    """
    if sys.platform == "darwin":
        from webview.platforms import cocoa

        original = cocoa.BrowserView.first_show

        def first_show(view):
            if view.pywebview_window is not window:
                return original(view)
            if not view.hidden:
                view.window.orderFrontRegardless()
            view.shown.set()
            if not cocoa.BrowserView.app.isRunning():
                menu = view._recreate_menus(view.menu)
                cocoa.BrowserView.app.setMainMenu_(menu)
                cocoa.AppHelper.installMachInterrupt()
                cocoa.BrowserView.app.run()

        cocoa.BrowserView.first_show = first_show
    elif os.name == "nt":
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        get_style = user32.GetWindowLongPtrW
        set_style = user32.SetWindowLongPtrW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_style.restype = ctypes.c_ssize_t
        initial = []

        def before_show():
            hwnd = window.native.Handle.ToInt64()
            initial.append((hwnd, get_style(hwnd, -20)))
            set_style(hwnd, -20, initial[-1][1] | 0x08000000)  # WS_EX_NOACTIVATE

        def shown():
            if initial:
                hwnd, style = initial.pop()
                set_style(hwnd, -20, style)

        window.events.before_show += before_show
        window.events.shown += shown


def main() -> None:
    try:
        import webview
    except Exception:  # pywebview missing: the classic window
        _classic()
        return
    try:
        page = PAGE.read_text(encoding="utf-8")
        screen = webview.screens[0]
        placement = Placement(progress_path().parent / "capsule.json", _corner())
        x, y = placement.start(screen.width, screen.height, START_SIZE)
        api = Api(placement, Notifier(), progress_view.AutoClose.from_env())
        dark = progress_view.dark_mode()
        window = webview.create_window(
            "PaperSearch", html=page, js_api=api, width=START_SIZE[0], height=START_SIZE[1], x=x, y=y,
            min_size=MIN_SIZE, resizable=False, frameless=True, easy_drag=False, on_top=True, focus=True,
            transparent=sys.platform == "darwin", shadow=True,
            background_color="#202124" if dark else "#FFFFFF",
        )
        api._window = window
        _prepare_nonactivating_start(window)
        window.events.moved += api.moved
        window.events.loaded += lambda: _enable_inactive_hover(window)
        if os.name == "nt":
            window.events.shown += lambda: (_round_windows_corners(window), _windows_taskbar_icon(window))
        progress_view.write_window_lock()
        # icon: the Dock icon on macOS, instead of a blank one; watch: notifications and closing.
        webview.start(func=api.watch, icon=str(ICON) if sys.platform == "darwin" else None)
    except Exception:  # no usable web engine (e.g. WebView2 missing): the classic window
        progress_view.release_window_lock()
        _classic()
        return
    progress_view.release_window_lock()
    # The window is gone. pywebview answers each page call on a thread of its own,
    # and one still waiting for the closed page would hold the interpreter's
    # shutdown forever (the window froze on screen): leave without waiting.
    os._exit(0)


if __name__ == "__main__":
    main()

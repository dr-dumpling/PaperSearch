"""The download progress capsule: a small always-on-top floating pill.

Collapsed it shows how far the task is ("12/40  正文 · Wiley"). Hovering opens
a card with the paper, the counts and every action of the classic window
(skip, no access, stop, problem report, settings, output folder). A step that
needs the user (school login, verification) turns amber with a breathing glow
and raises one system notification. Clicking the reminder activates the task's
browser. The page is HTML (``assets/capsule.html``)
drawn by pywebview with the system web engine: WebKit on macOS, WebView2 on
Windows. Without pywebview or a usable engine the classic window
(``progress_bar``) opens instead.

Usage: ``paper-search-carsi progress`` (or ``python -m paper_search_carsi.progress_capsule``).
Spawned automatically by ``progress_reporter.ensure_progress_bar`` when a download starts.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import download_directory, progress_view, user_settings
from .capsule_placement import Placement, Rect, ScreenArea
from .progress_reporter import progress_path, read_state

ASSETS = Path(__file__).with_name("assets")
PAGE = ASSETS / "capsule.html"
# PaperSearch's icon (assets/icon.svg) for the Dock and the Windows taskbar.
ICON, TASKBAR_ICON = ASSETS / "icon-512.png", ASSETS / "icon-64.png"
# The first, collapsed frame; the page then reports the size it needs.
START_SIZE = (260, 56)
MIN_SIZE = (60, 30)


def _corner() -> str:
    return "top" if sys.platform == "darwin" else "bottom"


def notify(title: str, body: str, state: dict[str, Any] | None = None) -> None:
    """One system notification, bound to the current task on macOS."""
    if not user_settings.notify_enabled():
        return
    try:
        if sys.platform == "darwin":
            from .progress_macos import notify as native_notify

            native_notify(title, body, state or {})
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
                           capture_output=True, timeout=10, check=True, creationflags=0x08000000)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("progress notification failed: %s", type(exc).__name__)


class Notifier:
    """A system notification when a step starts to need the user, once per prompt."""

    def __init__(self, send=notify) -> None:
        self._send = send
        self._seen: set[str] = set()
        self._task: tuple[str, str] = ("", "")

    def observe(self, state: dict[str, Any] | None) -> None:
        if not user_settings.notify_enabled():
            self._seen.clear()
            if sys.platform == "darwin":
                from .progress_macos import close

                close()
            return
        task = (str((state or {}).get("run_id") or ""), str((state or {}).get("current") or ""))
        attention = state.get("attention") if state and state.get("status") == "running" else None
        prompts = {f"{key}@{value.get('since', '')}": value for key, value in attention.items()
                   if isinstance(value, dict)} if isinstance(attention, dict) else {}
        new = [prompts[key] for key in prompts if task != self._task or key not in self._seen]
        if self._seen and (not prompts or task != self._task) and sys.platform == "darwin":
            from .progress_macos import clear_notifications

            clear_notifications()
        self._seen = set(prompts)
        self._task = task
        if not new:
            return
        message = str(new[-1].get("message") or "需要你在浏览器里处理")
        threading.Thread(target=self._send, args=("PaperSearch", message, state), daemon=True).start()


class Api:
    """What the page calls (``window.pywebview.api``). Every method returns
    plain values and never raises into the page."""

    def __init__(self, placement: Placement, notifier: Notifier, auto_close: progress_view.AutoClose) -> None:
        self._window: Any = None
        self._placement = placement
        self._notifier = notifier
        self._auto_close = auto_close
        self._geometry_lock = threading.RLock()
        self._dragging = False
        self._native_geometry = False
        self._drag_origin: tuple[float, float, float, float] | None = None
        self._drag_pointer: tuple[float, float] | None = None
        self._hovering = False
        self._layout: tuple[int, bool, Rect, Rect] | None = None
        self._closed = False
        self._close_requested: float | None = None

    # --- what to show -----------------------------------------------------
    def platform(self) -> str:
        return sys.platform

    def state(self, hovering: bool = False) -> dict[str, Any]:
        """The capsule's view of the progress file; ``hovering`` keeps a finished window open."""
        self._hovering = bool(hovering) or self._dragging
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
    def activate_on_input(self) -> None:
        """The first real click restores normal Windows focus and keyboard input."""
        activate = getattr(self._window, "_capsule_activate_on_input", None)
        if callable(activate):
            activate()

    def act(self, action: str, current: str, run_id: str = "") -> str:
        """Control the running download, including showing its browser on request."""
        try:
            from .entitlements import SHOW_BROWSER, request_action

            if action == SHOW_BROWSER:
                # Asked for from a reminder, or from the paper on the card at any
                # time while it has a browser (user request, 2026-11-08).
                state = read_state() or {}
                if (state.get("status") != "running"
                        or str(state.get("current") or "") != current
                        or str(state.get("run_id") or "") != run_id):
                    return "当前没有正在下载的浏览器"
                if not state.get("attention") and state.get("channel"):
                    return "这一篇在查开放来源，没有打开浏览器"
                if sys.platform == "darwin":
                    from .browser.foreground import activate_mac

                    pid = state.get("browser_pid")
                    if not isinstance(pid, int) or pid <= 0 or not activate_mac(pid):
                        return "未能切到下载浏览器，请从程序坞打开"
                if os.name == "nt" and isinstance(state.get("owner_pid"), int) and state["owner_pid"] > 0:
                    # The click gives this foreground window permission to let
                    # the exact backend process activate its browser on Windows.
                    import ctypes

                    ctypes.windll.user32.AllowSetForegroundWindow(state["owner_pid"])

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

    def open_article(self, doi: str) -> str:
        """The article's page (doi.org) in the user's own browser, to fetch what the
        batch could not; only a DOI is opened, never another address."""
        doi = str(doi or "").strip()
        if not progress_view.DOI.fullmatch(doi):
            return "打开失败：不是有效的 DOI"
        import webbrowser
        from urllib.parse import quote

        try:
            opened = webbrowser.open("https://doi.org/" + quote(doi, safe="/:;()._-"))
        except Exception as exc:
            return f"打开失败：{type(exc).__name__}"
        return "已在浏览器打开这篇文章" if opened else "打开失败：没有找到默认浏览器"

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

    def set_notifications(self, enabled: bool) -> dict[str, Any]:
        """The notification switch saves immediately, independently of other fields."""
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "通知开关必须为开启或关闭"}
        try:
            user_settings.set_notify(enabled)
            self._notifier.observe(read_state())
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"保存失败：{type(exc).__name__}"}
        return {"ok": True, "notify": enabled}

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
    def _button_held(self) -> bool:
        if sys.platform == "darwin" and self._native_geometry:
            return _mac_button_held()
        if sys.platform == "win32":
            return _windows_button_held()
        return True

    def _drag_point(self, x: float, y: float) -> tuple[float, float]:
        if sys.platform == "darwin" and self._native_geometry:
            return _mac_pointer()
        if sys.platform == "win32":
            return _windows_pointer()
        return x, y

    def set_dragging(self, active: bool, screen_x: float | None = None,
                     screen_y: float | None = None) -> None:
        """Freeze resizing while held, then place the window on its drop screen."""
        with self._geometry_lock:
            if active:
                x, y, _, _ = _window_geometry(self._window, self._native_geometry)
                scale = _window_scale(self._window)
                point = self._drag_point(screen_x or 0, screen_y or 0)
                self._drag_origin = (*point, x * scale, y * scale)
                self._drag_pointer = point
                self._dragging = self._hovering = True
                self._placement.rescale(scale)
                self._layout = None
            elif self._dragging:
                try:
                    if screen_x is not None and screen_y is not None:
                        self.move_drag(screen_x, screen_y)
                finally:
                    self._dragging = False
                origin, point = self._drag_origin, self._drag_pointer
                self._drag_origin = None
                self._drag_pointer = None
                if self._window is None or origin is None or point is None or point == origin[:2]:
                    return
                actual = Rect(*_window_geometry(self._window, self._native_geometry))
                scale = _window_scale(self._window)
                self._placement.rescale(scale)
                target = self._placement.dragged(actual, _screen_areas(self._window),
                                                 (point[0] / scale, point[1] / scale))
                if target != actual:
                    _set_window_frame(self._window, target)

    def move_drag(self, screen_x: float, screen_y: float) -> None:
        """Use pointer deltas, independent of the web engine's screen origin."""
        with self._geometry_lock:
            if not self._dragging or self._drag_origin is None:
                return
            sx, sy, x, y = self._drag_origin
            if not self._button_held():
                # The page reports the release late, and the pointer may have
                # moved on since: the window stays where it was let go.
                return
            # WebView coordinates can rebase across monitors. Native pointer
            # deltas stay global; on Windows they are physical until the move.
            screen_x, screen_y = self._drag_point(screen_x, screen_y)
            if self._drag_pointer == (screen_x, screen_y):
                return
            self._drag_pointer = (screen_x, screen_y)
            x, y = round(x + screen_x - sx), round(y + screen_y - sy)
            if sys.platform == "darwin" and self._native_geometry:
                import AppKit

                def move():
                    top = AppKit.NSScreen.screens()[0].frame().size.height
                    self._window.native.setFrameTopLeftPoint_(AppKit.NSPoint(x, top - y))
                _cocoa_call(move)
            else:
                scale = _window_scale(self._window)
                self._window.move(round(x / scale), round(y / scale))

    def hover_state(self) -> dict[str, Any]:
        """Read the real pointer/frame together; native enter/exit events may be stale."""
        import AppKit

        def read():
            point = AppKit.NSEvent.mouseLocation()
            frame = self._window.native.frame()
            return {"x": point.x, "y": point.y,
                    "inside": frame.origin.x + 10 <= point.x < frame.origin.x + frame.size.width - 10
                    and frame.origin.y + 10 <= point.y < frame.origin.y + frame.size.height - 10}
        return _cocoa_call(read)

    def begin_layout(self, expanded: bool, width: float, height: float, generation: int) -> dict[str, Any]:
        """Choose a corner once per expansion and plan one atomic frame animation."""
        with self._geometry_lock:
            if self._dragging or self._window is None:
                return {}
            actual = Rect(*_window_geometry(self._window, self._native_geometry))
            self._placement.rescale(_window_scale(self._window))
            self._placement.begin(expanded, actual, _screen_areas(self._window))
            target = self._placement.target(max(MIN_SIZE[0], int(width)), max(MIN_SIZE[1], int(height)), expanded)
            self._layout = (generation, expanded, actual, target)
            vertical, horizontal = self._placement.direction
            return {"vertical": vertical, "horizontal": horizontal,
                    "width": target.width, "height": target.height,
                    "from_width": actual.width, "from_height": actual.height}

    def resize(self, width: float, height: float, fraction: float = 1, generation: int = 0) -> None:
        """Position and size change together; obsolete animation frames are ignored."""
        with self._geometry_lock:
            if self._dragging or self._window is None or self._layout is None:
                return
            current, _, start, target = self._layout
            if generation != current:
                return
            t = max(0, min(1, fraction))
            frame = Rect(round(start.x + (target.x - start.x) * t),
                         round(start.y + (target.y - start.y) * t),
                         round(start.width + (target.width - start.width) * t),
                         round(start.height + (target.height - start.height) * t))
            _set_window_frame(self._window, frame)

    def finish_layout(self, generation: int) -> None:
        with self._geometry_lock:
            if self._layout is None or self._layout[0] != generation or self._dragging:
                return
            _, expanded, _, target = self._layout
            self._placement.finish(expanded, target)
            self._layout = None

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
                    window.evaluate_js("observeHover()")
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


def _cocoa_call(action):
    """Wait for the one native geometry operation instead of queuing frames."""
    from PyObjCTools import AppHelper

    complete, cancelled = threading.Event(), threading.Event()
    result, errors = [], []

    def apply():
        try:
            if not cancelled.is_set():
                result.append(action())
        except Exception as exc:
            errors.append(exc)
        finally:
            complete.set()

    AppHelper.callAfter(apply)
    if not complete.wait(2):
        cancelled.set()
        raise TimeoutError("capsule native geometry did not complete")
    if errors:
        raise errors[0]
    return result[0]


def _window_geometry(window: Any, native: bool = False) -> tuple[float, float, float, float]:
    if sys.platform == "darwin" and native:
        import AppKit

        def read():
            frame = window.native.frame()
            top = AppKit.NSScreen.screens()[0].frame().size.height
            return frame.origin.x, top - frame.origin.y - frame.size.height, frame.size.width, frame.size.height
        return _cocoa_call(read)
    if sys.platform == "win32":
        n = window.native
        scale = _window_scale(window)
        return n.Location.X / scale, n.Location.Y / scale, n.Width / scale, n.Height / scale
    return window.x, window.y, window.width, window.height


def _mac_pointer() -> tuple[float, float]:
    import AppKit

    def read():
        point = AppKit.NSEvent.mouseLocation()
        top = AppKit.NSScreen.screens()[0].frame().size.height
        return point.x, top - point.y
    return _cocoa_call(read)


def _mac_button_held() -> bool:
    import AppKit

    return bool(_cocoa_call(lambda: AppKit.NSEvent.pressedMouseButtons() & 1))


def _windows_button_held() -> bool:
    import ctypes

    user32 = ctypes.windll.user32
    # The physical button state: the primary one is the right button when the
    # user swapped them (SM_SWAPBUTTON).
    button = 0x02 if user32.GetSystemMetrics(23) else 0x01
    return bool(user32.GetAsyncKeyState(button) & 0x8000)


def _windows_pointer() -> tuple[float, float]:
    import ctypes
    from ctypes import wintypes

    point = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        raise OSError("Cannot read capsule pointer position")
    return point.x, point.y


def _window_scale(window: Any = None) -> float:
    if sys.platform != "win32":
        return 1.0
    if window is not None:
        return float(window.native._scale)
    import ctypes

    return ctypes.windll.user32.GetDpiForSystem() / 96


def _screen_areas(window: Any = None) -> list[ScreenArea]:
    """Use native work areas in the same logical coordinate space as the window."""
    if sys.platform == "darwin":
        import AppKit

        def read():
            screens = AppKit.NSScreen.screens()
            top = screens[0].frame().origin.y + screens[0].frame().size.height

            def rect(frame):
                return Rect(frame.origin.x, top - frame.origin.y - frame.size.height,
                            frame.size.width, frame.size.height)

            return [ScreenArea(str(s.deviceDescription()["NSScreenNumber"]),
                               rect(s.frame()), rect(s.visibleFrame())) for s in screens]
        return _cocoa_call(read) if window is not None else read()
    if sys.platform == "win32":
        return _windows_screen_areas(window)
    import webview

    return [ScreenArea(str(i), Rect(s.x, s.y, s.width, s.height), Rect(s.x, s.y, s.width, s.height))
            for i, s in enumerate(webview.screens)]


def _windows_screen_areas(window: Any = None) -> list[ScreenArea]:
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    user = ctypes.windll.user32
    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user.GetMonitorInfoW.restype = wintypes.BOOL
    user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.MonitorFromWindow.restype = wintypes.HANDLE
    scale = _window_scale(window)
    if scale <= 0:
        raise RuntimeError("Invalid capsule monitor DPI")
    current = user.MonitorFromWindow(window.native.Handle.ToInt64(), 2) if window is not None else None
    areas = []
    failures = []

    def collect(handle, _dc, _rect, _data):
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if not user.GetMonitorInfoW(handle, ctypes.byref(info)):
            failures.append(handle)
            return False

        def rect(r):
            return Rect(r.left / scale, r.top / scale, (r.right - r.left) / scale,
                        (r.bottom - r.top) / scale)

        areas.append((handle == current if current is not None else bool(info.dwFlags & 1),
                      ScreenArea(info.szDevice, rect(info.rcMonitor), rect(info.rcWork))))
        return True

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), callback_type, wintypes.LPARAM]
    user.EnumDisplayMonitors.restype = wintypes.BOOL
    if not user.EnumDisplayMonitors(None, None, callback_type(collect), 0) or failures or not areas:
        raise OSError("Cannot read capsule monitor work areas")
    return [s for _, s in sorted(areas, key=lambda item: not item[0])]


def _cocoa_rect(frame: Rect) -> Any:
    """``frame`` (top-left coordinates from the primary screen's top) as a Cocoa rect."""
    import AppKit

    top = AppKit.NSScreen.screens()[0].frame().size.height
    return AppKit.NSMakeRect(frame.x, top - frame.y - frame.height, frame.width, frame.height)


def _moved_origin(ns_window: Any) -> tuple[float, float]:
    """pywebview's moved-event origin, also for a window not yet on any screen: it read
    that window's screen, found none, and the capsule remembered on a second display
    never opened (2026-11-07). The primary screen stands in."""
    import AppKit

    frame = ns_window.frame()
    screen = (ns_window.screen() or AppKit.NSScreen.screens()[0]).frame()
    return frame.origin.x, screen.size.height - frame.size.height - frame.origin.y


def _set_window_frame(window: Any, frame: Rect) -> None:
    """Move and resize in one native operation, without activating the window."""
    if sys.platform == "darwin":
        _cocoa_call(lambda: window.native.setFrame_display_(_cocoa_rect(frame), True))
    elif sys.platform == "win32":
        window._capsule_set_frame(frame)
    else:
        from webview.window import FixPoint

        window.resize(frame.width, frame.height, fix_point=FixPoint.NORTH | FixPoint.WEST)
        window.move(frame.x, frame.y)


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


def _classic(separate: bool = False) -> None:
    """The classic window. ``separate``: in a process of its own, where pywebview has
    already set up Cocoa in this one; Tk's own setup then crashed (2026-11-07)."""
    if separate:
        import subprocess

        subprocess.run([sys.executable, "-m", "paper_search_carsi.progress_bar"], check=False)
        return
    from .progress_bar import main as classic_window

    classic_window()


def _prepare_nonactivating_start(window: Any) -> None:
    """Show the capsule without taking keyboard focus; clicks can still activate it.

    pywebview's focus=False also disables keyboard entry in Settings, so only
    suppress initial activation, not the window's ability to become active.
    """
    if sys.platform == "darwin":
        from webview.platforms import cocoa

        import objc

        def acceptsFirstMouse_(self, event):
            # Accept the first grab instead of consuming it just for activation.
            return self.pywebview_window is window

        objc.classAddMethods(cocoa.BrowserView.WebKitHost, [acceptsFirstMouse_])

        def windowDidMove_(self, notification):
            i = cocoa.BrowserView.get_instance('window', notification.object())
            if i:
                i.pywebview_window.events.moved.set(*_moved_origin(i.window))

        objc.classAddMethods(cocoa.BrowserView.WindowDelegate, [windowDidMove_])
        original = cocoa.BrowserView.first_show

        def first_show(view):
            if view.pywebview_window is not window:
                return original(view)
            home = getattr(window, "_capsule_home", None)
            if home is not None:
                # The remembered place, from the primary screen's top like every
                # other capsule move: pywebview's own x/y count from the screen
                # with the active window, another display when one is in use.
                view.window.setFrame_display_(_cocoa_rect(home), False)
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
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        initial = []

        def before_show():
            from webview.window import FixPoint

            native = window.native
            hwnd = native.Handle.ToInt64()
            initial.append((hwnd, get_style(hwnd, -20)))
            set_style(hwnd, -20, initial[-1][1] | 0x08000000)  # WS_EX_NOACTIVATE
            # WinForms' geometry methods omit SWP_NOACTIVATE: even an animated
            # resize can steal focus after the nonactivating initial show.
            # Preserve their logical-pixel geometry, only for this capsule.
            def resize(width, height, fix_point):
                width, height = int(width * native._scale), int(height * native._scale)
                x, y = native.Location.X, native.Location.Y
                if fix_point & FixPoint.EAST:
                    x += native.Width - width
                if fix_point & FixPoint.SOUTH:
                    y += native.Height - height
                user32.SetWindowPos(hwnd, None, x, y, width, height, 0x0054)

            def move(x, y):
                user32.SetWindowPos(hwnd, None, int(x * native._scale), int(y * native._scale),
                                    0, 0, 0x0055)  # NOSIZE | NOZORDER | NOACTIVATE | SHOWWINDOW

            native.resize, native.move = resize, move

            def set_frame(frame):
                scale = native._scale
                # NOZORDER | NOACTIVATE; preserve hidden/minimized state as well.
                if not user32.SetWindowPos(hwnd, None, round(frame.x * scale), round(frame.y * scale),
                                          round(frame.width * scale), round(frame.height * scale), 0x0014):
                    raise OSError("Cannot update capsule window frame")

            window._capsule_set_frame = set_frame
            # pywebview's Shown handler calls WebView2.Focus() after raising
            # events.shown. That explicit focus defeats the initial native
            # style, even if we restore the style later. Suppress just this
            # first Focus call; later user-initiated restores keep normal input.
            original = native.on_shown

            def first_shown(*_):
                native.Shown -= first_shown
                native.Shown += original
                window.events.shown.set()

            native.Shown -= original
            native.Shown += first_shown

        def activate_on_input():
            if initial:
                hwnd, style = initial.pop()
                set_style(hwnd, -20, style)
                user32.SetForegroundWindow(hwnd)

        window.events.before_show += before_show
        # Keep the style through the native startup sequence. Restoring it on
        # shown allows Application.Run/WebView2 to focus the just-shown form.
        window._capsule_activate_on_input = activate_on_input


def main() -> None:
    try:
        import webview
    except Exception:  # pywebview missing: the classic window
        _classic()
        return
    try:
        page = PAGE.read_text(encoding="utf-8")
        screens = _screen_areas()
        placement = Placement(progress_path().parent / "capsule.json", _corner())
        x, y = placement.start(screens, START_SIZE, _window_scale())
        size = (round(placement.home.width), round(placement.home.height))
        api = Api(placement, Notifier(), progress_view.AutoClose.from_env())
        dark = progress_view.dark_mode()
        if sys.platform == "darwin":
            x = y = None  # placed at placement.home on its first show (_prepare_nonactivating_start)
        window = webview.create_window(
            "PaperSearch", html=page, js_api=api, width=size[0], height=size[1], x=x, y=y,
            min_size=MIN_SIZE, resizable=False, frameless=True, easy_drag=False, on_top=True, focus=True,
            transparent=sys.platform == "darwin", shadow=True,
            background_color="#202124" if dark else "#FFFFFF",
        )
        api._window = window
        window._capsule_home = placement.home if sys.platform == "darwin" else None
        if sys.platform == "darwin":
            from .progress_macos import install_notification_handler

            try:
                install_notification_handler(lambda current, run_id: api.act("show_browser", current, run_id))
            except (OSError, RuntimeError) as exc:
                import logging

                logging.getLogger(__name__).warning("notification host unavailable: %s", type(exc).__name__)
        api._native_geometry = sys.platform == "darwin"
        _prepare_nonactivating_start(window)
        # Do not persist native moved events: animated resizing emits them too.
        # Only the user's completed drag updates the collapsed home.
        window.events.loaded += lambda: _enable_inactive_hover(window)
        if os.name == "nt":
            def restore_after_dpi_setup():
                # pywebview enables DPI awareness while creating the native form.
                # Re-read work areas before showing it, in that form's actual scale.
                placement.start(_screen_areas(window), START_SIZE, _window_scale(window))
                _set_window_frame(window, placement.home)

            window.events.before_show += restore_after_dpi_setup
            window.events.shown += lambda: (_round_windows_corners(window), _windows_taskbar_icon(window))
        progress_view.write_window_lock()
        # icon: the Dock icon on macOS, instead of a blank one; watch: notifications and closing.
        webview.start(func=api.watch, icon=str(ICON) if sys.platform == "darwin" else None)
    except Exception:  # no usable web engine (e.g. WebView2 missing): the classic window
        if sys.platform == "darwin":
            from .progress_macos import close

            close()
        progress_view.release_window_lock()
        _classic(separate=sys.platform == "darwin")
        return
    progress_view.release_window_lock()
    if sys.platform == "darwin":
        from .progress_macos import close

        close()
    # The window is gone. pywebview answers each page call on a thread of its own,
    # and one still waiting for the closed page would hold the interpreter's
    # shutdown forever (the window froze on screen): leave without waiting.
    os._exit(0)


if __name__ == "__main__":
    main()

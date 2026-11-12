"""The capsule's native window on macOS and Windows, for ``progress_capsule``.

Where it is and on which screens (in one top-left, logical coordinate space on
both systems), moving and sizing it in one native step, the pointer and its
button while dragging (macOS follows the mouse itself, ``_MacDrag``), and the
first show that takes no focus. Cocoa calls run on the main thread
(``_cocoa_call``); nothing here knows the page or the download.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

from .capsule_placement import Rect, ScreenArea

# PaperSearch's icon for the Windows taskbar (assets/icon.svg).
TASKBAR_ICON = Path(__file__).with_name("assets") / "icon-64.png"


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


class _MacDrag:
    """The capsule follows the mouse by itself while it is dragged (macOS).

    A local event monitor sees each press in the window from its mouse-down.
    Once the page says the press is a drag, the window moves on the main
    thread with each drag event, keeping the point grabbed under the mouse,
    and stops where the button came up. Moved from the page over the bridge,
    the window fell behind a busy Mac, and the moves still queued at the
    release were dropped (they had made it jump after the release, 2026-11-08):
    it stopped short of where it was let go (the user's recording, 2026-11-10).
    The page's drag start comes over the same bridge, late as well, possibly
    after the release: measured from the press itself, the window catches up.
    """

    def __init__(self, window: Any) -> None:
        self._window = window
        self._monitor: Any = None
        self._press: tuple[float, float, float, float] | None = None  # pointer x, y; window x, y (top-left, global)
        self._held = self._started = self._following = False
        self._ended: tuple[float, float] | None = None
        self.last: tuple[float, float] | None = None

    def install_soon(self) -> None:
        from PyObjCTools import AppHelper

        AppHelper.callAfter(self.install)

    def install(self) -> None:
        """Watch the window's presses (main thread); without this, drags follow the page."""
        import AppKit

        if self._monitor is not None:
            return

        def handle(event: Any) -> Any:
            try:
                self._event(event)
            except Exception as exc:
                import logging

                logging.getLogger(__name__).warning("capsule drag event: %s", exc)
            return event  # the page still gets its pointer events

        try:
            self._monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                AppKit.NSEventMaskLeftMouseDown | AppKit.NSEventMaskLeftMouseDragged
                | AppKit.NSEventMaskLeftMouseUp, handle)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("capsule drag follows the page: %s", exc)

    def _event(self, event: Any) -> None:
        import AppKit
        import Quartz

        kind = event.type()
        if kind == AppKit.NSEventTypeLeftMouseDown and event.windowNumber() != self._window.native.windowNumber():
            return  # a dialog's press
        # Global and from the top: events queued on a busy Mac are relative to
        # where the window was when they came, not where it has moved since.
        location = Quartz.CGEventGetLocation(event.CGEvent())
        point = (location.x, location.y)
        if kind == AppKit.NSEventTypeLeftMouseDown:
            if self._following:  # the page has not ended the last drag yet
                self._ended, self._following = self.last, False
            frame = self._window.native.frame()
            top = AppKit.NSScreen.screens()[0].frame().size.height
            self._press = (*point, frame.origin.x, top - frame.origin.y - frame.size.height)
            self.last, self._held, self._started = point, True, False
            return
        if not self._held:
            return  # the mouse moves on after the release: the window stays
        self.last = point
        self._held = kind != AppKit.NSEventTypeLeftMouseUp
        if self._following:
            self._move()

    def _move(self) -> None:
        import AppKit

        sx, sy, x, y = self._press
        top = AppKit.NSScreen.screens()[0].frame().size.height
        self._window.native.setFrameTopLeftPoint_(
            AppKit.NSPoint(round(x + self.last[0] - sx), top - round(y + self.last[1] - sy)))

    def start(self) -> tuple[float, float, float, float] | None:
        """The page's drag start (main thread): its press, the window caught up; None without one."""
        if self._press is None or self._started:
            return None
        self._started = self._following = True
        self._ended = None
        if self.last != self._press[:2]:
            self._move()
        return self._press

    def stop(self) -> tuple[float, float] | None:
        """The page's drag end (main thread): where the drag ended."""
        self._following = False
        point, self._ended = self._ended or self.last, None
        return point


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

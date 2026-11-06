"""An explicit capsule click brings its download browser to the foreground.

No browser is launched here. Native activation is limited to the connected
ego profile's owner or descendants of this page's Playwright driver.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import threading
from concurrent.futures import Future
from typing import Any

def _process_parents() -> dict[int, int]:
    if os.name != "nt":
        result = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True,
                                check=True, timeout=2)
        return {int(parts[0]): int(parts[1]) for line in result.stdout.splitlines()
                if len(parts := line.split()) == 2}
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("exe", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        fn = getattr(kernel, name)
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        fn.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ProcessEntry(size=ctypes.sizeof(ProcessEntry))
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        parents = {}
        while more and len(parents) < 65536:
            parents[int(entry.pid)] = int(entry.parent)
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return parents
    finally:
        kernel.CloseHandle(snapshot)


def _browser_pids(page: Any, config: dict) -> list[int]:
    from .backend import BACKEND_EGO, ego_user_data_dir, resolve_backend
    from .profiles import _profile_owner_pid

    if resolve_backend(config) == BACKEND_EGO:
        pid = _profile_owner_pid(str(ego_user_data_dir(config)))
        return [pid] if pid else []
    # Playwright has no public browser PID. Its pipe transport is the driver
    # that launched this exact browser, including a persistent context.
    driver = page.context._impl_obj._connection._transport._proc.pid
    if not isinstance(driver, int) or isinstance(driver, bool) or driver <= 1:
        raise RuntimeError("the download browser driver has no valid owner PID")
    parents = _process_parents()
    frontier, found = {int(driver)}, []
    while frontier:
        children = {pid for pid, parent in parents.items() if parent in frontier and pid not in found}
        found.extend(sorted(children))
        frontier = children
    return found


def _activate_windows(pids: list[int], title: str = "") -> bool:
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found = []

    @callback_type
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user.IsWindowVisible(hwnd) and not user.GetWindow(hwnd, 4):
            found.append(hwnd)
        return True

    user.EnumWindows(visit, 0)
    if not found:
        return False
    matches = []
    for hwnd in found:
        text = ctypes.create_unicode_buffer(1024)
        user.GetWindowTextW(hwnd, text, len(text))
        if title and text.value.casefold().startswith(title.casefold()):
            matches.append(hwnd)
    active = user.GetForegroundWindow()
    candidates = matches or found
    hwnd = active if active in candidates else candidates[0]
    if user.IsIconic(hwnd):
        user.ShowWindow(hwnd, 9)  # SW_RESTORE, only this browser's minimized window
    return bool(user.SetForegroundWindow(hwnd))


def mac_browser_pid(page: Any, config: dict) -> int:
    """The owned browser application, never one of its nonactivatable helpers."""
    import AppKit

    for pid in _browser_pids(page, config):
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if (app is not None and app.bundleURL() is not None
                and app.activationPolicy() == AppKit.NSApplicationActivationPolicyRegular):
            return pid
    return 0


def activate_mac(pid: int) -> bool:
    """Called by the clicked capsule, whose Cocoa loop owns the activation handoff.

    macOS 14+ requires cooperative activation. The CLI's worker has no Cocoa
    main loop and must not dispatch UI work to its own main thread.
    """
    import AppKit

    def activate() -> bool:
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None or app.activationPolicy() != AppKit.NSApplicationActivationPolicyRegular:
            return False
        current = AppKit.NSRunningApplication.currentApplication()
        native = AppKit.NSApplication.sharedApplication()
        app.unhide()
        if hasattr(native, "yieldActivationToApplication_"):
            native.yieldActivationToApplication_(app)
            activated = bool(app.activateFromApplication_options_(current, AppKit.NSApplicationActivateAllWindows))
        else:
            activated = bool(app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps
                                                     | AppKit.NSApplicationActivateAllWindows))
        # Activation alone leaves miniaturized Firefox windows in the Dock.
        # The same reopen event as a Dock click restores them. Address the
        # existing PID, so a stale request can never launch another browser.
        return activated and _reopen_mac(pid)

    if threading.current_thread() is threading.main_thread():
        return activate()
    from PyObjCTools import AppHelper

    answer: Future[bool] = Future()

    def on_main():
        if not answer.set_running_or_notify_cancel():
            return
        try:
            answer.set_result(activate())
        except Exception as exc:
            answer.set_exception(exc)

    AppHelper.callAfter(on_main)
    try:
        return answer.result(timeout=2)
    except TimeoutError as exc:
        answer.cancel()
        raise TimeoutError("browser activation did not reach the capsule's native thread") from exc


def _reopen_mac(pid: int) -> bool:
    import Foundation

    descriptor = Foundation.NSAppleEventDescriptor
    event = descriptor.appleEventWithEventClass_eventID_targetDescriptor_returnID_transactionID_(
        int.from_bytes(b"aevt", "big"), int.from_bytes(b"rapp", "big"),
        descriptor.descriptorWithProcessIdentifier_(pid), -1, 0)
    _, error = event.sendEventWithOptions_timeout_error_(
        Foundation.NSAppleEventSendWaitForReply | Foundation.NSAppleEventSendNeverInteract, 2, None)
    if error is not None:
        raise RuntimeError("the owned browser did not accept its reopen event")
    return True


def show(page: Any, config: dict) -> None:
    page.bring_to_front()  # select this task's tab; macOS activation is done by the capsule
    if os.name != "nt":
        return
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    try:
        title = page.locator('head > title').first.text_content(timeout=1000) or ""
    except PlaywrightTimeoutError:
        title = ""  # a title is optional; native activation still selects the task browser
    if _activate_windows(_browser_pids(page, config), title.strip()):
        return
    raise RuntimeError("the download browser window could not be activated")

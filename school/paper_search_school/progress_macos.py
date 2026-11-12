"""A bundled native notification host; clicks use the capsule's current-task action.

No compiler, third-party notifier, system setting changes or global input hooks
are needed on the user's Mac. Notification permission remains managed by macOS.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
from pathlib import Path
import plistlib
import struct
import subprocess
import threading
import zlib
from typing import Any, Callable

logger = logging.getLogger(__name__)
BUNDLE_ID = "com.papersearch.progress"
_bridge: NotificationBridge | None = None
_callback: Callable[[str, str], Any] | None = None
_bridge_lock = threading.RLock()


LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
              "LaunchServices.framework/Support/lsregister")


def _write_if_changed(path: Path, content: bytes, mode: int = 0o644) -> bool:
    """Write ``content`` unless the file already holds it; True when written."""
    if path.is_file() and path.read_bytes() == content:
        return False
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    temporary.chmod(mode)
    temporary.replace(path)
    return True


def _register(app: Path) -> None:
    """Have Launch Services read the bundle again, its icon included; best effort."""
    try:
        os.utime(app)
        subprocess.run([LSREGISTER, "-f", str(app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def prepare_app(app_root: Path | None = None) -> Path:
    """Give Notification Center a real executable, stable app identity and icon."""
    assets = Path(__file__).with_name("assets")
    # One identity and bundle for all profiles and upgrades, so users only have
    # one PaperSearch notification preference. Task isolation belongs in messages.
    app_root = app_root or Path.home() / "Library" / "Application Support" / "PaperSearch"
    app = app_root.resolve() / "PaperSearch.app"
    macos, resources = app / "Contents/MacOS", app / "Contents/Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    chunks = []
    for size, kind in ((32, b"icp5"), (64, b"icp6"), (512, b"ic09")):
        image = (assets / f"icon-{size}.png").read_bytes()
        chunks.append(kind + struct.pack(">I", len(image) + 8) + image)
    body = b"".join(chunks)
    icns = b"icns" + struct.pack(">I", len(body) + 8) + body
    # macOS keeps a bundle's icon from its cache while the bundle seems unchanged:
    # notifications still showed the old icon after the new one was written into
    # the bundle (2026-11-08). The version follows the icon, and a changed bundle
    # is registered again.
    changed = _write_if_changed(app / "Contents/Info.plist", plistlib.dumps({
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": "PaperSearch", "CFBundleDisplayName": "PaperSearch",
        "CFBundleExecutable": "PaperSearch", "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0", "CFBundleVersion": str(zlib.crc32(icns)),
        "CFBundleIconFile": "PaperSearch.icns", "LSUIElement": True,
    }))
    changed = _write_if_changed(resources / "PaperSearch.icns", icns) or changed
    executable = macos / "PaperSearch"
    _write_if_changed(executable, (assets / "papersearch-notifier").read_bytes(), 0o755)
    if changed:
        _register(app)
    return executable


class NotificationBridge:
    def __init__(self, executable: Path, callback: Callable[[str, str], Any]) -> None:
        self.callback = callback
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self.process = subprocess.Popen(
            [str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
        )
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        if not self._ready.wait(5):
            self.close()
            raise RuntimeError("PaperSearch's notification host did not start")

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            while line := self.process.stdout.readline(65536):
                if not line.endswith("\n"):
                    raise ValueError("oversized notification event")
                event = json.loads(line)
                if not isinstance(event, dict):
                    continue
                if event.get("event") == "ready":
                    self._ready.set()
                elif event.get("event") == "clicked":
                    current, run_id = event.get("current"), event.get("run_id")
                    if isinstance(current, str) and isinstance(run_id, str) and current and run_id:
                        try:
                            self.callback(current, run_id)
                        except Exception as exc:
                            logger.warning("notification click failed: %s", type(exc).__name__)
        except (OSError, ValueError) as exc:
            logger.warning("notification host event failed: %s", type(exc).__name__)
        finally:
            self.process.stdout.close()

    def send(self, action: str, **values: Any) -> None:
        payload = json.dumps({"action": action, **values}, ensure_ascii=False) + "\n"
        if len(payload.encode("utf-8")) >= 65536:
            raise ValueError("notification is too long")
        with self._lock:
            if self.process.poll() is not None or self.process.stdin is None or self.process.stdin.closed:
                raise RuntimeError("PaperSearch's notification host has exited")
            self.process.stdin.write(payload)
            self.process.stdin.flush()

    def close(self) -> None:
        with self._lock:
            if self.process.stdin is not None and not self.process.stdin.closed:
                self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)


def install_notification_handler(callback: Callable[[str, str], Any]) -> None:
    """Register clicks without installing or starting the optional native host."""
    global _callback
    with _bridge_lock:
        close()
        _callback = callback


def _host() -> NotificationBridge:
    """The running native host, started on first use (called under _bridge_lock)."""
    global _bridge
    if _bridge is None:
        if _callback is None:
            raise RuntimeError("PaperSearch's notification click handler is unavailable")
        _bridge = NotificationBridge(prepare_app(), _callback)
    return _bridge


def notify(title: str, body: str, state: dict[str, Any]) -> None:
    from .user_settings import notify_enabled

    with _bridge_lock:
        # A queued notification must also respect a switch turned off meanwhile.
        if not notify_enabled():
            return
        _host().send("notify", title=title, body=body, current=str(state.get("current") or ""),
                     run_id=str(state.get("run_id") or ""))


# System Settings keeps each app's notification settings in com.apple.ncprefs ("apps", one
# entry per app that has shown notifications): bit 25 of "flags" is "Allow notifications",
# bits 3-5 the alert style (0 none, 1 banners, 2 alerts). Undocumented, read as System
# Settings writes it (macOS 15, 2026-11-10). The host cannot ask instead: for its notifications
# UNUserNotificationCenter answers "not determined" while PaperSearch is allowed.
ALLOWED_FLAG = 1 << 25


def notifications_allowed() -> str:
    """"ok", "off" (not allowed, or nothing shown on screen), or "unknown"."""
    try:
        exported = subprocess.run(["defaults", "export", "com.apple.ncprefs", "-"], capture_output=True,
                                  timeout=5, check=True).stdout
        apps = plistlib.loads(exported).get("apps", [])
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, ValueError, AttributeError) as exc:
        logger.warning("notification settings unreadable: %s", type(exc).__name__)
        return "unknown"
    entry = next((app for app in apps if isinstance(app, dict) and app.get("bundle-id") == BUNDLE_ID), None)
    if entry is None:
        return "ok"  # never shown yet: the first notification lists PaperSearch in the settings
    flags = entry.get("flags")
    if not isinstance(flags, int):
        return "unknown"
    return "ok" if flags & ALLOWED_FLAG and (flags >> 3) & 7 else "off"


def send_test(title: str, body: str) -> None:
    """A notification for the settings' test: no task behind it, so a click does nothing."""
    with _bridge_lock:
        _host().send("notify", title=title, body=body, current="", run_id="")


def open_settings() -> None:
    """System Settings at PaperSearch's notifications (macOS 13+), else the Notifications pane."""
    import platform

    major = int((platform.mac_ver()[0] or "0").split(".")[0] or 0)
    url = (f"x-apple.systempreferences:com.apple.Notifications-Settings.extension?id={BUNDLE_ID}" if major >= 13
           else "x-apple.systempreferences:com.apple.preference.notifications")
    subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def clear_notifications() -> None:
    with _bridge_lock:
        if _bridge is not None:
            try:
                _bridge.send("clear")
            except (OSError, RuntimeError) as exc:
                logger.warning("notification clear failed: %s", type(exc).__name__)


def close() -> None:
    global _bridge
    with _bridge_lock:
        bridge, _bridge = _bridge, None
        if bridge is not None:
            bridge.close()


atexit.register(close)

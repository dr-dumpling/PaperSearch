"""Notification identity, lifecycle and task-scoped click transport (no desktop UI)."""
import io
import json
import os
from pathlib import Path
import plistlib
import struct
from unittest.mock import Mock, patch

import pytest

from paper_search_carsi import progress_macos as mac


@pytest.fixture(autouse=True)
def registered(monkeypatch):
    """Unit tests never register a bundle with Launch Services."""
    calls = Mock()
    monkeypatch.setattr(mac, "_register", calls)
    return calls


def test_a_new_icon_changes_the_version_and_registers_the_bundle_again(tmp_path, registered, monkeypatch):
    """Notifications kept the old icon although the new one was in the bundle (2026-11-08)."""
    executable = mac.prepare_app(tmp_path)
    bundle = executable.parent.parent.parent
    version = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())["CFBundleVersion"]
    registered.assert_called_once_with(bundle)
    registered.reset_mock()
    mac.prepare_app(tmp_path)
    registered.assert_not_called()  # nothing changed: no new registration
    assets = tmp_path / "assets"
    assets.mkdir()
    for name in ("icon-32.png", "icon-64.png", "papersearch-notifier"):
        (assets / name).write_bytes((Path(mac.__file__).with_name("assets") / name).read_bytes())
    (assets / "icon-512.png").write_bytes(b"\x89PNG another icon")
    monkeypatch.setattr(mac, "__file__", str(assets.parent / "progress_macos.py"))
    mac.prepare_app(tmp_path)
    assert plistlib.loads((bundle / "Contents/Info.plist").read_bytes())["CFBundleVersion"] != version
    registered.assert_called_once_with(bundle)


def test_app_contains_native_host_and_icon_with_one_stable_application_identity(tmp_path):
    executable = mac.prepare_app(tmp_path / "profile with spaces")
    bundle = executable.parent.parent
    info = plistlib.loads((bundle / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == executable.name
    assert info["CFBundleDisplayName"] == "PaperSearch"
    assert info["LSUIElement"] is True
    assert os.access(executable, os.X_OK)
    assert not executable.is_symlink()
    data = executable.read_bytes()
    # Universal Mach-O: both supported Macs get a native executable, not Python.
    assert data[:4] == b"\xca\xfe\xba\xbe"
    assert struct.unpack(">I", data[4:8])[0] == 2
    assert {struct.unpack_from(">I", data, 8 + i * 20)[0] for i in range(2)} == {0x1000007, 0x100000c}
    icon = (bundle / "Resources/PaperSearch.icns").read_bytes()
    assert icon[:4] == b"icns" and struct.unpack(">I", icon[4:8])[0] == len(icon)
    assert b"ic09" in icon  # the high-resolution PaperSearch icon
    mtime = executable.stat().st_mtime_ns
    assert mac.prepare_app(tmp_path / "profile with spaces") == executable
    assert executable.stat().st_mtime_ns == mtime
    other = mac.prepare_app(tmp_path / "other")
    other_info = plistlib.loads((other.parent.parent / "Info.plist").read_bytes())
    assert other_info["CFBundleIdentifier"] == info["CFBundleIdentifier"] == mac.BUNDLE_ID


def test_default_bundle_is_independent_of_download_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('CARSI_DATA_DIR', str(tmp_path / 'profile-one'))
    first = mac.prepare_app()
    monkeypatch.setenv('CARSI_DATA_DIR', str(tmp_path / 'profile-two'))
    assert mac.prepare_app() == first
    assert first == tmp_path / 'Library/Application Support/PaperSearch/PaperSearch.app/Contents/MacOS/PaperSearch'


def fake_host(events):
    process = Mock()
    process.stdin = io.StringIO()
    process.stdout = io.StringIO("".join(json.dumps(event) + "\n" for event in events))
    process.poll.return_value = None
    return process


def test_only_valid_clicks_reach_the_current_task_callback():
    process = fake_host([
        {"event": "ready"}, {"event": "delivered", "current": "doi", "run_id": "run"},
        {"event": "clicked", "current": "doi", "run_id": "run"},
        {"event": "clicked", "current": "doi", "run_id": ""},
        {"event": "clicked", "current": ["doi"], "run_id": "run"},
    ])
    callback = Mock()
    with patch.object(mac.subprocess, "Popen", return_value=process):
        bridge = mac.NotificationBridge(Path("/fixture/PaperSearch"), callback)
    bridge._reader.join(timeout=1)
    callback.assert_called_once_with("doi", "run")
    bridge.send("notify", title="PaperSearch", body="请登录学校", current="doi", run_id="run")
    assert json.loads(process.stdin.getvalue())["body"] == "请登录学校"
    bridge.close()
    assert process.stdin.closed
    process.terminate.assert_not_called()


def test_long_notification_and_exited_helper_are_explicit_failures():
    process = fake_host([{"event": "ready"}])
    with patch.object(mac.subprocess, "Popen", return_value=process):
        bridge = mac.NotificationBridge(Path("/fixture/PaperSearch"), Mock())
    with pytest.raises(ValueError, match="too long"):
        bridge.send("notify", body="文" * 65536)
    process.poll.return_value = 1
    with pytest.raises(RuntimeError, match="exited"):
        bridge.send("clear")
    bridge.close()


def test_notification_preserves_task_identity_and_clear_is_scoped_to_helper():
    bridge = Mock()
    with patch.object(mac, "_bridge", bridge), \
            patch('paper_search_carsi.user_settings.notify_enabled', return_value=True):
        mac.notify("PaperSearch", "请登录学校", {"current": "doi", "run_id": "run"})
        mac.clear_notifications()
    assert bridge.send.call_args_list[0].kwargs == {
        "title": "PaperSearch", "body": "请登录学校", "current": "doi", "run_id": "run"}
    assert bridge.send.call_args_list[1].args == ("clear",)


def test_disabled_notifications_never_prepare_or_start_the_native_host():
    callback = Mock()
    with patch.object(mac, '_bridge', None), patch.object(mac, '_callback', None), \
            patch.object(mac, 'prepare_app') as prepare, patch.object(mac, 'NotificationBridge') as bridge, \
            patch('paper_search_carsi.user_settings.notify_enabled', return_value=False):
        mac.install_notification_handler(callback)
        mac.notify('PaperSearch', '请登录学校', {'current':'doi','run_id':'run'})
        prepare.assert_not_called()
        bridge.assert_not_called()


def test_enabling_lazily_starts_one_host_and_disabling_reclaims_it():
    callback = Mock()
    with patch.object(mac, '_bridge', None), patch.object(mac, '_callback', None), \
            patch.object(mac, 'prepare_app', return_value=Path('/fixture/PaperSearch')) as prepare, \
            patch.object(mac, 'NotificationBridge') as factory, \
            patch('paper_search_carsi.user_settings.notify_enabled', return_value=True) as enabled:
        mac.install_notification_handler(callback)
        prepare.assert_not_called()
        mac.notify('PaperSearch', '请登录学校', {'current':'doi','run_id':'run'})
        mac.notify('PaperSearch', '请完成验证', {'current':'doi','run_id':'run'})
        factory.assert_called_once_with(Path('/fixture/PaperSearch'), callback)
        enabled.return_value = False
        mac.close()
        factory.return_value.close.assert_called_once()
        mac.notify('PaperSearch', 'queued', {'current':'doi','run_id':'run'})
        assert factory.call_count == 1


def ncprefs(*apps):
    return Mock(stdout=plistlib.dumps({"apps": list(apps)}))


@pytest.mark.parametrize("apps, state", [
    # Allow notifications (bit 25) with banners or alerts, as System Settings writes them (macOS 15).
    ([{"bundle-id": mac.BUNDLE_ID, "flags": 41951246}], "ok"),
    ([{"bundle-id": mac.BUNDLE_ID, "flags": 0x2000010}], "ok"),
    ([{"bundle-id": mac.BUNDLE_ID, "flags": 41951246 & ~(1 << 25)}], "off"),  # Allow notifications off
    ([{"bundle-id": mac.BUNDLE_ID, "flags": 0x2000006}], "off"),  # allowed, alert style none
    ([{"bundle-id": "com.google.Chrome", "flags": 0}], "ok"),  # never shown yet
    ([{"bundle-id": mac.BUNDLE_ID, "flags": "x"}], "unknown"),
])
def test_what_the_system_settings_say_about_papersearchs_notifications(apps, state):
    # The settings' check of system notifications (user, 2026-11-10).
    with patch.object(mac.subprocess, "run", return_value=ncprefs(*apps)) as read:
        assert mac.notifications_allowed() == state
    assert read.call_args.args[0] == ["defaults", "export", "com.apple.ncprefs", "-"]


def test_unreadable_notification_settings_are_unknown():
    for failure in (OSError("defaults"), mac.subprocess.CalledProcessError(1, "defaults")):
        with patch.object(mac.subprocess, "run", side_effect=failure):
            assert mac.notifications_allowed() == "unknown"
    with patch.object(mac.subprocess, "run", return_value=Mock(stdout=b"not a plist")):
        assert mac.notifications_allowed() == "unknown"


def test_a_test_notification_has_no_task_and_the_settings_open_at_papersearch():
    host = Mock()
    with patch.object(mac, "_host", return_value=host):
        mac.send_test("PaperSearch", "测试通知")
    host.send.assert_called_once_with("notify", title="PaperSearch", body="测试通知", current="", run_id="")
    for version, url in (("14.5", f"x-apple.systempreferences:com.apple.Notifications-Settings.extension?id={mac.BUNDLE_ID}"),
                         ("12.7.1", "x-apple.systempreferences:com.apple.preference.notifications")):
        with patch("platform.mac_ver", return_value=(version, ("", "", ""), "arm64")), \
                patch.object(mac.subprocess, "Popen") as opened:
            mac.open_settings()
        assert opened.call_args.args[0] == ["open", url]

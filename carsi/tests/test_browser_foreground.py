"""A click may activate only a browser owned by this page's driver/profile."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from paper_search_carsi.browser import foreground


class ExplicitBrowserFocusTests(unittest.TestCase):
    def test_show_selects_the_requested_pages_title_in_the_owned_browser(self):
        page = Mock()
        page.locator.return_value.first.text_content.return_value = 'Login test'
        with patch.object(foreground, 'os', SimpleNamespace(name='nt')), \
                patch.object(foreground, '_browser_pids', return_value=[10, 11]), \
                patch.object(foreground, '_activate_windows', return_value=True) as activate:
            foreground.show(page, {})
        activate.assert_called_once_with([10, 11], 'Login test')


def test_process_selection_does_not_include_daily_browsers_or_the_driver():
    page = SimpleNamespace(context=SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(
        _transport=SimpleNamespace(_proc=SimpleNamespace(pid=100))))))
    with patch.object(foreground, '_process_parents', return_value={
            100: 1, 101: 100, 102: 101, 500: 1, 501: 500}):
        assert foreground._browser_pids(page, {'browser_backend': 'camoufox'}) == [101, 102]


def test_invalid_driver_pid_never_inspects_unrelated_processes():
    import pytest

    for pid in (None, 0, 1, True, '100', Mock()):
        page = SimpleNamespace(context=SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(
            _transport=SimpleNamespace(_proc=SimpleNamespace(pid=pid))))))
        with patch.object(foreground, '_process_parents') as parents:
            with pytest.raises(RuntimeError, match='no valid owner PID'):
                foreground._browser_pids(page, {'browser_backend': 'camoufox'})
            parents.assert_not_called()


def test_mac_selects_only_the_owned_regular_app():
    app = Mock()
    app.bundleURL.return_value = '/owned/browser.app'
    app.activationPolicy.return_value = 0
    appkit = SimpleNamespace(NSRunningApplication=Mock(), NSApplicationActivationPolicyRegular=0)
    appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.return_value = app
    with patch.object(foreground, '_browser_pids', return_value=[101]), \
            patch.dict('sys.modules', AppKit=appkit):
        assert foreground.mac_browser_pid(Mock(), {}) == 101
    appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.assert_called_once_with(101)


def test_capsule_hands_activation_to_the_exact_browser_process():
    app = Mock()
    app.activationPolicy.return_value = 0
    app.activateFromApplication_options_.return_value = True
    native, current = Mock(), Mock()
    appkit = SimpleNamespace(NSRunningApplication=Mock(), NSApplication=Mock(),
                             NSApplicationActivationPolicyRegular=0, NSApplicationActivateAllWindows=1)
    appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.return_value = app
    appkit.NSRunningApplication.currentApplication.return_value = current
    appkit.NSApplication.sharedApplication.return_value = native
    with patch.dict('sys.modules', AppKit=appkit), \
            patch.object(foreground, '_reopen_mac', return_value=True) as reopen:
        assert foreground.activate_mac(101)
    app.unhide.assert_called_once()
    reopen.assert_called_once_with(101)
    native.yieldActivationToApplication_.assert_called_once_with(app)
    app.activateFromApplication_options_.assert_called_once_with(current, 1)
    appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.assert_called_once_with(101)


def test_closed_browser_is_not_reopened():
    appkit = SimpleNamespace(NSRunningApplication=Mock())
    appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.return_value = None
    with patch.dict('sys.modules', AppKit=appkit):
        assert not foreground.activate_mac(101)


def test_native_errors_reach_the_click_handler_from_the_capsule_thread():
    import pytest
    app = Mock()
    app.activationPolicy.return_value = 0
    app.activateFromApplication_options_.side_effect = RuntimeError('activation failed')
    appkit = SimpleNamespace(NSRunningApplication=Mock(), NSApplication=Mock(),
                             NSApplicationActivationPolicyRegular=0, NSApplicationActivateAllWindows=1)
    appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.return_value = app
    helper = SimpleNamespace(AppHelper=SimpleNamespace(callAfter=lambda callback: callback()))
    with patch.dict('sys.modules', AppKit=appkit, PyObjCTools=helper), \
            patch.object(foreground.threading, 'current_thread', return_value=object()):
        with pytest.raises(RuntimeError, match='activation failed'):
            foreground.activate_mac(101)


def test_older_mac_versions_restore_the_owned_browser_windows():
    app = Mock()
    app.activationPolicy.return_value = 0
    appkit = SimpleNamespace(NSRunningApplication=Mock(), NSApplication=Mock(),
                             NSApplicationActivationPolicyRegular=0,
                             NSApplicationActivateIgnoringOtherApps=2, NSApplicationActivateAllWindows=1)
    appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.return_value = app
    appkit.NSApplication.sharedApplication.return_value = SimpleNamespace()
    with patch.dict('sys.modules', AppKit=appkit), \
            patch.object(foreground, '_reopen_mac', return_value=True) as reopen:
        assert foreground.activate_mac(101)
    app.unhide.assert_called_once()
    reopen.assert_called_once_with(101)
    app.activateWithOptions_.assert_called_once_with(3)

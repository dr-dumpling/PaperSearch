"""Owned browser activation and its startup handshake; no desktop input in unit tests."""
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from paper_search_carsi.browser import background, backend


def test_readiness_rejects_stale_launch_and_reports_current_failure(tmp_path, monkeypatch):
    path = tmp_path / 'papersearch-background.json'
    path.write_text(json.dumps({'ready': True, 'session': 'old'}))
    monkeypatch.setattr(background.time, 'sleep', lambda _: path.write_text(json.dumps({'ready': False, 'session': 'new'})))
    with pytest.raises(RuntimeError, match='initialization failed'):
        background.ready(tmp_path, 'new')


def test_readiness_failure_closes_owned_context_before_any_site(tmp_path, monkeypatch):
    context = Mock()
    monkeypatch.setattr(backend, 'wait_for_profile_release', lambda *a: True)
    monkeypatch.setattr(backend, '_launch_camoufox_persistent', lambda *a, **k: context)
    monkeypatch.setattr(background, 'ready', Mock(side_effect=RuntimeError('not ready')))
    with pytest.raises(RuntimeError, match='not ready'):
        backend.launch_persistent_context(str(tmp_path), headless=False)
    context.close.assert_called_once()
    context.new_page.assert_not_called()


def test_headless_launch_does_not_load_privileged_helper():
    opts = backend._camoufox_options(True, None, None, False, {})
    assert str(background.ADDON_DIR) not in opts.get('addons', [])
    assert not opts['firefox_user_prefs'].get('extensions.experiments.enabled')
    assert opts['firefox_user_prefs']['papersearch.background.enabled'] is False
    assert opts['firefox_user_prefs']['papersearch.background.bootstrap'] is False


@pytest.mark.parametrize('platform,headless', [('nt', False), ('posix', False), ('posix', True)])
def test_troubleshoot_mode_guard_only_reaches_the_owned_headed_child(tmp_path, monkeypatch, platform, headless):
    camoufox = pytest.importorskip('camoufox')
    sync_api = pytest.importorskip('playwright.sync_api')
    parent = {'PATH': 'inherited'}
    explicit = {'PATH': 'provided'}
    monkeypatch.setattr(backend, 'os', SimpleNamespace(name=platform, environ=parent))
    monkeypatch.setattr(background, 'install_startup_helper', Mock())
    monkeypatch.setattr(sync_api, 'sync_playwright', Mock())
    browser = Mock(return_value=Mock())
    monkeypatch.setattr(camoufox, 'NewBrowser', browser)

    backend._launch_camoufox_persistent(str(tmp_path), headless, None, None, False, env=explicit)

    env = browser.call_args.kwargs['env']
    assert env['PATH'] == 'provided'
    for key in ('MOZ_DISABLE_AUTO_SAFE_MODE', 'MOZ_DISABLE_SAFE_MODE_KEY'):
        assert env.get(key) == (None if headless else '1')
        assert key not in parent and key not in explicit


def test_helper_has_no_site_permissions_or_content_scripts():
    manifest = json.loads((background.ADDON_DIR / 'manifest.json').read_text())
    assert not manifest.get('permissions')
    assert not manifest.get('content_scripts')
    assert not manifest.get('web_accessible_resources')


def test_startup_helper_refreshes_only_its_owned_profile_addon(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'manifest.json').write_text(json.dumps({'version': '1.0'}))
    script = source / 'api.js'
    script.write_text('initial helper')
    monkeypatch.setattr(background, 'ADDON_DIR', source)
    profile = tmp_path / 'owned-profile'
    other = profile / 'extensions' / 'other.xpi'
    other.parent.mkdir(parents=True)
    other.write_bytes(b'existing extension')

    background.install_startup_helper(profile)
    installed = other.with_name(background.ADDON_ID + '.xpi')
    initial = installed.read_bytes()
    stamp = installed.stat().st_mtime_ns
    background.install_startup_helper(profile)
    assert installed.stat().st_mtime_ns == stamp
    script.write_text('updated helper')
    background.install_startup_helper(profile)
    assert installed.read_bytes() != initial
    with zipfile.ZipFile(installed) as archive:
        assert archive.read('api.js') == b'updated helper'
    assert other.read_bytes() == b'existing extension'

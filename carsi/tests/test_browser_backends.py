"""Two browser backends: Camoufox (Playwright) by default, ego-lite on request."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import paper_search_carsi.browser.backend as bb
from paper_search_carsi.browser import engine as browser_engine


class TestResolveBackend:
    def test_default_is_camoufox(self):
        assert bb.resolve_backend({}) == bb.BACKEND_CAMOUFOX
        assert bb.resolve_backend(None) == bb.BACKEND_CAMOUFOX

    @pytest.mark.parametrize("retired", ["patchright", "cloakbrowser", "CloakBrowser"])
    def test_retired_values_map_to_camoufox(self, retired):
        assert bb.resolve_backend({"browser_backend": retired}) == bb.BACKEND_CAMOUFOX

    def test_unknown_value_resets_to_default(self):
        assert bb.resolve_backend({"browser_backend": "nonsense"}) == bb.DEFAULT_BACKEND

    def test_ego_is_kept_when_installed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bb, "ego_user_data_dir", lambda config=None: tmp_path)
        assert bb.resolve_backend({"browser_backend": "ego"}) == bb.BACKEND_EGO
        assert bb.uses_playwright({"browser_backend": "ego"}) is True

    def test_ego_not_installed_falls_back_to_camoufox(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bb, "ego_user_data_dir", lambda config=None: tmp_path / "missing")
        assert bb.resolve_backend({"browser_backend": "ego"}) == bb.BACKEND_CAMOUFOX

    def test_missing_camoufox_is_not_swapped_for_ego(self, monkeypatch):
        monkeypatch.setattr(bb, "is_available", lambda name=None: name == bb.BACKEND_EGO)
        assert bb.resolve_backend({"browser_backend": "camoufox"}) == bb.BACKEND_CAMOUFOX


class TestPlaywrightGate:
    def test_engine_serves_both_backends(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bb, "is_available", lambda name=None: True)
        monkeypatch.setattr(bb, "ego_user_data_dir", lambda config=None: tmp_path)
        assert browser_engine._check_browser_backend({"browser_backend": "camoufox"}) is True
        assert browser_engine._check_browser_backend({"browser_backend": "ego"}) is True

    def test_missing_camoufox_reports_unavailable(self, monkeypatch):
        monkeypatch.setattr(bb, "is_available", lambda name=None: False)
        assert browser_engine._check_browser_backend({}) is False


class TestEgo:
    def test_endpoint_comes_from_devtools_active_port(self, tmp_path):
        cfg = {"ego_user_data_dir": str(tmp_path)}
        assert bb.ego_endpoint(cfg) is None
        (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/abc-123\n")
        assert bb.ego_endpoint(cfg) == "ws://127.0.0.1:9222/devtools/browser/abc-123"
        (tmp_path / "DevToolsActivePort").write_text("garbage")
        assert bb.ego_endpoint(cfg) is None

    def test_remote_debugging_off_explains_how_to_turn_it_on(self, tmp_path, monkeypatch):
        cfg = {"browser_backend": "ego", "ego_user_data_dir": str(tmp_path)}
        monkeypatch.setattr(bb, "ego_running", lambda config=None: True)
        with pytest.raises(bb.EgoUnavailable, match="chrome://inspect/#remote-debugging"):
            bb.launch_persistent_context(str(tmp_path / "p"), config=cfg)

    def test_ego_without_a_window_gets_one_and_is_reconnected(self, tmp_path, monkeypatch):
        calls = []
        class Chromium:
            def connect_over_cdp(self, endpoint, timeout):
                calls.append(endpoint)
                if len(calls) == 1:
                    raise RuntimeError("Protocol error (Browser.setDownloadBehavior): Browser context management is not supported.")
                return "browser"
        class PW:
            chromium = Chromium()
            def stop(self): calls.append("stop")
        import playwright.sync_api as sync_api
        monkeypatch.setattr(sync_api, "sync_playwright", lambda: type("S", (), {"start": lambda self: PW()})())
        monkeypatch.setattr(bb, "ego_running", lambda config=None: True)
        monkeypatch.setattr(bb, "ego_endpoint", lambda config=None: "ws://127.0.0.1:9222/devtools/browser/x")
        monkeypatch.setattr(bb, "_relay_endpoint", lambda upstream: upstream)
        reopened = []
        monkeypatch.setattr(bb, "_reopen_ego_window", lambda config: reopened.append(1) or True)
        pw, browser = bb._connect_ego({})
        assert browser == "browser" and reopened == [1] and len(calls) == 2

    def test_closed_ego_is_started_and_waited_for(self, tmp_path, monkeypatch):
        cfg = {"ego_user_data_dir": str(tmp_path), "ego_app": str(tmp_path)}
        started = []
        def popen(command, **kwargs):
            started.append(command)
            (tmp_path / "DevToolsActivePort").write_text("9333\n/devtools/browser/fresh\n")
        monkeypatch.setattr("subprocess.Popen", popen)
        monkeypatch.setattr(bb.time, "sleep", lambda s: None)
        assert bb._start_ego(cfg) is True
        assert str(tmp_path) in started[0]
        assert bb.ego_endpoint(cfg) == "ws://127.0.0.1:9333/devtools/browser/fresh"

    def test_ego_not_running_and_not_startable_is_reported(self, tmp_path, monkeypatch):
        cfg = {"browser_backend": "ego", "ego_user_data_dir": str(tmp_path), "ego_app": str(tmp_path / "none")}
        (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/stale\n")  # left by a closed ego
        monkeypatch.setattr(bb, "ego_running", lambda config=None: False)
        with pytest.raises(bb.EgoUnavailable, match="not running"):
            bb.launch_persistent_context(str(tmp_path / "p"), config=cfg)

    def test_context_shows_and_closes_only_own_tabs_and_their_popups(self):
        class Page:
            def __init__(self, opener=None):
                self._opener, self.closed = opener, False
            def opener(self):
                return self._opener
            def is_closed(self):
                return self.closed
            def close(self):
                self.closed = True

        class Context:
            def __init__(self):
                self._pages, self.handlers = [Page(), Page()], {}  # the user's own tabs
            @property
            def pages(self):
                return list(self._pages)
            def on(self, event, handler):
                self.handlers.setdefault(event, []).append(handler)
            def new_page(self):
                page = Page(); self._pages.append(page); return page
            def emit_page(self, page):
                self._pages.append(page)
                for handler in self.handlers.get("page", []):
                    handler(page)

        context = Context()
        user_tabs = context.pages
        owned = bb._scope_to_own_tabs(context)
        seen = []
        context.on("page", seen.append)
        mine = context.new_page()
        popup, stranger = Page(opener=mine), Page(opener=user_tabs[0])
        context.emit_page(popup)
        context.emit_page(stranger)
        assert context.pages == [mine, popup]
        assert seen == [popup]
        assert owned == {mine, popup}
        assert isinstance(context, Context)  # still the same object for page.context


class TestCamoufoxLaunch:
    def test_persistent_profile_is_a_separate_firefox_directory(self, monkeypatch, tmp_path):
        chromium_profile = tmp_path / "publisher_profile_wiley"
        calls = {}
        monkeypatch.setattr(bb, "wait_for_profile_release", lambda d, *a, **k: calls.setdefault("wait", d))
        monkeypatch.setattr(bb, "_launch_camoufox_persistent",
                            lambda d, **kw: calls.setdefault("launch", (d, kw)) and "ctx")
        assert bb.launch_persistent_context(str(chromium_profile), config={}) == "ctx"
        expected = str(tmp_path / "publisher_profile_wiley-camoufox")
        assert calls["wait"] == expected
        assert calls["launch"][0] == expected
        assert Path(expected).is_dir()
        assert bb.camoufox_profile_dir(expected) == Path(expected)  # not suffixed twice

    def test_configured_proxy_is_passed_explicitly(self, monkeypatch, tmp_path):
        seen = {}
        monkeypatch.setattr(bb, "wait_for_profile_release", lambda *a, **k: True)
        monkeypatch.setattr(bb, "_launch_camoufox_persistent", lambda d, **kw: seen.update(kw) or "ctx")
        bb.launch_persistent_context(str(tmp_path / "p"), config={"network_proxy": "http://127.0.0.1:7890"})
        assert seen["proxy"] == {"server": "http://127.0.0.1:7890"}

    def test_launch_drops_chromium_args_and_matches_host_os(self, monkeypatch):
        pytest.importorskip("playwright")
        pytest.importorskip("camoufox")
        captured: dict = {}

        class _FakeBrowser:
            def close(self):
                captured["closed"] = True

        class _PW:
            def stop(self):
                captured["stopped"] = True

        monkeypatch.setattr("playwright.sync_api.sync_playwright",
                            lambda: type("SP", (), {"start": staticmethod(lambda: _PW())})())
        monkeypatch.setattr("camoufox.NewBrowser", lambda pw, **kw: captured.update(kw) or _FakeBrowser())
        browser = bb._launch_camoufox(headless=True, proxy=None,
                                      args=["--disable-blink-features=AutomationControlled"], humanize=False)
        assert captured.get("args") in (None, [])
        assert captured["os"] == bb._host_os()
        browser.close()
        assert captured["closed"] and captured["stopped"]


def test_firefox_profile_lock_names_its_owner(tmp_path):
    os.symlink("192.168.1.2:+4242", tmp_path / "lock")
    assert bb._profile_owner_pid(str(tmp_path)) == 4242


def test_session_cookies_survive_the_next_launch(tmp_path):
    class Ctx:
        def __init__(self, cookies):
            self._cookies, self.added = cookies, []

        def cookies(self):
            return self._cookies

        def add_cookies(self, cookies):
            self.added.extend(cookies)

    session = {"name": "CASTGC", "value": "v", "domain": "cas.example.edu.cn", "path": "/", "expires": -1}
    persistent = {"name": "pref", "value": "1", "domain": "x.org", "path": "/", "expires": 9999999999}
    bb._save_session_cookies(Ctx([session, persistent]), tmp_path)
    saved = tmp_path / bb.SESSION_COOKIES_FILE
    assert oct(saved.stat().st_mode & 0o777) == "0o600"
    nxt = Ctx([])
    assert bb._restore_session_cookies(nxt, tmp_path) == 1
    assert nxt.added[0]["name"] == "CASTGC" and "expires" not in nxt.added[0]
    data = __import__("json").loads(saved.read_text())
    data["saved_at"] -= bb.SESSION_COOKIES_MAX_AGE_SEC + 1
    saved.write_text(__import__("json").dumps(data))
    assert bb._restore_session_cookies(Ctx([]), tmp_path) == 0


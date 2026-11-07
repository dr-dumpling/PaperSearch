"""The chrome backend: the installed Google Chrome, driven by Patchright, public switches only."""
import re
import sys
import types
from pathlib import Path

import pytest

from paper_search_carsi.browser import backend, driver


@pytest.fixture
def chrome(tmp_path, monkeypatch):
    executable = tmp_path / "Google Chrome"
    executable.write_text("")
    monkeypatch.setattr(backend, "find_chrome", lambda config=None: executable)
    monkeypatch.setattr(backend, "patchright_version", lambda: "1.64.4")
    return executable


def test_installed_chrome_is_selected_and_keeps_its_window(chrome):
    config = {"browser_backend": "chrome"}
    assert backend.resolve_backend(config) == backend.BACKEND_CHROME
    assert backend.supports("batch_window", config)


def test_chrome_is_the_default_and_without_a_browser_the_launch_says_how_to_get_one(chrome, monkeypatch):
    assert backend.DEFAULT_BACKEND == backend.BACKEND_CHROME
    assert backend.is_available()
    monkeypatch.setattr(backend, "find_chrome", lambda config=None: None)
    assert backend.resolve_backend({}) == backend.BACKEND_CHROME and not backend.is_available()
    with pytest.raises(RuntimeError, match="https://www.google.com/chrome/"):
        backend._chrome_options(True, None, [], {})


def test_a_configured_executable_is_used_only_when_it_exists(tmp_path):
    executable = tmp_path / "chrome"
    executable.write_text("")
    assert backend.find_chrome({"chrome_executable": str(executable)}) == executable
    assert backend.find_chrome({"chrome_executable": str(tmp_path / "missing")}) is None
    from paper_search_carsi.config import DEFAULT_CONFIG

    # A known key: `config set chrome_executable` does not warn; Chrome is the default.
    assert DEFAULT_CONFIG["chrome_executable"] == "" and DEFAULT_CONFIG["browser_backend"] == "chrome"


def test_launch_options_are_public_chrome_switches(chrome):
    options = backend._chrome_options(False, {"server": "http://proxy.test:1"},
                                      ["--disable-features=CrossOriginOpenerPolicy",
                                       "--proxy-server=http://proxy.test:1"], {})
    assert options == {"executable_path": str(chrome), "headless": False,
                       "args": ["--disable-features=CrossOriginOpenerPolicy", "--test-type"], "chromium_sandbox": True,
                       "proxy": {"server": "http://proxy.test:1"}, "no_viewport": True}


def test_new_tabs_open_in_the_background():
    sent, opened = [], []

    class Created:
        value = "background tab"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Context:
        browser = type("Browser", (), {"new_browser_cdp_session": lambda self: type(
            "Session", (), {"send": lambda self, method, params: sent.append((method, params))})()})()

        def new_page(self, *args, **kwargs):
            opened.append((args, kwargs))
            return "driver tab"

        def expect_page(self):
            return Created()

    context = Context()
    backend._open_tabs_in_background(context)
    assert context.new_page() == "background tab"
    assert sent == [("Target.createTarget", {"url": "about:blank", "background": True})]
    assert context.new_page(viewport=None) == "driver tab" and opened == [((), {"viewport": None})]


def test_the_persistent_context_is_launched_by_patchright(chrome, tmp_path, monkeypatch):
    launched = {}

    class Context:
        browser = types.SimpleNamespace(version="156.0")

        def close(self):
            launched["closed"] = True

    class Chromium:
        def launch_persistent_context(self, profile, **options):
            launched.update(profile=profile, **options)
            return Context()

    class Driver:
        chromium = Chromium()

        def stop(self):
            launched["stopped"] = True

    module = types.ModuleType("patchright.sync_api")
    module.sync_playwright = lambda: types.SimpleNamespace(start=lambda: Driver())
    monkeypatch.setitem(sys.modules, "patchright.sync_api", module)
    context = backend._launch_chrome_persistent(tmp_path / "profile-chrome", False, None, [], {})
    assert launched["profile"] == str(tmp_path / "profile-chrome")
    assert launched["executable_path"] == str(chrome) and launched["no_viewport"] is True
    assert backend.browser_info() == {"backend": "chrome", "app": "Google Chrome", "version": "156.0",
                                      "driver": "patchright 1.64.4"}
    context.close()
    assert launched["closed"] and launched["stopped"]


def test_persistent_context_uses_its_own_profile_and_keeps_session_cookies(chrome, tmp_path, monkeypatch):
    calls, saved = {}, []

    class Context:
        browser = None
        pages: list = []

        def close(self):
            calls["closed"] = True

        def new_page(self):
            return object()

    def launch(profile, headless, proxy, args, config):
        calls.update(profile=profile, headless=headless)
        return Context()

    monkeypatch.setattr(backend, "_launch_chrome_persistent", launch)
    monkeypatch.setattr(backend, "wait_for_profile_release", lambda path: True)
    monkeypatch.setattr(backend, "_restore_session_cookies", lambda context, profile: 0)
    monkeypatch.setattr(backend, "_save_session_cookies", lambda context, profile: saved.append(profile))
    monkeypatch.setattr(backend, "_open_tabs_in_background", lambda context: calls.update(background=True))
    context = backend.launch_persistent_context(str(tmp_path / "profile"), headless=False,
                                                config={"browser_backend": "chrome"})
    assert calls == {"profile": tmp_path / "profile-chrome", "headless": False, "background": True}
    context.close()
    assert calls["closed"] and saved == [tmp_path / "profile-chrome"]


def test_one_driver_package_its_errors_and_the_page_world():
    import patchright.sync_api as patchright
    from patchright._impl import _sync_base

    assert driver.Error is patchright.Error and driver.TimeoutError is patchright.TimeoutError
    assert driver.sync_bases() == [_sync_base.SyncBase]
    assert driver.main_world() == {"isolated_context": False}
    assert driver.is_driver_error(patchright.TimeoutError("t"), "TimeoutError")
    assert driver.is_driver_error(patchright.Error("e")) and not driver.is_driver_error(patchright.Error("e"), "TimeoutError")
    assert not driver.is_driver_error(RuntimeError("program bug"))


def test_the_package_imports_neither_playwright_nor_camoufox():
    root = Path(backend.__file__).resolve().parents[1]
    imports = re.compile(r"^\s*(?:from|import)\s+(?:playwright|camoufox)\b", re.M)
    assert [str(p.relative_to(root)) for p in root.rglob("*.py") if imports.search(p.read_text(encoding="utf-8"))] == []

"""The attach backend: the user's own Chrome over its remote debugging port."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from paper_search_school.browser import backend


def test_a_bare_host_and_port_becomes_a_cdp_endpoint():
    assert backend.attach_endpoint({"browser_attach_url": "127.0.0.1:9222"}) == "http://127.0.0.1:9222"
    assert backend.attach_endpoint({"browser_attach_url": "http://127.0.0.1:9222"}) == "http://127.0.0.1:9222"
    assert backend.attach_endpoint({}) == ""


def test_attach_is_available_only_with_an_address(monkeypatch):
    monkeypatch.setattr(backend, "patchright_version", lambda: "1.64.4")
    assert backend.is_available("attach", {}) is False
    assert backend.is_available("attach", {"browser_attach_url": "http://127.0.0.1:9222"}) is True
    monkeypatch.setattr(backend, "patchright_version", lambda: "")
    assert backend.is_available("attach", {"browser_attach_url": "http://127.0.0.1:9222"}) is False


def test_asking_for_attach_without_an_address_falls_back_to_chrome():
    assert backend.resolve_backend({"browser_backend": "attach"}) == backend.BACKEND_CHROME
    assert backend.resolve_backend(
        {"browser_backend": "attach", "browser_attach_url": "http://127.0.0.1:9222"}) == backend.BACKEND_ATTACH


def test_attach_declares_no_batch_window():
    config = {"browser_backend": "attach", "browser_attach_url": "http://127.0.0.1:9222"}
    assert backend.supports("batch_window", config) is False
    assert backend.uses_playwright(config) is True


def test_connecting_uses_the_configured_endpoint(monkeypatch):
    browser = SimpleNamespace(version="157.0.0.0")
    connection = Mock(return_value=browser)
    driver = SimpleNamespace()
    driver.chromium = SimpleNamespace(connect_over_cdp=connection)
    driver.stop = Mock()
    monkeypatch.setattr("patchright.sync_api.sync_playwright",
                        lambda: SimpleNamespace(start=lambda: driver))
    _, connected = backend._connect_attach({"browser_attach_url": "127.0.0.1:9222"})
    assert connected is browser
    assert connection.call_args.args[0] == "http://127.0.0.1:9222"
    assert backend._launched["backend"] == backend.BACKEND_ATTACH


def test_an_unreachable_chrome_raises_with_the_address(monkeypatch):
    driver = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=Mock(side_effect=RuntimeError("refused"))),
                             stop=Mock())
    monkeypatch.setattr("patchright.sync_api.sync_playwright",
                        lambda: SimpleNamespace(start=lambda: driver))
    with pytest.raises(backend.AttachUnavailable) as raised:
        backend._connect_attach({"browser_attach_url": "http://127.0.0.1:9222"})
    assert "127.0.0.1:9222" in str(raised.value)
    driver.stop.assert_called_once()


def test_the_attached_context_is_the_users_own_and_closes_only_our_tabs(monkeypatch):
    context = Mock()
    context.pages = []
    page = Mock()
    page.is_closed.return_value = False
    context.new_page.return_value = page
    browser = Mock()
    browser.contexts = [context]
    browser.version = "157.0.0.0"
    driver = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=Mock(return_value=browser)), stop=Mock())
    monkeypatch.setattr("patchright.sync_api.sync_playwright",
                        lambda: SimpleNamespace(start=lambda: driver))
    owned: set = set()
    monkeypatch.setattr(backend, "_scope_to_own_tabs", lambda ctx: owned)

    launched = backend._launch_attach({"browser_attach_url": "http://127.0.0.1:9222"})
    assert launched is browser
    assert browser.new_context() is context  # never a second, empty profile
    owned.add(page)
    browser.close()
    page.close.assert_called_once()
    driver.stop.assert_called_once()  # the connection goes, the browser stays

"""Callers ask the browser backend for a capability, never for its name."""
import inspect

from paper_search_school.browser import backend
from paper_search_school.engine import bridge


def test_every_backend_declares_its_capabilities():
    assert set(backend.SUPPORTED_BACKENDS) <= set(backend.BACKEND_CAPABILITIES)


def test_batch_window_follows_the_declaration(monkeypatch):
    monkeypatch.setattr(backend, "resolve_backend", lambda config=None: backend.BACKEND_CHROME)
    assert backend.supports("batch_window")
    monkeypatch.setattr(backend, "resolve_backend", lambda config=None: backend.BACKEND_EGO)
    assert not backend.supports("batch_window")
    monkeypatch.setitem(backend.BACKEND_CAPABILITIES, backend.BACKEND_EGO, frozenset({"batch_window"}))
    assert backend.supports("batch_window")


def test_batch_reuse_does_not_name_a_backend():
    source = inspect.getsource(bridge._try_browser_batch_download)
    assert "BACKEND_CHROME" not in source and "BACKEND_EGO" not in source

"""A real slow HTTP redirect must not look like a page needing a user click."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from paper_search_carsi import progress_reporter
from paper_search_carsi.browser.backend import launch
from paper_search_carsi.engine.page_activity import PageActivity

pytestmark = pytest.mark.skipif(os.environ.get("CARSI_LOCAL_BROWSER_TEST") != "1",
                                reason="local Camoufox fixture opt-in")


def test_slow_redirect_and_idle_document_do_not_invent_a_user_action(tmp_path, monkeypatch, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="paper_search_carsi.engine.page_activity")
    after = int(os.environ.get("CARSI_TEST_STALL_AFTER", "1"))
    delay = after + (3 if after >= 30 else 1)
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/slow":
                stop.wait(delay)
                self.send_response(302)
                self.send_header("Location", "/ready")
                self.end_headers()
            else:
                body = b"<title>Ready</title><body>Waiting for an action</body>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    monkeypatch.setenv("CARSI_DATA_DIR", str(tmp_path))
    progress_reporter.start_task("local navigation fixture", total=1)
    notices = []
    real_attention = progress_reporter.set_attention
    started = time.monotonic()

    def record(*args, **kwargs):
        notices.append(time.monotonic() - started)
        real_attention(*args, **kwargs)

    monkeypatch.setattr(progress_reporter, "set_attention", record)
    browser = activity = watcher = None
    failures = []
    try:
        browser = launch(headless=True, humanize=False, config={"browser_backend": "camoufox"})
        context = browser.new_context()
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(
            f"http://127.0.0.1:{server.server_port}/") else route.abort())
        page = context.new_page()
        activity = PageActivity("10.1234/fixture", {"browser_stall_notify_after": after,
                               "browser_page_wait_timeout": max(10, after * 2)})
        activity.observe(page)

        def observe():
            try:
                while not stop.wait(0.05):
                    activity.check()
            except Exception as exc:
                failures.append(type(exc).__name__)

        watcher = threading.Thread(target=observe, daemon=True)
        started = time.monotonic()
        watcher.start()
        page.goto(f"http://127.0.0.1:{server.server_port}/slow", wait_until="domcontentloaded",
                  timeout=(delay + 10) * 1000)
        loaded = time.monotonic() - started
        assert loaded >= delay
        assert notices == []
        assert not progress_reporter.read_state()["attention"]
        page.wait_for_timeout((after + 0.3) * 1000)
        assert notices == []
        assert "page_idle:" in caplog.text
        assert not progress_reporter.read_state()["attention"]
        assert not failures
        print(json.dumps({"configured_idle_seconds": after, "navigation_seconds": round(loaded, 2),
                          "notifications_during_loading": 0,
                          "idle_diagnostic_without_notification": True}))
    finally:
        stop.set()
        if watcher is not None:
            watcher.join(timeout=2)
        if activity is not None:
            activity.close()
        if browser is not None:
            browser.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

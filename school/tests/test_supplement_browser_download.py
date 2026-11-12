"""Browser downloads must also save inline PDFs without buffering them in Python."""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from paper_search_school.browser.backend import launch
from paper_search_school.engine.batch import PublisherBatchDownloader
from test_pdf_after_check import article_pdf


@pytest.mark.skipif(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") != "1",
                    reason="local browser fixture opt-in")
@pytest.mark.parametrize("suffix", [
    pytest.param("/inline.pdf", marks=pytest.mark.xfail(strict=True, reason=(
        "Chrome shows an inline PDF in its viewer with no download event; only Firefox's PDF.js could be "
        "read (ADR 0016). Supplements came through the other routes in the Chrome acceptance."))),
    "/attachment.pdf",
])
def test_native_inline_pdf_and_attachment_use_the_same_disk_save(tmp_path, suffix):
    body = article_pdf("10.1000/local-supplement") + b"\n%" + b"x" * (1024 * 1024 + 123)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", ("attachment" if self.path == "/attachment.pdf" else "inline")
                             + '; filename="supplement.pdf"')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    browser = None
    try:
        browser = launch(headless=True, humanize=False, config={"browser_backend": "chrome"})
        context = browser.new_context(accept_downloads=True)
        origin = f"http://127.0.0.1:{server.server_port}"
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(origin + "/")
                      else route.abort())
        page = context.new_page()
        downloader = PublisherBatchDownloader({})
        saved, name = downloader._download_in_new_tab(page, origin + suffix)
        try:
            assert saved.read_bytes() == body
            assert name == ("inline.pdf" if suffix == "/inline.pdf" else "supplement.pdf")
            assert context.pages == [page]
        finally:
            saved.unlink()
    finally:
        if browser is not None:
            browser.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

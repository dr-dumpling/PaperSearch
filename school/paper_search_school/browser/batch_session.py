"""One browser window and tab kept for a serial MCP batch, on its Playwright
worker thread. Used when the backend declares ``batch_window``
(browser/backend.py); only plain Playwright calls, no backend of its own."""
from contextvars import ContextVar

from .preview import ensure_enabled


# How long a keep-alive load of the article page may take.
KEEP_SESSION_TIMEOUT_MS = 30_000


class BatchBrowser:
    def __init__(self):
        self.context = None
        self.page = None
        self.info = None
        self.id = ""
        #: The publisher's article page of the last paper, when that paper saved its PDF.
        self.article_url = ""

    def open(self, downloader, *, relaunch=""):
        if self.context is not None and not self.context.pages:
            self.close()
        if self.context is None:
            self.context = downloader._launch_context(relaunch=relaunch)
            self.info = downloader.browser
        else:
            downloader.browser = self.info
            ensure_enabled(self.context, downloader.config)
        if self.page is None or self.page.is_closed():
            self.page = self.context.new_page()
        return self.context

    def keep_session(self):
        """While the batch waits (the hourly limit the user set): the last paper's
        article page, loaded again in the batch's tab, so the publisher's institutional
        session does not lapse for want of a request (Wiley: about half an hour,
        2026-11-12). Only after a paper that saved its PDF: a tab left on a school's
        login page is never taken away from the user."""
        page = self.page
        if self.context is None or page is None or page.is_closed() or not self.article_url:
            return {"kept": False, "reason": "no_publisher_page"}
        try:
            page.goto(self.article_url, wait_until="domcontentloaded", timeout=KEEP_SESSION_TIMEOUT_MS)
        except Exception as exc:
            return {"kept": False, "reason": type(exc).__name__}
        return {"kept": True}

    def finish_item(self):
        # Keep the original tab and its native window. Article/PDF/login
        # popups cannot leak into the next publisher's page detection.
        for page in self.context.pages:
            if page is not self.page and not page.is_closed():
                page.close()

    def close(self):
        context, self.context, self.page, self.info = self.context, None, None, None
        if context is not None:
            context.close()


active_batch: ContextVar[BatchBrowser | None] = ContextVar("active_browser_batch", default=None)

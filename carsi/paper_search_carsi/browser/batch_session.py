"""One browser window and tab kept for a serial MCP batch, on its Playwright
worker thread. Used when the backend declares ``batch_window``
(browser/backend.py); only plain Playwright calls, no backend of its own."""
from contextvars import ContextVar

from .preview import ensure_enabled


class BatchBrowser:
    def __init__(self):
        self.context = None
        self.page = None
        self.info = None
        self.id = ""

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

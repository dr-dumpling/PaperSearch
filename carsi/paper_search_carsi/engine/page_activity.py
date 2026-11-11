"""Track idle owned pages without treating missing progress as a user action.

A quiet interval is handed to the downloader (``on_idle``): it looks at the page on
the browser thread and reminds the user (``remind``) only for a page it does not know
with something to click on it (the user, 2026-11-11). Silence alone asks nothing.

Main-document requests, navigation, a loaded document, a workflow step or
received file bytes refresh the timer. An in-flight navigation gets only the
existing page wait budget; polling and unrelated background traffic do not.
The request watcher can check the timer without making a browser RPC.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any

from .. import progress_reporter
from ..config import DEFAULT_CONFIG


class PageActivity:
    def __init__(self, doi: str, config: dict, *, clock=None):
        self.after = int(config.get("browser_stall_notify_after",
                                    DEFAULT_CONFIG["browser_stall_notify_after"]))
        self._navigation_timeout = max(10.0, float(config.get("browser_page_wait_timeout")
                                                  or DEFAULT_CONFIG["browser_page_wait_timeout"]))
        self._clock = clock or time.monotonic
        self._last_progress = self._clock()
        self._lock = threading.RLock()
        self._doi = doi
        self._reported = False
        self.key = f"page-unknown:{id(self)}:{doi}"
        self._shown = False
        # Called with the lock held once a quiet interval has passed, from any thread
        # and without a browser call: it may only schedule work (``watchdog.run_soon``).
        self.on_idle: Any = None
        self._transfers = 0
        self._automatic_until = 0.0
        self.closed = False
        self.page = None
        self._pages: dict[int, tuple[Any, dict]] = {}
        self._navigations: dict[int, tuple[Any, float]] = {}

    def progress(self, page=None) -> None:
        with self._lock:
            if self.closed:
                return
            self._last_progress = self._clock()
            if page is not None:
                self.page = page
            self._clear()

    def _clear(self) -> None:
        self._reported = False
        if self._shown:
            progress_reporter.clear_attention(self.key)
            self._shown = False

    def automatic_for(self, seconds: float) -> None:
        """Defer idle diagnostics until the caller's existing automatic deadline.

        This is a finite lease, not progress: polling must pass only the time
        remaining on the original bound. Zero releases it at manual handoff.
        The watcher can still log if the browser call never returns.
        """
        with self._lock:
            self._automatic_until = self._clock() + max(0.0, seconds)
            if seconds > 0:
                self._clear()

    def check(self) -> None:
        """Thread safe; never inspect a page or interrupt an in-flight operation."""
        with self._lock:
            if self.closed:
                return
            if progress_reporter.has_attention(current=self._doi, excluding=self.key):
                # School login and other explicit requests have priority. Start
                # a fresh quiet interval when they finish rather than duplicating them.
                self._last_progress = self._clock()
                self._clear()
            elif (not self._reported and not self._transfers
                  and self._clock() >= self._automatic_until
                  and not self._navigation_loading()
                  and self._clock() - self._last_progress >= self.after):
                # Silence is not evidence of a login or verification control.
                # Keep a bounded diagnostic; only the workflow can request the
                # user's attention after inspecting the current page.
                logging.getLogger(__name__).info("page_idle: no observed progress for %.0f seconds",
                                                 self._clock() - self._last_progress)
                self._reported = True
                if self.on_idle is not None:
                    self.on_idle()

    def stalled(self) -> bool:
        """Still quiet for the whole interval: the downloader checks again before reminding."""
        with self._lock:
            return (not self.closed and not self._transfers and self._clock() >= self._automatic_until
                    and not self._navigation_loading() and self._clock() - self._last_progress >= self.after)

    def remind(self, message: str) -> None:
        """Ask the user to look at the page; the downloader calls it after inspecting the
        page. Progress, another reminder for this paper or the article's end clears it."""
        with self._lock:
            if self.closed or self._shown:
                return
            progress_reporter.set_attention(self.key, message, current=self._doi, phase="需要你操作")
            self._shown = True

    def _navigation_loading(self) -> bool:
        pending = self._navigations.get(id(self.page))
        return pending is not None and self._clock() < pending[1]

    def observe(self, page) -> None:
        """Attach only on the browser thread, including this page's owned popups."""
        if self.closed or id(page) in self._pages:
            return

        def navigated(frame):
            if frame == page.main_frame:
                self.progress(page)

        def loaded():
            with self._lock:
                self._navigations.pop(id(page), None)
                self.progress(page)

        def requested(request):
            # These are cached Playwright properties, not browser RPCs. Ads,
            # analytics, XHR polling and subframes cannot silence a stuck page.
            if not request.is_navigation_request() or request.frame != page.main_frame:
                return
            with self._lock:
                previous = self._navigations.get(id(page))
                deadline = (previous[1] if previous and request.redirected_from is previous[0]
                            else self._clock() + self._navigation_timeout)
                self._navigations[id(page)] = (request, deadline)
                self.progress(page)

        def responded(response):
            with self._lock:
                pending = self._navigations.get(id(page))
                if pending is not None and response.request is pending[0]:
                    self.progress(page)

        def failed(request):
            with self._lock:
                pending = self._navigations.get(id(page))
                if pending is not None and request is pending[0]:
                    self._navigations.pop(id(page), None)
                    self.progress(page)

        def closed():
            with self._lock:
                self._pages.pop(id(page), None)
                self._navigations.pop(id(page), None)
                if self.page is page:
                    self.page = next((p for p, _ in reversed(list(self._pages.values()))), None)
                self.progress()
            for event, handler in handlers.items():
                page.remove_listener(event, handler)

        handlers = {"framenavigated": navigated, "domcontentloaded": loaded,
                    "request": requested, "response": responded, "requestfailed": failed,
                    "popup": self.observe, "close": closed}
        self._pages[id(page)] = (page, handlers)
        for event, handler in handlers.items():
            page.on(event, handler)
        self.progress(page)

    @contextmanager
    def transfer(self):
        """A browser body/save RPC exposes no byte events. Its existing network
        and watchdog limits still apply; do not call it a page needing a click."""
        with self._lock:
            self._transfers += 1
            self.progress()
        try:
            yield
        finally:
            with self._lock:
                self._transfers -= 1
                self.progress()

    def close(self) -> None:
        """Detach on the browser thread before the next item."""
        with self._lock:
            self.closed = True
            self._navigations.clear()
            self._clear()
        for page, handlers in list(self._pages.values()):
            for event, handler in handlers.items():
                page.remove_listener(event, handler)
        self._pages.clear()


@contextmanager
def transfer(result):
    activity = getattr(result, "_page_activity", None)
    if activity is None:
        yield
    else:
        with activity.transfer():
            yield

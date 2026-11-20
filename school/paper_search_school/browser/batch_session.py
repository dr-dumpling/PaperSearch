"""One browser window and tab kept for a serial MCP batch, on its Playwright
worker thread. Used when the backend declares ``batch_window``
(browser/backend.py); only plain Playwright calls, no backend of its own."""
import queue
import threading
import time
from concurrent.futures import Executor, Future
from contextvars import ContextVar
from urllib.parse import urlsplit

from .challenge import detection as challenges
from .preview import ensure_enabled


# How long a keep-alive load of the article page may take, and how long the page then
# has to settle back on the article's site (a Cloudflare check cleared, a sign-in the
# publisher runs by itself); the client waits up to a minute for all of it.
KEEP_SESSION_TIMEOUT_MS = 25_000
KEEP_SESSION_SETTLE_SECONDS = 20
# Between papers, how long each pass lets the browser's events through, and how long the
# thread waits for the next job first.
IDLE_PASS_MS = 200
IDLE_POLL_SEC = 0.05


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
        login page is never taken away from the user.

        A Cloudflare check met on the way is cleared as a download clears it (its
        checkbox only). A page that does not come back to the article's site (a check
        that does not clear, the publisher's own sign-in, a load that hangs) leaves the
        tab blank, and no keep-alive runs again until a paper saves; the next paper signs
        in as a download does. The tab sat spinning on a Cloudflare check, and on
        Elsevier's sign-in page (id.elsevier.com) that never loaded, for the rest of the
        wait (Windows, 2026-11-13)."""
        page = self.page
        if self.context is None or page is None or page.is_closed() or not self.article_url:
            return {"kept": False, "reason": "no_publisher_page"}
        try:
            page.goto(self.article_url, wait_until="domcontentloaded", timeout=KEEP_SESSION_TIMEOUT_MS)
            reason = _settle(page, _site(self.article_url))
        except Exception as exc:
            reason = type(exc).__name__
        if not reason:
            return {"kept": True}
        self.article_url = ""
        try:
            page.goto("about:blank", timeout=5_000)
        except Exception:
            pass
        return {"kept": False, "reason": reason}

    def pump(self):
        """Between papers (the batch waiting for 登录并继续, for its hourly limit): the batch's
        tab goes on answering. Patchright sends every request of a tab with an init script
        through this process first, and a sync driver hears it only during a call of its
        own: with no paper running, the school's login page did not move after 登录
        (Windows, 2026-11-18)."""
        page = self.page
        if self.context is None or page is None:
            time.sleep(IDLE_PASS_MS / 1000)
            return
        from . import watchdog

        try:
            if not page.is_closed():
                page.wait_for_timeout(IDLE_PASS_MS)
                return
        except Exception:
            pass  # the next paper finds the browser as it is and says so
        finally:
            watchdog.take_period()  # not the next paper's browser calls
        time.sleep(IDLE_PASS_MS / 1000)

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


class BatchThread(Executor):
    """The batch's one browser thread: runs its jobs in order, and with none waiting calls
    ``idle`` (BatchBrowser.pump), so the batch's tab works while no paper runs."""

    def __init__(self, idle, name="school-batch"):
        self._idle = idle
        self._jobs: queue.SimpleQueue = queue.SimpleQueue()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, fn, /, *args, **kwargs):
        if self._closed:
            raise RuntimeError("cannot schedule new futures after shutdown")
        future = Future()
        self._jobs.put((future, fn, args, kwargs))
        return future

    def _run(self):
        while True:
            try:
                job = self._jobs.get(timeout=IDLE_POLL_SEC)
            except queue.Empty:
                try:
                    self._idle()
                except Exception:
                    time.sleep(IDLE_PASS_MS / 1000)
                continue
            if job is None:
                return
            future, fn, args, kwargs = job
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)

    def shutdown(self, wait=True, *, cancel_futures=False):
        self._closed = True
        self._jobs.put(None)
        if wait:
            self._thread.join()


def _on_verification(page) -> bool:
    try:
        title = page.title()
    except Exception:
        title = ""  # mid-navigation: the URL still tells
    return challenges.looks_like_challenge(str(page.url or ""), title)


def _site(url: str) -> str:
    host = urlsplit(str(url or "")).hostname or ""
    return host[4:] if host.startswith("www.") else host


def _settle(page, site: str) -> str:
    """"" once the page has settled on the article's site, no Cloudflare check up; else,
    after KEEP_SESSION_SETTLE_SECONDS, "verification" or "signin" (another site: the
    publisher's sign-in, a school's login). A check's checkbox is clicked as in a
    download (at most three times, three seconds apart)."""
    from .challenge.interaction import click_checkbox
    until = time.monotonic() + KEEP_SESSION_SETTLE_SECONDS
    clicks, next_click = 0, 0.0
    page.wait_for_timeout(2000)  # a redirect the page makes once loaded
    while True:
        if _on_verification(page):
            reason = "verification"
            now = time.monotonic()
            if clicks < 3 and now >= next_click:
                if click_checkbox(page, timeout_ms=2500, checkpoint=lambda: None) == "clicked":
                    clicks, next_click = clicks + 1, time.monotonic() + 3
        elif _site(page.url) == site:
            return ""
        else:
            reason = "signin"
        if time.monotonic() >= until:
            return reason
        page.wait_for_timeout(1000)

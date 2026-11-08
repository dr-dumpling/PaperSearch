"""Definitions shared by the publisher batch downloader modules (batch.py and batch_*.py)."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import requests

from ..browser import watchdog
from ..browser.driver import is_driver_error
from ..browser.challenges import looks_like_challenge


EST_ISSN = "1520-5851"
MIN_PDF_BYTES = 5_000
MAX_BROWSER_CONCURRENCY = 4
PDF_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

logger = logging.getLogger(__package__ + ".batch")  # the engine's one channel


def page_operation(method):
    """Bound an engine page operation by its existing page-wait setting."""
    @wraps(method)
    def bounded(self, *args, **kwargs):
        with watchdog.operation(self.page_wait_sec, method.__name__):
            return method(self, *args, **kwargs)
    return bounded


def _resolve_profile_dir(config: dict[str, Any], explicit: str | Path | None = None) -> Path:
    """Fixed browser profile dir; explicit/config wins, default is data-dir scoped.

    Never fall back to the current working directory: in agent runs the cwd
    changes per task, which would silently create a fresh profile — and force a
    re-login — every time.
    """
    if explicit:
        return Path(explicit)
    configured = str(config.get("chrome_profile_dir", "") or "").strip()
    if configured:
        return Path(configured)
    data_dir = Path(os.environ.get("CARSI_DATA_DIR", str(Path.home() / ".local" / "share" / "paper-search-cli" / "carsi")))
    return data_dir / "browser_profiles" / "publisher"

RETRYABLE_REASONS = {
    "pdf_not_captured",
    "navigation_error",
    "challenge_or_viewer_timeout",
}

# Consecutive ip_blocked results from one run that halt the remaining records.
# An ACS / publisher IP block is not transient for the session (the IP stays
# blocked), so continuing only deepens it. 3 tolerates a stray single-record 403
# (e.g. one entitlement miss) while still tripping fast on a real block.
# NOTE: "ip_blocked" is intentionally NOT in RETRYABLE_REASONS.
IP_BLOCK_STOP_THRESHOLD = 3

# HTTP status codes that, when seen on a publisher PDF/article endpoint, are
# treated as an IP block signal. 403 is ACS's block-page status; 429 is the
# generic rate-limit/block code.
_IP_BLOCK_STATUS_CODES = {403, 429}

# Reusable JS helpers injected into page.evaluate() calls
_JS_VISIBLE = """(el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
}"""

_JS_TEXTOF = """(el) => [
    el.innerText || '',
    el.textContent || '',
    el.value || '',
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || ''
].join(' ')"""


@dataclass
class PaperRecord:
    doi: str
    title: str = ""
    published: str = ""
    url: str = ""




def _block_state(block_reason: str | None) -> str:
    """Terminal state for a capture that ended on a block: an unfinished
    verification stays a timeout, anything else is an explicit block."""
    return "challenge_or_viewer_timeout" if block_reason == "challenge_or_viewer_timeout" else "ip_blocked"


# A visible "Get Access" or "Access through <institution>" control: the article
# is shown without full-text access, so no PDF control on it is the article's.
_ACCESS_GATE_JS = r"""() => [...document.querySelectorAll('a,button,[role="button"]')].some(el => {
    if (el.getClientRects().length === 0 || getComputedStyle(el).visibility === 'hidden') return false;
    const t = (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    return /^get access$/i.test(t) || /^access through (?!.*\bpurchase\b).{2,80}$/i.test(t);
})"""

# A control inside the reference list, or a citation linkout, is never the article's own PDF.
_REFERENCE_AREA = "#references, .references, #bibliography, .bibliography, .ref-list, .biblioentry, .citations, .citation, .c-article-references"
_IN_REFERENCES_JS = """el => !!el.closest(\"""" + _REFERENCE_AREA + """\")
    || ((el.getAttribute('href') || '') + '').toLowerCase().includes('/servlet/linkout')"""


# "Open Access This article is licensed under a Creative Commons ..." states that
# this article is open; its words must not read as the paywall marker
# "access this article" (Nature Communications was sent to institution login).
_OPEN_ACCESS_LICENSE = re.compile(r"open access\s+this article is (?:licensed|distributed) under")
_OPEN_ACCESS_LICENSE_PHRASE = re.compile(r"open access\s+this article")


def _observe_preview(page: Any) -> None:
    """Refresh the live preview while waiting; it is throttled and keeps one frame per unchanged page."""
    from ..browser.preview import observe_page
    observe_page(page)


def _is_browser_error(exc: BaseException, name: str = "") -> bool:
    """A driver error (optionally of class ``name``), not a program bug."""
    return is_driver_error(exc, name)


def page_title(page: Any) -> str:
    """Read optional title text without consuming the whole page budget."""
    try:
        # Page.title has no timeout. A busy renderer held it for 30 s
        # after access was ready, before the first PDF attempt (2026-11-04).
        value = page.locator("head > title").first.text_content(timeout=1_000)
        return re.sub(r"\s+", " ", str(value or "")).strip()
    except Exception as exc:
        if not _is_browser_error(exc):
            raise
        return ""


# A browser call cut off by the page navigating: its document replaced, its frame gone.
_NAVIGATION_CUT = ("Execution context was destroyed", "Cannot find context with specified id",
                   "Frame was detached", "because of a navigation")


def _is_navigation_cut(exc: BaseException) -> bool:
    """A browser error from the page navigating during the call (not a closed page,
    not a protocol failure)."""
    return _is_browser_error(exc) and any(marker in str(exc) for marker in _NAVIGATION_CUT)


# The publisher's site did not answer: Chromium's network errors, and a page
# load that ran out of time. Not a program error (thieme-connect.de's empty
# response and pubs.acs.org's 60 s loads, 2026-11-01).
_NETWORK_FAILURE = ("net::ERR_",)


def _is_network_failure(exc: BaseException) -> bool:
    if not _is_browser_error(exc):
        return False
    message = str(exc)
    if _is_browser_error(exc, "TimeoutError") and message.startswith("Page.goto:"):
        return True
    return "net::ERR_ABORTED" not in message and any(marker in message for marker in _NETWORK_FAILURE)


# Waits go on as soon as their condition holds; the old fixed pauses (2-5 s after
# every page and click) are only upper bounds now (user request, 2026-11-01).
POLL_MS = 250


def settle(page: Any, timeout_ms: int) -> None:
    """Until the page has loaded, at most ``timeout_ms``: a loaded page goes on at once.
    A browser error (the page moving on meanwhile) ends the wait, not the article."""
    try:
        page.wait_for_load_state("load", timeout=timeout_ms)
    except Exception as exc:
        if not _is_browser_error(exc):
            raise


def pump_until(page: Any, done: Callable[[], bool], timeout_ms: int, step_ms: int = POLL_MS) -> bool:
    """Let the browser run (events, navigations, captured responses) until ``done()``,
    at most ``timeout_ms`` by the clock, ``done()``'s own time included (counting
    passes alone let a slow ``done()`` run far past it, review 2026-11-02); True once
    it holds. Each pass waits ``step_ms`` in the browser, so on a real page the clock
    ends the wait first; the pass count (``timeout_ms // step_ms``) bounds only a page
    whose wait returns at once (the tests' pages, some with clocks of their own)."""
    deadline = time.monotonic() + timeout_ms / 1000
    for _ in range(max(1, timeout_ms // step_ms)):
        if done():
            return True
        left_ms = int((deadline - time.monotonic()) * 1000)
        if left_ms <= 0:
            return False
        page.wait_for_timeout(min(step_ms, left_ms))
    return bool(done())


# The page's document can be read: parsed (DOMContentLoaded), or its body text has
# stopped growing. pubs.acs.org showed its article and citation metadata 4.5 s
# after the request and held DOMContentLoaded back until 33 s on an ad script
# that never answered (headless probe, 2026-11-02); the login's returns to the
# article waited 32-40 s each for it.
# This is DOM readiness, not an access verdict. Avoid laying out the whole
# article, and do not read its body at all once the parser has finished.
_DOCUMENT_STATE_JS = """() => [document.readyState,
    document.readyState === 'loading' && document.body ? document.body.textContent.length : 0]"""


# A connection the network dropped before the site answered: Chromium's codes for a
# closed, reset or timed-out connection, a failed proxy tunnel or name lookup, a
# broken protocol stream. A system proxy in front of doi.org dropped 1 of 6
# connections and 3 articles failed on it, each fine on the next try (Windows,
# 2026-11-07); such a navigation is tried again after these pauses.
_DROPPED_CONNECTION = (
    "net::ERR_CONNECTION_CLOSED", "net::ERR_CONNECTION_RESET", "net::ERR_CONNECTION_TIMED_OUT",
    "net::ERR_TIMED_OUT", "net::ERR_EMPTY_RESPONSE", "net::ERR_NETWORK_CHANGED",
    "net::ERR_PROXY_CONNECTION_FAILED", "net::ERR_TUNNEL_CONNECTION_FAILED", "net::ERR_NAME_NOT_RESOLVED",
    "net::ERR_SSL_PROTOCOL_ERROR", "net::ERR_HTTP2_PROTOCOL_ERROR", "net::ERR_QUIC_PROTOCOL_ERROR",
)
DROPPED_CONNECTION_RETRY_MS = (2_000, 5_000)


def goto_retrying(page: Any, url: str, *, timeout_ms: int, wait_until: str = "commit",
                  started: float | None = None, **kwargs: Any) -> Any:
    """``page.goto``, again after a dropped connection while ``timeout_ms`` (counted
    from ``started``, default now) allows. Every navigation of the download goes
    through here: the article (``open_page``), its PDF, supplement tabs."""
    started = time.monotonic() if started is None else started
    dropped: BaseException | None = None
    for attempt, pause_ms in enumerate((*DROPPED_CONNECTION_RETRY_MS, None)):
        spent_ms = int((time.monotonic() - started) * 1000) if attempt else 0  # the first try: the whole budget
        try:
            return page.goto(url, wait_until=wait_until, timeout=max(1_000, timeout_ms - spent_ms), **kwargs)
        except Exception as exc:
            message = str(exc) if _is_browser_error(exc) else ""
            if any(code in message for code in _DROPPED_CONNECTION):
                dropped = exc
            elif not (dropped and "net::ERR_ABORTED" in message):
                raise
            # After a dropped connection Chromium's error page reloads by itself and
            # can cut the next try short (net::ERR_ABORTED): still the dropped
            # connection, and reported as such (T&F through doi.org, Windows 2026-11-07).
            spent_ms = int((time.monotonic() - started) * 1000)
            if pause_ms is None or spent_ms + pause_ms >= timeout_ms:
                raise dropped from (exc if exc is not dropped else None)
            logger.info("   [Navigation] %s; trying again in %d s", message.splitlines()[0][:200], pause_ms // 1000)
            page.wait_for_timeout(pause_ms)
    raise AssertionError("unreachable")


def open_page(page: Any, url: str, *, timeout_ms: int = 60_000, ready_ms: int = 15_000, **kwargs: Any) -> Any:
    """Go to ``url`` and on as soon as its document can be read: the navigation
    commits within ``timeout_ms`` (a dropped connection is tried again), then at
    most ``ready_ms`` until the document is parsed or its text stops growing; a
    verification page is left untouched at once. The caller checks the page state
    it needs (``settle``, the access rule, the verification wait). Returns the response."""
    committed = False

    def navigated(frame: Any) -> None:
        nonlocal committed
        if frame == page.main_frame and str(frame.url).startswith(("https://", "http://")):
            committed = True

    started = time.monotonic()
    page.on("framenavigated", navigated)
    try:
        try:
            response = goto_retrying(page, url, timeout_ms=timeout_ms, started=started, **kwargs)
        except Exception as exc:
            # A script redirect can replace the requested navigation before goto
            # returns (net::ERR_ABORTED). Continue only after an observed
            # top-level document commit; the caller still checks identity/access.
            if not _is_browser_error(exc) or "net::ERR_ABORTED" not in str(exc):
                raise
            left = max(0, min(ready_ms, timeout_ms - int((time.monotonic() - started) * 1000)))
            if not committed and not pump_until(page, lambda: committed, left):
                raise
            response = None
    finally:
        page.remove_listener("framenavigated", navigated)
    text = {"size": -1, "since": time.time()}  # the body text's length, and since when

    def readable() -> bool:
        try:
            if looks_like_challenge(str(getattr(page, "url", "") or ""), page_title(page)):
                return True
            state = page.evaluate(_DOCUMENT_STATE_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return False  # the document is being replaced
        if not (isinstance(state, list) and len(state) == 2):
            return True
        ready_state, size = state
        if size != text["size"]:
            text.update(size=size, since=time.time())
        return ready_state != "loading" or (isinstance(size, int) and size >= 200 and time.time() - text["since"] >= 1)

    pump_until(page, readable, ready_ms)
    return response


# When an earlier article of the batch waited on the user until its time was up
# (config ``user_wait: short``: the user seems away), each wait on the user lasts
# at most this long, and so does a login page on which nothing moves.
AWAY_WAIT_SEC = 60


@dataclass
class DownloadResult:
    doi: str
    status: str
    reason: str = ""
    state: str = ""
    article_url: str = ""
    final_url: str = ""
    title: str = ""
    pdf_url: str = ""
    pdf_path: str = ""
    text_length: int = 0
    size_bytes: int = 0
    verified_match: bool = False
    diagnostic_path: str = ""
    record_path: str = ""
    events: list[dict[str, str]] = field(default_factory=list)
    #: Supplementary files collected for this article (see supplements.collect).
    supplements: list[dict[str, Any]] = field(default_factory=list)
    #: Where a login that waited on the user ended (``_login_wait_page``).
    login_wait_page: str = ""
    #: How the browser of this item started: who held its profile, the wait for
    #: it, the launch's seconds, a relaunch (``_launch_context``).
    browser_start: dict[str, Any] = field(default_factory=dict)
    #: Seconds spent per phase: open, verification, login, pdf, supplements (``_phase``).
    phases: dict[str, float] = field(default_factory=dict)
    #: Every PDF tried, by a click or its address: what came back and how it ended
    #: (``_record_pdf_attempt``).
    pdf_attempts: list[dict[str, Any]] = field(default_factory=list)
    #: The page at the item's decision points: URL, title, a small picture (``_snapshot``).
    snapshots: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "success"


def safe_name(doi: str) -> str:
    return re.sub(r"[^\w\-.]", "_", doi)


def fetch_est_records(
    *,
    year: int,
    limit: int,
    email: str = "",
    session: requests.Session | None = None,
) -> list[PaperRecord]:
    """Fetch EST records from Crossref in newest-first publication order."""
    params = {
        "filter": (
            f"issn:{EST_ISSN},type:journal-article,"
            f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31"
        ),
        "sort": "published",
        "order": "desc",
        "rows": str(limit),
    }
    if email:
        params["mailto"] = email
    url = "https://api.crossref.org/works?" + urlencode(params)
    sess = session or requests.Session()
    resp = sess.get(
        url,
        timeout=30,
        headers={"User-Agent": f"instsci/0.1 ({email or 'local'})"},
    )
    resp.raise_for_status()
    records: list[PaperRecord] = []
    for item in resp.json().get("message", {}).get("items", []):
        doi = str(item.get("DOI", "")).strip()
        if not doi:
            continue
        title = " ".join(item.get("title") or [])
        published = item.get("published-print") or item.get("published-online") or item.get("published") or {}
        date_parts = published.get("date-parts") or [[]]
        published_text = ""
        if date_parts and date_parts[0]:
            published_text = "-".join(
                f"{part:02d}" if idx else str(part)
                for idx, part in enumerate(date_parts[0])
            )
        records.append(
            PaperRecord(
                doi=doi,
                title=re.sub(r"\s+", " ", title).strip(),
                published=published_text,
                url=str(item.get("URL", "")),
            )
        )
    return records[:limit]


class _PagePool:
    """Thread-safe page pool sharing a single browser context.

    All pages share the same context, which means they share:
    - Cookies (session tokens, auth cookies)
    - localStorage (publisher auth tokens)
    - sessionStorage (temporary session data)
    - HTTP connection pool (keep-alive authenticated connections)
    - TLS session tickets (established encrypted sessions)

    This is essential: login state is the ENTIRE browser context, not just cookies.
    Creating a new context is like switching devices — publishers may reject it.
    """

    def __init__(self, context: Any, max_size: int = 2):
        self._context = context
        self._max_size = max_size
        self._available: list[Any] = []
        self._in_use: set[int] = set()
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)

    def acquire(self) -> Any:
        """Acquire a page from the pool. Creates new if pool is empty and under limit."""
        with self._not_empty:
            # Try to reuse an available page
            while self._available:
                page = self._available.pop()
                try:
                    _ = page.url  # Test if page is still alive
                    self._in_use.add(id(page))
                    return page
                except Exception:
                    try:
                        page.close()
                    except Exception:
                        pass

            # Create new page if under limit
            if len(self._in_use) < self._max_size:
                page = self._context.new_page()
                self._in_use.add(id(page))
                return page

            # Wait for a page to be returned
            while not self._available:
                self._not_empty.wait(timeout=30)
                if self._available:
                    page = self._available.pop()
                    try:
                        _ = page.url
                        self._in_use.add(id(page))
                        return page
                    except Exception:
                        try:
                            page.close()
                        except Exception:
                            pass
            # Should not reach here, but just in case
            page = self._context.new_page()
            self._in_use.add(id(page))
            return page

    def release(self, page: Any) -> None:
        """Return a page to the pool for reuse."""
        with self._not_empty:
            self._in_use.discard(id(page))
            try:
                self._available.append(page)
            except Exception:
                pass
            self._not_empty.notify()

    def close_all(self) -> None:
        """Close all pages."""
        with self._lock:
            for page in self._available:
                try:
                    page.close()
                except Exception:
                    pass
            self._available.clear()
            self._in_use.clear()


class PublisherContentError(RuntimeError):
    """Publisher returned an explicit content-service error, not a PDF."""


class PublisherPlatformUnsupported(PublisherContentError):
    """The article is served only on a platform this engine cannot use (e.g. ClinicalKey)."""


class ArticleNotYetPublished(PublisherContentError):
    """The publisher lists the article as accepted; its full text is not online yet."""


class PublisherAccessBlocked(RuntimeError):
    """An explicit site security block, without an interactive verification."""

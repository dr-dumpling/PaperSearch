"""Visit a site's own root once per run before opening its articles.

Cloudflare grants two kinds of clearance (developers.cloudflare.com, read
2026-11-18): challenge clearance from passing a check, and precursor clearance
that it keeps updating from session behaviour. A browser that arrives straight
at a deep article URL has neither — the site sees a session that began at the
article. Opening the root first gives it a first-party document to read before
the article, which is what the published warm-up implementations do
(patchright-docker's ``--warmup``, curlwright's stealth warm-up).

Nothing here waits for verification, clicks a control, or decides access: a
root visit that ends on a challenge is left alone and the existing verification
wait on the article page handles it. The root opens in its own tab and that tab
is closed again, so the article's page and its listeners are untouched.

The browser is the same one the download already uses (the user's Chrome or the
user's ego over the same Patchright driver), never a second browser.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

#: Longest root visit. The article keeps its own 60 s navigation budget.
WARMUP_TIMEOUT_MS = 12_000
#: Time the root page gets after its document is parsed, for the site's own
#: scripts (challenge platform included) to run once.
SETTLE_MS = 600

#: Sites whose root was already visited in this process. One visit per site is
#: the point: a second one in the same session adds nothing Cloudflare reads.
_visited: set[str] = set()


def site_root(url: str) -> str:
    """``https://host/`` for a page URL, or "" when the URL has no usable site."""
    parsed = urlsplit(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/"


def reset(hosts: Iterable[str] | None = None) -> None:
    """Forget the visited sites (tests, or a new download run)."""
    _visited.clear() if hosts is None else _visited.difference_update(
        host.lower() for host in hosts)


def warm(page: Any, url: str, *, timeout_ms: int = WARMUP_TIMEOUT_MS,
         settle_ms: int = SETTLE_MS) -> str:
    """Visit the site root of ``url`` once; ``warmed``, ``skipped`` or ``failed``.

    ``skipped`` covers a URL without a site and a site already visited. A visit
    that raises is ``failed`` and the download continues: this is an extra
    first-party document, not a step the article depends on. Watchdog and
    cancellation errors still reach the caller.
    """
    from .. import watchdog

    root = site_root(url)
    if not root:
        return "skipped"
    site = urlsplit(root).netloc.lower()
    if site in _visited:
        return "skipped"
    _visited.add(site)

    context = getattr(page, "context", None)
    open_tab = getattr(context, "new_page", None)
    if not callable(open_tab):
        return "skipped"

    tab: Any = None
    try:
        tab = open_tab()
        tab.goto(root, wait_until="domcontentloaded", timeout=max(1_000, timeout_ms))
        if settle_ms > 0:
            tab.wait_for_timeout(settle_ms)
        return "warmed"
    except Exception as exc:  # noqa: BLE001 - the article's own navigation decides
        if isinstance(exc, (watchdog.CallAbandoned, watchdog.BrowserUnresponsive)):
            raise
        return "failed"
    finally:
        try:
            if tab is not None and not tab.is_closed():
                tab.close()
        except Exception:  # noqa: BLE001 - a tab that will not close is not the article's problem
            pass

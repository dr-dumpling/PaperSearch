"""ovid.com/jnls/: LWW articles Ovid serves behind a two-step access panel.

Without access the abstract page shows "Check Access" (an offer of the shared
access rule), which opens the panel with the institutional login."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ...engine.batch_common import _is_browser_error

HOSTS = {"ovid.com", "www.ovid.com"}
_ARTICLE = re.compile(r"/jnls/[^/]+/(?:abstract|fulltext|pdf)/")


def is_page(url: str) -> bool:
    parsed = urlparse(url or "")
    return (parsed.hostname or "").lower() in HOSTS and parsed.path.startswith("/jnls/")


def is_redirect(url: str) -> bool:
    """``ovid.com/<DOI>``: Ovid's DOI address, which its script moves on to the
    article (``/jnls/<journal>/fulltext/...``); no PDF link on it yet (Epidemiology, 2026-11-01)."""
    parsed = urlparse(url or "")
    return (parsed.hostname or "").lower() in HOSTS and bool(re.match(r"/10\.\d{4,9}/", parsed.path))


def is_article(url: str) -> bool:
    parsed = urlparse((url or "").lower())
    return parsed.scheme == "https" and bool(_ARTICLE.match(parsed.path))


class OvidSite:
    """Answers for ovid.com/jnls/ pages; ``None`` = no opinion."""

    def __init__(self, downloader: Any):
        self.d = downloader

    def open_pdf_entry(self, page: Any, result: Any) -> bool:
        """Open this article's PDF with the article page as Referer. Without it
        Ovid answers 307 back to the full text, and the "Download PDF" click
        went without it now and then (J Clin Gastroenterology, 2026-11-01)."""
        article = str(getattr(page, "url", "") or "")
        hrefs = page.evaluate("() => [...document.querySelectorAll('a[href*=\"/pdf/\"]')].map(a => a.href)")
        for href in hrefs if isinstance(hrefs, list) else []:
            if isinstance(href, str) and self.d._article_pdf_url_matches(href, result.doi):
                self.d._event(result, "pdf_button_clicked", "ovid-article-pdf")
                try:
                    page.goto(href, wait_until="commit", timeout=self.d.pdf_timeout_ms, referer=article)
                except Exception as exc:
                    if not _is_browser_error(exc):
                        raise
                    # The capture may answer the request itself (Chromium: 204,
                    # so no download); whether the PDF came is the capture's call.
                    self.d._event(result, "pdf_navigation_ended", type(exc).__name__)
                return True
        return False

    def open_institution_entry(self, page: Any, result: Any) -> bool:
        # Select the institutional control, avoiding individual/AAOS login.
        institution = page.locator("a.omni-sso-url").filter(
            has_text=re.compile(r"Institutional\s+Users", re.I)).first
        if not institution.is_visible():
            wall = page.locator("button.omni-article-tool__check-access").first
            if not wall.is_visible():
                return False
            wall.click(timeout=5_000, no_wait_after=True)
            institution.wait_for(state="visible", timeout=5_000)
        institution.click(timeout=10_000, no_wait_after=True)
        self.d._event(result, "sso_entry_clicked", "ovid-institution-control")
        return True

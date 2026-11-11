"""BMJ: journals on <journal>.bmj.com (HighWire).

Without access the article page offers the article for sale ("Buy this
article", an offer of the shared access rule). The institution login is HighWire's "Log in via Institution", a
Shibboleth discovery page on the journal's own host (``/login/shibboleth``).

Supplementary files are linked in the full text, in ``div.supplementary-material``:
``/content/<journal>/<volume>/<issue>/<page>/DC<n>/embed/inline-supplementary-material-<m>.<ext>``
for the article at ``/content/<volume>/<issue>/<page>`` (BJSM, BMJ Open, 2026-11-11).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from ...browser.driver import is_driver_error
from ...engine.batch_common import open_page
from ..base import PublisherAdapter, SupplementLink, register

# The full text's body: its sections or paragraphs (the page wraps it in .highwire-markup, 2026-11-11).
_FULL_TEXT = ".article.fulltext-view .section, .article.fulltext-view p"
_SUPPLEMENT_ROWS_JS = """() => ({
  fullText: !!document.querySelector('""" + _FULL_TEXT + """'),
  rows: [...document.querySelectorAll('a[href]')].map(a => ({
    href: a.href,
    label: (a.closest('.supplementary-material')?.textContent || a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240),
    supplement: !!a.closest('.supplementary-material'),
  })),
})"""
_DC_FILE = re.compile(r"/content/[^/]+/(?P<article>.+)/DC\d+/embed/[^/]+\.[A-Za-z0-9]{1,8}")
_ARTICLE = re.compile(r"/content/(?P<article>.+?)(?:\.(?:full|abstract|long|full-text))?/?")


def supplement_links_from_page(data: Any, page_url: str) -> list[SupplementLink] | None:
    """The article's supplementary files, or None while its full text is not shown:
    an abstract page lists none, which says nothing about the article."""
    if not isinstance(data, dict) or not data.get("fullText"):
        return None
    page = urlparse(page_url)
    host = (page.hostname or "").lower()
    article = _ARTICLE.fullmatch(page.path)
    links: list[SupplementLink] = []
    for row in data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        target = urlparse(str(row.get("href") or ""))
        found = _DC_FILE.fullmatch(target.path)
        if (target.scheme != "https" or (target.hostname or "").lower() != host or not host.endswith("bmj.com")
                or not found):
            continue
        # This article's files only: its own path, or at least its supplementary-material block.
        if article and found.group("article") != article.group("article"):
            continue
        if not article and not row.get("supplement"):
            continue
        url = target._replace(query="", fragment="").geturl()
        if url not in {link.url for link in links}:
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


@register
class BMJAdapter(PublisherAdapter):
    publisher = "bmj"

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        if not (urlparse(str(getattr(page, "url", "") or "")).hostname or "").lower().endswith("bmj.com"):
            return None
        try:  # the full text renders after the page has loaded
            page.wait_for_selector(_FULL_TEXT, timeout=10_000)
        except Exception as exc:
            if not is_driver_error(exc, "TimeoutError"):
                raise
        return supplement_links_from_page(page.evaluate(_SUPPLEMENT_ROWS_JS), str(page.url))

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        """HighWire's "Log in via Institution"; the login menu also holds
        personal and society logins, which are never used."""
        host = (urlparse(str(getattr(page, "url", "") or "")).hostname or "").lower()
        if not host.endswith("bmj.com"):
            return None
        for control in page.locator('a[href*="/login/shibboleth"]').all():
            target = urlparse(urljoin(str(page.url), control.get_attribute("href") or ""))
            if target.scheme == "https" and target.hostname == host and target.path == "/login/shibboleth":
                open_page(page, target.geturl(), timeout_ms=30_000)
                self.d._event(result, "sso_entry_clicked", "bmj-institution-login")
                return True
        return False

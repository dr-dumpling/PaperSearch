"""Wolters Kluwer / LWW: publisher-wide answers and two site types.

    LWWAdapter (this module)        the PDF (always Ovid's), the Wolters Kluwer
                                    login page's federated option
      ├─ JournalsLwwSite (journals_lww.py)   journals.lww.com article pages
      └─ OvidSite        (ovid.py)           ovid.com/jnls/ article pages

Each hook hands the page to the site type its URL belongs to, as Elsevier's do.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from ...engine.batch_common import open_page
from ..base import PublisherAdapter, SupplementLink, register
from . import journals_lww, ovid
from .journals_lww import JournalsLwwSite
from .ovid import OvidSite

_PDF = re.compile(r"/jnls/[^/]+/pdf/(10\.\d{4,9}/.+)")
SDC_HOST = "links.lww.com"
# The article's "Supplemental Digital Content" list (Ovid: .lww-article-sdc).
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href*="links.lww.com/"]')].map(a => ({
    href: a.href, label: (a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 200),
    sdc: !!a.closest('[class*="sdc" i], [id*="sdc" i]')}))"""


@register
class LWWAdapter(PublisherAdapter):
    publisher = "lww"
    validates_article_pdf = True
    keeps_pdf_out_of_downloads = True
    native_pdf_patterns = ("https://www.ovid.com/jnls/*/pdf/*", "https://ovid.com/jnls/*/pdf/*")

    def __init__(self, downloader: Any):
        super().__init__(downloader)
        self.journals_lww = JournalsLwwSite(downloader)
        self.ovid = OvidSite(downloader)

    def is_article_page_url(self, url: str) -> bool | None:
        lower = (url or "").lower()
        if ovid.is_page(lower):
            return ovid.is_article(lower)
        return urlparse(lower).scheme == "https" and journals_lww.is_page(lower)

    def is_redirect_page(self, url: str) -> bool:
        return ovid.is_redirect(url)

    def is_article_pdf_url(self, url: str, doi: str = "") -> bool | None:
        # The PDF is always Ovid's, also for articles shown on journals.lww.com.
        parsed = urlparse(url)
        path = unquote(parsed.path).lower().split("~", 1)[0].rstrip("/")
        match = _PDF.fullmatch(path)
        return (parsed.scheme == "https" and parsed.hostname in ovid.HOSTS
                and match is not None and (not doi or match[1] == doi.lower())
                and not self.d._is_supplementary_url(url))

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        """``links.lww.com/<journal>/<id>`` in this article's Supplemental Digital
        Content list. The link carries no DOI, so only that list on this article's
        page counts, not the same link quoted in the text."""
        links: list[SupplementLink] = []
        rows = page.evaluate(_SUPPLEMENT_ROWS_JS)
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get("sdc"):
                continue
            target = urlparse(str(row.get("href") or ""))
            if (target.hostname or "").lower() != SDC_HOST or not re.fullmatch(r"/[A-Za-z]+/[A-Za-z0-9]+", target.path):
                continue
            url = target._replace(scheme="https", fragment="").geturl()
            if url not in {link.url for link in links}:
                links.append(SupplementLink(url, str(row.get("label") or "")))
        return links

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        url = str(getattr(page, "url", "") or "")
        if ovid.is_page(url):
            return self.ovid.open_institution_entry(page, result)
        if journals_lww.is_page(url):
            return self.journals_lww.open_institution_entry(page, result)
        return None

    def open_pdf_entry(self, page: Any, result: Any) -> bool | None:
        url = str(getattr(page, "url", "") or "")
        return self.ovid.open_pdf_entry(page, result) if ovid.is_page(url) else None

    def follow_federated_login(self, page: Any, result: Any) -> bool:
        """The Wolters Kluwer login page offers "OpenAthens | Institutional" next
        to the personal username/password form. Follow it once per item."""
        if (urlparse(str(getattr(page, "url", "") or "")).hostname != "login.wolterskluwer.com"
                or any(e.get("detail") == "lww-openathens-institutional" for e in result.events)):
            return False
        link = page.locator("a#athensLoginUrl").first
        if not link.is_visible():
            return False
        target = urlparse(urljoin(str(page.url), link.get_attribute("href") or ""))
        if target.scheme != "https" or target.hostname != "login.wolterskluwer.com":
            return False
        open_page(page, target.geturl(), timeout_ms=30_000)
        self.d._event(result, "sso_entry_clicked", "lww-openathens-institutional")
        return True

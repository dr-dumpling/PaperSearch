"""American Meteorological Society: journals on journals.ametsoc.org.

The PDF of an article page ``/view/<path>.xml`` is ``/downloadpdf/view/<path>.pdf``.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from ...engine.router import _append_ams_candidates
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => ({
    href: a.href, label: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
}))"""


def supplement_links_from_rows(rows: list[dict], doi: str) -> list[SupplementLink]:
    """Only files listed under this article's own supplemental XML directory."""
    if not doi.lower().startswith("10.1175/"):
        return []
    article = re.escape(doi.split("/", 1)[1])
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in rows:
        target = urlparse(str(row.get("href") or ""))
        if (target.scheme != "https" or target.netloc != "journals.ametsoc.org"
                or not re.fullmatch(r"/supplemental/+journals/[^/]+/\d+/\d+/" + article
                                    + r"\.xml/[^/]+", unquote(target.path), re.I)):
            continue
        url = target._replace(fragment="").geturl()
        # In-text and end-of-article links differ by a duplicate slash.
        identity = re.sub(r"/+", "/", unquote(target.path))
        if identity not in seen:
            seen.add(identity)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


@register
class AMSAdapter(PublisherAdapter):
    publisher = "ams"

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_rows(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_ams_candidates(urls, source_url)
        return urls

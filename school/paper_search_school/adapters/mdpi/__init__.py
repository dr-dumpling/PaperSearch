"""MDPI: open-access journals on www.mdpi.com.

The PDF is the article page's ``/pdf``; the page is the source page or derived
from the DOI for the journals whose codes are known.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from ...engine.router import _append_mdpi_candidates
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => ({
    doi: document.querySelector('meta[name="citation_doi"]')?.content || '',
    rows: [...document.querySelectorAll('a[href]')].map(a => ({
        href: a.href,
        label: (a.closest('.html-p')?.innerText || a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
    }))
})"""


def supplement_links_from_page(data: Any, doi: str) -> list[SupplementLink]:
    """MDPI's DOI-bound /sN links redirect to the original supporting files."""
    if not isinstance(data, dict) or str(data.get("doi", "")).strip().lower() != doi.lower():
        return []
    pattern = re.compile(r"/article/" + re.escape(doi) + r"/s[1-9][0-9]*", re.I)
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in data.get("rows", []):
        target = urlparse(str(row.get("href") or ""))
        url = target._replace(fragment="").geturl()
        if (target.scheme == "https" and target.hostname in {"www.mdpi.com", "mdpi.com"}
                and pattern.fullmatch(unquote(target.path)) and url not in seen):
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


@register
class MDPIAdapter(PublisherAdapter):
    publisher = "mdpi"

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_mdpi_candidates(urls, doi, source_url)
        return urls

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_page(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

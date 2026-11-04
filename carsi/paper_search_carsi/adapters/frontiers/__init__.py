"""Frontiers supplementary files on the article's own download panel."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => ({
    doi: document.querySelector('meta[name="citation_doi"]')?.content || '',
    rows: [...document.querySelectorAll('#supplementaryMaterial a[href], #supplementary-material a[href]')].map(a => ({
        href: a.href,
        label: (a.closest('li')?.innerText || a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
    }))
})"""


def supplement_links_from_page(data: Any, doi: str) -> list[SupplementLink]:
    """The panel, citation DOI and file's article ID must all agree."""
    article = re.fullmatch(r"10\.3389/[a-z0-9]+\.\d{4}\.(\d+)", doi, re.I)
    if (not article or not isinstance(data, dict)
            or str(data.get("doi", "")).strip().lower() != doi.lower()):
        return []
    article_id = article.group(1)
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in data.get("rows", []):
        target = urlparse(str(row.get("href") or ""))
        url = target._replace(fragment="").geturl()
        if (target.scheme == "https"
                and re.fullmatch(r"public-pages-files(?:-\d{4})?\.frontiersin\.org", target.hostname or "")
                and unquote(target.path).startswith(f"/articles/{article_id}/file/")
                and url not in seen):
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


@register
class FrontiersAdapter(PublisherAdapter):
    publisher = "frontiers"

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_page(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

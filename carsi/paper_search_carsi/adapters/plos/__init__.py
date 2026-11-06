"""PLOS: open-access journals on journals.plos.org.

The printable PDF is ``/<journal>/article/file?id=<DOI>&type=printable``; the journal
path comes from the source page or the DOI's journal code.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ...engine.router import _append_plos_candidates
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => ({
    href: a.href, label: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
}))"""


def supplement_links_from_rows(rows: list[dict], doi: str) -> list[SupplementLink]:
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in rows:
        target = urlparse(str(row.get("href") or ""))
        query = parse_qs(target.query)
        ids = query.get("id", [])
        if (target.scheme != "https" or target.netloc != "journals.plos.org"
                or not re.fullmatch(r"/[a-z]+/article/file", target.path)
                or query.get("type") != ["supplementary"] or len(ids) != 1
                or not re.fullmatch(re.escape(doi) + r"\.s\d+", ids[0], re.I)):
            continue
        identity = ids[0].lower()
        if identity not in seen:
            seen.add(identity)
            links.append(SupplementLink(target._replace(fragment="").geturl(), str(row.get("label") or "")))
    return links


@register
class PLOSAdapter(PublisherAdapter):
    publisher = "plos"

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_rows(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_plos_candidates(urls, doi, source_url)
        return urls

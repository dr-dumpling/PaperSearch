"""Dove Medical Press: open-access journals on dovepress.com.

No sign-in: the article page links its PDF (``citation_pdf_url``,
``/article/download/<n>``, an address without "pdf" in it: taken as the
article's PDF so that it is opened when the click brings nothing in time; a
20 MB PDF did not arrive within the click's 5 s, 2026-11-03). Its
supplementary files are ``/article/supplementary_file/<n>/<name>``, where
``<n>`` is the number in the DOI (10.2147/JIR.S620421: 620421), often linked
more than once (2026-11-01).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from ..base import PublisherAdapter, SupplementLink, register

_HOSTS = frozenset({"dovepress.com", "www.dovepress.com"})
_NUMBER = re.compile(r"^10\.2147/[a-z]+\.s(\d+)$", re.I)
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href*="/article/supplementary_file/"]')].map(a => ({
    href: a.href, label: (a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 200)}))"""


@register
class DovePressAdapter(PublisherAdapter):
    publisher = "dove medical press"
    metadata_pdf_patterns = ("https://www.dovepress.com/article/download/*",)

    @classmethod
    def profile_pdf_candidate_url(cls, url: str) -> bool | None:
        target = urlparse(url)
        if (target.scheme == "https" and target.netloc.lower() in _HOSTS
                and re.fullmatch(r"/article/download/\d+", target.path)):
            return True
        return None

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        match = _NUMBER.match((doi or "").strip())
        if not match:
            return []
        prefix = f"/article/supplementary_file/{match.group(1)}/"
        links: list[SupplementLink] = []
        rows = page.evaluate(_SUPPLEMENT_ROWS_JS)
        for row in rows if isinstance(rows, list) else []:
            target = urlparse(str(row.get("href") or "") if isinstance(row, dict) else "")
            url = target._replace(fragment="").geturl()
            if (target.scheme == "https" and (target.hostname or "").lower() in _HOSTS
                    and unquote(target.path).startswith(prefix) and url not in {link.url for link in links}):
                links.append(SupplementLink(url, str(row.get("label") or "")))
        return links

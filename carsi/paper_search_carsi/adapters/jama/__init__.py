"""JAMA Network: journals on jamanetwork.com.

The article PDF is ``/journals/<journal>/articlepdf/<article id>/<name>.pdf``,
an opaque id: only the article page's ``citation_pdf_url``, with its
``citation_doi`` exactly this DOI, is a candidate or an accepted PDF
(``binds_pdf_to_citation``, the engine's one rule). The page's own PDF link
(``js-pdfaccess``) checks access before it opens the PDF, so the engine clicks
it rather than opening its address.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from ..base import PublisherAdapter, SupplementLink, register

# The article's "Supplemental content" files, on JAMA's own CDN: .../<code>supp1_prod_....pdf
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('[class*="supplement"] a[href]')].map(a => ({
    href: a.href, label: (a.innerText || a.getAttribute('title') || '').replace(/\\s+/g, ' ').trim().slice(0, 200)}))"""


@register
class JAMAAdapter(PublisherAdapter):
    publisher = "jama"
    validates_article_pdf = True
    binds_pdf_to_citation = True
    keeps_pdf_out_of_downloads = True
    binds_response_url = True
    native_pdf_patterns = ("https://jamanetwork.com/journals/*/articlepdf/*",)
    # Redirects have no body to validate. Native/HTTP final responses retain
    # the chain and decide whether it belongs to the article; do not
    # blacklist the legitimate origin.
    passes_over_redirects = True
    unquotes_supplement_urls = True

    @classmethod
    def names_supplement(cls, url: str) -> bool:
        return bool(re.search(r"supp\d+(?:[_\W]|$)", url))  # JAMA's supplement files: supp1, supp2, ...

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        """The "Supplemental content" files of the article page, on cdn.jamanetwork.com
        and named supp1, supp2, ... (JAMA Network Open, 2026-11-03). Its CDN paths
        name no DOI: only the article page's own supplement section is read."""
        links: list[SupplementLink] = []
        rows = page.evaluate(_SUPPLEMENT_ROWS_JS)
        for row in rows if isinstance(rows, list) else []:
            target = urlparse(str(row.get("href") or "") if isinstance(row, dict) else "")
            name = unquote(target.path).rsplit("/", 1)[-1]
            url = target._replace(fragment="").geturl()
            if (target.scheme == "https" and target.hostname == "cdn.jamanetwork.com" and self.names_supplement(name)
                    and url not in {link.url for link in links}):
                links.append(SupplementLink(url, str(row.get("label") or "") or name))
        return links

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
from urllib.parse import unquote, urljoin, urlparse

from ..base import PublisherAdapter, SupplementLink, register
from ...engine.batch_common import _is_browser_error

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
    # The articlepdf address redirects to Silverchair's watermarked file, the
    # response Chrome has to capture (Firefox read it from PDF.js, 2026-11-07).
    native_pdf_patterns = ("https://jamanetwork.com/journals/*/articlepdf/*", "https://watermark*.silverchair.com/*")
    # Redirects have no body to validate. Native/HTTP final responses retain
    # the chain and decide whether it belongs to the article; do not
    # blacklist the legitimate origin.
    passes_over_redirects = True
    unquotes_supplement_urls = True

    @classmethod
    def names_supplement(cls, url: str) -> bool:
        return bool(re.search(r"supp\d+(?:[_\W]|$)", url))  # JAMA's supplement files: supp1, supp2, ...

    def open_pdf_entry(self, page: Any, result: Any) -> bool | None:
        """The toolbar's access handler uses data-article-url, not its href.
        Click it only when its address is the current DOI's citation PDF."""
        bound = self.d._bound_pdf_urls(page, result.doi) or []
        if not bound:
            return None
        for control in page.locator('.js-pdfaccess[data-article-url]').all()[:8]:
            try:
                target = urljoin(str(page.url), control.get_attribute('data-article-url') or '')
                if target.split('?', 1)[0].split('#', 1)[0] not in bound or not control.is_visible():
                    continue
                if self.d._click_control(page, control, result, 'jama-article-pdf'):
                    self.d._event(result, 'pdf_button_clicked', 'jama-data-article-url')
                    return True
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                self.d._event(result, 'pdf_button_error', type(exc).__name__)
        return None

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

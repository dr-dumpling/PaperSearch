"""Springer Nature (link.springer.com, nature.com, BMC)."""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse

from ...engine.router import is_springer_article_pdf_url, is_supplementary_url
from ..base import PublisherAdapter, SupplementLink, register

# Every supplementary-file link on the page with its item's caption.
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href*="static-content.springer.com/esm/"]')].map(a => {
    const item = a.closest('.c-article-supplementary__item, li, tr');
    const text = s => (s || '').replace(/\\s+/g, ' ').trim();
    return {href: a.href, label: text(item ? item.innerText : a.innerText).slice(0, 240)};
})"""


def supplement_links_from_rows(rows: Any, doi: str) -> list[SupplementLink]:
    """This article's electronic supplementary material:
    ``https://static-content.springer.com/esm/art%3A<DOI>/MediaObjects/<name>_ESM.<ext>``."""
    prefix = "/esm/art:" + (doi or "").lower() + "/"
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        target = urlparse(str(row.get("href") or ""))
        url = target._replace(fragment="").geturl()
        if (doi and target.scheme == "https" and target.hostname == "static-content.springer.com"
                and unquote(target.path).lower().startswith(prefix) and url not in seen):
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


@register
class SpringerNatureAdapter(PublisherAdapter):
    publisher = "springer nature"
    validates_article_pdf = True
    # Springer marks its main PDF anchors as downloads.
    keeps_pdf_out_of_downloads = True
    native_pdf_patterns = (
        "https://link.springer.com/content/pdf/*",
        "https://nature.com/articles/*.pdf*",
        "https://www.nature.com/articles/*.pdf*",
    )
    unquotes_supplement_urls = True

    def login_url(self) -> str | None:
        return "https://link.springer.com/institutional-login"

    @classmethod
    def keeps_pdf_candidate(cls, profile: Any, url: str, doi: str) -> bool:
        return is_springer_article_pdf_url(url, doi) and not is_supplementary_url(profile, url)

    @classmethod
    def belongs_to_article(cls, url: str, doi: str, source_url: str) -> bool | None:
        return is_springer_article_pdf_url(url, doi)
    sso_selectors = ("a:has-text('Log in via an institution')", "button:has-text('Log in via an institution')")

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        return supplement_links_from_rows(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

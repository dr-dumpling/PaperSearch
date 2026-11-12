"""ACS Publications: journals on pubs.acs.org.

Article pages are ``/<journal>/article(-abstract)/<four numbers>(/<name>)``;
an ``/article-abstract/`` page is the article without access and "Subscribed"
by the title means access. Signed in, the header's institution dropdown
(``button.at-institution``) names the school, without the older "access
provided by" text: all three are the shared access rule's
(engine/access_rules.py). The article PDF endpoint (``/article-pdf/``,
``metadata_pdf_patterns``) is the page's ``citation_pdf_url`` when its
``citation_doi`` is this DOI (the engine's one rule, batch_pdf_urls.py); once
known, every other PDF response is refused.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ..base import PublisherAdapter, SupplementLink, register
from ..platforms import silverchair


@register
class ACSAdapter(PublisherAdapter):
    publisher = "acs"
    keeps_pdf_out_of_downloads = True
    metadata_pdf_patterns = ("https://pubs.acs.org/*/article-pdf/*",)
    # ACS's IP-block page names its contact mailbox (moved from the engine, review 2026-11-02).
    block_page_markers = ("ipblock@acs.org",)

    def login_url(self) -> str | None:
        return "https://pubs.acs.org/"

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        # The Supporting Information: the Silverchair platform's rule (ACS's site is
        # Silverchair's since 2026; its PDF rules stay its own above).
        return silverchair.supplement_links(page, doi, frozenset({"pubs.acs.org"}))

    def is_success_article_url(self, url: str) -> bool | None:
        parsed = urlparse(url.lower())
        if parsed.hostname != "pubs.acs.org":
            return False
        # Volume/issue/page article ids, or the DOI form of the 2026 pages
        # ("/jacsat/article-abstract/doi/10.1021/jacs.6c12304/5461066/Investigation-…", 2026-11-02).
        if re.fullmatch(r"/[^/]+/article(?:-abstract)?/(?:(?:\d+/){3}\d+|doi/10\.\d{4,9}/[^/]+/\d+)(?:/[^/]+)?/?", parsed.path):
            return True
        return None

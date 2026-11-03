"""Royal Society of Chemistry: journals on pubs.rsc.org (Silverchair).

Its institution login (2026-11-01): ``/institutional-login`` holds a
SeamlessAccess button that opens RSC's own institution search on
``sso.rsc.org/WAYF``: a search box, the school's entry, then Next.
Without a subscription the abstract page says "You do not currently have
access to this content." (the shared access rule's denial line, also after
the school's login).
Opening an article first passes RSC's silent sign-in check (sso.rsc.org
/connect/authorize and back), which is neither the article nor a login.
Its article PDFs are bound to the article page, and its article pages in
Silverchair's form (``/fd/article/doi/<DOI>/<n>/...``, Faraday Discussions,
2026-11-03) are the platform's (``platforms/silverchair``); its older
``/en/content/articlelanding|articlehtml/<year>/`` pages are its own.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from ...engine.batch_common import open_page
from ..base import register
from ..platforms.silverchair import SilverchairAdapter

# The older article pages: /en/content/articlelanding|articlehtml/<year>/...
_OLD_ARTICLE = re.compile(r"/en/content/article(?:landing|html)/\d{4}/")


def _on_pubs(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == "pubs.rsc.org"


@register
class RSCAdapter(SilverchairAdapter):
    publisher = "rsc"
    site_hosts = frozenset({"pubs.rsc.org"})

    def is_redirect_page(self, url: str) -> bool:
        """RSC's silent sign-in check on the way to the article: sso.rsc.org's
        /connect/authorize, then a form post back through /ExternalAuthentication/."""
        parsed = urlparse(url or "")
        host, path = (parsed.hostname or "").lower(), parsed.path.lower()
        return parsed.scheme == "https" and (
            (host == "sso.rsc.org" and path.startswith("/connect/authorize"))
            or (host == "pubs.rsc.org" and path.startswith("/externalauthentication/")))

    def is_article_page_url(self, url: str) -> bool | None:
        parsed = urlparse((url or "").lower())
        if parsed.scheme == "https" and parsed.hostname == "pubs.rsc.org" and _OLD_ARTICLE.match(parsed.path):
            return True
        return bool(super().is_article_page_url(url))  # any other address: not an article page

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        """The explicit "/institutional-login" link, which avoids generic ancestor
        matching and the unrelated personal OIDC login. It is opened directly: a
        click on it in the header timed out once and failed the article (2026-11-01)."""
        if not _on_pubs(str(getattr(page, "url", "") or "")):
            return None
        for control in page.locator('a[href]').all():
            target = urlparse(urljoin(str(page.url), control.get_attribute("href") or ""))
            if (target.scheme == "https" and target.hostname == "pubs.rsc.org"
                    and target.path == "/institutional-login" and control.is_visible()):
                open_page(page, target.geturl(), timeout_ms=30_000)
                self.d._event(result, "sso_entry_clicked", "rsc-official-institution-control")
                return True
        return False

    def is_institution_chooser(self, url: str) -> bool:
        parsed = urlparse(url or "")
        return (parsed.scheme == "https" and (parsed.hostname or "").lower() == "sso.rsc.org"
                and parsed.path.lower() == "/wayf")


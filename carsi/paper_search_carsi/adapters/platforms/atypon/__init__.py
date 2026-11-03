"""Atypon (Literatum) journal sites: the institution login at ``/action/ssostart``.

A site type shared by publishers on the platform (Taylor & Francis, AHA
journals, Neurology); each publisher's adapter names its hosts. The article's
access box links to ``/action/ssostart`` with this article as ``redirectUri``
(or ``uri``); a site whose article page has no such link (NEJM: only its own
"SIGN IN", whose page leads to the chooser, 2026-11-03) gets the chooser's
address with this article as ``redirectUri``. A link with an ``idp`` parameter
goes straight to one identity provider (AHA's member login on ahajournals.org)
and is never used. The
chooser is either a federation dropdown (``#shib-search--fed``, Taylor &
Francis: CARSI is selected here, then the school) or only a search box
("Type the name of your institution", ahajournals.org and neurology.org,
2026-11-01), where the engine types and chooses the configured school.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

from ....engine.batch_common import _is_browser_error, open_page
from ...base import PublisherAdapter, SupplementLink, register

_ARTICLE = re.compile(r"/doi/(?:(?:abs|full|pdf|epdf|pdfdirect|reader)/)?(10\.\d{4,9}/[^?#]+)", re.I)
_CARSI = "China CERNET Federation (CARSI)"
# Supplement files: /doi/suppl/<DOI>/suppl_file/<name>, with the link text.
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href*="/doi/suppl/"]')].map(a => ({
    href: a.href, label: (a.innerText || a.getAttribute('title') || '').replace(/\\s+/g, ' ').trim().slice(0, 200)}))"""
# The page's institution-login links, read at once: a link-by-link lookup waited
# 30 s on a page still navigating after a silent IdP return (ASCE, 2026-11-02).
_SSOSTART_LINKS_JS = """() => [...document.querySelectorAll('a[href*="/action/ssostart"]')].map(a => ({
    href: a.href, visible: a.getClientRects().length > 0 && getComputedStyle(a).visibility !== 'hidden'}))"""


class AtyponAdapter(PublisherAdapter):
    """Shared rules of Atypon sites; subclasses set ``site_hosts`` (not ``hosts``: that selects a journal-level adapter)."""

    site_hosts: frozenset[str] = frozenset()
    entry_event = "atypon-institution-link"

    def _on_site(self, url: str) -> bool:
        parsed = urlparse(url or "")
        return parsed.scheme == "https" and (parsed.hostname or "").lower() in self.site_hosts

    def _chooser(self, url: str) -> bool:
        return self._on_site(url) and urlparse(url).path == "/action/ssostart"

    def is_article_page_url(self, url: str) -> bool | None:
        return self._on_site(url) and bool(_ARTICLE.match(urlparse(url).path))

    def is_institution_chooser(self, url: str) -> bool:
        return self._chooser(url)

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        """Files under ``/doi/suppl/<this DOI>/suppl_file/``; a supplement link of
        another article on the page (AHA, 2026-11-01) is not this article's."""
        links: list[SupplementLink] = []
        rows = page.evaluate(_SUPPLEMENT_ROWS_JS)
        prefix = f"/doi/suppl/{doi.lower()}/suppl_file/"
        for row in rows if isinstance(rows, list) and doi else []:
            target = urlparse(str(row.get("href") or "") if isinstance(row, dict) else "")
            url = target._replace(fragment="").geturl()
            if (self._on_site(url) and unquote(target.path).lower().startswith(prefix)
                    and url not in {link.url for link in links}):
                links.append(SupplementLink(url, str(row.get("label") or "")))
        return links

    def institution_chooser_open(self, page: Any) -> bool:
        return self._chooser(str(getattr(page, "url", "") or "")) and page.locator("select#shib-search--fed").is_visible()

    def institution_link(self, page: Any, doi: str) -> str:
        """The access box's institution login: the chooser with this article as
        its redirect, shown to a reader without access; never a link to one IdP."""
        try:
            links = page.evaluate(_SSOSTART_LINKS_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return ""
        for link in links if isinstance(links, list) else []:
            if not isinstance(link, dict):
                continue
            target = urlparse(urljoin(str(page.url), str(link.get("href") or "")))
            query = parse_qs(target.query)
            redirect = unquote((query.get("redirectUri") or query.get("uri") or [""])[0]).lower()
            if (doi and self._chooser(target.geturl()) and "idp" not in query
                    and doi.lower() in redirect and link.get("visible")):
                return target.geturl()
        return ""

    def chooser_url(self, url: str) -> str:
        """The platform's institution chooser for the article at ``url``, with it
        as ``redirectUri``; "" off an article page of this site."""
        if not self.is_article_page_url(url):
            return ""
        parsed = urlparse(url)
        return f"https://{parsed.hostname}/action/ssostart?redirectUri={quote(parsed.path, safe='')}"

    def looks_logged_out(self, page: Any, url: str, text: str) -> bool | None:
        """The access box's institution login for this article: Atypon shows it
        only to readers without access, with no offer text the shared rule knows
        (Medical Teacher, 2026-11-01). An open article shows it too (NXI,
        2026-11-01), but its open-access icon has answered before this is asked."""
        match = _ARTICLE.match(urlparse(url or "").path) if self.is_article_page_url(url) else None
        if not match:
            return None
        return True if self.institution_link(page, unquote(match.group(1))) else None

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        # On the chooser the school is chosen there; no other entry is clicked.
        if self._chooser(str(getattr(page, "url", "") or "")):
            return False
        d = self.d
        # The access box's link, else the chooser's address: the same page (NEJM).
        target = ((self.institution_link(page, result.doi) or self.chooser_url(str(getattr(page, "url", "") or "")))
                  if result is not None else "")
        if not target or (d.config.get("publisher_institution_federation") == "carsi"
                          and not d._manual_institution_target_allowed(target)):
            return None
        # Opened, not clicked: a click soon after the article loaded left the
        # page on the article (Neurological Research, cold start 2026-11-01, twice).
        open_page(page, target, timeout_ms=30_000)
        d._event(result, "sso_entry_clicked", self.entry_event)
        return True

    def choose_institution(self, page: Any, result: Any) -> bool | None:
        d = self.d
        if not self._chooser(str(getattr(page, "url", "") or "")):
            return False
        federation = page.locator("select#shib-search--fed")
        if not federation.is_visible():
            return None  # a search box only: the engine chooses the school there
        changed = federation.locator("option:checked").inner_text() != _CARSI
        if changed:
            # Changed by the user only on the very page where CARSI was chosen; a
            # chooser reloaded with its first federation is chosen again (the
            # engine's one rule, review 2026-11-02).
            here = d._federation_choice_page(page, result)
            if here is None:
                return False
            federation.select_option(label=_CARSI, timeout=5_000)
            d._federation_chosen(result, here, "carsi")
        # The federation is set here; the configured school is then chosen in
        # the school list by the engine's assistance (2026-11-01: the configured
        # CARSI school was chosen automatically), else by the user.
        if not any(event["state"] == "institution_selection_required" for event in result.events):
            d._event(result, "institution_selection_required", "carsi")
        return changed

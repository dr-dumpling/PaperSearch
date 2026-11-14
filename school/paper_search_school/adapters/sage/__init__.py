"""Sage Journals: every journal on journals.sagepub.com, DOI paths.

One site type so far. The institution login is the "Institution" link in the
article's access panel (``/action/ssostart`` with the article as redirectUri).
The panel's "Access via <school> is not available as they do not subscribe to
Sage Journals content." is the shared access rule's denial line.
A new site type gets its own module here, as Elsevier's do.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

from ...engine.batch_common import _is_browser_error, open_page
from ..base import PublisherAdapter, SupplementLink, register

_ARTICLE = re.compile(r"/doi/(?:(?:abs|full|pdf|epdf)/)?10\.1177/")
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href*="/suppl_file/"]')]
    .map(a => ({href: a.href, label: (a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 200)}))"""
_PANEL_TEXT_JS = """() => { const panel = document.querySelector('#core-collateral-purchase-access');
    return panel ? panel.innerText.replace(/\\s+/g, ' ').trim().slice(0, 300) : 'no access panel'; }"""
SSO_START = "https://journals.sagepub.com/action/ssostart"


@register
class SageAdapter(PublisherAdapter):
    publisher = "sage"

    def is_article_page_url(self, url: str) -> bool | None:
        parsed = urlparse((url or "").lower())
        return (parsed.scheme == "https" and parsed.hostname == "journals.sagepub.com"
                and bool(_ARTICLE.match(parsed.path)))

    def choose_institution(self, page: Any, result: Any) -> bool | None:
        """Sage's own list knows no CARSI school (2026-11-01: no CARSI federation,
        the configured school not found). When the configured school is not in it, sign in
        through OpenAthens, whose "Find your institution" does list it."""
        url = str(getattr(page, "url", "") or "")
        parsed = urlparse(url)
        if (parsed.hostname != "journals.sagepub.com" or parsed.path != "/action/ssostart"
                or "idp" in parse_qs(parsed.query)
                or not any(e["state"] == "auto_institution_not_found" and e.get("detail", "").endswith(f"@ {url}")
                           for e in result.events)):
            return None
        for control in page.locator('a[href*="/action/ssostart"][href*="idp="]').all():
            target = urlparse(urljoin(url, control.get_attribute("href") or ""))
            idp = parse_qs(target.query).get("idp", [""])[0]
            if (target.hostname == "journals.sagepub.com" and "openathens" in idp.lower()
                    and control.is_visible()):
                open_page(page, target.geturl(), timeout_ms=30_000)
                self.d._event(result, "sso_entry_clicked", "sage-openathens")
                return True
        return None

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        """``/doi/suppl/<this DOI>/suppl_file/<name>`` in the Supplemental Material section."""
        prefix = f"/doi/suppl/{(doi or '').lower()}/suppl_file/"
        links: list[SupplementLink] = []
        rows = page.evaluate(_SUPPLEMENT_ROWS_JS)
        for row in rows if isinstance(rows, list) and doi else []:
            target = urlparse(str(row.get("href") or "") if isinstance(row, dict) else "")
            url = target._replace(fragment="").geturl()
            if (target.scheme == "https" and target.hostname == "journals.sagepub.com"
                    and unquote(target.path).lower().startswith(prefix)
                    and url not in {link.url for link in links}):
                links.append(SupplementLink(url, str(row.get("label") or "")))
        return links

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        d = self.d
        parsed = urlparse(str(getattr(page, "url", "") or ""))
        if (parsed.hostname or "").lower() != "journals.sagepub.com" or not parsed.path.startswith("/doi/"):
            return False
        if not page.locator('a[href*="/action/ssostart"]').count():
            for access in page.locator('a[href$="#core-collateral-purchase-access"]').all():
                if access.is_visible():
                    try:
                        access.click(timeout=5_000, no_wait_after=True)
                    except Exception as exc:
                        if not _is_browser_error(exc, "TimeoutError"):
                            raise
                        # Covered by an overlay right after a Cloudflare
                        # check: the in-page anchor only toggles the panel.
                        access.evaluate("el => el.click()")
                        d._event(result, "sage_access_click_dispatched")
                    if d._institution_pdf_entitlement_missing(page):
                        return False  # the panel names the school and says it does not subscribe
                    # The access panel loads asynchronously and can take
                    # well over 5 s right after a Cloudflare check. Wait for
                    # the institution link, opening the "Institution" tab
                    # once if the panel shows it first.
                    institution_opened = False
                    deadline = time.time() + 15
                    while (time.time() < deadline
                           and not page.locator('a[href*="/action/ssostart"]').count()):
                        institution = page.get_by_role("button", name="Institution", exact=True)
                        if not institution_opened and institution.count() and institution.first.is_visible():
                            institution_opened = True
                            # Open already: a click would close it, and under an overlay it
                            # timed out and ended the article (2026-11-14).
                            if institution.first.get_attribute("aria-expanded") != "true":
                                try:
                                    institution.first.click(timeout=5_000, no_wait_after=True)
                                except Exception as exc:
                                    if not _is_browser_error(exc, "TimeoutError"):
                                        raise
                                    institution.first.evaluate("el => el.click()")  # covered, as above
                        page.wait_for_timeout(500)
                    if not page.locator('a[href*="/action/ssostart"]').count():
                        d._event(result, "sage_institution_link_missing", self._panel_text(page))
                        return self._open_sso_start(page, result)
                    break
        # The publisher keeps this official institution link in a hidden
        # access accordion. Follow only the observed link, returning to this
        # article: since 2026-11 its redirectUri is the site's home page.
        article = urlparse(str(page.url))._replace(fragment="").geturl()
        for control in page.locator('a[href*="/action/ssostart"]').all():
            href = control.get_attribute("href") or ""
            target = urlparse(urljoin(str(page.url), href))
            query = parse_qs(target.query)
            redirects = query.get("redirectUri", [])
            home = all(urlparse(value).hostname == "journals.sagepub.com" and urlparse(value).path in ("", "/")
                       for value in redirects)
            if (target.scheme == "https" and target.hostname == "journals.sagepub.com"
                    and target.path == "/action/ssostart" and result is not None
                    and (d.federation is None or d._manual_institution_target_allowed(target.geturl()))
                    and redirects and (home or any(d._url_matches_record(value, result.doi) for value in redirects))):
                if home:
                    query["redirectUri"] = [article]
                    target = target._replace(query=urlencode(query, doseq=True))
                open_page(page, target.geturl(), timeout_ms=30_000)
                d._event(result, "sso_entry_clicked", "sage-institution-control")
                return True
        d._event(result, "sage_institution_link_unusable", str(page.url)[:160])
        return False

    def _open_sso_start(self, page: Any, result: Any) -> bool:
        """The panel came up without its institution link (The American Surgeon in
        a batch, 2026-11-01: re-clicking "Get access" waited out the five-minute
        user wait; the same article alone listed the link). The link is the same
        on every article, so open it directly, returning to this article."""
        d = self.d
        article = urlparse(str(page.url))._replace(fragment="").geturl()
        target = f"{SSO_START}?{urlencode({'redirectUri': article})}"
        if result is None or (d.federation is not None and not d._manual_institution_target_allowed(target)):
            return False
        open_page(page, target, timeout_ms=30_000)
        d._event(result, "sso_entry_clicked", "sage-institution-address")
        return True

    @staticmethod
    def _panel_text(page: Any) -> str:
        try:
            return str(page.evaluate(_PANEL_TEXT_JS) or "")
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return ""

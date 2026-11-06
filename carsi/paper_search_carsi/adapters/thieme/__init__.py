"""Thieme: journals on thieme-connect.de and thieme-connect.com.

Article pages are ``/products/ejournals/(abstract|fulltext|pdf)/10.1055/<id>``.
The institution login runs on profile.thieme.de: the login page links the
Shibboleth search, which links the federation chooser
(``/HTML/sso/ejournals/shibboleth.htm``, "China (CARSI)"). Its session
label ``#institutionName``, its "Buy Article" offer and the ``type=auth_denied``
login page a PDF the institution may not read is sent to are the shared access
rule's (engine/access_rules.py).
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

from ...engine.router import is_thieme_article_pdf_url
from ...engine.batch_common import _is_browser_error, open_page
from ..base import PublisherAdapter, SupplementLink, register

_HOSTS = frozenset({"thieme-connect.de", "www.thieme-connect.de", "thieme-connect.com", "www.thieme-connect.com"})

_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => ({
    href: a.href, label: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
}))"""


def supplement_links_from_rows(rows: list[dict], doi: str) -> list[SupplementLink]:
    stem = doi.lower().replace(".", "-").replace("/", "-")
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in rows:
        target = urlparse(str(row.get("href") or ""))
        path = unquote(target.path).lower()
        url = target._replace(fragment="").geturl()
        if (target.scheme == "https" and target.netloc.lower() in _HOSTS
                and re.fullmatch(r"/media/[^/]+/\d+/supmat/" + re.escape(stem) + r"_[^/]+", path)
                and url not in seen):
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


@register
class ThiemeAdapter(PublisherAdapter):
    publisher = "thieme"
    validates_article_pdf = True
    binds_response_url = True
    requires_institution_entry = True

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_rows(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

    @classmethod
    def profile_pdf_candidate_url(cls, url: str) -> bool | None:
        return is_thieme_article_pdf_url(url)

    def is_success_article_url(self, url: str) -> bool | None:
        parsed = urlparse(url.lower())
        return (parsed.scheme == "https" and parsed.netloc in _HOSTS
                and bool(re.fullmatch(r"/products/ejournals/(?:abstract|fulltext|pdf)/10\.1055/[^/]+", parsed.path)))

    def is_article_pdf_url(self, url: str, doi: str = "") -> bool | None:
        return is_thieme_article_pdf_url(url, doi) and not self.d._is_supplementary_url(url)

    def is_institution_chooser(self, url: str) -> bool:
        """The Shibboleth search and federation chooser on profile.thieme.de
        (``/HTML/sso/ejournals/shibboleth*``; moved from the engine's chooser list,
        review 2026-11-02). Its login page with a password field stays the user's."""
        parsed = urlparse(url or "")
        return (parsed.scheme == "https" and parsed.hostname == "profile.thieme.de"
                and parsed.path.startswith("/HTML/sso/ejournals/shibboleth"))

    def own_institution_entry(self, page: Any, result: Any) -> bool | None:
        """The official federation links, followed from the article to the chooser; never account forms."""
        d = self.d
        if result is None:
            return False
        current = urlparse(str(page.url))
        login_path = "/HTML/sso/THIEME/login.htm"
        chooser_path = "/HTML/sso/ejournals/shibboleth.htm"
        if (current.scheme != "https" or current.hostname not in {
                "www.thieme-connect.de", "thieme-connect.de",
                "www.thieme-connect.com", "thieme-connect.com", "profile.thieme.de"}):
            return False

        def observed_link(path: str, *, visible: bool) -> str:
            for link in page.locator("a[href]").all():
                target = urlparse(urljoin(str(page.url), (link.get_attribute("href") or "").strip()))
                if (target.scheme == "https" and target.netloc == "profile.thieme.de"
                        and target.path == path and (not visible or link.is_visible())):
                    return target.geturl()
            return ""

        if current.hostname != "profile.thieme.de":
            if not (d._is_success_article_url(str(page.url)) and d._url_matches_record(str(page.url), result.doi)):
                return False
            login = observed_link(login_path, visible=False)
            if not login:
                return False
            target = urlparse(login)
            query = parse_qs(target.query)
            if not set(query) <= {"hook_url", "rdeLocaleAttr"}:
                return False
            # The observed login link may point back to alerts. Return only
            # to this public article; do not carry alert actions or tokens.
            query["hook_url"] = [current._replace(query="", fragment="").geturl()]
            open_page(page, target._replace(query=urlencode(query, doseq=True), fragment="").geturl(),
                      timeout_ms=15_000)

        for source, destination in (
            (login_path, "/HTML/sso/ejournals/shibboleth-idpsearch.htm"),
            ("/HTML/sso/ejournals/shibboleth-idpsearch.htm", chooser_path),
        ):
            current = urlparse(str(page.url))
            if current.hostname != "profile.thieme.de" or current.path != source:
                continue
            # Preserve an operator's input if this page was already in use.
            if page.evaluate("""() => [...document.querySelectorAll('input[type="text"],input[type="email"],input[type="password"]')]
                    .some(el => el.checkVisibility() && el.value.length > 0)"""):
                return False
            page.locator(f'a[href*="{destination}"]').first.wait_for(state="visible", timeout=5_000)
            link = observed_link(destination, visible=True)
            if not link:
                return False
            open_page(page, link, timeout_ms=15_000)
        current = urlparse(str(page.url))
        if (current.scheme == "https" and current.netloc == "profile.thieme.de"
                and current.path == chooser_path):
            d._event(result, "sso_entry_clicked", "thieme-official-federation-entry")
            return True
        return False

    # The federation step's Continue, per item: the institution list can take a
    # second one (the page came back on this step with CARSI chosen, 2026-11-02).
    CONTINUE_TRIES = 3
    CONTINUE_GAP_SEC = 5

    def choose_institution(self, page: Any, result: Any) -> bool | None:
        """On the federation chooser: China (CARSI), then the form's own Continue,
        again while the page stays on this step (``CONTINUE_TRIES``)."""
        d = self.d
        current = urlparse(str(page.url))
        if (current.scheme != "https" or current.netloc != "profile.thieme.de"
                or current.path != "/HTML/sso/ejournals/shibboleth.htm"):
            return False
        federation = page.locator("select#federation")
        if not federation.is_visible():
            return False
        label = "China (CARSI)"
        if label not in federation.locator("option").all_text_contents():
            return False
        changed = federation.locator("option:checked").inner_text() != label
        if changed:
            # Changed by the user only on the very page where CARSI was chosen: Thieme
            # reloads the step with its first federation selected after a Continue
            # (2026-11-02), a new page chosen again (the engine's one rule).
            here = d._federation_choice_page(page, result)
            if here is None:
                return False
            federation.select_option(label=label, timeout=5_000)
            d._federation_chosen(result, here, "carsi")
        # Only the form's own fields: a cookie panel's search box (OneTrust's vendor
        # search on this page, 2026-11-02) is not the page asking for the school.
        school_box = federation.locator("xpath=ancestor::form[1]").locator(
            "input[type='text']:visible, input[type='search']:visible, input:not([type]):visible")
        pressed = sum(event["state"] == "institution_federation_continue" for event in result.events)
        if (d.institution_query and not school_box.count() and pressed < self.CONTINUE_TRIES
                and time.time() - getattr(result, "_federation_continue_at", 0.0) >= self.CONTINUE_GAP_SEC):
            # Automated policy: on the federation-only step the form's own
            # Continue leads to the institution list, where the configured
            # school is chosen. A page that also asks for the school is left
            # to the school assistance (never submitted half-filled).
            button = page.locator(
                "button:has-text('Continue'), input[type='submit'][value='Continue']").first
            try:
                if (button.is_visible(timeout=1_500) is True
                        and d._click_control(page, button, result, "Thieme federation Continue")):
                    result._federation_continue_at = time.time()
                    d._event(result, "institution_federation_continue", "carsi")
                    return True
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
        if not any(event["state"] == "institution_selection_required" for event in result.events):
            d._event(result, "institution_selection_required", "carsi")
        return changed

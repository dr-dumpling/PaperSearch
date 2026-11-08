"""What the page says about access: signed out, not subscribed, the institution session, the article page.

Part of ``PublisherBatchDownloader`` (batch.py), which combines the mixins."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse

from . import access_rules

from .batch_common import (
    open_page,
    settle,
    DownloadResult,
    PublisherAccessBlocked,
    ArticleNotYetPublished,
    PublisherContentError,
    PublisherPlatformUnsupported,
    _ACCESS_GATE_JS,
    _is_browser_error,
)

# The bare body a publisher's front proxy serves when the server behind it did
# not answer: Envoy, nginx and similar. Nothing else is on such a page.
_GATEWAY_ERROR_MARKERS = (
    "upstream connect error or disconnect/reset before headers",
    "502 bad gateway", "503 service unavailable", "503 service temporarily unavailable",
    "504 gateway time-out", "504 gateway timeout",
)


class AccessMixin:
    """What the page says about access: signed out, not subscribed, the institution session, the article page."""

    @staticmethod
    def _access_gate_visible(page: Any) -> bool:
        try:
            return page.evaluate(_ACCESS_GATE_JS) is True
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return False

    def _gateway_error_text(self, page: Any) -> str:
        """The text of a front proxy's bare error page (the publisher's server did
        not answer in time); empty for any other page."""
        text = self._body_text(page, limit=400)
        if len(text) > 300:
            return ""
        return text if any(marker in text.lower() for marker in _GATEWAY_ERROR_MARKERS) else ""

    def _raise_on_publisher_content_error(self, page: Any) -> None:
        self._raise_on_publisher_access_blocked(page)
        platform = self.adapter.unsupported_platform(page)
        if platform:
            raise PublisherPlatformUnsupported(platform)
        if self.adapter.content_error(page):
            raise PublisherContentError(self._title(page)[:160] or "publisher_content_error")

    def _return_from_other_article(self, page: Any, result: DownloadResult) -> None:
        """Open this article again, once, when the login came back to another
        article's page (an identity provider can keep an earlier item's return URL)."""
        if (any(e["state"] == "other_article_return" for e in result.events)
                or not self.adapter.is_other_article(page, result.doi)):
            return
        self._event(result, "other_article_return", str(getattr(page, "url", "") or "")[:160])
        try:
            open_page(page, result.article_url, timeout_ms=60_000)
            settle(page, 3_000)
            self._dismiss_cookie_banners(page, result)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "other_article_return_error", type(exc).__name__)

    def _return_to_article_after_login(self, page: Any, result: DownloadResult) -> None:
        """After this item's school login the tab may rest on another page of the
        publisher: JAMA's login came back to store.jamanetwork.com/index.aspx and
        the PDF step read that page's metadata (2026-11-02), Wiley's once to
        /search/advanced. Open the article again, once, before the PDF is tried."""
        url = str(getattr(page, "url", "") or "")
        if (getattr(result, "_article_reopened_after_login", False) or not self._school_login_done()
                or not url.startswith("http") or self._is_auth_page(url) or self._challenge_shell(page)
                or self._on_this_article(page, result)):
            return
        result._article_reopened_after_login = True
        self._event(result, "record_article_return",
                    f"after the school login: {url[:160]} | {self._title(page)[:80]} -> {result.article_url[:160]}")
        try:
            open_page(page, result.article_url)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "record_article_return_error", f"{type(exc).__name__}: {str(exc)[:160]}")
            return
        settle(page, 3_000)
        self._wait_past_redirect_page(page, result)
        self._wait_for_challenge(page, result)
        self._dismiss_cookie_banners(page, result)

    def _on_this_article(self, page: Any, result: DownloadResult) -> bool:
        """The tab shows this item's article: its address names the DOI, or the PII
        or article id of a page this item already had as its article (``final_url``,
        where its login started), or the page's citation metadata names the DOI."""
        url = str(getattr(page, "url", "") or "")
        if self._url_matches_record(url, result.doi):
            return True
        address = unquote(url).lower()
        had = [result.final_url] + [str(e.get("detail") or "") for e in result.events if e["state"] == "sso_start"]
        doi = result.doi.lower()
        for known in dict.fromkeys(u for u in had if u.startswith("http") and self._is_success_article_url(u)):
            if any(key in address for key in self._article_keys(known, doi)):
                return True
        return doi in self._citation_dois(page)

    def _citation_dois(self, page: Any) -> set[str]:
        """The page's ``citation_doi`` values, lower case, without a resolver prefix."""
        return {re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value).strip().lower())
                for value in self._page_pdf_links(page).get("dois") or ()}

    def _return_to_record_article_if_needed(self, page: Any, result: DownloadResult, doi: str) -> bool:
        if not self.adapter.returns_to_record_article and not self.adapter.returns_from_home_page:
            return False
        current_url = str(getattr(page, "url", "") or "")
        if not current_url or self._url_matches_record(current_url, doi):
            return False
        if self.adapter.returns_from_home_page:
            # A completed login may land at the publisher homepage. Return
            # once, without treating that homepage as an accessible article
            # or interfering with the institution chooser / active login.
            if (urlparse(current_url).path not in {"", "/"}
                    or any(e["state"] == "record_article_return" for e in result.events)):
                return False
        host = (urlparse(current_url).netloc or "").lower()
        if not any(host == domain or host.endswith(f".{domain}") for domain in self.profile.base_domains):
            return False
        try:
            open_page(page, result.article_url, timeout_ms=60_000)
            self._event(result, "record_article_return", result.article_url)
            settle(page, 3_000)
            if not self._wait_for_challenge(page, result):
                return False
            self._dismiss_cookie_banners(page, result)
            return True
        except Exception as exc:
            self._event(result, "record_article_return_error", f"{type(exc).__name__}: {exc}")
            return False

    @staticmethod
    def _url_matches_record(url: str, doi: str) -> bool:
        lower_url = str(url or "").lower()
        doi_lower = doi.lower()
        return doi_lower in lower_url or doi_lower.replace("/", "%2f") in lower_url

    def _publisher_access_blocked(self, page: Any) -> bool:
        title = self._title(page).lower()
        if "cloudflare" not in title:
            return False
        text = " ".join(self._body_text(page, 4000).lower().split())
        return ("sorry, you have been blocked" in text
                and "you are unable to access" in text)

    def _raise_on_publisher_access_blocked(self, page: Any) -> None:
        if self._publisher_access_blocked(page):
            raise PublisherAccessBlocked("publisher_access_blocked")

    def _is_auth_page(self, url: str) -> bool:
        """A login, identity-provider or school-chooser page (access_rules.is_auth_url)."""
        return (access_rules.is_auth_url(url, self.profile.auth_url_markers)
                or self._is_idp_host(urlparse(url).netloc) or self._is_federation_chooser(url))

    def _access_probe(self, page: Any) -> dict:
        """The page's labels, badges, access boxes and fields (access_rules.PROBE_JS)."""
        try:
            probe = page.evaluate(access_rules.PROBE_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return {}
        return probe if isinstance(probe, dict) else {}

    def _access_snapshot(self, page: Any) -> SimpleNamespace:
        """The page's whole visible text, by lines, and its probe, read once. Text the
        browser could not give (the page navigating) is said so in ``unreadable``:
        a page not read is not a page without evidence (review 2026-11-02)."""
        from ..browser.preview import observe_page
        observe_page(page)
        unreadable = ""
        try:
            text = page.locator("body").inner_text(timeout=3_000)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            text = ""
            unreadable = f"page text unreadable ({type(exc).__name__}: {(str(exc).splitlines() or [''])[0][:120]})"
        text = text if isinstance(text, str) else ""
        return SimpleNamespace(url=str(getattr(page, "url", "") or ""), text=text, unreadable=unreadable,
                               lines=access_rules.lines_of(text), probe=self._access_probe(page))

    def _access_decision(self, page: Any, snapshot: SimpleNamespace | None = None) -> tuple[str, str, str]:
        """``(verdict, basis, evidence)`` for the page (access_rules), in this order:
        out on a login, IdP or chooser page (basis ``login_page``); in with the
        institution's session (``session``); out on an abstract-only view
        (``abstract``); in when the page lets the reader read (``reader``); the
        adapter's own rule for a page type it knows (``site``); out on a password
        field, a denial or an offer (``closed``); otherwise unknown (the PDF decides),
        whose evidence says when the page's text could not be read."""
        url = str(getattr(page, "url", "") or "")
        if self._is_auth_page(url):
            return access_rules.OUT, "login_page", url[:160]
        snap = snapshot or self._access_snapshot(page)
        if access_rules.not_yet_published(str(getattr(snap, "text", "") or "")):
            raise ArticleNotYetPublished(url[:160])
        if self._institution_session(page, snap) == "ours":
            names = access_rules.session_names(snap.lines)
            label = next((str(l) for l in snap.probe.get("labels") or () if not access_rules.is_generic_label(str(l))), "")
            return access_rules.IN, "session", (f"session line: {names[0]}" if names else f"institution label: {label}")[:200]
        if access_rules.abstract_only(url):
            return access_rules.OUT, "abstract", url[:160]
        reader = access_rules.reader_access(snap.lines, snap.text, snap.probe)
        if reader:
            return access_rules.IN, "reader", reader
        special = self.adapter.looks_logged_out(page, url, " ".join(snap.text.split()).lower())
        if special is not None:
            return (access_rules.OUT if special else access_rules.IN), "site", type(self.adapter).__name__
        closed = (("password field" if snap.probe.get("password") else "")
                  or access_rules.denial_evidence(url, snap.lines, snap.probe)[0]
                  or access_rules.offer_evidence(snap.lines, snap.probe))
        if closed:
            return access_rules.OUT, "closed", closed
        return access_rules.UNKNOWN, "", getattr(snap, "unreadable", "")

    def _access_verdict(self, page: Any, snapshot: SimpleNamespace | None = None) -> str:
        """``in``, ``out`` or ``unknown`` (``_access_decision``)."""
        return self._access_decision(page, snapshot)[0]

    def _looks_logged_out(self, page: Any) -> bool:
        return self._access_verdict(page) == access_rules.OUT

    def _article_access_available(self, page: Any) -> bool:
        """The article page no longer says the reader is signed out: the PDF
        decides. In the login that follows a failed PDF, only the institution's
        session or a completed login round trip count."""
        # A verification/error page can retain the exact article URL. Its
        # lack of a sign-in button is not evidence of full-text access.
        if page.is_closed() is True:
            return False
        self._raise_on_publisher_content_error(page)
        if self._is_challenge_page(page):
            return False
        if self._institution_pdf_entitlement_missing(page):
            return False
        if not self._is_success_article_url(getattr(page, "url", "")):
            return False
        verdict, basis, _ = self._access_decision(page)
        if verdict == access_rules.OUT:
            return False
        if basis == "session" or self._school_login_done():
            return True
        # The login that follows a failed PDF waits for the school's login itself.
        return not getattr(getattr(self, "_item_result", None), "_pdf_retry_login", False)

    def _school_login_done(self) -> bool:
        """This item reached its IdP; selecting a school is only an attempt."""
        result = getattr(self, "_item_result", None)
        return result is not None and (getattr(result, "_visited_idp", False) or getattr(result, "_login_round_trip", False))

    def _institution_pdf_entitlement_missing(self, page: Any, snapshot: SimpleNamespace | None = None) -> bool:
        """The article page denies access (access_rules.denial_evidence) to a
        reader who is the institution: its session shows, this item has been
        through the school's login, or the denial names the configured school."""
        url = str(getattr(page, "url", "") or "")
        if not self._is_success_article_url(url) or self._is_auth_page(url):
            return False
        if snapshot is None and self._is_challenge_page(page):
            return False
        snap = snapshot or self._access_snapshot(page)
        evidence, named = access_rules.denial_evidence(url, snap.lines, snap.probe)
        if not evidence:
            return False
        # A supplied snapshot already rules out a denial without live reads.
        # Only a possible denial needs the verification guard; re-reading a
        # slow article here otherwise delays even confirmed public access.
        if snapshot is not None and self._is_challenge_page(page):
            return False
        if self._school_login_done() or self._institution_session(page, snap) == "ours":
            return True
        return bool(named) and self._names_configured_school(named)

    def _no_access_after_login(self, page: Any, result: DownloadResult) -> str:
        """Evidence that the article page, after this item's school login, still
        denies the article, shows only its abstract, offers it for sale or is the
        site's signed-out page type; "" otherwise, and while the site's own login
        pages remain to be opened (an Elsevier journal's site signs in on itself,
        then on ScienceDirect) or the login site's own article remains to be tried
        (``_return_from_login_site``). Not the "Access through <school>" gate: that
        is a remembered school not signed in on this site."""
        url = str(getattr(page, "url", "") or "")
        if (not self._is_success_article_url(url) or self._is_auth_page(url)
                or self._is_challenge_page(page) or not self._school_login_done()):
            return ""
        opened = {e.get("detail") for e in result.events if e["state"] == "login_page_opened"}
        if any(target not in opened for target in self.adapter.login_page_urls(page)):
            return ""
        if getattr(result, "_login_site_fallback", ""):
            # Back on the journal's site after signing in on the login site: only its
            # abstract there, and the login site's article not tried yet. jacc.org's
            # abstract after ScienceDirect's login ended the item before the fallback
            # took ScienceDirect's PDF (2026-11-03).
            return ""
        snap = self._access_snapshot(page)
        if access_rules.reader_access(snap.lines, snap.text, snap.probe):
            return ""
        denial = access_rules.denial_evidence(url, snap.lines, snap.probe)[0]
        if denial:
            return denial
        if access_rules.abstract_only(url):
            return f"abstract-only view: {url[:160]}"
        offer = access_rules.offer_evidence(snap.lines, snap.probe, gate=False)
        if offer:
            return offer
        # The site's own signed-out page type (Atypon's access box still offering
        # this article's institution login).
        if self.adapter.looks_logged_out(page, url, " ".join(snap.text.split()).lower()) is True:
            return f"{type(self.adapter).__name__}: still shown without access"
        return ""

    def _denied_after_login(self, page: Any) -> bool:
        """After this item's school login the PDF request ended on a denial address
        (Thieme sends it to its login page with type=auth_denied)."""
        url = str(getattr(page, "url", "") or "").lower()
        return self._school_login_done() and any(marker in url for marker in access_rules.DENIAL_URL_MARKERS)

    # Events after which this paper has chosen the configured school itself.
    _SCHOOL_CHOSEN = frozenset({"institution_selected", "auto_institution_entry"})
    # Words that do not tell schools apart.
    _INSTITUTION_FILLER = frozenset({"university", "univ", "college", "school", "institute", "institution",
                                     "library", "libraries", "hospital", "the", "and", "for"})

    def _school_names(self) -> list[str]:
        names = [str(self.config.get(key) or "").strip() for key in ("carsi_idp_name", "carsi_idp_name_en")]
        return [n for n in names + [str(self.institution_query or "").strip()] if n]

    def _names_configured_school(self, label: str) -> bool:
        """The label contains the configured school's Chinese name or every
        distinctive word of its English name: "<School> University Library" is the
        school, "<Other word> Medical University" is not "<Word> Medical University"."""
        label = " ".join(str(label or "").translate(self._QUOTES).split()).lower().strip(" .,:;")
        words_in_label = set(re.findall(r"[a-z0-9]+", label))
        for name in self._school_names():
            name = " ".join(name.translate(self._QUOTES).split()).lower()
            words = {w for w in re.findall(r"[a-z0-9]+", name) if len(w) > 2 and w not in self._INSTITUTION_FILLER}
            if name in label or (words and words <= words_in_label):
                return True
        return False

    def _session_names_other_institution(self, label: str) -> bool:
        """Login state E: the publisher's session names an institution that is not
        the configured school ("Brought to you by: Other University").

        Without a configured school, or once this paper has chosen the school
        itself, the session is accepted: a publisher's abbreviation must not send
        the paper round the login again."""
        label = " ".join(str(label or "").translate(self._QUOTES).split()).lower().strip(" .,:;")
        if (not self._school_names() or not re.search(r"[^\W\d_]{2}", label)
                or label in self._GENERIC_INSTITUTION_LABELS):
            return False
        result = getattr(self, "_item_result", None)
        if result is not None and any(e.get("state") in self._SCHOOL_CHOSEN for e in result.events):
            return False
        if self._names_configured_school(label):
            return False
        if result is not None and not any(e.get("state") == "institution_session_other" and e.get("detail") == label[:200]
                                          for e in result.events):
            self._event(result, "institution_session_other", label[:200])
        return True

    def _has_publisher_institution_session(self, page: Any) -> bool:
        return self._institution_session(page) == "ours"

    def _institution_session(self, page: Any, snapshot: SimpleNamespace | None = None) -> str | None:
        """Whose institution session the publisher's page shows: ``"ours"``, another
        school's (``"other"``, login state E), or None.

        A session line ("Brought to you by <school>", access_rules.session_names),
        or an institution label in the page header (ACS's dropdown, Thieme's
        #institutionName, Wiley's name by its logo) that names the configured
        school or, failing that, an institution at all. Affiliations, help copy
        and generic labels ("Institutional login") are no evidence."""
        url = str(getattr(page, "url", "") or "")
        if not self._on_publisher_host(url) or self._is_auth_page(url):
            return None
        snap = snapshot or self._access_snapshot(page)
        found = None
        for name in access_rules.session_names(snap.lines):
            if not self._session_names_other_institution(name):
                return "ours"
            found = "other"
        for label in snap.probe.get("labels") or ():
            label = str(label)
            if access_rules.is_generic_label(label):
                continue
            if self._names_configured_school(label):
                return "ours"
            if access_rules.INSTITUTION_WORD.search(label):
                if not self._session_names_other_institution(label):
                    return "ours"
                found = "other"
        return found

    def _is_success_article_url(self, url: str) -> bool:
        verdict = self.adapter.is_article_page_url(url)
        if verdict is not None:
            return verdict
        verdict = self.adapter.is_success_article_url(url)
        if verdict is not None:
            return verdict
        lower = url.lower()
        if self.profile.success_url_markers:
            return any(marker in lower for marker in self.profile.success_url_markers)
        return self._names_this_article(url)

    def _names_this_article(self, url: str) -> bool:
        """The article page for a profile without article-page markers of its own
        (a site's run-time profile, publishers/site.py): a page of the site, not a
        login page, whose address carries this item's DOI (as is or %2F-escaped,
        in any case), or which carried ``citation_doi`` equal to the DOI while it
        was open (remembered for the item: Cambridge's and ASH's article addresses
        name no DOI, 2026-11-02)."""
        doi = str(getattr(self, "_adapter_doi", "") or "").strip().lower()
        if (not doi or not str(url or "").startswith("http") or not self._on_publisher_host(url)
                or self._is_auth_page(url)):
            return False
        address = url.lower().split("#", 1)[0]
        if doi in address or doi.replace("/", "%2f") in address or doi in unquote(address):
            return True
        seen = getattr(self, "_citation_pages", None)
        if not seen or seen[0] != doi:
            seen = self._citation_pages = (doi, set())
        if address in seen[1]:
            return True
        page = getattr(self, "_adapter_page", None)
        if page is None or str(getattr(page, "url", "") or "").lower().split("#", 1)[0] != address:
            return False
        if self._citation_dois(page) != {doi}:
            return False
        seen[1].add(address)
        return True

    # The diagnostic's access states, from the most telling down.
    _ACCESS_STATES = ("logged_in_no_entitlement", "logged_in", "readable", "not_logged_in", "unknown")

    def _access_state(self, page: Any) -> tuple[str, list[str]]:
        """For the diagnostic, the engine's own judgement of the open tabs, the
        working tab first (at most six), and no words of its own (review 2026-11-02:
        a second set of patterns here could disagree with the run):

        - ``logged_in_no_entitlement``: a tab denies the article to the school
          (``_institution_pdf_entitlement_missing``);
        - else by ``_access_decision``: ``logged_in`` (the institution's session),
          ``readable`` (the reader may read without it), ``not_logged_in`` (a login
          page, an abstract-only view, an offer, a gate or a denial), ``unknown``.

        The most telling tab's state, and each tab's decision as evidence
        (``<url> | <verdict> (<rule>): <the page's words>``). Diagnostic only: it
        never changes the workflow."""
        tabs = [page]
        try:
            tabs += [p for p in list(page.context.pages) if p is not page and not p.is_closed()]
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
        state, evidence = "unknown", []
        for tab in tabs[:6]:
            url = str(getattr(tab, "url", "") or "")[:200]
            if self._institution_pdf_entitlement_missing(tab):
                tab_state, line = "logged_in_no_entitlement", f"{url} | no entitlement: {self._denial_line(tab)}"
            else:
                verdict, basis, said = self._access_decision(tab)
                tab_state = {access_rules.IN: "logged_in" if basis == "session" else "readable",
                             access_rules.OUT: "not_logged_in"}.get(verdict, "unknown")
                line = f"{url} | {verdict} ({basis or 'no rule'}): {said[:160]}"
            evidence.append(line)
            if self._ACCESS_STATES.index(tab_state) < self._ACCESS_STATES.index(state):
                state = tab_state
        return state, evidence

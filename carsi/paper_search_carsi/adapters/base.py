"""Adapter interface and registry (publisher level, optionally journal level)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

_REGISTRY: dict[str, list[type["PublisherAdapter"]]] = {}


@dataclass(frozen=True)
class SupplementLink:
    """One supplementary file offered on the article page."""

    url: str
    label: str = ""
    # Discovery failures are recorded alongside downloaded files.
    error: str = ""
    # Found on the page but not shown to be this article's (a dataset the page
    # only names): recorded with this reason, neither fetched nor counted.
    set_aside: str = ""


class PublisherAdapter:
    """Publisher-specific answers for the shared engine; ``None`` = no opinion.

    A journal with its own quirks subclasses its publisher's adapter, sets one
    or more of ``issns`` / ``hosts`` / ``doi_pattern`` and overrides only the
    hooks that differ; everything else is inherited.
    """

    #: Profile name in lower case; the registry key.
    publisher = ""
    #: Journal-level selection: print/electronic ISSNs (upper case, with hyphen).
    issns: frozenset[str] = frozenset()
    #: Journal-level selection: hosts the journal is served from (or their parent domain).
    hosts: tuple[str, ...] = ()
    #: Journal-level selection: regular expression on the lower-case DOI.
    doi_pattern: str = ""
    #: Captured PDFs must come from this article's own PDF endpoint.
    validates_article_pdf = False
    #: Event name used when a captured PDF is not accepted.
    pdf_rejected_event = "publisher_pdf_rejected"
    #: URL patterns whose PDF responses are captured natively by the browser.
    native_pdf_patterns: tuple[str, ...] = ()
    #: The site's own PDF addresses: once the page's citation PDF is one of them
    #: (batch_pdf_urls ``_metadata_pdf_urls``), it comes first, is captured
    #: natively, and every other PDF response is refused.
    metadata_pdf_patterns: tuple[str, ...] = ()
    #: The site's PDF paths name no article: the article page's own citation PDF
    #: (``citation_doi`` this DOI) is the only candidate and the only PDF accepted.
    binds_pdf_to_citation = False
    #: PDF responses are read later (signed CDN URLs answer only once).
    defers_pdf_response_body = False
    #: Open PDF candidates by script navigation in the article tab.
    async_pdf_navigation = False
    # Only a complete PDF counts (%%EOF at the end, pages, not repaired): a viewer's
    # first range can start with %PDF yet hold no usable pages (Taylor & Francis).
    requires_complete_pdf = False
    # The main PDF anchor is marked as a download: keep it out of the browser's
    # download manager (Chromium writes a UUID file even when CDP took the body).
    keeps_pdf_out_of_downloads = False
    # The article's PDF endpoint redirects to a CDN copy (``is_pdf_cdn_url``); the
    # redirect is remembered as its provenance (Oxford Academic -> Silverchair).
    pdf_cdn_redirects = False
    # Only the article's own PDF URLs are tried as candidates.
    article_pdf_candidates_only = False
    # Failures keep a full-page screenshot in the diagnostic packet.
    diagnostic_screenshots = True
    # A finished login that lands on the publisher's home page goes back to the
    # article once (Oxford Academic).
    returns_from_home_page = False
    # A login that ends on any other page of the publisher goes back to this
    # record's article (APS).
    returns_to_record_article = False
    # A captured response's own URL must be this article's PDF endpoint, not
    # only a hop of its redirect chain.
    binds_response_url = False
    # A CARSI login that opened no institution entry (and reached no login
    # page) ends as ``publisher_institution_entry_missing``.
    requires_institution_entry = False
    # Every PDF response that is not this article's bound PDF
    # (``binds_pdf_to_citation``) is refused and kept from the browser.
    discards_unbound_pdfs = False
    # Redirect responses are passed over while capturing: the final response
    # keeps the chain and decides whether it is the article's PDF.
    passes_over_redirects = False
    # Words (lower case) of the site's own IP-block page, besides the shared
    # "IP address ... blocked" rule (ACS's contact mailbox).
    block_page_markers: tuple[str, ...] = ()

    def __init__(self, downloader: Any):
        self.d = downloader

    # --- Profile-level rules, asked by the PDF router (engine/router.py),
    # which works on a profile: no downloader, page or journal is known there.

    #: Supplementary-file URLs are matched after percent-decoding.
    unquotes_supplement_urls = False

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        """PDF URLs derived from the DOI and the source page, tried before the profile's templates."""
        return []

    @classmethod
    def profile_pdf_candidate_url(cls, url: str) -> bool | None:
        """Whether ``url`` may be a PDF candidate (None = the profile's PDF URL markers decide)."""
        return None

    @classmethod
    def keeps_pdf_candidate(cls, profile: Any, url: str, doi: str) -> bool:
        """Whether the finished candidate list keeps ``url``."""
        return True

    @classmethod
    def names_supplement(cls, url: str) -> bool:
        """A supplementary file by the publisher's own file naming (``url`` lower
        case, decoded when ``unquotes_supplement_urls``); the profile's markers follow."""
        return False

    @classmethod
    def belongs_to_article(cls, url: str, doi: str, source_url: str) -> bool | None:
        """Whether a PDF URL found on the page is this article's (None = it is)."""
        return None

    @classmethod
    def is_journal_level(cls) -> bool:
        return bool(cls.issns or cls.hosts or cls.doi_pattern)

    @classmethod
    def matches_journal(cls, *, doi: str = "", host: str = "", issns: Iterable[str] = ()) -> bool:
        if not cls.is_journal_level():
            return False
        host = (host or "").lower()
        if cls.issns and cls.issns & {str(i).upper() for i in issns}:
            return True
        if host and any(host == h or host.endswith("." + h) for h in cls.hosts):
            return True
        return bool(cls.doi_pattern and doi and re.fullmatch(cls.doi_pattern, doi.lower()))

    def login_url(self) -> str | None:
        """Start page for a stand-alone institution login."""
        return None

    def article_url(self, doi: str) -> str | None:
        """This article's page when the profile's template cannot give it (APS's
        journal codes); None: the profile's ``article_url``."""
        return None

    def login_page_url(self, page: Any) -> str | None:
        """A page to start the institution login from instead of the current one
        (e.g. the publisher's main platform for a journal's own site)."""
        return None

    def ensure_login(self, page: Any, result: Any) -> bool | None:
        """Open the article and sign in with the publisher's own flow; True when
        the article is accessible. None = the engine's flow."""
        return None

    def complete_login(self, page: Any, result: Any) -> bool | None:
        """Finish the sign-in from the current page with the publisher's own flow.
        None = the engine's flow."""
        return None

    def login_page_urls(self, page: Any) -> list[str]:
        """Pages to start the institution login from, in order; each is opened at
        most once per article. Default: ``login_page_url``."""
        url = self.login_page_url(page)
        return [url] if url else []

    def own_institution_entry(self, page: Any, result: Any) -> bool | None:
        """Open the institution login with the publisher's own flow, asked before
        the engine's whole entry lookup (the adapter's login pages included);
        True when the chooser is reached. None = the engine's lookup."""
        return None

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        """Open the publisher's own institution login; True when navigated."""
        return None

    def openathens_entry(self, page: Any, result: Any) -> bool | None:
        """Outside CARSI, asked before the generic OpenAthens control: the
        publisher's own way to its OpenAthens sign-in from this page. True when
        navigated, False = none here (no generic control either), None = no opinion."""
        return None

    def click_institution_control(self, page: Any, result: Any) -> bool:
        """Outside CARSI, once no generic institution control matched: click the
        publisher's own; True when clicked."""
        return False

    def fill_institution_search(self, page: Any, result: Any) -> bool:
        """Outside CARSI: type the configured school into the publisher's own
        institution search and choose its entry; True when chosen."""
        return False

    def looks_logged_out(self, page: Any, url: str, text: str) -> bool | None:
        """A page type of this site that the shared access rule
        (engine/access_rules.py) cannot judge: True = shown without
        access, False = readable, None = the shared rule decides. Asked after the
        institution session and the reader's access, before offers and denials."""
        return None

    # Controls that open the institution login, tried before the generic ones.
    sso_selectors: tuple[str, ...] = ()

    def login_block_reason(self, page: Any, text: str) -> str | None:
        """A publisher-specific verdict on whether the login cannot proceed ("" = not blocked)."""
        return None

    def chooser_block_reason(self, page: Any, url: str, text: str) -> str | None:
        """On the publisher's own institution chooser, asked right after the
        verification checks and before every other block rule: "" = the chooser
        can be used, a reason = the login cannot proceed (None = no opinion)."""
        return None

    def content_error(self, page: Any) -> bool:
        """The publisher's own content-service error page (not a login or entitlement issue)."""
        return False

    def is_redirect_page(self, url: str) -> bool:
        """A page that moves on to the article by script (wait for it to leave)."""
        return False

    def is_institution_chooser(self, url: str) -> bool:
        """A page of the publisher's own sign-in service, on another host of its
        own, where the user's organisation is searched; the configured school is
        chosen there as on a federation's chooser."""
        return False

    def institution_chooser_open(self, page: Any) -> bool:
        """The publisher's own federation/school chooser is on screen: there the
        school is chosen (``choose_institution``) and nothing else is clicked."""
        return False

    def leave_email_step(self, page: Any, result: Any) -> bool:
        """The publisher's sign-in asks for the user's work email, not the school:
        go back to its school search before anything is typed; True when clicked."""
        return False

    def prepare_institution_choice(self, page: Any, result: Any) -> bool | None:
        """In the CARSI school choice, after the federation form and the school
        assistance, before the SeamlessAccess and publisher choosers: the
        publisher's own step on this page. False ends this pass (None = go on)."""
        return None

    def choose_institution(self, page: Any, result: Any) -> bool | None:
        """Choose the federation and school on the publisher's own chooser; True
        when something was chosen. None = the engine's generic school assistance."""
        return None

    def follow_federated_login(self, page: Any, result: Any) -> bool:
        """On the publisher's own login page, follow its institutional (federated)
        option instead of the personal form; True when navigated."""
        return False

    def is_other_article(self, page: Any, doi: str) -> bool:
        """The page is another article's page (a login returned to a stale target)."""
        return False

    def unsupported_platform(self, page: Any) -> str | None:
        """Name of the platform the article page landed on when the engine cannot
        sign in or capture a PDF there; None = supported."""
        return None

    def open_pdf_entry(self, page: Any, result: Any) -> bool | None:
        """Click the article's own PDF control; True when clicked."""
        return None

    def is_article_pdf_url(self, url: str, doi: str = "") -> bool | None:
        """Whether ``url`` is this publisher's article PDF endpoint (for ``doi``)."""
        return None

    def is_pdf_cdn_url(self, url: str, doi: str) -> bool:
        """A CDN copy of this article's PDF, reached by redirect from its endpoint."""
        return False

    def is_article_page_url(self, url: str) -> bool | None:
        """Whether ``url`` is an article page of this publisher on a host outside the profile's domains."""
        return None

    def is_success_article_url(self, url: str) -> bool | None:
        """Whether ``url`` is an article page, for the access checks only (None =
        the profile's success markers decide). Unlike ``is_article_page_url`` it
        neither makes the host the publisher's nor the page a supplements page."""
        return None

    def supplements_page_url(self, doi: str) -> str | None:
        """The article page listing supplementary files (None = the profile's article URL)."""
        return None

    def supplements_page_urls(self, doi: str) -> list[str]:
        """Pages to look for supplements on, in order; the first that lists any is used."""
        url = self.supplements_page_url(doi)
        return [url] if url else []

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        """Supplementary files listed on the article page."""
        return None


def register(cls: type[PublisherAdapter]) -> type[PublisherAdapter]:
    _REGISTRY.setdefault(cls.publisher, []).append(cls)
    return cls


def adapter_class(publisher: str, *, doi: str = "", host: str = "",
                  issns: Iterable[str] = ()) -> type[PublisherAdapter]:
    """Most specific adapter: journal, then publisher, then the generic one."""
    classes = _REGISTRY.get((publisher or "").lower(), [])
    issns = tuple(issns)
    for cls in classes:
        if cls.matches_journal(doi=doi, host=host, issns=issns):
            return cls
    for cls in classes:
        if not cls.is_journal_level():
            return cls
    return PublisherAdapter


def adapter_class_for(profile: Any) -> type[PublisherAdapter]:
    """The publisher-level adapter class of a profile (no article, host or journal known)."""
    return adapter_class(str(getattr(profile, "name", "") or ""))


def adapter_for(downloader: Any, *, doi: str = "", host: str = "",
                issns: Iterable[str] = ()) -> PublisherAdapter:
    name = str(getattr(getattr(downloader, "profile", None), "name", "") or "")
    return adapter_class(name, doi=doi, host=host, issns=issns)(downloader)

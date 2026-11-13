"""Elsevier: publisher-wide answers, and two site types with their own rules.

    ElsevierAdapter (this module)      sign-in entry, remembered school, linkinghub,
                                       ClinicalKey, returning to the article,
                                       where to look for supplementary files
      ├─ ScienceDirectSite  (sciencedirect.py)   articles and book chapters on ScienceDirect
      └─ JournalSite        (journal_site.py)    journals on their own sites (cell.com, thelancet.com, ...)

Each hook below hands the page to the site type its URL belongs to. A new URL
format is handled in its site type, so it covers every journal of that kind;
a single host gets its own subclass (``journal_site_class`` /
``sciencedirect_class`` on an adapter with ``hosts``) only when its site type
cannot cover it.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urlparse

from ...browser.driver import is_driver_error
from ...engine.router import elsevier_journal_article, extract_elsevier_pii
from ..base import PublisherAdapter, SupplementLink, register
from . import journal_site, sciencedirect

# An account's sign-in route in Elsevier ID's search results ("entityId": null or "...").
_ENTITY_ID = re.compile(r'"entityId"\s*:\s*(null|"[^"]*")')
_IP_OR_VPN_ONLY = re.compile(r"can grant access through either an IP address or a VPN", re.I)
from .journal_site import JournalSite, _record_pii
from .sciencedirect import ScienceDirectSite

# ClinicalKey (clinicalkey.com, .fr, .es, .com.au, ...): EMC titles are served
# only there, a separate subscription with its own sign-in and reader.
_CLINICALKEY = re.compile(r"(?:www\.)?clinicalkey\.[a-z]{2,3}(?:\.[a-z]{2})?")
_ASH_DOI = re.compile(r"10\.1182/(?:blood|bloodadvances)\.[^/?#\s]+", re.I)
_ASH_HOSTS = frozenset({"ashpublications.org", "www.ashpublications.org"})


# Every file link on the page with the text around it (the item's caption).
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => {
    const item = a.closest('.e-component, .article-attachment, .supplementary-material__item, li, figure, tr');
    const text = s => (s || '').replace(/\\s+/g, ' ').trim();
    const own = text(a.innerText);
    const around = item ? text(item.innerText).replace(own, '').trim() : '';
    return {href: a.href, label: (around || own).slice(0, 240)};
})"""


def supplement_links_from_rows(rows: Any, page_url: str, doi: str) -> list[SupplementLink]:
    """This article's supplementary files among the page's links: ScienceDirect's
    ``mmc`` files for the page's PII, or a journal site's ``/cms/<DOI>/attachment/``."""
    page = urlparse(page_url or "")
    pii = extract_elsevier_pii(page_url or "") if sciencedirect.is_page(page_url) else ""
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        target = urlparse(str(row.get("href") or ""))
        if target.scheme != "https" or target.fragment:
            continue
        url = target._replace(fragment="").geturl()
        ok = (sciencedirect.is_supplement(target, pii) if pii
              else journal_site.is_supplement(target, page.hostname, doi))
        if ok and url not in seen:
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links

# The article page's "Access through your organization/institution" control.
# In CARSI mode only the generic chooser is used (never a remembered school's
# InstitutionLogin shortcut); otherwise a remembered entry must name the
# configured school.
# Elsevier ID's "Enter your organizational email" (Windows, 2026-11-11): the same
# #bdd-email field as "Find your organization", but for an email only; its
# "Access via another organization" leads back to the search by name.
_EMAIL_STEP_JS = """() => {
  const shown = (el) => !!el && el.getClientRects().length > 0;
  const field = document.querySelector("#bdd-email");
  const label = (document.querySelector("#emaillabel") || {}).textContent || "";
  const other = document.querySelector("#bdd-elsSecondaryBtn");
  if (!shown(field) || !/e-?mail/i.test(label) || /name/i.test(label) || !shown(other)
      || !/another organi[sz]ation/i.test(other.textContent || "")) return false;
  other.click();
  return true;
}"""

# Elsevier ID's "Access through your organization – You will be sent to <school>"
# for a school chosen before in this browser, with "Try Another way" to its search:
# the school shown, when the page is that one (2026-11-13: it named the previous
# school and no other could be chosen there).
_REMEMBERED_JS = """() => {
  const shown = (el) => !!el && el.getClientRects().length > 0;
  const another = [...document.querySelectorAll("#bdd-elsSecondaryBtn-tryAnotherWay, #bdd-elsSecondaryBtn")]
    .find((el) => shown(el) && /try another way/i.test(el.textContent || ""));
  const body = (document.body && document.body.innerText) || "";
  if (!another || !/you will be sent to/i.test(body)) return null;
  const school = [...document.querySelectorAll("#bdd-elsPrimaryBtn .els-institution-group, #bdd-elsPrimaryBtn")].find(shown);
  return {school: ((school && (school.innerText || school.textContent)) || "").replace(/\\s+/g, " ").trim()};
}"""
_TRY_ANOTHER_JS = """() => {
  const el = [...document.querySelectorAll("#bdd-elsSecondaryBtn-tryAnotherWay, #bdd-elsSecondaryBtn")]
    .find((el) => el.getClientRects().length > 0 && /try another way/i.test(el.textContent || ""));
  if (!el) return false;
  el.click();
  return true;
}"""

_ENTRY_JS = """
                ({manualSelection, institutionQuery}) => {
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const textOf = (el) => [
                    el.innerText || '',
                    el.textContent || '',
                    el.value || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || ''
                  ].join(' ').replace(/\\s+/g, ' ').trim();
                  const hrefOf = (el) => ((el.href || el.getAttribute('href') || el.getAttribute('formaction') || '') + '');
                  const controls = [...document.querySelectorAll('a,button,[role="button"],input[type="button"],input[type="submit"]')]
                    .filter(visible)
                    .map((el) => {
                      const text = textOf(el);
                      const href = hrefOf(el);
                      const haystack = `${text} ${href}`.toLowerCase();
                      if (manualSelection) {
                        // InstitutionLogin bypasses discovery for a remembered
                        // school. Only the generic chooser belongs to this mode.
                        if (href.toLowerCase().includes('/shibauth/institutionlogin')) return null;
                        if (href) {
                          const targetUrl = new URL(href, location.href);
                          if (targetUrl.protocol !== 'https:' || !['auth.elsevier.com',
                              'www.sciencedirect.com', 'sciencedirect.com'].includes(targetUrl.hostname)) return null;
                          // Not [...searchParams.keys()]: "not iterable" in the Firefox build's evaluate,
                          // which kept every signed-out ScienceDirect entry from a click (2026-10-31).
                          if (/[?&](?:entityid|idp|institutionid|organizationid|homeorg)=/i.test(targetUrl.search)) return null;
                        }
                        const label = (el.innerText || el.getAttribute('aria-label') || el.value || '')
                            .replace(/\\s+/g, ' ').trim().toLowerCase();
                        if (!['access through your organization', 'access through another organization',
                              'access through your institution'].includes(label)) return null;
                        return {el, text, href, score: 100};
                      }
                      let score = 0;
                      let matched = false;
                      if (href.toLowerCase().includes('/shibauth/institutionlogin')) {
                        if (!institutionQuery || !text.toLowerCase().includes(institutionQuery.toLowerCase())) return null;
                        score += 100; matched = true;
                      }
                      if (haystack.includes('access through your organization')) { score += 40; matched = true; }
                      if (haystack.includes('access through another organization')) score -= 60;
                      if (haystack.includes('purchase pdf')) score -= 80;
                      if (haystack.includes('go to elsevier homepage') || href.toLowerCase().replace(/\\/$/, '') === 'http://www.elsevier.com') return null;
                      if (!matched) return null;
                      if (el.tagName === 'A') score += 10;
                      return {el, text, href, score};
                    })
                    .filter(Boolean)
                    .filter((item) => item.score > 0)
                    .sort((a, b) => b.score - a.score);
                  const target = controls[0];
                  if (!target) return null;
                  target.el.scrollIntoView({block: 'center', inline: 'center'});
                  target.el.click();
                  return {
                    selector: 'elsevier-institution-access',
                    text: target.text.slice(0, 220),
                    href: target.href.slice(0, 500),
                    score: target.score
                  };
                }
                """


@register
class ElsevierAdapter(PublisherAdapter):
    publisher = "elsevier"
    native_pdf_patterns = ("https://pdf.sciencedirectassets.com/*",)
    defers_pdf_response_body = True
    async_pdf_navigation = True
    sciencedirect_class = ScienceDirectSite
    journal_site_class = JournalSite

    def __init__(self, downloader: Any):
        super().__init__(downloader)
        self.sciencedirect = self.sciencedirect_class(downloader)
        self.journal_site = self.journal_site_class(downloader)

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls = []
        journal_article = elsevier_journal_article(source_url)
        if journal_article:
            # The journal's own PDF first: Cell Press and society journals may be
            # readable there while ScienceDirect offers only the abstract.
            host = urlparse(source_url).hostname
            urls.append(f"https://{host}/action/showPdf?pii={journal_article[0]}")
        pii = extract_elsevier_pii(source_url)
        if pii:
            urls.append(f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft")
        return urls

    @classmethod
    def belongs_to_article(cls, url: str, doi: str, source_url: str) -> bool | None:
        if urlparse(url).path.lower().startswith("/servlet/linkout"):
            return False  # a reference's full-text link on a journal site
        source_pii = extract_elsevier_pii(source_url)
        candidate_pii = extract_elsevier_pii(url)
        if source_pii and candidate_pii:
            return source_pii.lower() == candidate_pii.lower()
        lower = url.lower()
        doi_lower = doi.lower()
        doi_escaped = doi_lower.replace("/", "%2f")
        if source_pii:
            return source_pii.lower() in lower or doi_lower in lower or doi_escaped in lower
        return True

    def login_url(self) -> str | None:
        return "https://www.sciencedirect.com/"

    def article_url(self, doi: str) -> str | None:
        # ASH's society site points its institution entry to this same-DOI
        # Linking Hub route. Use the publishing partner's existing flow rather
        # than treating that explicit cross-site entry as a missing login.
        if _ASH_DOI.fullmatch(doi):
            return "https://linkinghub.elsevier.com/retrieve/doi/" + quote(doi, safe="/")
        return None

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        clicked = self.click_institution_entry(page, result)
        if self.d.federation is not None:
            return clicked
        return True if clicked else None  # otherwise the generic entries are tried

    def click_institution_entry(self, page: Any, result: Any) -> bool:
        if self.d._is_human_login_page(page):
            return False
        manual_selection = self.d.federation is not None
        if manual_selection and urlparse(str(page.url)).hostname not in sciencedirect.HOSTS | {"auth.elsevier.com"}:
            return False
        try:
            detail = page.evaluate(_ENTRY_JS, {"manualSelection": manual_selection,
                                               "institutionQuery": self.d.institution_query})
            if isinstance(detail, dict) and detail:
                if result is not None:
                    self.d._event(result, "sso_entry_clicked", "elsevier-generic-institution-entry"
                                  if manual_selection else json.dumps(detail, ensure_ascii=False))
                return True
        except Exception as exc:
            if result is not None:
                self.d._event(result, "elsevier_institution_entry_error", f"{type(exc).__name__}: {exc}")
        return False

    def login_block_reason(self, page: Any, text: str) -> str | None:
        # A remembered school's entry is a continuation, not a block.
        if self.remembered_institution_entry(text):
            return ""
        # "Instructions from your organization": the school grants access only by
        # IP address or VPN, no sign-in through it (Elsevier ID, 2026-11-11).
        if (self.is_institution_chooser(str(getattr(page, "url", "") or ""))
                and _IP_OR_VPN_ONLY.search(" ".join(text.split()))):
            return "institution_federation_unavailable"
        return None

    def institution_entry_signs_in(self, data: str) -> bool | None:
        """Elsevier ID's organization search keeps each entry's account as JSON in a
        hidden field: ``"entityId": null`` is an account without a federated
        sign-in (its IP range, VPN, or a work email: "derivedFlowType": "EIA")."""
        found = _ENTITY_ID.search(data or "")
        if not found:
            return None
        return found.group(1) != "null"

    def remembered_institution_entry(self, text: str) -> bool:
        """ScienceDirect shows "Access through <institution>" once an institution is remembered.

        Generic labels ("your institution", "another organization") do not count.
        With a configured institution only that institution's entry counts.
        """
        names = [name.lower() for name in self.d._institution_names()]
        for match in re.finditer(r"access through ([^\n\r]{2,80})", text.lower()):
            label = re.sub(r"\s+", " ", match.group(1)).strip(" .:;,")
            if label in self.d._GENERIC_INSTITUTION_LABELS or label.startswith(("your ", "another ")):
                continue
            if not names or any(label.startswith(name) or name.startswith(label) for name in names):
                return True
        return False

    def leave_email_step(self, page: Any, result: Any) -> bool:
        if not self.is_institution_chooser(str(getattr(page, "url", "") or "")):
            return False
        try:
            clicked = page.evaluate(_EMAIL_STEP_JS) is True
        except Exception as exc:
            if not is_driver_error(exc):
                raise
            return False  # the page moved on while it was read
        if clicked:
            self.d._event(result, "elsevier_email_step_left", "Access via another organization")
            return True
        return self._leave_remembered_other_school(page, result)

    def _leave_remembered_other_school(self, page: Any, result: Any) -> bool:
        """Elsevier ID offers only a school chosen before in this browser (``_REMEMBERED_JS``):
        when it is not the configured school, "Try Another way" goes to the search.
        The configured school's own page, and any page with no school configured,
        stay as they are."""
        names = [n for n in self.d._institution_names() if n]
        if not names:
            return False
        try:
            shown = page.evaluate(_REMEMBERED_JS)
            if not isinstance(shown, dict) or not shown.get("school"):
                return False
            key = lambda text: re.sub(r"[\W_]+", "", str(text or "").casefold())
            if any(key(name) and key(name) in key(shown["school"]) for name in names):
                return False
            clicked = page.evaluate(_TRY_ANOTHER_JS) is True
        except Exception as exc:
            if not is_driver_error(exc):
                raise
            return False  # the page moved on while it was read
        if clicked:
            self.d._event(result, "elsevier_remembered_school_left", f"{shown['school'][:120]}: not the configured school")
        return clicked

    def is_redirect_page(self, url: str) -> bool:
        # doi.org -> linkinghub "Redirecting" -> ScienceDirect, the journal's site or
        # ClinicalKey; and Elsevier ID's sign-in round trip a PDF request may take
        # first (JAD, 2026-10-31: still on it 5 s after the click).
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return host == "linkinghub.elsevier.com" or (
            host in ("id.elsevier.com", "auth.elsevier.com")
            and bool(re.search(r"/authorization\.(?:ping|oauth2)$", parsed.path)))

    def is_institution_chooser(self, url: str) -> bool:
        # Elsevier ID's "Find your organization" (state C, 2026-10-31): with no
        # school session and no remembered school, "Access through your
        # organization" leads here; the school's entry goes on to its sign-in page.
        parsed = urlparse(url)
        return (parsed.scheme == "https" and (parsed.hostname or "").lower() == "id.elsevier.com"
                and parsed.path.startswith("/as/"))

    def unsupported_platform(self, page: Any) -> str | None:
        url = str(getattr(page, "url", "") or "")
        host = (urlparse(url).hostname or "").lower()
        if _CLINICALKEY.fullmatch(host) or (sciencedirect.is_page(url) and self.sciencedirect.clinicalkey_only(page)):
            return "ClinicalKey"
        return None

    def supplements_page_urls(self, doi: str) -> list[str]:
        """ScienceDirect first; journals on their own Elsevier site (Cell Press,
        Gastroenterology) show only the abstract there, so the DOI's landing page follows."""
        from .journal_site import _get_elsevier_pii

        if _ASH_DOI.fullmatch(doi):
            # ASH keeps supplementary content on the original journal page.
            # A ScienceDirect detour spends the same discovery budget on an
            # extra verification without supplying these Silverchair files.
            return [f"https://doi.org/{doi}"]
        pii = _get_elsevier_pii(doi)
        first = [f"https://www.sciencedirect.com/science/article/pii/{pii}"] if pii else []
        return first + [f"https://doi.org/{doi}"]

    def login_page_url(self, page: Any) -> str | None:
        url = str(getattr(page, "url", "") or "")
        return self.journal_site.login_page_url(url) if journal_site.is_page(url) else None

    def login_page_urls(self, page: Any) -> list[str]:
        # A journal's own site signs in on itself first (Elsevier ID signs in to
        # ScienceDirect at the same time), then ScienceDirect's same article.
        if not journal_site.is_page(str(getattr(page, "url", "") or "")):
            return []
        return [url for url in (self.journal_site.institution_login_url(page), self.login_page_url(page)) if url]

    def is_article_page_url(self, url: str) -> bool | None:
        return True if journal_site.is_page(url) else None

    def looks_logged_out(self, page: Any, url: str, text: str) -> bool | None:
        # ScienceDirect's /abs/pii/ view, its "Full text access" label, the
        # "Access through <school>" gate and "<school> does not subscribe to this
        # content" are the shared access rule's; a journal site's abstract view is not.
        return self.journal_site.looks_logged_out(page, url, text) if journal_site.is_page(url) else None

    def content_error(self, page: Any) -> bool:
        url = str(getattr(page, "url", "") or "")
        return self.sciencedirect.content_error(page) if sciencedirect.is_page(url) else False

    def open_pdf_entry(self, page: Any, result: Any) -> bool | None:
        if journal_site.is_page(str(getattr(page, "url", "") or "")):
            return self.journal_site.open_pdf_entry(page, result)
        return self.sciencedirect.open_pdf_entry(page, result)

    def is_other_article(self, page: Any, doi: str) -> bool:
        url = str(getattr(page, "url", "") or "")
        doi_page = journal_site.doi_article(url)
        if doi_page:
            return bool(doi) and doi_page[0].lower() != doi.lower()
        if not sciencedirect.is_page(url) and not journal_site.article(url):
            return False
        here = extract_elsevier_pii(url)
        expected = _record_pii(doi) if here and doi else ""
        return bool(expected) and here != expected

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        if (urlparse(str(page.url)).hostname or "").lower() in _ASH_HOSTS and _ASH_DOI.fullmatch(doi):
            from ..platforms.silverchair import supplement_links
            return supplement_links(page, doi, _ASH_HOSTS)
        if sciencedirect.is_page(str(page.url)):
            self.sciencedirect.wait_for_full_text(page)
        return supplement_links_from_rows(page.evaluate(_SUPPLEMENT_ROWS_JS), str(page.url), doi)

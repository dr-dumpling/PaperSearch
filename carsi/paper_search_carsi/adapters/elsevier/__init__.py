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

from ...engine.router import elsevier_journal_article, extract_elsevier_pii
from ..base import PublisherAdapter, SupplementLink, register
from . import journal_site, sciencedirect
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
                          // Not [...searchParams.keys()]: "not iterable" in Camoufox's evaluate,
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
        if self.d.config.get("publisher_institution_federation") == "carsi":
            return clicked
        return True if clicked else None  # otherwise the generic entries are tried

    def click_institution_entry(self, page: Any, result: Any) -> bool:
        if self.d._is_human_login_page(page):
            return False
        manual_selection = self.d.config.get("publisher_institution_federation") == "carsi"
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
        return "" if self.remembered_institution_entry(text) else None

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
        host = (urlparse(str(getattr(page, "url", "") or "")).hostname or "").lower()
        return "ClinicalKey" if _CLINICALKEY.fullmatch(host) else None

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

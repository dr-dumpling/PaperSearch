"""PDF candidate URLs, and whether a response belongs to the article.

Part of ``PublisherBatchDownloader`` (batch.py), which combines the mixins."""

from __future__ import annotations

import re
from fnmatch import fnmatch
from typing import Any
from urllib.parse import unquote, urlparse

from .router import build_pdf_candidates, extract_elsevier_pii, is_pdf_candidate_url, is_supplementary_url, is_springer_article_pdf_url
from .batch_common import PaperRecord, _REFERENCE_AREA, _is_browser_error


# A link is never this article's PDF when its path is a sharing, login,
# password, registration, purchase or advertising action, whatever its query
# carries (Taylor & Francis J Nat Hist 1975 tried addtoany.com/share,
# /action/showLogin, /action/clickThrough and /action/requestResetPassword as
# PDFs for 80 s, their return addresses naming the PDF, 2026-11-02).
_NOT_PDF_LINK = re.compile(
    r"/action/(?:showlogin|clickthrough|requestresetpassword|ssostart|registration|showpurchase)"
    r"|/(?:login|logon|signin|sign-in|register|registration|share|sharer|cart|checkout|purchase|subscribe)(?:[/.]|$)"
    r"|password|/ads?/|doubleclick|addtoany", re.I)
# A path that serves a PDF: a .pdf file or a PDF view (Wiley /doi/pdf|epdf|pdfdirect/,
# ScienceDirect /pdfft, RSC /articlepdf/, Elsevier journals' /action/showPdf, IEEE's
# stamp.jsp and stampPDF, Optica's viewmedia.cfm, PLOS's /article/file).
_PDF_PATH = re.compile(
    r"\.pdf$|/(?:pdf|epdf|pdfdirect|pdfft|articlepdf|stamppdf)(?:/|$)|/action/showpdf$|/stamp/stamp\.jsp$"
    r"|viewmedia\.cfm$|/article/file$", re.I)
# Article views that are not an article id ("/article/123/fulltext").
_VIEWS = frozenset({"fulltext", "abstract", "full", "abs", "html", "pdf", "epdf", "summary", "info", "references"})
# The page's citation metadata and its visible links outside the references, in one round trip.
_PAGE_PDF_LINKS_JS = """() => {
    const shown = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
    const meta = name => [...document.querySelectorAll('meta[name="' + name + '"]')]
        .map(el => (el.content || '').trim()).filter(Boolean);
    const absolute = value => { try { return new URL(value, location.href).href; } catch (_) { return ''; } };
    const links = [...document.querySelectorAll('a[href]')]
        .filter(a => shown(a) && !a.closest(REFERENCES)).map(a => a.href).filter(href => /^https?:/i.test(href));
    return {dois: meta('citation_doi'), pdfs: meta('citation_pdf_url').map(absolute).filter(Boolean),
            links: [...new Set(links)].slice(0, 800)};
}""".replace("REFERENCES", repr(_REFERENCE_AREA))


def _plain_url(url: str) -> str:
    return str(url or "").split("#", 1)[0].split("?", 1)[0]


class PdfUrlsMixin:
    """PDF candidate URLs, and whether a response belongs to the article."""

    def _page_pdf_links(self, page: Any) -> dict:
        try:
            found = page.evaluate(_PAGE_PDF_LINKS_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return {}
        return found if isinstance(found, dict) else {}

    def _on_article_site(self, url: str, page_url: str) -> bool:
        """An https address on the page's own host or the publisher's domains."""
        target = urlparse(url)
        host = (target.hostname or "").lower()
        domains = [*self.profile.base_domains, (urlparse(page_url).hostname or "").lower()]
        return (target.scheme == "https" and not target.username and not target.password
                and any(domain and (host == domain or host.endswith("." + domain)) for domain in domains))

    @staticmethod
    def _article_keys(page_url: str, doi: str) -> list[str]:
        """What names this article in an address: its DOI (as is, %2F-escaped, its
        suffix), the page's PII and the page's own numeric article id."""
        doi = (doi or "").strip().lower()
        keys = [doi, doi.replace("/", "%2f")] if doi else []
        suffix = doi.split("/", 1)[-1]
        if len(suffix) >= 6 and re.search(r"\d", suffix):
            keys.append(suffix)
        pii = extract_elsevier_pii(page_url or "")
        if pii:
            keys.append(pii.lower())
        segments = [part for part in urlparse(page_url or "").path.lower().split("/") if part and part not in _VIEWS]
        ids = [part for part in segments if re.fullmatch(r"\d{5,}", part)]
        if ids:
            keys.append(ids[-1])
        return [key for key in dict.fromkeys(keys) if key]

    def _citation_pdf_urls(self, page: Any, doi: str, found: dict | None = None) -> list[str]:
        """The page's own ``citation_pdf_url`` when its ``citation_doi`` is this DOI
        and no other: on the article's site, a PDF address, no attachment. One rule
        for every publisher (it was ACS's, JAMA's and Silverchair's three copies)."""
        page_url = str(getattr(page, "url", "") or "")
        found = self._page_pdf_links(page) if found is None else found
        dois = {re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value).strip().lower())
                for value in found.get("dois") or ()}
        if not doi or dois != {doi.strip().lower()}:
            return []
        return [str(url) for url in dict.fromkeys(found.get("pdfs") or ())
                if self._on_article_site(str(url), page_url)
                and not _NOT_PDF_LINK.search(urlparse(str(url)).path)
                and (_PDF_PATH.search(urlparse(str(url)).path)
                     or self.adapter.profile_pdf_candidate_url(str(url)) is True)
                and not self._is_supplementary_url(str(url))]

    def _bound_pdf_urls(self, page: Any, doi: str) -> list[str] | None:
        """For a site whose PDF paths name no article (``binds_pdf_to_citation``):
        the article page's citation PDF, the only candidate and the only PDF
        accepted ([] = none: nothing is fetched). None for other sites."""
        if not self.adapter.binds_pdf_to_citation:
            return None
        if not self._is_success_article_url(str(getattr(page, "url", "") or "")):
            return []
        return list(dict.fromkeys(_plain_url(url) for url in self._citation_pdf_urls(page, doi)))

    def _citation_pdf_missing(self, page: Any, doi: str) -> tuple[bool, str]:
        """``(metadata missing, why)``: why the page gives no citation PDF for ``doi``.
        True only on an article page that carries no ``citation_doi`` at all."""
        url = str(getattr(page, "url", "") or "")
        if not self._is_success_article_url(url):
            return False, f"not an article page: {url[:160]}"
        found = self._page_pdf_links(page)
        dois = list(found.get("dois") or ())
        return not dois, (f"no citation PDF for this DOI (citation_doi: {', '.join(dois) or 'none'}; "
                          f"citation_pdf_url: {', '.join(found.get('pdfs') or ())[:160] or 'none'})")

    def _article_pdf_links_on_page(self, page: Any, doi: str) -> list[str]:
        """The page's own PDF links naming this article (its DOI or the page's
        article id, ``_article_pdf_link``), without their query and fragment."""
        url = str(getattr(page, "url", "") or "")
        keys = self._article_keys(url, doi)
        links = [str(link) for link in self._page_pdf_links(page).get("links") or ()
                 if self._article_pdf_link(str(link), keys, url)]
        return list(dict.fromkeys(_plain_url(link) for link in links))

    def _metadata_pdf_urls(self, page: Any, doi: str) -> list[str]:
        """The citation PDF among the site's own PDF addresses (``metadata_pdf_patterns``,
        ACS): once known, it comes first and every other PDF response is refused."""
        patterns = self.adapter.metadata_pdf_patterns
        if not patterns:
            return []
        return list(dict.fromkeys(url for url in (_plain_url(u) for u in self._citation_pdf_urls(page, doi))
                                  if any(fnmatch(url, pattern) for pattern in patterns)))

    def _article_pdf_link(self, url: str, keys: list[str], page_url: str) -> bool:
        """A link to this article's PDF: on its site, a PDF path, naming the article,
        and no sharing, login, password, purchase or advertising action."""
        path = urlparse(url).path
        if (not self._on_article_site(url, page_url) or _NOT_PDF_LINK.search(path)
                or not _PDF_PATH.search(path) or self._is_supplementary_url(url)
                or self.adapter.profile_pdf_candidate_url(url) is False):
            return False
        try:
            decoded = unquote(url).lower()
        except Exception:
            decoded = url.lower()
        return any(key in decoded or key in url.lower() for key in keys)

    def _pdf_candidates(self, page: Any, doi: str) -> list[str]:
        """This article's PDF addresses: a bound citation PDF alone; otherwise the
        adapter's and profile's formulas, then the citation PDF and the page's
        own PDF links (``_citation_pdf_urls``, ``_article_pdf_link``)."""
        bound = self._bound_pdf_urls(page, doi)
        if bound is not None:
            return bound
        page_url = str(getattr(page, "url", "") or "")
        found = self._page_pdf_links(page)
        keys = self._article_keys(page_url, doi)
        discovered = [*self._citation_pdf_urls(page, doi, found),
                      *(str(url) for url in found.get("links") or () if self._article_pdf_link(str(url), keys, page_url))]
        urls = build_pdf_candidates(self.profile, doi, source_url=page_url, discovered_urls=discovered)
        if self.adapter.article_pdf_candidates_only:
            return [url for url in urls if self._article_pdf_url_matches(url, doi)]
        return urls

    def _filter_pdf_candidates_for_current_article(self, urls: list[str], page: Any, doi: str) -> list[str]:
        return build_pdf_candidates(
            self.profile,
            doi,
            source_url=str(getattr(page, "url", "") or ""),
            discovered_urls=urls,
        )

    @staticmethod
    def _extract_elsevier_pii(url: str) -> str:
        return extract_elsevier_pii(url)

    def _is_pdf_candidate_url(self, url: str) -> bool:
        return is_pdf_candidate_url(self.profile, url)

    def _is_supplementary_url(self, url: str) -> bool:
        return is_supplementary_url(self.profile, url)

    def _article_pdf_url_matches(self, url: str, doi: str = "", *,
                                 article_pdf_urls: frozenset[str] | None = None) -> bool:
        own = self.adapter.is_article_pdf_url(url, doi)
        if own is not None:
            return own
        if self.adapter.binds_pdf_to_citation:
            # Only the citation PDF bound by this capture, for this DOI.
            return (bool(doi) and urlparse(url).scheme == "https" and not self._is_supplementary_url(url)
                    and _plain_url(url) in (article_pdf_urls or ()))
        return is_springer_article_pdf_url(url, doi)

    def _response_matches_article(self, response: Any, doi: str, *,
                                  article_pdf_urls: frozenset[str] | None = None) -> bool:
        if not self._uses_article_pdf_validation():
            return True
        status = getattr(response, "status", None)
        if status is None:
            status = getattr(response, "status_code", 0)
        if not doi or not 200 <= status < 300:
            return False
        article_options = {"article_pdf_urls": article_pdf_urls} if article_pdf_urls is not None else {}
        final = str(getattr(response, "url", "") or "")
        if (self.adapter.binds_response_url and not self._article_pdf_url_matches(final, doi, **article_options)
                and not self._bound_pdf_copy(final, response, doi, article_options)):
            return False
        if (self.adapter.pdf_cdn_redirects
                and not (self._article_pdf_url_matches(str(getattr(response, "url", "") or ""), doi)
                         or self.adapter.is_pdf_cdn_url(str(getattr(response, "url", "") or ""), doi))):
            return False
        for hop in [*(getattr(response, "history", ()) or ()), response]:
            headers = {name.lower(): value for name, value in (getattr(hop, "headers", {}) or {}).items()}
            if self._is_supplementary_url(headers.get("content-disposition", "")):
                return False
        # A PDF subresource is not proof of article identity. Accept only the
        # current DOI endpoint or its HTTP redirect chain, never an incidental PDF.
        urls = self._response_urls(response)
        return (not any(self._is_supplementary_url(url) for url in urls)
                and not any(self._article_pdf_url_matches(url) and not self._article_pdf_url_matches(url, doi, **article_options) for url in urls)
                and any(self._article_pdf_url_matches(url, doi, **article_options) for url in urls))

    _wiley_response_matches_article = _response_matches_article

    def _bound_pdf_copy(self, final: str, response: Any, doi: str, article_options: dict) -> bool:
        """The bound PDF's own file served by the delivery host its address redirects
        to: the chain starts at this article's PDF, and the final address is on
        another host and keeps its file name (JAMA's articlepdf ->
        watermark02.silverchair.com/<the same name>.pdf, refused by the
        final-address rule although it was the article, 2026-11-02). Another
        article's file, an attachment or a login page has another name or stays
        on the publisher's own host."""
        def name(url: str) -> str:
            return unquote(urlparse(url).path).rsplit("/", 1)[-1].lower()

        own, host = name(final), urlparse(final).hostname
        return own.endswith(".pdf") and any(
            name(url) == own and urlparse(url).hostname != host
            and self._article_pdf_url_matches(url, doi, **article_options)
            for url in self._response_urls(response)[1:])

    @staticmethod
    def _response_urls(response: Any) -> list[str]:
        """Read Playwright redirects or requests history without following links."""
        urls = [str(getattr(response, "url", "") or "")]
        urls.extend(str(getattr(hop, "url", "") or "") for hop in (getattr(response, "history", ()) or ()))
        request = getattr(response, "request", None)
        seen: set[int] = set()
        while request is not None and id(request) not in seen and len(seen) < 20:
            seen.add(id(request))
            urls.append(str(getattr(request, "url", "") or ""))
            request = getattr(request, "redirected_from", None)
        return urls

    _wiley_response_urls = _response_urls

    @staticmethod
    def _text_matches_record(text: str, record: PaperRecord, fallback_title: str = "") -> bool:
        """The saved PDF names this article, by the one identity rule (pdf_guard)."""
        from .pdf_guard import assess

        title = record.title.strip()
        if not title and fallback_title:
            # The page title "Article title | Journal - Publisher".
            title = re.split(r"\s+\|\s+|\s+-\s+", fallback_title.strip(), maxsplit=1)[0]
            if title.lower().startswith("loading "):
                title = ""
        return assess((text or "")[:15_000], record.doi, title) == "verified"

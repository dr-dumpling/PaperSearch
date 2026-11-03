"""Elsevier journals on their own sites. Two kinds of journal site:

- **PII paths** (Cell Press, The Lancet, Gastroenterology, OARSI, Journal of
  Hepatology, ARD and several hundred society journals), e.g.
  ``https://www.gastrojournal.org/article/S0016-5085(24)00291-9/fulltext``,
  ``https://www.cell.com/cell-metabolism/fulltext/S1550-4131(25)00486-3`` or
  ``https://www.thelancet.com/journals/lanrhe/article/PIIS2665-9913(25)00091-8/fulltext``.
- **DOI paths** (jacc.org), e.g. ``https://www.jacc.org/doi/10.1016/j.jacc.2026.06.019``.
  The site's own "Sign In" is a personal society account; institutions sign in
  on ScienceDirect, which carries the same articles.

PII-path sites have their own institution login ("Get Access" → "Access through
your institution", ``/action/idLogin?type=institution``) through Elsevier ID.
ScienceDirect's session alone does not open them: after a cold start ARD and
Cell Metabolism stayed at the abstract although ScienceDirect showed the
school's session (2026-10-31). So they sign in there first, and ScienceDirect's
same article is the second place to look.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from ...engine.batch_common import _is_browser_error
from ...engine.router import elsevier_journal_article, extract_elsevier_pii
from .sciencedirect import HOSTS as SCIENCEDIRECT_HOSTS

# /doi/<DOI>, /doi/abs/<DOI>, /doi/full/<DOI>; pdf, epdf and pdfdirect are the PDF views.
_DOI_PAGE = re.compile(r"/doi/(?:(abs|full|pdf|epdf|pdfdirect)/)?(10\.\d{4,9}/[^?#]+)", re.I)
_DOI_VIEWS = {"abs": "abstract", "full": "fulltext", "pdf": "pdf", "epdf": "pdf", "pdfdirect": "pdf", "": ""}


_PII: dict[str, tuple[str, float]] = {}
# An unknown PII is looked up again after this long (not on every check of a
# login loop, which asks every few seconds).
_UNKNOWN_PII_RETRY_SEC = 60


def _record_pii(doi: str) -> str:
    """The DOI's PII in compact form; "" when unknown. Crossref's alternative-id
    first; when Crossref cannot be reached, the address doi.org registers
    (linkinghub /retrieve/pii/<PII>). Answers are kept; an unknown PII is asked
    for again after a minute."""
    known = _PII.get(doi)
    if known and (known[0] or time.monotonic() - known[1] < _UNKNOWN_PII_RETRY_SEC):
        return known[0]
    pii = _get_elsevier_pii(doi)
    if pii is None:
        pii = _doi_handle_pii(doi)
    pii = (extract_elsevier_pii(pii) or pii.replace("-", "")).upper()
    _PII[doi] = (pii, time.monotonic())
    return pii


_record_pii.cache_clear = _PII.clear  # type: ignore[attr-defined]


def _get_elsevier_pii(doi: str) -> str | None:
    """Get PII (Publisher Item Identifier) from Crossref API: the PII, "" when
    Crossref answers without one, None when it could not be reached.

    A busy (429), failing (5xx) or slow answer is retried twice: a lookup lost
    to rate limiting sent a jacc.org article down the wrong login (2026-10-31).
    """
    import requests
    from ...network import USER_AGENT

    for attempt in range(3):
        try:
            resp = requests.get(f"https://api.crossref.org/works/{doi}", timeout=10,
                                headers={"User-Agent": USER_AGENT})
        except Exception:
            resp = None
        if resp is not None and resp.status_code == 200:
            try:
                alt_ids = resp.json().get("message", {}).get("alternative-id", [])
            except Exception:
                alt_ids = []
            return next((aid for aid in alt_ids if aid.startswith("S") and len(aid) >= 16), "")
        if resp is not None and resp.status_code == 404:
            return ""
        if attempt < 2:
            wait = 2.0 * (attempt + 1)
            if resp is not None and resp.status_code == 429:
                try:
                    wait = min(10.0, float(resp.headers.get("Retry-After") or wait))
                except ValueError:
                    pass
            time.sleep(wait)
    return None


def _doi_handle_pii(doi: str) -> str:
    """The PII in the address doi.org registers for the DOI (a second source)."""
    try:
        import requests

        resp = requests.get(f"https://doi.org/api/handles/{doi}", timeout=10)
        values = (resp.json().get("values") or []) if resp.status_code == 200 else []
    except Exception:
        return ""
    for value in values:
        pii = extract_elsevier_pii(str((value.get("data") or {}).get("value") or ""))
        if pii:
            return pii
    return ""


def article(url: str) -> tuple[str, str] | None:
    """``(formatted PII, view)`` for an article page with a PII path, else None."""
    return elsevier_journal_article(url)


def doi_article(url: str) -> tuple[str, str] | None:
    """``(DOI, view)`` for an article page with a DOI path (jacc.org), else None."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host in SCIENCEDIRECT_HOSTS or host.endswith("elsevier.com"):
        return None
    match = _DOI_PAGE.fullmatch(unquote(parsed.path))
    return (match.group(2), _DOI_VIEWS[(match.group(1) or "").lower()]) if match else None


def is_page(url: str) -> bool:
    return bool(article(url) or doi_article(url))


def is_supplement(target: Any, page_host: str, doi: str) -> bool:
    """``/cms/<DOI>/attachment/<id>/mmcN.<ext>`` on the page's own host."""
    return (bool(doi) and target.hostname == page_host
            and unquote(target.path).lower().startswith("/cms/" + doi.lower() + "/attachment/"))


# "Access through your institution" behind a PII-path site's "Get Access".
_OWN_LOGIN = 'a[href*="/action/idLogin"][href*="type=institution"]'
_OWN_LOGIN_JS = f"""() => (document.querySelector('{_OWN_LOGIN}') || {{}}).href || ''"""


def _sciencedirect_url(pii: str) -> str:
    return f"https://www.sciencedirect.com/science/article/pii/{pii}"


class JournalSite:
    """Answers for an Elsevier journal's own site; ``None`` = no opinion."""

    def __init__(self, downloader: Any):
        self.d = downloader
        self._own_login: dict[str, str] = {}  # page URL -> the site's institution login ("" = none)

    def institution_login_url(self, page: Any) -> str | None:
        """A PII-path site's own institution login, returning to the article's
        full text: with access the site shows it, without access the abstract."""
        url = str(getattr(page, "url", "") or "")
        found = article(url)
        if not found:
            return None
        if url not in self._own_login:
            # The control is rendered a few seconds after the page loads (ARD:
            # still missing 3 s after it, 2026-10-31); looked for once per page.
            try:
                page.wait_for_selector(_OWN_LOGIN, state="attached", timeout=10_000)
                href = page.evaluate(_OWN_LOGIN_JS)
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                href = ""
            self._own_login[url] = href if isinstance(href, str) else ""
        target = urlparse(self._own_login[url])
        here = urlparse(url)
        if target.scheme != "https" or target.hostname != here.hostname:
            return None
        path = re.sub(r"/abstract(?=/|$)", "/fulltext", here.path) if found[1] == "abstract" else here.path
        query = parse_qs(target.query)
        query["redirectUri"] = [here._replace(path=path, query="", fragment="").geturl()]
        return target._replace(query=urlencode(query, doseq=True)).geturl()

    def login_page_url(self, url: str) -> str | None:
        # ScienceDirect's same article (after the site's own login, if it has one).
        found = article(url)
        if found:
            return _sciencedirect_url(extract_elsevier_pii(found[0])) if found[1] == "abstract" else None
        found = doi_article(url)
        pii = _record_pii(found[0]) if found else ""
        return _sciencedirect_url(pii) if pii else None

    def looks_logged_out(self, page: Any, url: str, text: str) -> bool | None:
        """Journal sites redirect to their abstract view without access. Not a
        shared rule: elsewhere /abstract/ is the article's main page (APS, Thieme).
        A full-text view says nothing more: with only a personal Elsevier account
        a Lancet article was taken as readable and its PDF never came
        (2026-11-02), so the PDF decides."""
        return True if (article(url) or doi_article(url))[1] == "abstract" else None

    def open_pdf_entry(self, page: Any, result: Any) -> bool:
        """Click this article's own PDF link; reference "Full Text (PDF)" links never qualify.

        PII paths: ``/action/showPdf?pii=<PII>`` or ``/pdf/<PII>``.
        DOI paths: ``/doi/pdf|epdf|pdfdirect/<DOI>``.
        """
        url = str(getattr(page, "url", "") or "")
        found = article(url)
        if found:
            pii = extract_elsevier_pii(found[0])

            def own(path: str, href: str) -> bool:
                return ((path == "/action/showpdf" or "/pdf/" in path or path.endswith("/pdf"))
                        and extract_elsevier_pii(href) == pii)
        else:
            doi = doi_article(url)[0].lower()

            def own(path: str, href: str) -> bool:
                match = _DOI_PAGE.fullmatch(path)
                return bool(match) and _DOI_VIEWS[(match.group(1) or "").lower()] == "pdf" and match.group(2).lower() == doi
        return self._click_own_pdf(page, result, own)

    def _click_own_pdf(self, page: Any, result: Any, own: Callable[[str, str], bool]) -> bool:
        try:
            hrefs = page.evaluate("""() => [...document.querySelectorAll('a[href]')].map(a =>
                (a.getClientRects().length > 0 && !a.closest('#references, .references, [class*="reference"]')) ? a.href : '')""")
        except Exception as exc:
            self.d._event(result, "pdf_button_error", f"{type(exc).__name__}: {exc}")
            return False
        for index, href in enumerate(hrefs if isinstance(hrefs, list) else []):
            target = urlparse(str(href or ""))
            path = unquote(target.path).lower()
            if target.scheme == "https" and not path.startswith("/servlet/") and own(path, str(href)):
                clicked = page.evaluate("""(i) => {
                    const el = [...document.querySelectorAll('a[href]')][i];
                    if (!el) return false;
                    el.removeAttribute('target'); el.click(); return true;
                }""", index)
                if clicked is True:
                    self.d._event(result, "pdf_button_clicked", "elsevier-journal-pdf " + str(href)[:200])
                    return True
        return False

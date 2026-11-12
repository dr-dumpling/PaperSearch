"""IOP Publishing: journals on iopscience.iop.org.

Without access the article page offers "Access this article" or "Access
through your institution". The institution login starts at myIOPscience's
sign-in (``myiopscience.iop.org/signin``) with the article as its target: with
``origin=deeplink`` it leads to OpenAthens' institution finder (without it, to
the personal account sign-in only).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlencode, urlparse

from ...engine.batch_common import open_page
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => ({
    status: performance.getEntriesByType('navigation')[0]?.responseStatus || 0,
    doi: document.querySelector('meta[name="citation_doi"]')?.content || '',
    rows: [...document.querySelectorAll('a[href]')].map(a => ({
        href: a.href, label: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
    }))
})"""


def supplement_links_from_page(data: dict, page_url: str, doi: str) -> list[SupplementLink] | None:
    """Files declared by this article's dedicated supplementary-data page.

    IOP's current file host uses signed URLs without a full DOI in the path.
    Bind the list to the article page and keep the signature for the transfer.
    An article without supplementary data has no such page (404, "Page Not
    Found") and no "Supplementary data" link on its own page (2026-11-07).
    """
    page = urlparse(page_url)
    citation = str(data.get("doi") or "").lower().removeprefix("https://doi.org/")
    if (page.scheme != "https" or page.netloc != "iopscience.iop.org"
            or unquote(page.path).rstrip("/").lower() != f"/article/{doi.lower()}/data"):
        return None
    if not citation and data.get("status") == 404:
        return []
    if citation != doi.lower():
        return None
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in data.get("rows", []):
        target = urlparse(str(row.get("href") or ""))
        label = str(row.get("label") or "")
        if (target.scheme == "https"
                and target.netloc == "cfn-live-content-bucket-iop-org.s3.eu-west-1.amazonaws.com"
                and target.path.startswith("/journals/")
                and "supplement" in label.lower() and target.path not in seen):
            seen.add(target.path)
            links.append(SupplementLink(target._replace(fragment="").geturl(), label))
    return links


@register
class IOPAdapter(PublisherAdapter):
    publisher = "iop"

    def supplements_page_urls(self, doi: str) -> list[str]:
        return [f"https://iopscience.iop.org/article/{doi}/data"]

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        return supplement_links_from_page(page.evaluate(_SUPPLEMENT_ROWS_JS), str(page.url), doi)

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        current_url = str(getattr(page, "url", "") or "")
        host = (urlparse(current_url).hostname or "").lower()
        if host == "openathens.net" or host.endswith(".openathens.net"):
            return None  # a federation page: the engine clicks nothing there
        if "iopscience.iop.org/article/" not in current_url.lower():
            return None
        text = self.d._body_text(page, 5_000).lower()
        offered = "access this article" in text or "access through your institution" in text
        # An accepted manuscript's page has no access box, its PDF still needs the
        # institution's login (Physics in Medicine & Biology, 2026-11-08). Once per
        # article: back from the login without access, the page is left as it is.
        manuscript = "accepted manuscript" in text and result is not None and not any(
            e.get("state") == "sso_entry_clicked" and "myiopscience.iop.org/signin" in str(e.get("detail", ""))
            for e in getattr(result, "events", None) or [])
        if not offered and not manuscript:
            return None
        signin_url = "https://myiopscience.iop.org/signin?" + urlencode(
            {"origin": "deeplink", "target": current_url}
        )
        try:
            open_page(page, signin_url, timeout_ms=30_000)
            if result is not None:
                self.d._event(result, "sso_entry_clicked", signin_url)
            return True
        except Exception as exc:
            if result is not None:
                self.d._event(result, "sso_entry_error", f"{type(exc).__name__}: {exc}")
            return None  # the generic entries are tried next

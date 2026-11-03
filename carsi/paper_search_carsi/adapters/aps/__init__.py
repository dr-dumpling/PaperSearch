"""American Physical Society: journals on journals.aps.org (and link.aps.org DOIs).

Article pages are ``/<journal>/abstract/<DOI>`` and ``/pdf/<DOI>``, and
link.aps.org's ``/doi/`` addresses. Without access the article shows an
access box (``#inline-unauthorized-page``, a paywall box of the shared access
rule) offering APS member, APS account and institution-provided logins. The institution's own login is "Sign in via
your Institution" in the header's Sign-in menu (OpenAthens). A login that
ends on another APS page goes back to this record's article.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from ...engine.router import _append_aps_candidates
from ...engine.batch_common import open_page
from ..base import PublisherAdapter, register


# APS resolves article pages per journal code; the DOI suffix carries the journal.
def aps_article_url(doi: str) -> str:
    suffix = doi.split("/", 1)[-1] if "/" in doi else doi
    journal_codes = (
        ("PhysRevLett.", "prl"),
        ("PhysRevA.", "pra"),
        ("PhysRevB.", "prb"),
        ("PhysRevC.", "prc"),
        ("PhysRevD.", "prd"),
        ("PhysRevE.", "pre"),
        ("PhysRevX.", "prx"),
        ("PhysRevApplied.", "prapplied"),
        ("PhysRevResearch.", "prresearch"),
        ("RevModPhys.", "rmp"),
        ("PRXQuantum.", "prxquantum"),
    )
    for prefix, journal_code in journal_codes:
        if suffix.startswith(prefix):
            return f"https://journals.aps.org/{journal_code}/abstract/{doi}"
    return ""


@register
class APSAdapter(PublisherAdapter):
    publisher = "aps"
    returns_to_record_article = True

    def article_url(self, doi: str) -> str | None:
        return aps_article_url(doi) or None

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_aps_candidates(urls, source_url)
        return urls

    @classmethod
    def belongs_to_article(cls, url: str, doi: str, source_url: str) -> bool | None:
        lower = url.lower()
        host = (urlparse(url).hostname or "").lower()
        if host.endswith("journals.aps.org") or host.endswith("link.aps.org"):
            if "/accepted" in lower:
                return False
            doi_lower = doi.lower()
            doi_escaped = doi_lower.replace("/", "%2f")
            if "/pdf/" in lower or "/doi/" in lower:
                return doi_lower in lower or doi_escaped in lower
        return True

    def is_success_article_url(self, url: str) -> bool | None:
        parsed = urlparse(url.lower())
        host = parsed.netloc
        path = parsed.path
        if host.endswith("link.aps.org") and path.startswith("/doi/"):
            return True
        return host.endswith("journals.aps.org") and ("/abstract/" in path or "/pdf/" in path)

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        host = (urlparse(str(getattr(page, "url", "") or "")).hostname or "").lower()
        if host == "openathens.net" or host.endswith(".openathens.net"):
            return None  # a federation page: the engine clicks nothing there
        if self.institution_sign_in(page, result):
            return True
        if result is not None:
            self.d._event(result, "aps_institution_entry_missing", getattr(page, "url", ""))
        return False

    def institution_sign_in(self, page: Any, result: Any = None) -> bool:
        """APS "Sign in via your Institution" (OpenAthens federation).

        It sits in the header's Sign-in menu. The access box's
        "username/password provided by your institution" link is an APS
        account form, not the institution's own login, and is never used.
        """
        d = self.d
        current_url = str(getattr(page, "url", "") or "").lower()
        if "/auth/openathens/login" in current_url or "/login_inst_user" in current_url:
            return False
        try:
            detail = page.evaluate(
                """
                () => {
                  const norm = (value) => (value || '').toString().replace(/\\s+/g, ' ').trim();
                  const link = [...document.querySelectorAll('a[href]')].find((el) => {
                    let url;
                    try { url = new URL(el.getAttribute('href'), location.href); } catch (e) { return false; }
                    return url.protocol === 'https:' && url.hostname === 'journals.aps.org'
                      && url.pathname === '/auth/openathens/login' && url.searchParams.get('rt');
                  });
                  if (!link) return null;
                  return {
                    text: norm(link.innerText || link.textContent || '').slice(0, 200),
                    href: link.href || link.getAttribute('href') || ''
                  };
                }
                """
            )
            if not isinstance(detail, dict) or not detail.get("href"):
                return False
            open_page(page, str(detail["href"]), timeout_ms=30_000)
            if result is not None:
                d._event(result, "sso_entry_clicked", json.dumps(detail, ensure_ascii=False))
            return True
        except Exception as exc:
            if result is not None:
                d._event(result, "sso_entry_error", f"{type(exc).__name__}: {exc}")
            return False

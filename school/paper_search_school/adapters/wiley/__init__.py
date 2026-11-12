"""Wiley Online Library (onlinelibrary.wiley.com and its society subdomains).

Wiley shows "PDF" and "Read the full text" to every reader and no offer text
to one without access, so its access is the shared rule's positive evidence:
the signed-in school by the logo, the full-text sections, the .doi-access badge
("Full Access" on signed-in pages of old scanned articles and conference
digests, which have no full-text sections, 2026-11-02), the denial layout."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from ...engine.router import is_wiley_article_pdf_url
from ...engine.batch_common import open_page
from ..base import PublisherAdapter, SupplementLink, register

_ARTICLE_PATH = re.compile(r"/doi/(?:(?:abs|full|epdf|pdf|pdfdirect)/)?(10\.\d{4,9}/[^?#]+)")

# Clicks the article page's own "Institutional login" / "Access through your
# institution" control on a Wiley host; never personal account or register.
_ENTRY_JS = """
() => {
  const norm = (value) => (value || '').toString().replace(/\\s+/g, ' ').trim();
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const hrefOf = (el) => {
    const raw = el.href || el.getAttribute('href') || el.getAttribute('formaction') || '';
    if (!raw) return '';
    try { return new URL(raw, location.href).href; } catch { return raw; }
  };
  const controls = [...document.querySelectorAll('a,button,[role="button"],input[type="button"],input[type="submit"]')]
    .filter(visible)
    .map((el) => {
      if (!el.href && el.closest('form')) return null;
      const text = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '');
      const href = hrefOf(el);
      if (href) {
        const target = new URL(href, location.href);
        if (target.protocol !== 'https:' || !(target.hostname === 'onlinelibrary.wiley.com' || target.hostname.endsWith('.onlinelibrary.wiley.com'))) return null;
      }
      const haystack = `${text} ${href} ${el.className || ''} ${el.id || ''}`.toLowerCase();
      const exact = /^(?:institutional login|access through your institution)$/i.test(text);
      const institutionLogin = exact || haystack.includes('institutional login')
        || haystack.includes('access through your institution');
      if (!institutionLogin) return null;
      if (haystack.includes('personal') || haystack.includes('account') || haystack.includes('register') || haystack.includes('login / register')) return null;
      const rect = el.getBoundingClientRect();
      return {el, text, href, rect, score: (exact ? 100 : 20) - Math.max(0, rect.top / 1000)};
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score);
  const target = controls[0];
  if (!target) return null;
  target.el.scrollIntoView({block: 'center', inline: 'center'});
  target.el.click();
  return {
    selector: 'wiley-institutional-login',
    text: target.text.slice(0, 200),
    href: target.href.slice(0, 500),
    score: Math.round(target.score)
  };
}
"""


def _is_wiley_host(host: str | None) -> bool:
    return bool(host) and (host == "onlinelibrary.wiley.com" or host.endswith(".onlinelibrary.wiley.com"))


@register
class WileyAdapter(PublisherAdapter):
    publisher = "wiley"
    validates_article_pdf = True
    pdf_rejected_event = "wiley_pdf_rejected"
    unquotes_supplement_urls = True

    @classmethod
    def belongs_to_article(cls, url: str, doi: str, source_url: str) -> bool | None:
        return is_wiley_article_pdf_url(url, doi)

    def login_url(self) -> str | None:
        return "https://onlinelibrary.wiley.com/"

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        current = urlparse(str(getattr(page, "url", "") or ""))
        if current.scheme != "https" or not _is_wiley_host(current.hostname):
            return False
        if self.d._has_visible_editable_input(page):
            return False
        try:
            detail = page.evaluate(_ENTRY_JS)
            if isinstance(detail, dict) and detail.get("text"):
                if result is not None:
                    self.d._event(result, "sso_entry_clicked", "wiley-official-institution-control")
                return True
        except Exception as exc:
            if result is not None:
                self.d._event(result, "sso_entry_error", f"{type(exc).__name__}: {exc}")
            return False
        # Abstract pages of unentitled readers show no institution control at
        # all (only "Login / Register"); Wiley's own SSO start page is the
        # institution chooser for the current article.
        article = _ARTICLE_PATH.fullmatch(current.path)
        if not article:
            return False
        target = ("https://onlinelibrary.wiley.com/action/ssostart?redirectUri="
                  + quote(f"/doi/{article.group(1)}", safe=""))
        try:
            open_page(page, target, timeout_ms=30_000)
        except Exception as exc:
            if result is not None:
                self.d._event(result, "sso_entry_error", f"wiley-official-ssostart {type(exc).__name__}")
            return False
        if result is not None:
            self.d._event(result, "sso_entry_clicked", "wiley-official-ssostart")
        return True

    def is_article_pdf_url(self, url: str, doi: str = "") -> bool | None:
        return is_wiley_article_pdf_url(url, doi)

    def supplements_page_url(self, doi: str) -> str | None:
        return f"https://onlinelibrary.wiley.com/doi/full/{doi}"

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        """The Supporting Information table: ``/action/downloadSupplement?doi=<this DOI>&file=...``."""
        rows = page.evaluate("""() => [...document.querySelectorAll('a[href*="downloadSupplement"]')].map(a => {
            const row = a.closest('tr');
            // The description cells, not the file-name cell (name, type and size).
            const cells = row ? [...row.querySelectorAll('td')].filter(td => !td.contains(a)) : [];
            const description = cells.map(td => (td.innerText || '').replace(/\\s+/g, ' ').trim())
                .filter(Boolean).join(' ').slice(0, 240);
            return {href: a.href, text: (a.innerText || '').trim(), row: description};
        })""")
        links: list[SupplementLink] = []
        for row in rows if isinstance(rows, list) else []:
            target = urlparse(str(row.get("href") or ""))
            if (target.scheme != "https" or not _is_wiley_host(target.hostname)
                    or parse_qs(target.query).get("doi", [""])[0].lower() != doi.lower()):
                continue
            links.append(SupplementLink(target.geturl(), str(row.get("row") or row.get("text") or "")))
        return links

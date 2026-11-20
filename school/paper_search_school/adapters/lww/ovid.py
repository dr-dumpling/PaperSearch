"""ovid.com/jnls/: LWW articles Ovid serves behind a two-step access panel.

Without access the abstract page shows "Check Access" (an offer of the shared
access rule), which opens the panel with the institutional login."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ...engine.batch_common import _is_browser_error, goto_retrying

HOSTS = {"ovid.com", "www.ovid.com"}
_ARTICLE = re.compile(r"/jnls/[^/]+/(?:abstract|fulltext|pdf)/")

# --fulltext (engine/fulltext_page.py; PaperSearch's sites/templates/ovid.ts). Ovid sends
# the article rendered (Next.js, no MathJax): the body is .lww-article__body, which a
# reader without access does not get (the page offers "Check Access"); the references and
# the image gallery are in it, after the text. A figure shows its image 710 pixels wide and
# offers 1200 in its srcset (/image-api/imgsrv/…/width/1200.png): the largest is taken, as
# the converter does; the general sample rules had the 710 ones (Journal of Hypertension,
# Critical Care Medicine, pages saved after a school login, 2026-11-14). The references
# are all in the page (the list is only clamped on screen): nothing is opened before saving.
FULLTEXT_SHOWN_JS = """() => {
  const body = document.querySelector('article.lww-article .lww-article__body');
  if (!body || document.querySelector('button.omni-article-tool__check-access')) return false;
  const text = [...body.children]
    .filter((part) => !part.matches('.lww-article__end-matter, .omni-article-keywords, .lww-article-sdc, #image-gallery'))
    .reduce((total, part) => total + (part.innerText || '').length, 0);
  return text > 500;
}"""
FULLTEXT_IMAGES_JS = r"""() => [...document.querySelectorAll('article.lww-article figure img, article.lww-article .lww-article__table img')]
  .filter((img) => !img.closest('#image-gallery, figcaption')
    && (img.closest('figure') || !img.closest('.lww-article__table').querySelector('table')))
  .map((img) => {
    const width = (url) => Number(/\/width\/(\d+)\.\w+(?:[?#]|$)/.exec(url)?.[1] || 0);
    const candidates = [img.getAttribute('src') || '', ...(img.getAttribute('srcset') || '').split(',')
      .map((part) => part.trim().split(/\s+/)[0])].filter((src) => src && !src.startsWith('data:'));
    return candidates.reduce((best, url) => (width(url) > width(best) ? url : best), candidates[0] || '');
  })
  .filter(Boolean)
  .map((src) => new URL(src, location.href).href)"""


def is_page(url: str) -> bool:
    parsed = urlparse(url or "")
    return (parsed.hostname or "").lower() in HOSTS and parsed.path.startswith("/jnls/")


def is_redirect(url: str) -> bool:
    """``ovid.com/<DOI>``: Ovid's DOI address, which its script moves on to the
    article (``/jnls/<journal>/fulltext/...``); no PDF link on it yet (Epidemiology, 2026-11-01)."""
    parsed = urlparse(url or "")
    return (parsed.hostname or "").lower() in HOSTS and bool(re.match(r"/10\.\d{4,9}/", parsed.path))


def is_article(url: str) -> bool:
    parsed = urlparse((url or "").lower())
    return parsed.scheme == "https" and bool(_ARTICLE.match(parsed.path))


class OvidSite:
    """Answers for ovid.com/jnls/ pages; ``None`` = no opinion."""

    def __init__(self, downloader: Any):
        self.d = downloader

    def open_pdf_entry(self, page: Any, result: Any) -> bool:
        """Open this article's PDF with the article page as Referer. Without it
        Ovid answers 307 back to the full text, and the "Download PDF" click
        went without it now and then (J Clin Gastroenterology, 2026-11-01)."""
        article = str(getattr(page, "url", "") or "")
        hrefs = page.evaluate("() => [...document.querySelectorAll('a[href*=\"/pdf/\"]')].map(a => a.href)")
        for href in hrefs if isinstance(hrefs, list) else []:
            if isinstance(href, str) and self.d._article_pdf_url_matches(href, result.doi):
                self.d._event(result, "pdf_button_clicked", "ovid-article-pdf")
                try:
                    goto_retrying(page, href, timeout_ms=self.d.pdf_timeout_ms, referer=article)
                except Exception as exc:
                    if not _is_browser_error(exc):
                        raise
                    # The capture may answer the request itself (Chromium: 204,
                    # so no download); whether the PDF came is the capture's call.
                    self.d._event(result, "pdf_navigation_ended", type(exc).__name__)
                return True
        return False

    def open_institution_entry(self, page: Any, result: Any) -> bool:
        # Select the institutional control, avoiding individual/AAOS login.
        institution = page.locator("a.omni-sso-url").filter(
            has_text=re.compile(r"Institutional\s+Users", re.I)).first
        if not institution.is_visible():
            wall = page.locator("button.omni-article-tool__check-access").first
            if not wall.is_visible():
                return False
            if not self.d._click_control(page, wall, result, "ovid-check-access"):
                return False
            institution.wait_for(state="visible", timeout=5_000)
        if not self.d._click_control(page, institution, result, "ovid-institution-control"):
            return False
        self.d._event(result, "sso_entry_clicked", "ovid-institution-control")
        return True

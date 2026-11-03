"""ScienceDirect: Elsevier's own platform (journal articles and book chapters).

Its access (the /abs/pii/ view, the "Full text access" label, "Brought to you
by", the "Access through <school>" gate, "<school> does not subscribe to this
content on ScienceDirect.") is the shared access rule's. With full text through
ClinicalKey or a personal account but not the school, the article offers no
PDF control (J Hepatol, 2026-10-31): the PDF step then lands on the gate and
signs in (batch_capture.py)."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from ...engine.batch_common import _is_browser_error

HOSTS = {"sciencedirect.com", "www.sciencedirect.com"}
# Article and book-chapter pages: /science/article/(abs/)pii/<PII> and
# /science/chapter/<book type>/(abs/)pii/<PII>.
_ITEM = re.compile(r"/science/(?:article|chapter/[^/]+)/(abs/)?pii/", re.I)

# The article's own "View PDF" control (not the recommended-articles column);
# kept in the observed tab. A control linking to another PII (a recommended or
# related article) never qualifies, wherever the layout puts it.
_VIEW_PDF_JS = """
                () => {
                  const piiOf = (value) => {
                    const match = /\\/pii\\/([0-9A-Za-z]+)/.exec(value || '');
                    return match ? match[1].toUpperCase() : '';
                  };
                  const pagePii = piiOf(location.pathname);
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
                      const rect = el.getBoundingClientRect();
                      const text = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '');
                      const href = hrefOf(el);
                      const haystack = `${text} ${href} ${el.className || ''} ${el.id || ''}`.toLowerCase();
                      const isPdf = /\\bview pdf\\b/.test(haystack)
                        || /\\bdownload pdf\\b/.test(haystack)
                        || haystack.includes('/pdfft')
                        || haystack.includes('pdfreader');
                      if (!isPdf) return null;
                      const linkedPii = piiOf(href);
                      if (pagePii && linkedPii && linkedPii !== pagePii) return null;
                      const isRecommendedColumn = rect.left > Math.max(900, window.innerWidth * 0.70);
                      const exactScore = /^view pdf$/i.test(text) ? 120 : 0;
                      const topBarScore = rect.top < 160 ? 60 : 0;
                      const hrefScore = href.toLowerCase().includes('/pdfft') ? 30 : 0;
                      const recommendedPenalty = isRecommendedColumn ? 150 : 0;
                      return {el, text, href, rect, score: exactScore + topBarScore + hrefScore - recommendedPenalty - Math.max(0, rect.top / 1000)};
                    })
                    .filter(Boolean)
                    .sort((a, b) => b.score - a.score);
                  const target = controls[0];
                  if (!target || target.score < 0) return null;
                  const detail = {
                    selector: 'elsevier-view-pdf',
                    text: target.text.slice(0, 200),
                    href: target.href.slice(0, 500),
                    score: Math.round(target.score)
                  };
                  // Keep the site's normal navigation in the page whose PDF
                  // responses are being captured. Otherwise target=_blank
                  // opens a viewer in an unobserved tab and loses the file.
                  if (target.el.tagName === 'A') target.el.setAttribute('target', '_self');
                  target.el.click();
                  return detail;
                }
                """


def is_page(url: str) -> bool:
    return (urlparse(url or "").hostname or "").lower() in HOSTS


def is_supplement(target: Any, pii: str) -> bool:
    """``https://ars.els-cdn.com/content/image/1-s2.0-<PII>-mmcN.<ext>`` for this page's PII."""
    return (target.hostname == "ars.els-cdn.com"
            and bool(re.search(r"/content/image/1-s2\.0-" + re.escape(pii) + r"-mmc\d+\.[a-z0-9]+$",
                               target.path, re.I)))


class ScienceDirectSite:
    """Answers for ScienceDirect pages; ``None`` = no opinion."""

    @staticmethod
    def wait_for_full_text(page: Any) -> None:
        """The article body, and the appendices that list its supplementary files,
        render seconds after the page loads: 5-9 s without the browser's disk cache
        (foodchem, rineng: no files found 2 s after loading, 2026-11-01). An
        abstract-only page never gets a body; its links are read after the wait."""
        try:
            page.wait_for_selector("#body", state="attached", timeout=15_000)
            # The appendices follow the body: until the page's requests settle, at most 2 s.
            page.wait_for_load_state("networkidle", timeout=2_000)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise

    def __init__(self, downloader: Any):
        self.d = downloader

    def content_error(self, page: Any) -> bool:
        # ScienceDirect has no page for this article (EMC titles, served only
        # from EM-Consulte / ClinicalKey France): its PDF never arrives.
        if self.d._title(page).strip().lower() == "page not found | sciencedirect":
            return True
        text = " ".join(self.d._body_text(page, 5000).lower().split())
        return "cpe00001" in text and "there was a problem providing the content you requested" in text

    def open_pdf_entry(self, page: Any, result: Any) -> bool | None:
        try:
            detail = page.evaluate(_VIEW_PDF_JS)
            if isinstance(detail, dict) and detail.get("text"):
                self.d._event(result, "pdf_button_clicked", json.dumps(detail, ensure_ascii=False))
                return True
        except Exception as exc:
            self.d._event(result, "pdf_button_error", f"{type(exc).__name__}: {exc}")
            return None
        if _ITEM.match(urlparse(str(getattr(page, "url", "") or "")).path):
            # No PDF control of this article: the generic click would take the
            # first PDF link, a supplementary file ("Download Acrobat PDF file").
            self.d._event(result, "pdf_button_missing", "sciencedirect")
            return False
        return None

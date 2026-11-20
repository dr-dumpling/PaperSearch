"""Springer Nature (link.springer.com, nature.com, BMC)."""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse

from ...engine.router import is_springer_article_pdf_url, is_supplementary_url
from ..base import PublisherAdapter, SupplementLink, register

# Every supplementary-file link on the page with its item's caption.
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href*="static-content.springer.com/esm/"]')].map(a => {
    const item = a.closest('.c-article-supplementary__item, li, tr');
    const text = s => (s || '').replace(/\\s+/g, ' ').trim();
    return {href: a.href, label: text(item ? item.innerText : a.innerText).slice(0, 240)};
})"""


def supplement_links_from_rows(rows: Any, doi: str) -> list[SupplementLink]:
    """This article's electronic supplementary material:
    ``https://static-content.springer.com/esm/art%3A<DOI>/MediaObjects/<name>_ESM.<ext>``."""
    prefix = "/esm/art:" + (doi or "").lower() + "/"
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        target = urlparse(str(row.get("href") or ""))
        url = target._replace(fragment="").geturl()
        if (doi and target.scheme == "https" and target.hostname == "static-content.springer.com"
                and unquote(target.path).lower().startswith(prefix) and url not in seen):
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


@register
class SpringerNatureAdapter(PublisherAdapter):
    publisher = "springer nature"
    validates_article_pdf = True
    # Springer marks its main PDF anchors as downloads.
    keeps_pdf_out_of_downloads = True
    native_pdf_patterns = (
        "https://link.springer.com/content/pdf/*",
        "https://nature.com/articles/*.pdf*",
        "https://www.nature.com/articles/*.pdf*",
    )
    unquotes_supplement_urls = True

    def login_url(self) -> str | None:
        return "https://link.springer.com/institutional-login"

    @classmethod
    def keeps_pdf_candidate(cls, profile: Any, url: str, doi: str) -> bool:
        return is_springer_article_pdf_url(url, doi) and not is_supplementary_url(profile, url)

    @classmethod
    def belongs_to_article(cls, url: str, doi: str, source_url: str) -> bool | None:
        return is_springer_article_pdf_url(url, doi)
    sso_selectors = ("a:has-text('Log in via an institution')", "button:has-text('Log in via an institution')")
    # --fulltext on Springer Nature's article template (nature.com, SpringerLink, BMC): the
    # body is .main-content in .c-article-body, which a page without access does not have;
    # nature.com can leave its preview notice on a page the institution has full access
    # to. Each figure's largest image is its media.springernature.com address with "full"
    # for the size segment (lw685), an Extended Data figure's is its data-supp-info-image,
    # an Extended Data table's image the one its table page shows (put in by
    # fulltext_prepare_js). Pages saved after a school login, 2026-11-14; PaperSearch Pro
    # converts them.
    fulltext_shown_js = """() => {
      const body = document.querySelector('.c-article-body .main-content, .c-article-body.main-content');
      const granted = [...document.querySelectorAll('[data-test="access-message"]')]
        .some((node) => /full access to this article/i.test(node.textContent || ''));
      const preview = [...document.querySelectorAll('[data-test="institution-access-preview"], .c-preview-message__link, [data-test="access-article"]')]
        .some((node) => node.getClientRects().length > 0);
      return (body?.innerText.length || 0) > 500 && (granted || !preview);
    }"""
    fulltext_images_js = r"""() => {
      const full = (src) => {
        try {
          return new URL(src, document.baseURI).href
            .replace(/^(https?:\/\/media\.springernature\.com\/)(?:lw|w|m|h)\d+(?:h\d+)?\/(?=springer-static\/)/i, '$1full/');
        } catch {
          return '';
        }
      };
      const figures = [...document.querySelectorAll('.c-article-body .c-article-section__figure img, .c-article-body figure img')]
        .filter((img) => !img.closest('figcaption, .c-article-section__figure-description, .c-article-table, .c-article-equation'))
        .map((img) => img.getAttribute('src') || img.getAttribute('data-src'));
      const boxes = [...document.querySelectorAll('.c-article-body .c-article-box__content')]
        .filter((box) => !box.textContent.trim())
        .flatMap((box) => [...box.querySelectorAll('img')].map((img) => img.getAttribute('src')));
      const extended = [...document.querySelectorAll('.c-article-body a[data-supp-info-image]')]
        .map((a) => a.getAttribute('data-supp-info-image'));
      const tables = [...document.querySelectorAll('.c-article-body .c-article-table .c-article-table-image img')]
        .map((img) => img.getAttribute('src'));
      return [...figures, ...boxes, ...extended, ...tables].filter((src) => src && !src.startsWith('data:')).map(full).filter(Boolean);
    }"""
    # The article only links each table's own page (/tables/N). Before the page is read,
    # each such page is fetched from the article page (same origin, the session's
    # cookies), one after another, and its .c-article-table-container (the table, or an
    # Extended Data table's image, with its notes) put into the article's .c-article-table,
    # marked data-table-inlined; the converter writes it as the table. A page that does not
    # come in time, is not a table page (a challenge, a login) or names another table
    # leaves the link as it was. At most 30 tables, 5 s each, 12 s in all: the page read
    # has 40 s (batch_capture.FULLTEXT_READ_SEC).
    fulltext_prepare_js = r"""async () => {
      const deadline = Date.now() + 12000;
      const label = (text) => (((text || '').replace(/\s+/g, ' ').trim()
        .match(/^(?:extended data\s+)?tab(?:le)?\.?\s*[a-z]?\d+[a-z]?/i) || [''])[0]).toLowerCase().replace(/[.\s]+/g, ' ').trim();
      const pending = [...document.querySelectorAll('.c-article-body .c-article-table')]
        .filter((table) => !table.hasAttribute('data-table-inlined') && !table.querySelector('table, .c-article-table-image'))
        .slice(0, 30);
      let inlined = 0;
      for (const table of pending) {
        const remaining = deadline - Date.now();
        if (remaining < 500) break;
        const link = table.querySelector('a[data-test="table-link"], a[href*="/tables/"]');
        let url;
        try {
          url = new URL(link?.getAttribute('href') || '', document.baseURI);
        } catch {
          continue;
        }
        if (!link || url.origin !== location.origin || !/\/tables\/\d+\/?$/.test(url.pathname)) continue;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), Math.min(5000, remaining));
        try {
          const response = await fetch(url.href, {credentials: 'include', signal: controller.signal});
          if (!response.ok) continue;
          const page = new DOMParser().parseFromString(await response.text(), 'text/html');
          const container = page.querySelector('.c-article-table-container');
          if (!container || !container.querySelector('table, .c-article-table-image img')) continue;
          const theirs = label(page.querySelector('.c-article-satellite-title, h1')?.textContent);
          const ours = label(table.querySelector('[data-test="table-caption"], figcaption')?.textContent);
          if (theirs && ours && theirs !== ours) continue;
          container.querySelectorAll('script, style, link, button').forEach((node) => node.remove());
          const base = response.url || url.href;
          for (const node of container.querySelectorAll('[src], [href]')) {
            for (const name of ['src', 'href']) {
              const value = node.getAttribute(name);
              if (!value || /^(#|data:)/.test(value)) continue;
              try {
                node.setAttribute(name, new URL(value, base).href);
              } catch {
                // An address that does not parse stays as it is.
              }
            }
          }
          const footer = page.querySelector('.c-article-table-footer');
          const holder = table.querySelector('figure') || table;
          holder.appendChild(document.importNode(container, true));
          if (footer && !container.contains(footer)) holder.appendChild(document.importNode(footer, true));
          table.setAttribute('data-table-inlined', url.href);
          inlined += 1;
        } catch {
          // Not in time, or not read: the link stays.
        } finally {
          clearTimeout(timer);
        }
      }
      return inlined;
    }"""

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        return supplement_links_from_rows(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

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
import re
from typing import Any
from urllib.parse import unquote, urlparse

from ...engine.router import _append_aps_candidates
from ...engine.batch_common import open_page
from ...engine.fulltext_page import MATHJAX_SOURCES_JS
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => ({
    href: a.href, label: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
}))"""

# --fulltext (PaperSearch's sites/templates/aps.ts). The article page loads its full text
# after the abstract into #fulltext-content (data-loaded "pending", then "yes"). Without
# access the page has #inline-unauthorized-page and the full-text section is empty; an
# accepted paper (/<journal>/accepted/<DOI>) has only its abstract. A figure shows its
# 1000-pixel image; the page's own data (the window.APS script) lists each figure's images,
# and the largest (1600 pixels) is taken, as the converter does (10.1103/x226-5mcz, open
# access, 2026-11-15).
FULLTEXT_SHOWN_JS = """() => {
  if (/\\/accepted\\//i.test(location.pathname) || document.querySelector('#inline-unauthorized-page')) return false;
  const body = document.querySelector('#article-body #fulltext-content');
  if (!body || body.getAttribute('data-loaded') === 'pending') return false;
  const text = [...body.querySelectorAll('p')].filter((p) => !p.closest('figure, .article-fulltext-table-wrap'))
    .reduce((total, p) => total + (p.textContent || '').length, 0);
  return text > 500;
}"""
FULLTEXT_IMAGES_JS = """() => {
  const body = document.querySelector('#article-body #fulltext-content');
  if (!body) return [];
  const source = [...document.querySelectorAll('script:not([src])')].map((script) => script.textContent || '')
    .find((text) => text.includes('window.APS = ')) || '';
  let figures = [];
  const start = source.indexOf('{', source.indexOf('window.APS = '));
  for (let index = start, depth = 0, quoted = false; start >= 0 && index < source.length; index += 1) {
    const char = source[index];
    if (quoted) {
      if (char === '\\\\') index += 1;
      else if (char === '"') quoted = false;
    } else if (char === '"') {
      quoted = true;
    } else if (char === '{') {
      depth += 1;
    } else if (char === '}' && --depth === 0) {
      try { figures = JSON.parse(source.slice(start, index + 1))?.article?.figures || []; } catch { figures = []; }
      break;
    }
  }
  const area = (variant) => (String(variant?.meta?.actual_dimensions || '').match(/^(\\d+)x(\\d+)$/) || [0, 0, 0])
    .slice(1).reduce((product, side) => product * Number(side), 1);
  return [...body.querySelectorAll('figure')].flatMap((figure) => [...figure.querySelectorAll('img')]
    .filter((img) => !img.closest('figcaption'))
    .map((img) => {
      const shown = img.getAttribute('data-original') || img.getAttribute('src') || '';
      const images = ((Array.isArray(figures) ? figures : []).find((entry) => entry?.xmlid === figure.id)?.variants || [])
        .filter((variant) => /^image\\//.test(variant?.content_type || '') && variant?.uuid);
      const uuid = (shown.match(/\\/deliverable\\/([0-9a-f-]+)$/i) || [])[1];
      if (!uuid || !images.some((variant) => variant.uuid === uuid)) return shown;
      const largest = images.reduce((best, variant) => (area(variant) > area(best)
        || (area(variant) === area(best) && (variant.size || 0) > (best.size || 0)) ? variant : best));
      return shown.replace(/[0-9a-f-]+$/i, largest.uuid);
    }))
    .filter((src) => src && !src.startsWith('data:'))
    .map((src) => new URL(src, location.href).href);
}"""
# Formulas are MathML (abstract, body, references) that MathJax 4 replaces with lazy
# placeholders; MATHJAX_SOURCES_JS keeps the sources MathJax still lists. The body is put
# in in two parts (front, back), and the first part's formulas were in none of MathJax's
# lists, nor typeset when scrolled to (216 of 281 in a headless Chromium, 2026-11-15). Their
# sources are then taken from the full text's JSON the page loaded them from
# (<urlPrefix>fulltext/<DOI>, same origin, the session's cookies, 10 s): each part's
# <math> in order, put on the part's formulas in order only when the counts agree, each is
# a display formula where the page has one, and those MathJax still knew are the same.
# It returns the count kept, or with the JSON a short report for the record.
FULLTEXT_PREPARE_JS = r"""async () => {
  const kept = await (MATHJAX_SOURCES_JS)();
  const content = document.querySelector('#article-body #fulltext-content');
  if (!content?.querySelector('mjx-container:not([data-original-mathml])')) return kept;
  const prefix = String(window.APS?.product?.urlPrefix || '');
  const id = String(window.APS?.article?.id || '');
  if (!/^\/[a-z]+\/$/i.test(prefix) || !/^10\.\d{4,9}\//.test(id)) return `${kept} kept; no APS article data`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  let data, failed = '';
  try {
    const response = await fetch(`${prefix}fulltext/${id}`, {credentials: 'include', headers: {Accept: 'application/json'},
                                                             signal: controller.signal});
    failed = response.ok ? '' : `HTTP ${response.status}`;
    data = response.ok ? await response.json() : null;
  } catch (error) {
    failed = error?.name || 'error';
    data = null;
  } finally {
    clearTimeout(timer);
  }
  if (!data || typeof data !== 'object') return `${kept} kept; full-text JSON: ${failed || 'not an object'}`;
  const display = (source) => /^<math\b[^>]*\bdisplay=["']block["']/.test(source);
  const text = (source) => source.replace(/<[^>]*>/g, '').replace(/\s+/g, '');
  let filled = 0;
  const parts = [];
  for (const part of ['front', 'back']) {
    const sources = [];
    const walk = (component) => {
      if (!component || typeof component !== 'object') return;
      for (const found of String(component.body || '').matchAll(/<math\b[\s\S]*?<\/math>/g)) sources.push(found[0]);
      for (const child of Array.isArray(component.components) ? component.components : []) walk(child);
    };
    walk(data[part]);
    const nodes = [...content.querySelectorAll(`.article-fulltext-${part} mjx-container`)];
    const differs = nodes.length !== sources.length ? -1 : nodes.findIndex((node, index) => display(sources[index]) !== !!node.closest('.article-fulltext-disp-eq')
      || (node.hasAttribute('data-original-mathml') && text(node.getAttribute('data-original-mathml')) !== text(sources[index])));
    let put = 0;
    if (nodes.length && nodes.length === sources.length && differs < 0) {
      nodes.forEach((node, index) => {
        if (node.hasAttribute('data-original-mathml')) return;
        node.setAttribute('data-original-mathml', sources[index]);
        put += 1;
      });
    }
    filled += put;
    parts.push(`${part} ${put} filled, ${nodes.length} on the page, ${sources.length} in the JSON`
      + (differs >= 0 ? `, formula ${differs + 1} differs` : ''));
  }
  return `${kept + filled} kept (MathJax ${kept}); ${parts.join('; ')}`;
}""".replace("MATHJAX_SOURCES_JS", MATHJAX_SOURCES_JS)


def supplement_links_from_rows(rows: list[dict], doi: str) -> list[SupplementLink]:
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in rows:
        target = urlparse(str(row.get("href") or ""))
        path = unquote(target.path).lower()
        url = target._replace(fragment="").geturl()
        if (target.scheme == "https" and target.netloc == "journals.aps.org"
                and re.fullmatch(r"/[a-z]+/supplemental/" + re.escape(doi.lower()) + r"/[^/]+", path)
                and url not in seen):
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


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
        if suffix.lower().startswith(prefix.lower()):
            # DOI identity is case-insensitive, but APS's article paths are not.
            canonical_suffix = prefix + suffix[len(prefix):]
            canonical_doi = doi[:len(doi) - len(suffix)] + canonical_suffix
            return f"https://journals.aps.org/{journal_code}/abstract/{canonical_doi}"
    return ""


@register
class APSAdapter(PublisherAdapter):
    publisher = "aps"
    returns_to_record_article = True
    fulltext_shown_js = FULLTEXT_SHOWN_JS
    fulltext_images_js = FULLTEXT_IMAGES_JS
    fulltext_prepare_js = FULLTEXT_PREPARE_JS

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_rows(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

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

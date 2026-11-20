"""Silverchair journal sites whose PDF paths name no article (RSC, Karger).

Article pages are ``/<journal>/article(-abstract)/<n>/...``, newer ones with the
DOI first: ``/<journal>/article(-abstract)/doi/<DOI>/<n>/...`` (Karger's
Dermatology, 2026-11-02; RSC's Faraday Discussions, 2026-11-03), on the
publisher's own hosts (``site_hosts``). The article PDF is ``/<journal>/article-pdf/<four numbers>/<DOI suffix>.pdf``
on the publisher's own host. It is bound to the article by the article page's
own metadata: ``citation_doi`` (exactly this DOI) and ``citation_pdf_url``
(``binds_pdf_to_citation``, the engine's one rule). Only such a bound URL is a
PDF candidate or an accepted PDF; any other PDF response is refused and kept
from the browser's download manager. An
``/article-abstract/`` page (the article shown without access) is the shared
access rule's.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from ...base import PublisherAdapter, SupplementLink

_ARTICLE = re.compile(r"/[^/]+/article(?:-abstract)?/(?:doi/10\.\d{4,9}/.+/)?\d+/")
# Silverchair's download address for an article's supplementary file, by the article's id.
_SUPPLEMENT = re.compile(r"/[^/]+/article-supplement/(\d{5,})/")
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => ({
    href: a.href, label: (a.innerText || a.getAttribute('title') || '').replace(/\\s+/g, ' ').trim().slice(0, 200),
    in_section: !!a.closest('[class*="supplementary-material"], .dataSuppLink')}))"""


# The article toolbar's content filters ("Figures & tables", "Video", "Supplementary
# Material", ...): a kind the article has is marked "has-content", one it lacks "hide".
_CONTENT_FILTERS_JS = """() => ({
    doi: document.querySelector('meta[name="citation_doi"]')?.content || '',
    filters: [...document.querySelectorAll('li.article-content-filter')].map(li => ({
        label: (li.textContent || '').replace(/\\s+/g, ' ').trim(),
        hide: li.classList.contains('hide'), has: li.classList.contains('has-content')}))})"""


# --fulltext on Silverchair's article page (PaperSearch's sites/templates/silverchair.ts):
# the article is in .widget-ArticleFulltext (JAMA: three of them, OUP and Karger: one),
# its body paragraphs p.para (JAMA) or p.chapter-para (OUP) outside the abstract, floats
# and references; a reader without access gets data-userHasAccess="False". A figure's
# largest image is the link it sits in (JAMA: the lazy <img> has only its medium copy in
# data-original), else the original behind its "Download slide" link
# (/DownloadFile/DownloadImage.aspx?image=<CDN URL>&Expires=…&Signature=…, OUP and
# Karger), else the image shown; a table given as HTML is not fetched as an image.
# JAMA Network and Oxford Academic verified on pages saved after a school login
# (2026-11-14); a publisher on the platform names these once one of its pages is verified
# (Karger's one page was an accepted manuscript, PDF only). ACS, AIP and the Royal Society
# write their body paragraphs as plain <p> in .article-section-wrapper (2026-11-15).
SILVERCHAIR_FULLTEXT_SHOWN_JS = """() => {
  if ([...document.querySelectorAll('[data-userhasaccess]')].some((node) => (node.getAttribute('data-userhasaccess') || '').toLowerCase() === 'false')) return false;
  const outside = '.abstract, #AbstractSection, .fig-section, .figure-table-wrapper, .table-wrap, .ref-list, .references, .footnote';
  return [...document.querySelectorAll('.widget-ArticleFulltext p.chapter-para, .widget-ArticleFulltext p.para, .widget-ArticleFulltext .article-section-wrapper > p')]
    .filter((p) => !p.closest(outside)).reduce((sum, p) => sum + p.innerText.length, 0) > 500;
}"""
SILVERCHAIR_FULLTEXT_IMAGES_JS = r"""() => {
  const decoded = (value) => { try { return decodeURIComponent(value); } catch (error) { return value; } };
  const stem = (url) => decoded((url || '').split(/[?#]/)[0].split('/').pop() || '').toLowerCase().replace(/\.[^.]*$/, '').replace(/^m_/, '');
  const absolute = (href) => { try { return new URL(href, location.href).href; } catch (error) { return href; } };
  const unwrap = (href) => {
    const query = href.indexOf('?');
    if (query < 0 || !/\/downloadimage\.aspx$/i.test(href.slice(0, query))) return '';
    let image = '';
    const signature = new Map();
    for (const segment of href.slice(query + 1).split('#')[0].split('&')) {
      const equals = segment.indexOf('=');
      if (equals < 0) continue;
      const name = decoded(segment.slice(0, equals)).trim().toLowerCase();
      if (name === 'image' && !image) image = segment.slice(equals + 1);
      else if (['expires', 'signature', 'key-pair-id'].includes(name) && !signature.has(name)) signature.set(name, segment);
    }
    if (!image) return '';
    let url;
    try { url = new URL(decoded(image), location.href); } catch (error) { return ''; }
    if (url.protocol !== 'https:') return '';
    const own = new Set([...url.searchParams.keys()].map((key) => key.toLowerCase()));
    const missing = [...signature].filter(([name]) => !own.has(name)).map(([, segment]) => segment);
    return missing.length ? new URL(`${url.href}${url.search ? '&' : '?'}${missing.join('&')}`).href : url.href;
  };
  const urls = [];
  const floats = document.querySelectorAll('.widget-ArticleFulltext .fig-section, .widget-ArticleFulltext .figure-table-wrapper, .widget-ArticleFulltext .table-wrap');
  for (const float of floats) {
    if (float.parentElement && float.parentElement.closest('.fig-section, .figure-table-wrapper, .table-wrap, .formula-wrap, .disp-formula')) continue;
    const table = float.matches('.table-wrap') || !!float.querySelector('.table-label');
    if (table && [...float.querySelectorAll('table')].some((node) => !node.parentElement.closest('table, .table-modal'))) continue;
    for (const img of float.querySelectorAll('img')) {
      const holder = img.parentElement && img.parentElement.closest('.fig-caption, .figure-caption, .fig-label, .figure-label, .inline-formula, .disp-formula');
      if (holder && holder !== float && float.contains(holder)) continue;
      const shown = [img.getAttribute('src'), img.getAttribute('data-original'), img.getAttribute('data-src')]
        .map((value) => (value || '').trim()).find((value) => value && !value.startsWith('data:')) || '';
      const stems = [stem(shown), stem(img.getAttribute('data-path-from-xml') || '')].filter(Boolean);
      let best = '';
      const anchor = img.parentElement && img.parentElement.closest('a');
      if (anchor && anchor !== float && float.contains(anchor)) {
        const href = (anchor.getAttribute('href') || '').trim();
        // Karger's /view-large/figure/…jpg is a viewer page, not the image (2026-11-14).
        if (/\.(png|jpe?g|gif|tiff?|webp)$/i.test(href.split(/[?#]/)[0]) && !/\/view-large\//i.test(href)
            && stems.includes(stem(href))) best = absolute(href);
      }
      if (!best) {
        for (const a of float.querySelectorAll('a')) {
          const original = unwrap((a.getAttribute('href') || '').trim());
          if (original && stems.includes(stem(original))) { best = original; break; }
        }
      }
      if (!best && shown) best = absolute(shown);
      if (best) urls.push(best);
    }
  }
  return urls;
}"""


def declares_no_supplements(page: Any, doi: str) -> bool:
    """This article's own Silverchair page says it has no supplementary material:
    its "Supplementary Material" filter hidden while another kind is marked as
    present (pubs.aip.org, whose files are otherwise found only through Figshare
    links, 2026-11-08). Any other page says nothing."""
    data = page.evaluate(_CONTENT_FILTERS_JS)
    if not isinstance(data, dict) or str(data.get("doi") or "").lower() != (doi or "").lower():
        return False
    filters = [f for f in data.get("filters") or () if isinstance(f, dict)]
    supplements = [f for f in filters if re.fullmatch(r"supplementary (?:material|data)", str(f.get("label") or ""), re.I)]
    return (bool(supplements) and all(f.get("hide") and not f.get("has") for f in supplements)
            and any(f.get("has") for f in filters))


def supplement_links(page: Any, doi: str, hosts: frozenset[str]) -> list[SupplementLink]:
    """This article's supplementary files on a Silverchair page: Silverchair's own
    address ``/<journal>/article-supplement/<article id>/<type>/<name>/`` on the
    site's ``hosts``, the id the one in the article page's address (ACS Nano,
    2026-11-03), and files on Silverchair's CDN whose path names the DOI ("/" as
    "_") in the page's supplementary section (OUP's form). Figure slides
    (``/DownloadFile/DownloadImage.aspx``) are no files; a file linked several
    times is taken once."""
    article_ids = set(re.findall(r"/(\d{5,})(?=/|$)", urlparse(str(getattr(page, "url", "") or "")).path))
    key = (doi or "").lower().replace("/", "_")
    links: list[SupplementLink] = []
    seen: set[str] = set()
    rows = page.evaluate(_SUPPLEMENT_ROWS_JS)
    for row in rows if isinstance(rows, list) and key else []:
        if not isinstance(row, dict):
            continue
        target = urlparse(str(row.get("href") or ""))
        host, path = (target.hostname or "").lower(), unquote(target.path).lower()
        own = _SUPPLEMENT.match(path)
        ours = ((host in hosts and own is not None and own.group(1) in article_ids)
                or (host.endswith(".silverchair-cdn.com") and row.get("in_section") is True
                    and f"/{key}/" in path and "/downloadfile/" not in path))
        url = target._replace(fragment="").geturl()
        if target.scheme == "https" and ours and url not in seen:
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


class SilverchairAdapter(PublisherAdapter):
    """Shared rules of Silverchair sites."""

    validates_article_pdf = True
    binds_pdf_to_citation = True
    keeps_pdf_out_of_downloads = True
    binds_response_url = True
    discards_unbound_pdfs = True
    # Inspect redirected PDFs too, so an unverified destination can be
    # discarded. Acceptance still requires the bound URL.
    native_pdf_patterns = ("https://*/*",)
    site_hosts: frozenset[str] = frozenset()

    def is_article_page_url(self, url: str) -> bool | None:
        """On this site: an article page or not (else the publisher's rules decide).
        Only an article page counts: the profile's marker would take every page of
        the site for one."""
        parsed = urlparse((url or "").lower())
        if parsed.scheme != "https" or parsed.hostname not in self.site_hosts:
            return None
        return bool(_ARTICLE.match(parsed.path))

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        return supplement_links(page, doi, self.site_hosts)

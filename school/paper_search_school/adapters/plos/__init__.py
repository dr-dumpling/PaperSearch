"""PLOS: open-access journals on journals.plos.org.

The printable PDF is ``/<journal>/article/file?id=<DOI>&type=printable``; the journal
path comes from the source page or the DOI's journal code. The article's JATS XML is
``…&type=manuscript`` (served from another host).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ...engine.router import _append_plos_candidates, _plos_journal_path_from_source
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => ({
    href: a.href, label: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
}))"""

# --fulltext (PaperSearch Pro's sites/publishers/plos/template.ts). The article page is open
# and rendered by the server: div#artText holds the abstracts (div.abstract), the article's
# information (div.articleinfo), one div.section per body section, the supporting
# information (div.supplementary-material), the acknowledgments and the references
# (ol.references). A figure and a table alike are a div.figure: the thumbnail
# (size=inline) links to a medium image, the download links to the larger PNG (size=large,
# the original's pixels) and the original TIFF; the larger PNG is taken, as the converter
# does. The general rules took the thumbnails (2026-11-18).
FULLTEXT_SHOWN_JS = r"""() => {
  const text = document.querySelector('div#artText');
  if (!text) return false;
  const body = [...text.children].filter((part) => part.matches('div.section') && !part.matches('.abstract, .contributions')
    && !part.querySelector('div.supplementary-material, ol.references')
    && !/^(acknowledge?ments?|author contributions)$/i.test((part.querySelector(':scope > h2')?.textContent || '').trim()));
  const chars = body.flatMap((part) => [...part.querySelectorAll('p')]).filter((p) => !p.closest('div.figure'))
    .reduce((total, p) => total + (p.textContent || '').replace(/\s+/g, ' ').trim().length, 0);
  return chars >= 200;
}"""
FULLTEXT_IMAGES_JS = r"""() => [...document.querySelectorAll('div#artText div.figure')].map((figure) => {
  const links = [...figure.querySelectorAll('a[href]')].map((a) => a.getAttribute('href'));
  const img = figure.querySelector('img');
  const href = links.find((value) => /[?&]size=large(?:&|$)/.test(value))
    || links.find((value) => /[?&]size=medium(?:&|$)/.test(value)) || img?.getAttribute('src') || '';
  try { return href ? new URL(href, location.href).href : ''; } catch (error) { return ''; }
}).filter((url) => /^https?:/.test(url))"""
# Formulas are only images on the page (span.inline-formula, span.equation, an
# img.inline-graphic inside whose id is the formula's DOI): the page has no MathML, and the
# article's XML, which has it, is on another host without CORS, out of the page's reach
# (Failed to fetch, Chromium, 2026-11-18). The backend fetches the XML
# (fulltext_prepare_source) and hands it to this script, which writes each formula's MathML
# on its span as data-original-mathml, as MATHJAX_SOURCES_JS does elsewhere: unprefixed and
# with closing tags (an HTML parser takes <mml:mspace/> for an open element). What it did is
# said in the record.
FULLTEXT_PREPARE_JS = r"""(xml) => {
  const holders = [...document.querySelectorAll('div#artText span.inline-formula, div#artText span.equation')];
  if (!holders.length) return 'no formulas';
  if (typeof xml !== 'string' || !xml) return `MathML for 0 of ${holders.length} formulas: no article XML`;
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) return `MathML for 0 of ${holders.length} formulas: the article XML did not parse`;
  const MATHML = 'http://www.w3.org/1998/Math/MathML';
  const XLINK = 'http://www.w3.org/1999/xlink';
  const escape = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const write = (node) => {
    if (node.nodeType === Node.TEXT_NODE) return escape(node.nodeValue);
    if (node.nodeType !== Node.ELEMENT_NODE) return '';
    const attributes = [...node.attributes].filter((attribute) => attribute.prefix !== 'xmlns' && attribute.name !== 'xmlns')
      .map((attribute) => ` ${attribute.localName}="${escape(attribute.value).replace(/"/g, '&quot;')}"`).join('');
    return `<${node.localName}${attributes}>${[...node.childNodes].map(write).join('')}</${node.localName}>`;
  };
  const sources = new Map();
  for (const formula of [...doc.getElementsByTagName('inline-formula'), ...doc.getElementsByTagName('disp-formula')]) {
    const math = formula.getElementsByTagNameNS(MATHML, 'math')[0];
    if (!math) continue;
    for (const graphic of [...formula.getElementsByTagName('inline-graphic'), ...formula.getElementsByTagName('graphic')]) {
      const doi = (graphic.getAttributeNS(XLINK, 'href') || '').replace(/^info:doi\//, '').toLowerCase();
      if (doi) sources.set(doi, write(math));
    }
  }
  let kept = 0;
  for (const holder of holders) {
    let id = '';
    try { id = new URL(holder.querySelector('img')?.getAttribute('src') || '', location.href).searchParams.get('id') || ''; } catch (error) { id = ''; }
    const source = sources.get(id.toLowerCase());
    if (source) {
      holder.setAttribute('data-original-mathml', source);
      kept += 1;
    }
  }
  return `MathML for ${kept} of ${holders.length} formulas from the article XML`;
}"""


def supplement_links_from_rows(rows: list[dict], doi: str) -> list[SupplementLink]:
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in rows:
        target = urlparse(str(row.get("href") or ""))
        query = parse_qs(target.query)
        ids = query.get("id", [])
        if (target.scheme != "https" or target.netloc != "journals.plos.org"
                or not re.fullmatch(r"/[a-z]+/article/file", target.path)
                or query.get("type") != ["supplementary"] or len(ids) != 1
                or not re.fullmatch(re.escape(doi) + r"\.s\d+", ids[0], re.I)):
            continue
        identity = ids[0].lower()
        if identity not in seen:
            seen.add(identity)
            links.append(SupplementLink(target._replace(fragment="").geturl(), str(row.get("label") or "")))
    return links


@register
class PLOSAdapter(PublisherAdapter):
    publisher = "plos"
    fulltext_shown_js = FULLTEXT_SHOWN_JS
    fulltext_images_js = FULLTEXT_IMAGES_JS
    fulltext_prepare_js = FULLTEXT_PREPARE_JS

    def fulltext_prepare_source(self, doi: str, page_url: str) -> str:
        """The article's XML, which has every formula's MathML: on the article page's journal
        (journals.plos.org/<journal>/article?id=<DOI>), else none."""
        journal = _plos_journal_path_from_source(page_url)
        if not journal or not re.fullmatch(r"10\.1371/[^\s&#?]+", doi or "", re.I):
            return ""
        return f"https://journals.plos.org/{journal}/article/file?id={doi}&type=manuscript"

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_rows(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_plos_candidates(urls, doi, source_url)
        return urls

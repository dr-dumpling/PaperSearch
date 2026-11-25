"""Frontiers: open-access journals on www.frontiersin.org (Frontiers for Young Minds on kids.frontiersin.org); supplementary files on the article's own download panel."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from ...engine.fulltext_page import paragraph_text_js
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => ({
    doi: document.querySelector('meta[name="citation_doi"]')?.content || '',
    rows: [...document.querySelectorAll('#supplementaryMaterial a[href], #supplementary-material a[href]')].map(a => ({
        href: a.href,
        label: (a.closest('li')?.innerText || a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
    }))
})"""

# The original of an image the site's resizer serves (/api/ipx/w=287&f=webp&v=7/<original>), as
# the converter takes it back (sites/publishers/frontiers/template.ts's original()).
_ORIGINAL_JS = "const original = (url) => (/\\/api\\/ipx\\/[^/]*\\/(https?:\\/\\/.+)$/.exec(url) || [])[1] || url;"

# --fulltext (PaperSearch Pro's sites/publishers/frontiers/template.ts). The article page
# (/journals/<journal>/articles/<DOI>/full, open access) holds the article in
# div.ArticleContent, in parts side by side: the abstract (a div whose h2 is "Abstract"),
# one div per body section, the statements (div.Statement__<name>), the references (a div
# with ul.References) and div.Summary. The general rule read the first of main, article and
# [role=main]: a journal card (article.CardJournal) in the left column comes before <main>,
# so the page was said to show no full text (Frontiers in Energy Research, 10 papers not in
# PubMed Central, 2026-11-18). A figure (div.ArticleFigure) is a <picture>: its <img> is
# the original (files/Articles/<id>/xml-images/<name>), its <source>s the same through the
# site's resizer (/api/ipx/w=…/<original>), taken back to the original as the converter
# does; the general rule's figure images also took the authors' photos and the cards'. A
# table is HTML (div.ArticleTable). MathJax 2 keeps each formula's MathML in a math/mml
# script beside its output, so nothing is prepared.
FULLTEXT_SHOWN_JS = """() => {
  const content = document.querySelector('div.ArticleContent');
  if (!content) return false;
  const body = [...content.children].filter((part) => part.tagName === 'DIV'
    && !part.matches('.Summary, [class*="Statement__"]') && !part.querySelector('ul.References')
    && !/^abstract$/i.test((part.querySelector(':scope > h2')?.textContent || '').trim()));
  const text = body.flatMap((part) => [...part.querySelectorAll('p')])
    .filter((p) => !p.closest('.ArticleFigure, .ArticleTable'))
    .reduce((total, p) => total + (p.textContent || '').length, 0);
  return text > 500;
}"""
FULLTEXT_IMAGES_JS = """() => {
  const content = document.querySelector('div.ArticleContent');
  if (!content) return [];
  """ + _ORIGINAL_JS + """
  const caption = 'figcaption, .ArticleTable__description, .ArticleTable__foot';
  const image = (float) => {
    const img = [...float.querySelectorAll('img')].find((node) => !node.closest(caption));
    const sources = [...float.querySelectorAll('source[srcset]')].filter((node) => !node.closest(caption))
      .flatMap((node) => node.getAttribute('srcset').split(',').map((candidate) => candidate.trim().split(/\\s+/)[0]));
    return [img?.getAttribute('src'), img?.getAttribute('data-src'), ...sources]
      .filter((value) => value && !value.startsWith('data:'))
      .map((value) => { try { return new URL(original(value), location.href).href; } catch (error) { return ''; } })
      .find((url) => /^https?:/i.test(url)) || '';
  };
  const figures = [...content.querySelectorAll('div.ArticleFigure')].map(image);
  const tables = [...content.querySelectorAll('div.ArticleTable')].filter((table) => !table.querySelector('table')).map(image);
  return [...figures, ...tables].filter(Boolean);
}"""


# --fulltext for Frontiers for Young Minds (PaperSearch Pro's
# sites/publishers/frontiers/templateYoungMinds.ts). kids.frontiersin.org is another page than
# www.frontiersin.org's: no div.ArticleContent, which the scripts above wait for, so its two papers
# of the publisher sweep were said to show no full text when their PDFs were taken (2026-11-22).
# The server renders the article in div.fulltext-content, flat: div.abstract, the paragraphs and
# h2/h3 headings, the exercise boxes, the glossary, then section#full-text-references. A figure is
# a <figure>: its <img> lazy (src empty, data-src the resizer's address of the original,
# /api/ipx/w=1200&f=webp/<files/Articles/…/image_m/figure-1.jpg>), taken back to the original as
# the converter does; the main illustration and the people's photos are not in the article.
YOUNG_MINDS_FULLTEXT_SHOWN_JS = paragraph_text_js("p", "div.abstract, section#full-text-references, figure", "> 500",
                                                  root="div.fulltext div.fulltext-content")
YOUNG_MINDS_FULLTEXT_IMAGES_JS = """() => {
  const content = document.querySelector('div.fulltext div.fulltext-content');
  if (!content) return [];
  """ + _ORIGINAL_JS + """
  return [...content.querySelectorAll('figure')].map((figure) => {
    const img = figure.querySelector('img');
    return [img?.getAttribute('data-src'), img?.getAttribute('src')]
      .filter((value) => value && !value.startsWith('data:'))
      .map((value) => { try { return new URL(original(value), location.href).href; } catch (error) { return ''; } })
      .find((url) => /^https?:/i.test(url)) || '';
  }).filter(Boolean);
}"""


def supplement_links_from_page(data: Any, doi: str) -> list[SupplementLink]:
    """The panel, citation DOI and file's article ID must all agree."""
    article = re.fullmatch(r"10\.3389/[a-z0-9]+\.\d{4}\.(\d+)", doi, re.I)
    if (not article or not isinstance(data, dict)
            or str(data.get("doi", "")).strip().lower() != doi.lower()):
        return []
    article_id = article.group(1)
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in data.get("rows", []):
        target = urlparse(str(row.get("href") or ""))
        url = target._replace(fragment="").geturl()
        if (target.scheme == "https"
                and re.fullmatch(r"public-pages-files(?:-\d{4})?\.frontiersin\.org", target.hostname or "")
                and unquote(target.path).startswith(f"/articles/{article_id}/file/")
                and url not in seen):
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


@register
class FrontiersAdapter(PublisherAdapter):
    publisher = "frontiers"
    fulltext_shown_js = FULLTEXT_SHOWN_JS
    fulltext_images_js = FULLTEXT_IMAGES_JS

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_page(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)


@register
class FrontiersForYoungMindsAdapter(FrontiersAdapter):
    """Frontiers for Young Minds on kids.frontiersin.org: its article page's own scripts, the rest Frontiers'."""

    hosts = ("kids.frontiersin.org",)
    fulltext_shown_js = YOUNG_MINDS_FULLTEXT_SHOWN_JS
    fulltext_images_js = YOUNG_MINDS_FULLTEXT_IMAGES_JS

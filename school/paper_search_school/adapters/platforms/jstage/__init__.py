"""J-STAGE (www.jstage.jst.go.jp): the Japan Science and Technology Agency's platform that
hundreds of Japanese societies publish their journals on, each under its own DOI prefix.

No publisher profile names these societies: their articles are downloaded with the shared
rules, under the profile the engine builds for the site at run time
(``publishers/site.py``: ``site:jst.go.jp``, J-STAGE's registrable domain). This platform's
rules are registered by that name, so that a society without a profile of its own still has
them; they are chosen on J-STAGE's own host only (``hosts``): the run-time profile's domain is
all of JST's sites. A society given a profile of its own later inherits this adapter. Only the
full-text page is J-STAGE's here; the login and the PDF stay the shared rules'.

--fulltext (PaperSearch Pro's sites/platforms/jstage.ts). The download opens the article's
abstract page (``/article/<journal>/<volume>/<issue>/<code>/_article``, ``…/_article/-char/ja/``);
the full text, where the journal gives one in HTML, is the "Full Text HTML" page
(``…/_html/-char/en``), read in a tab of its own (``fulltext_page_url``). Most articles have
their PDF alone: that address answers 404, and the page read ends there. On the full-text page
the body is ``#article-overiew-abstract-wrap`` (sic) of ``div#abstract`` and one
``div#sec<NN>`` per section (inside ``div.fullHtmlNonDisp``); a figure is
``div.global-image-holder`` with its image (``./Graphics/<name>``, the largest the site has:
its "Figures" panel shows the same file). MathJax 2 typesets the formulas; their MathML is kept
before saving (Environmental Health and Preventive Medicine, Journal of Atherosclerosis and
Thrombosis, 2026-11-23).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from ....engine.fulltext_page import MATHJAX_SOURCES_JS, paragraph_text_js
from ....publishers.site import SITE_PREFIX
from ...base import PublisherAdapter, register

_HOSTS = frozenset({"www.jstage.jst.go.jp", "jstage.jst.go.jp"})
# An article's abstract page, with the language it is shown in when the address names one.
_ABSTRACT_PAGE = re.compile(r"(/article/(?:[^/]+/){4})_article(?:/-char/([a-z]{2}))?/?")

FULLTEXT_SHOWN_JS = paragraph_text_js('#article-overiew-abstract-wrap > div[id^="sec"] p',
                                      ".global-image-holder, .responsive-table-wrap, .fj-list-ref", ">= 200")
FULLTEXT_IMAGES_JS = r"""() => [...document.querySelectorAll('#article-overiew-abstract-wrap > div[id^="sec"] div.global-image-holder img')]
  .map((img) => {
    const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
    try { return src ? new URL(src, location.href).href : ''; } catch (error) { return ''; }
  })
  .filter((url) => /^https?:/.test(url))"""


@register
class JStageAdapter(PublisherAdapter):
    publisher = SITE_PREFIX + "jst.go.jp"
    hosts = ("jstage.jst.go.jp",)
    fulltext_shown_js = FULLTEXT_SHOWN_JS
    fulltext_images_js = FULLTEXT_IMAGES_JS
    fulltext_prepare_js = MATHJAX_SOURCES_JS

    def fulltext_page_url(self, doi: str, page_url: str) -> str:
        """The article's "Full Text HTML" page beside its abstract page (``…/_article`` →
        ``…/_html/-char/en``, in the language the abstract page was shown in); "" on any
        other page, the full-text page itself included."""
        target = urlparse(page_url or "")
        host = (target.hostname or "").lower()
        found = _ABSTRACT_PAGE.fullmatch(target.path)
        if target.scheme != "https" or host not in _HOSTS or not found:
            return ""
        return f"https://{host}{found.group(1)}_html/-char/{found.group(2) or 'en'}"

"""PLOS's --fulltext page scripts run on a synthetic article page in the local Chrome.

SCHOOL_LOCAL_BROWSER_TEST=1 enables them; the page is served at a PLOS address so that the
images' addresses resolve as on the site. The article's XML is synthetic too, as the backend
hands it to the preparation (fulltext_prepare_source).
"""
import os
import unittest

from paper_search_school.adapters.plos import FULLTEXT_IMAGES_JS, FULLTEXT_PREPARE_JS, FULLTEXT_SHOWN_JS

ARTICLE = "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0300001"
FIGURES = "https://journals.plos.org/plosone/article/figure/image?"
BODY_TEXT = ("Swollen knees trouble many rats in the cold season, and the bark of the red magnolia tree is an "
             "old remedy for them that nobody has measured. ") * 2


def float_(name, label):
    """A div.figure as the site renders it: the thumbnail linking to the medium image, the download links."""
    doi = f"10.1371/journal.pone.0300001.{name}"
    return f"""<div class="figure" data-doi="{doi}"><div class="img-box"><a title="Click for larger image"
  href="article/figure/image?size=medium&amp;id={doi}"><img src="article/figure/image?size=inline&amp;id={doi}" class="thumbnail"></a></div>
<div class="figure-inline-download">Download:<ul><li><a href="article/figure/image?download&amp;size=large&amp;id={doi}">PNG larger image</a></li>
  <li><a href="article/figure/image?download&amp;size=original&amp;id={doi}">TIFF original image</a></li></ul></div>
<div class="figcaption"><span>{label}. </span> A float.</div><p class="caption_target"></p>
<p class="caption_object"><a href="https://doi.org/{doi}">https://doi.org/{doi}</a></p></div>"""


def formula(number, block=False):
    image = f'<img src="article/file?type=thumbnail&amp;id=10.1371/journal.pone.0300001.e00{number}" class="inline-graphic">'
    return f'<span class="equation">{image}<span class="note">({number})</span></span>' if block else f'<span class="inline-formula">{image}</span>'


# The carousel's thumbnails before #artText; the abstract, the body (a formula inline, one
# display formula, a figure, a table), the supporting information, the acknowledgments and the
# references; a figure in the aside.
PAGE = f"""<!DOCTYPE html><html><head><meta name="citation_doi" content="10.1371/journal.pone.0300001"></head><body>
<main id="main-content"><div class="article-content">
<div id="figure-carousel-section"><div class="carousel-item lightbox-figure"><img src="/plosone/article/figure/image?size=inline&amp;id=10.1371/journal.pone.0300001.g001"></div></div>
<div class="article-text" id="artText">
<div class="abstract toc-section abstract-type-"><h2>Abstract</h2><div class="abstract-content"><p>{BODY_TEXT}</p></div></div>
<div class="articleinfo"><p><strong>Funding: </strong>{BODY_TEXT}</p></div>
<div id="section1" class="section toc-section"><h2>Introduction</h2><p>{{body}} The dose was {formula(1)} a day.</p>
  {formula(2, block=True)}
  {float_("g001", "Fig 1")}{float_("t001", "Table 1")}</div>
<div id="section2" class="section toc-section"><h2>Supporting information</h2><div class="supplementary-material">
  <h3 class="siTitle"><a href="article/file?type=supplementary&amp;id=10.1371/journal.pone.0300001.s001">S1 Fig. </a>Knees.</h3>
  <p class="preSiDOI">{BODY_TEXT}</p></div></div>
<div class="section toc-section"><h2>Acknowledgments</h2><p>{BODY_TEXT}</p></div>
<div class="toc-section"><h2>References</h2><ol class="references"><li id="ref1">1. {BODY_TEXT}</li></ol></div>
</div></div>
<aside><div class="figure"><img src="https://journals.plos.org/resource/img/related.png"></div></aside></main></body></html>"""

# The article's XML (JATS): each formula's MathML beside its image, named by the image's DOI;
# one formula the page does not show.
XML = """<?xml version="1.0" encoding="utf-8"?>
<article xmlns:mml="http://www.w3.org/1998/Math/MathML" xmlns:xlink="http://www.w3.org/1999/xlink"><body><sec><p>
<inline-formula id="pone.0300001.e001"><alternatives><inline-graphic xlink:href="info:doi/10.1371/journal.pone.0300001.e001"/>
  <mml:math id="M1"><mml:mn>2</mml:mn><mml:mspace width="0.25em"/><mml:mtext>mg &amp; more</mml:mtext></mml:math></alternatives></inline-formula>
<disp-formula id="pone.0300001.e002"><alternatives><graphic xlink:href="info:doi/10.1371/journal.pone.0300001.e002"/>
  <mml:math display="block" id="M2"><mml:mi>D</mml:mi><mml:mo>=</mml:mo><mml:mfrac><mml:mi>w</mml:mi><mml:mn>100</mml:mn></mml:mfrac></mml:math>
  </alternatives><label>(2)</label></disp-formula>
<inline-formula id="pone.0300001.e009"><alternatives><inline-graphic xlink:href="info:doi/10.1371/journal.pone.0300001.e009"/>
  <mml:math id="M9"><mml:mi>x</mml:mi></mml:math></alternatives></inline-formula>
</p></sec></body></article>"""


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class PLOSFulltextPageDOMTests(unittest.TestCase):
    def run_scripts(self, html, xml=XML):
        from patchright.sync_api import sync_playwright

        def serve(route):
            if route.request.url == ARTICLE:
                route.fulfill(status=200, content_type="text/html", body=html)
            else:
                route.abort()

        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context()
                context.route("**/*", serve)
                page = context.new_page()
                page.goto(ARTICLE)
                shown, images = page.evaluate(FULLTEXT_SHOWN_JS), page.evaluate(FULLTEXT_IMAGES_JS)
                prepared = page.evaluate(FULLTEXT_PREPARE_JS, xml, isolated_context=False)
                kept = page.evaluate("""() => [...document.querySelectorAll('[data-original-mathml]')]
                  .map((node) => [node.className, node.getAttribute('data-original-mathml')])""")
                return shown, images, prepared, kept
            finally:
                browser.close()

    def test_the_body_shows_each_floats_larger_image_and_each_formulas_mathml(self):
        shown, images, prepared, kept = self.run_scripts(PAGE.replace("{body}", BODY_TEXT))
        self.assertTrue(shown)
        # Not the thumbnails, the medium images, the TIFFs, the carousel's or the aside's.
        self.assertEqual(images, [f"{FIGURES}download&size=large&id=10.1371/journal.pone.0300001.g001",
                                  f"{FIGURES}download&size=large&id=10.1371/journal.pone.0300001.t001"])
        self.assertEqual(prepared, "MathML for 2 of 2 formulas from the article XML")
        # Unprefixed, every element closed (an HTML parser takes <mml:mspace/> for an open one), text escaped.
        self.assertEqual(kept, [
            ["inline-formula", '<math id="M1"><mn>2</mn><mspace width="0.25em"></mspace><mtext>mg &amp; more</mtext></math>'],
            ["equation", '<math display="block" id="M2"><mi>D</mi><mo>=</mo><mfrac><mi>w</mi><mn>100</mn></mfrac></math>'],
        ])

    def test_without_the_article_xml_the_formulas_stay_images_and_the_record_says_why(self):
        page = PAGE.replace("{body}", BODY_TEXT)
        self.assertEqual(self.run_scripts(page, "")[2:], ("MathML for 0 of 2 formulas: no article XML", []))
        self.assertEqual(self.run_scripts(page, "<article><p>")[2:], ("MathML for 0 of 2 formulas: the article XML did not parse", []))

    def test_an_article_whose_body_is_short_is_not_the_full_text(self):
        # The abstract, the statements, the supporting information, the acknowledgments and the
        # references, each long enough, are not the body.
        shown, images, _, _ = self.run_scripts(PAGE.replace("{body}", "Short."))
        self.assertFalse(shown)
        self.assertEqual(len(images), 2)


if __name__ == "__main__":
    unittest.main()

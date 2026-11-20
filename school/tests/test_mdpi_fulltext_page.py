"""MDPI's --fulltext page scripts run on synthetic pages of both designs in the local Chrome.

SCHOOL_LOCAL_BROWSER_TEST=1 enables them; the page is served at an MDPI address so that the
images' addresses resolve as on the site.
"""
import os
import unittest

from paper_search_school.adapters.mdpi import FULLTEXT_IMAGES_JS, FULLTEXT_SHOWN_JS

ARTICLE = "https://www.mdpi.com/2999-0000/3/11/42"
IMAGES = "https://mdpi-res.com/joints/joints-03-00042/article_deploy/html/images/joints-03-00042-"
BODY_TEXT = ("Knee pain is common in runners, and bark of Magnolia rubra has long been used for it. "
             "Each runner took a dose set by body mass and scored the pain weekly on a ten-point scale. ") * 4

# The current design (2026): div#article-contents; a figure's thumbnail in src, its full size in
# data-large; the hidden copies in section#FiguresandTable; the pop-ups moved to the end of <body>.
CURRENT = f"""<!DOCTYPE html><html><head><meta name="citation_doi" content="10.3390/joints3110042"></head><body>
<aside><div class="html-fig-wrap"><img data-large="https://example.org/related.png"></div></aside>
<div id="article-contents">
  <div id="Abstract_a1"><section class="html-abstract"><h2>Abstract</h2><div class="html-p">{BODY_TEXT}</div></section></div>
  <div id="html-graphical"><div class="html-fig-wrap"><img data-large="{IMAGES}ga.png"></div></div>
  <div id="Introduction_a2"><section id="sec1-joints-03-00042"><h2>1. Introduction</h2><div class="html-p">{BODY_TEXT}</div>
    <div class="html-fig-wrap" id="joints-03-00042-f001"><div class="html-fig_img"><div class="html-figpopup html-figpopup-link" href="#fig_body_display_joints-03-00042-f001">
      <button class="html-media-button"><img data-large="{IMAGES}g001.png" data-original="{IMAGES}g001.png" src="{IMAGES}g001-550.jpg"></button></div></div>
      <div class="html-fig_description"><b>Figure 1.</b> Design.</div></div>
    <div class="html-table-wrap" id="joints-03-00042-t001"><div class="html-table_wrap_td"><div class="html-tablepopup html-tablepopup-link" href="#table_body_display_joints-03-00042-t001">
      <img src="https://pub.mdpi-res.com/img/table.png"></div></div><div class="html-table_wrap_discription"><b>Table 1.</b> Scores.</div></div>
    <div class="html-table-wrap" id="joints-03-00042-t002"><div class="html-table_wrap_td"><div class="html-tablepopup html-tablepopup-link" href="#table_body_display_joints-03-00042-t002">
      <img src="https://pub.mdpi-res.com/img/table.png"></div></div><div class="html-table_wrap_discription"><b>Table 2.</b> Doses.</div></div>
  </section></div>
  <div id="Funding_a3"><section class="html-notes"><h2>Funding</h2><div class="html-p">This research received no external funding.</div></section></div>
  <section id="FiguresandTable" type="display-objects" style="display: none;">
    <div class="html-fig-wrap" id="media_joints-03-00042-f001"><img data-large="{IMAGES}g001.png" src="{IMAGES}g001-550.jpg"></div>
  </section>
</div>
<div class="html-fig_show mfp-hide" id="fig_body_display_joints-03-00042-f001" data-hidden-media-relocate="true" style="display: none;">
  <div class="html-caption"><b>Figure 1.</b> Design.</div><div class="html-img"><img data-large="{IMAGES}g001.png" src="{IMAGES}g001.png"></div></div>
<div class="html-table_show mfp-hide" id="table_body_display_joints-03-00042-t001" data-hidden-media-relocate="true" style="display: none;">
  <div class="html-caption"><b>Table 1.</b> Scores.</div><table><tr><td>6.2</td></tr></table></div>
<div class="html-table_show mfp-hide" id="table_body_display_joints-03-00042-t002" data-hidden-media-relocate="true" style="display: none;">
  <div class="html-caption"><b>Table 2.</b> Doses.</div><div class="html-img"><img src="{IMAGES}g002.gif"></div></div>
</body></html>"""

# The earlier design: div.html-body and div.html-back, image addresses on the site's own host,
# the pop-ups in section#FiguresandTables.
EARLIER = f"""<!DOCTYPE html><html><head><meta name="citation_doi" content="10.3390/joints3110042"></head><body><article>
<div class="html-dynamic"><section class="html-abstract"><h2>Abstract</h2><div class="html-p">{BODY_TEXT}</div></section></div>
<div class="html-body"><section id="sec1-joints-03-00042"><h2>1. Introduction</h2><div class="html-p">{BODY_TEXT}</div>
  <div class="html-fig-wrap" id="joints-03-00042-f001"><div class="html-fig_img"><div class="html-figpopup html-figpopup-link" href="#fig_body_display_joints-03-00042-f001">
    <img data-large="/joints/joints-03-00042/article_deploy/html/images/joints-03-00042-g001.png" data-lsrc="/joints/joints-03-00042/article_deploy/html/images/joints-03-00042-g001-550.jpg">
    <a class="html-expand html-figpopup" href="#fig_body_display_joints-03-00042-f001"></a></div></div>
    <div class="html-fig_description"><b>Figure 1.</b> Design.</div></div></section></div>
<div class="html-back"><section class="html-notes"><h2>Funding</h2><div class="html-p">None.</div></section>
  <section id="FiguresandTables" type="display-objects"><div class="html-fig_show mfp-hide" id="fig_body_display_joints-03-00042-f001">
    <div class="html-img"><img data-large="/joints/joints-03-00042/article_deploy/html/images/joints-03-00042-g001.png"></div></div></section></div>
</article></body></html>"""


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class MDPIFulltextPageDOMTests(unittest.TestCase):
    def read(self, html):
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
                return page.evaluate(FULLTEXT_SHOWN_JS), page.evaluate(FULLTEXT_IMAGES_JS)
            finally:
                browser.close()

    def test_the_current_design_shows_its_body_and_each_figures_full_size_image(self):
        shown, images = self.read(CURRENT)
        self.assertTrue(shown)
        # Figure 1 once, in full; Table 2 is only an image; not the graphical abstract, the hidden
        # copy, the pop-up's own image, the side panel or a table's icon.
        self.assertEqual(images, [IMAGES + "g001.png", IMAGES + "g002.gif"])

    def test_the_earlier_design_resolves_its_images_on_the_site(self):
        shown, images = self.read(EARLIER)
        self.assertTrue(shown)
        self.assertEqual(images, ["https://www.mdpi.com/joints/joints-03-00042/article_deploy/html/images/joints-03-00042-g001.png"])

    def test_an_article_with_only_its_abstract_is_not_the_full_text(self):
        start = EARLIER.index('<div class="html-body">')
        abstract_only = EARLIER[:start] + EARLIER[EARLIER.index('<div class="html-back">'):]
        shown, images = self.read(abstract_only)
        self.assertFalse(shown)
        self.assertEqual(images, [])


if __name__ == "__main__":
    unittest.main()

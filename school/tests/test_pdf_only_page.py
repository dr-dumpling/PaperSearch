"""The page that sends the reader to the PDF, read in the local Chrome (_PDF_ONLY_JS).

SCHOOL_LOCAL_BROWSER_TEST=1 enables it. Synthetic pages: an Atypon page with no HTML of the article
(ACM 10.1145/3863936, 2026-11-19), a one-page figure article, and a page with its full text.
"""
import os
import unittest

from paper_search_school.engine.fulltext_page import _PDF_ONLY_JS

ARTICLE = "https://dl.example.org/doi/10.1145/0000001"
BODY = "Race detectors check each pair of accesses that the program can order in another way. " * 12

FORMATS = f"""<!DOCTYPE html><html><body><main><article>
<h1>On models for sound race detection</h1><section id="abstract"><p>{BODY[:400]}</p></section>
<section id="bodymatter"><h2>Formats available</h2><p>You can view the full content in the following formats:</p>
<a href="/doi/pdf/10.1145/0000001">PDF</a>/<a href="/doi/epdf/10.1145/0000001">eReader</a></section>
</article></main></body></html>"""
SNAPSHOT = """<!DOCTYPE html><html><body><article><section id="bodymatter">
<p>To view this SnapShot, open or download the PDF.</p></section></article></body></html>"""
FULL = f"""<!DOCTYPE html><html><body><article><section id="bodymatter"><h2>Introduction</h2><p>{BODY}</p>
<p>The full text is also available as a PDF.</p></section></article></body></html>"""


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class PdfOnlyPageTests(unittest.TestCase):
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
                context = browser.new_context(service_workers="block")
                context.route("**/*", serve)
                page = context.new_page()
                page.goto(ARTICLE)
                return page.evaluate(_PDF_ONLY_JS)
            finally:
                browser.close()

    def test_a_page_offering_its_content_as_pdf_alone_is_taken_for_one(self):
        self.assertIn("view the full content in the following formats: PDF", self.read(FORMATS))
        self.assertEqual(self.read(SNAPSHOT), "To view this SnapShot, open or download the PDF")

    def test_a_page_with_its_full_text_is_not(self):
        self.assertEqual(self.read(FULL), "")


if __name__ == "__main__":
    unittest.main()

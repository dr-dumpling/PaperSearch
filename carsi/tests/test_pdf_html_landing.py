"""A PDF address that opens an ordinary web page has failed within seconds (The
Lancet's showPdf and /pdfs/....pdf showed the article page to a personal
account and each waited out 60 s, 2026-11-02). Mocked pages, and a local Chrome
fixture (opt-in) whose requests are all answered locally."""
import itertools
import os
import time
import unittest
from unittest.mock import Mock, patch

from paper_search_carsi.engine import batch_capture
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import get_publisher_profile

DOI = "10.1016/s0140-6736(75)92262-x"
ARTICLE = "https://www.thelancet.com/journals/lancet/article/PIIS0140-6736(75)92262-X/fulltext"
SHOW_PDF = "https://www.thelancet.com/action/showPdf?pii=S0140-6736(75)92262-X"


def clock(step=0.5):
    ticks = itertools.count()
    start = time.time()
    return lambda: start + next(ticks) * step


class LandedOnHtmlTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        self.page = Mock(url=ARTICLE)
        self.page.locator.return_value.first.text_content.return_value = "Article"

    def test_a_finished_html_page_fails_after_its_grace(self):
        self.page.evaluate.return_value = "text/html"
        landing = {}
        with patch.object(batch_capture.time, "time", side_effect=[100.0, 101.0, 103.5]):
            self.assertEqual(self.d._landed_on_html(self.page, landing), "")  # just landed
            self.assertEqual(self.d._landed_on_html(self.page, landing), "")  # within 3 s
            self.assertEqual(self.d._landed_on_html(self.page, landing), ARTICLE)

    def test_a_pdf_a_verification_or_the_old_document_is_no_landing(self):
        for kind in ("application/pdf", ""):  # the viewer; the article page before the navigation
            with self.subTest(kind=kind):
                self.page.evaluate.return_value = kind
                landing = {}
                self.assertEqual(self.d._landed_on_html(self.page, landing), "")
                self.assertEqual(landing, {})
        self.page.evaluate.return_value = "text/html"
        self.page.locator.return_value.first.text_content.return_value = "Just a moment..."
        self.assertEqual(self.d._landed_on_html(self.page, {"url": ARTICLE, "since": 0.0}), "")

    def test_a_page_at_a_pdf_address_gets_longer(self):
        self.page.url = "https://www.sciencedirect.com/science/article/pii/S014067367592262X/pdfft?crasolve=1"
        self.page.evaluate.return_value = "text/html"
        landing = {}
        with patch.object(batch_capture.time, "time", side_effect=[100.0, 104.0, 111.0]):
            self.d._landed_on_html(self.page, landing)
            self.assertEqual(self.d._landed_on_html(self.page, landing), "")
            self.assertEqual(self.d._landed_on_html(self.page, landing), self.page.url)

    def test_the_async_navigation_gives_up_at_the_landing(self):
        self.d._pdf_step_hit_wall = Mock(return_value=False)
        self.d._landed_on_html = Mock(side_effect=["", ARTICLE])
        self.d._is_challenge_page = Mock(return_value=False)
        self.d._raise_on_publisher_content_error = Mock()
        self.d._capture_loaded_pdf_viewer = Mock(return_value=None)
        self.d._page_state_pdf_urls = Mock(return_value=[])
        result = DownloadResult(doi=DOI, status="failed")
        captured = {"bytes": None}
        with patch.object(batch_capture.time, "time", side_effect=clock()):
            self.assertEqual(self.d._capture_pdf_via_async_navigation(self.page, SHOW_PDF, result, captured), (None, ""))
        self.assertEqual(captured["landed_html"], ARTICLE)
        self.assertEqual(result.events[-1]["state"], "pdf_candidate_html")
        self.assertEqual(self.d._landed_on_html.call_count, 2)


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class HtmlLandingPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        article = "<title>Article</title><h1>Article</h1><p>Abstract only.</p>"

        def respond(route):
            # Both the article and its PDF address answer with the article's page.
            route.fulfill(status=200, content_type="text/html", body=article)
        self.context.route("**/*", respond)
        self.page = self.context.new_page()
        self.page.goto(ARTICLE)
        self.d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        self.d._fetch_pdf_url_with_browser_state = Mock(return_value=(None, "", None))

    def test_the_article_page_at_the_pdf_address_fails_within_seconds(self):
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        started = time.time()
        body, _ = self.d._capture_pdf_via_async_navigation(self.page, SHOW_PDF, result, {"bytes": None})
        self.assertIsNone(body)
        self.assertLess(time.time() - started, 20)
        self.assertIn("pdf_candidate_html", [e["state"] for e in result.events])

"""A 304 (revalidated cache) PDF response is read from the viewer, not rejected; requests are local."""
import os
import unittest
from unittest.mock import Mock

from test_springer_native_capture import ARTICLE, DOI, PDF, TITLE


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class CachedPdfResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        import test_wiley_capture as fixtures
        harness = fixtures.WileyCaptureTests(methodName="runTest")
        self.addCleanup(harness.doCleanups)
        harness.setUp()
        self.batch = harness.batch
        self.d = self.batch.PublisherBatchDownloader(config={}, profile=harness.profiles.SPRINGER_PROFILE,
                                                     pdf_timeout_sec=3, login_timeout_sec=1)
        self.d._fetch_page_state_pdf = Mock(return_value=(None, "", None))
        self.d._save_publisher_session = Mock()
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)

    def test_not_modified_pdf_goes_to_the_viewer_copy(self):
        def respond(route):
            if route.request.url == ARTICLE:
                route.fulfill(status=200, content_type="text/html", body=f"<title>{TITLE}</title>Full text access")
            else:
                route.abort()
        self.context.route("**/*", respond)
        page = self.context.new_page()
        page.goto(ARTICLE)
        # Firefox revalidates its cached PDF (conditional request -> 304) and
        # shows the cached copy; Chromium cannot be made to do that offline.
        real_goto = page.goto
        page.goto = lambda url, **kw: (Mock(status=304, url=url, headers={}, request=None, history=())
                                       if url == PDF else real_goto(url, **kw))
        body = b"%PDF-1.7\n" + b"x" * 20000
        self.d._pdf_candidates = Mock(return_value=[PDF])
        self.d._capture_native_viewer_pdf = Mock(return_value=(body, PDF))
        result = self.batch.DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        captured, url, block = self.d._capture_pdf(page, DOI, result)
        self.assertIsNone(block)
        self.assertEqual((captured, url), (body, PDF))
        self.assertEqual(self.d._capture_native_viewer_pdf.call_args.args[1], PDF)
        self.assertIn("pdf_cached_response", [e["state"] for e in result.events])


if __name__ == "__main__":
    unittest.main()

"""Firefox evicts the PDF response body once PDF.js renders it; the viewer copy is used instead."""
import unittest
from unittest.mock import Mock, patch

from paper_search_carsi.engine import batch
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from test_thieme_capture import DOI, profile

PDF_URL = "https://www.thieme-connect.de/products/ejournals/pdf/" + DOI + ".pdf"
BODY = b"%PDF-1.7\n" + b"x" * 20000


class NativeViewerCaptureTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=profile())
        self.result = DownloadResult(doi=DOI, status="failed")
        accept = patch.object(self.d, "_accept_pdf_body", return_value=True)  # PDF parsing is tested elsewhere
        accept.start(); self.addCleanup(accept.stop)

    def test_loaded_viewer_document_is_returned(self):
        page = Mock(); page.evaluate.return_value = True
        with patch.object(self.d, "_capture_loaded_pdf_viewer", return_value=BODY):
            body, url = self.d._capture_native_viewer_pdf(page, PDF_URL, self.result, doi=DOI)
        self.assertEqual((body, url), (BODY, PDF_URL))
        self.assertIn("pdf_native_viewer_captured", [e["state"] for e in self.result.events])

    def test_waits_while_the_viewer_is_still_loading(self):
        page = Mock(); page.evaluate.return_value = True
        with patch.object(self.d, "_capture_loaded_pdf_viewer", side_effect=[None, None, BODY]):
            body, _ = self.d._capture_native_viewer_pdf(page, PDF_URL, self.result, doi=DOI)
        self.assertEqual(body, BODY)
        self.assertEqual(page.wait_for_timeout.call_count, 2)

    def test_a_document_judged_by_its_text_ends_the_wait(self):
        # Kept as the fallback (a notice naming another article too): read again it says the same.
        def judged(body, url):
            self.d._last_identity = {"verdict": "unknown", "doi": True, "other_dois": ["10.1056/evidoa2200282"]}
            return False
        page = Mock(); page.evaluate.return_value = True
        with patch.object(self.d, "_accept_pdf_body", side_effect=judged), \
             patch.object(self.d, "_capture_loaded_pdf_viewer", return_value=BODY) as reader:
            body, _ = self.d._capture_native_viewer_pdf(page, PDF_URL, self.result, doi=DOI)
        self.assertIsNone(body)
        reader.assert_called_once()
        page.wait_for_timeout.assert_not_called()
        # Refused before its text was judged (a short or broken body): the viewer is read again.
        page = Mock(); page.evaluate.return_value = True
        with patch.object(self.d, "_accept_pdf_body", side_effect=[False, True]), \
             patch.object(self.d, "_capture_loaded_pdf_viewer", return_value=BODY) as reader:
            body, _ = self.d._capture_native_viewer_pdf(page, PDF_URL, self.result, doi=DOI)
        self.assertEqual(body, BODY)
        self.assertEqual(reader.call_count, 2)

    def test_non_viewer_pages_give_up_quickly(self):
        page = Mock(); page.evaluate.return_value = False
        clock = iter([0, 0, 1, 3, 6, 6, 6])
        with patch.object(batch.time, "time", side_effect=lambda: next(clock)), \
             patch.object(self.d, "_capture_loaded_pdf_viewer") as reader:
            body, _ = self.d._capture_native_viewer_pdf(page, PDF_URL, self.result, doi=DOI)
        self.assertIsNone(body)
        reader.assert_not_called()

    def test_viewer_reader_accepts_firefox_156_documents(self):
        """The viewer keeps the https URL there; detection must not require resource://pdf.js/."""
        import inspect
        source = inspect.getsource(PublisherBatchDownloader._capture_loaded_pdf_viewer)
        self.assertIn('contentType || "") === "application/pdf"', source)
        self.assertIn("new Blob([data]", source)

    def test_a_publishers_html_reader_is_not_the_native_viewer(self):
        """Wiley's ePDF reader runs PDF.js in an HTML page: waiting on it cost 60 s per article."""
        import inspect
        source = inspect.getsource(PublisherBatchDownloader._pdf_viewer_present)
        self.assertIn('=== "application/pdf"', source)
        self.assertIn('startsWith("resource://pdf.js/")', source)


class ClickedPdfInViewerTests(unittest.TestCase):
    """ARD on Firefox: the clicked 8 MB PDF was on screen, yet downloaded again over HTTP (~50 s)."""

    def capture(self, viewer: bool):
        from test_chromium_pdf_capture import article_pdf
        from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE
        body = article_pdf()
        pdf_url = "https://pdf.sciencedirectassets.com/example/main.pdf"
        d = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
        d._return_to_record_article_if_needed = Mock()
        # The article has no extra candidates. Once the PDF is captured the
        # viewer must never be queried for candidates again.
        d._pdf_candidates = Mock(side_effect=[[], AssertionError("viewer DOM must not be read after capture")])
        d._fetch_page_state_pdf = Mock(return_value=(body, pdf_url, None))
        d._pdf_viewer_present = Mock(return_value=viewer)
        d._capture_native_viewer_pdf = Mock(return_value=(body, pdf_url))
        page = Mock(); page.url = "https://www.sciencedirect.com/science/article/pii/S0000000000000000"
        page.evaluate.return_value = None
        page.locator.return_value.inner_text.return_value = ""
        def click(*args, **kwargs):
            page.url = pdf_url
            return True
        d._click_pdf_entry = Mock(side_effect=click)
        page.context.browser.browser_type.name = "firefox"
        result = DownloadResult(doi="10.0000/example", status="failed")
        return d._capture_pdf(page, result.doi, result), d, body, pdf_url

    def test_the_viewer_copy_is_used_without_a_second_download(self):
        captured, d, body, url = self.capture(viewer=True)
        self.assertEqual(captured, (body, url, None))
        d._fetch_page_state_pdf.assert_not_called()

    def test_a_403_followed_by_the_pdf_in_the_viewer_is_not_a_block(self):
        # JAD on ScienceDirect: the signed PDF URL answered 403, then PDF.js showed the article.
        from test_chromium_pdf_capture import article_pdf
        from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE
        body = article_pdf()
        d = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE, require_interactive_browser=True)
        tab = Mock(); tab.url = "https://pdf.sciencedirectassets.com/x/main.pdf"; tab.is_closed.return_value = False
        tab.context.browser = None  # a Firefox persistent context
        tab.context.pages = [tab]
        d._pdf_viewer_present = Mock(return_value=True)
        d._capture_loaded_pdf_viewer = Mock(return_value=body)
        d._accept_pdf_body = Mock(return_value=True)  # PDF parsing is tested elsewhere
        captured = {"suspect_block": "403 " + tab.url, "block_reason": None, "bytes": None}
        result = DownloadResult(doi="10.0000/example", status="failed")
        self.assertTrue(d._resolve_suspect_block(tab, result, captured))
        self.assertEqual((captured["bytes"], captured["url"]), (body, tab.url))
        self.assertIn("challenge_resolved", [e["state"] for e in result.events])
        tab.wait_for_timeout.assert_not_called()

    def test_the_citation_pdf_in_the_viewer_ends_the_wait(self):
        # Karger, 2026-11-02: after the check on its PDF address PDF.js showed the
        # article's citation PDF; the wait judged it without the capture's bound
        # address and watched an "unknown" page for 30 s instead of reading it.
        from test_chromium_pdf_capture import article_pdf
        from paper_search_carsi.publishers.profiles import get_publisher_profile
        body = article_pdf()
        pdf_url = "https://karger.com/crd/article-pdf/146/6/772/123/000000001.pdf"
        d = PublisherBatchDownloader(config={}, profile=get_publisher_profile("karger"),
                                     require_interactive_browser=True)
        tab = Mock(); tab.url = pdf_url; tab.is_closed.return_value = False
        tab.context.browser = None  # a Firefox persistent context
        tab.context.pages = [tab]
        d._pdf_viewer_present = Mock(return_value=True)
        d._capture_loaded_pdf_viewer = Mock(return_value=body)
        d._accept_pdf_body = Mock(return_value=True)  # PDF parsing is tested elsewhere
        d._is_challenge_page = Mock(return_value=False)
        d._pdf_step_needs_login = Mock(return_value=False)
        d.SUSPECT_UNKNOWN_GRACE_SEC = 0
        captured = {"suspect_block": "403 " + pdf_url, "block_reason": None, "bytes": None,
                    "article_pdf_urls": frozenset({pdf_url})}
        result = DownloadResult(doi="10.1159/000000001", status="failed")
        self.assertTrue(d._resolve_suspect_block(tab, result, captured))
        self.assertEqual((captured["bytes"], captured["url"]), (body, pdf_url))
        self.assertIn("challenge_resolved", [e["state"] for e in result.events])

    def test_without_a_viewer_the_pdf_is_fetched_again(self):
        captured, d, body, url = self.capture(viewer=False)
        self.assertEqual(captured, (body, url, None))
        d._capture_native_viewer_pdf.assert_not_called()
        d._fetch_page_state_pdf.assert_called_once()


if __name__ == "__main__":
    unittest.main()

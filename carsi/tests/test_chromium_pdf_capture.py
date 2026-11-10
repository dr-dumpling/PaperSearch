import base64
import unittest
from unittest.mock import Mock

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE


def article_pdf():
    """A readable PDF naming the fixture DOI (main-text evidence)."""
    import pymupdf

    with pymupdf.open() as document:
        for index in range(12):
            document.new_page().insert_text((40, 50), "Fixture article\nDOI: 10.0000/example\n" + "Results\n" * 40)
        return document.tobytes(deflate=False)


class ChromiumPDFCaptureTests(unittest.TestCase):
    def capture(self, status=200, content_type="application/pdf", body=None, body_error=False, title=None):
        pdf_bytes = body if body is not None else article_pdf()
        pdf_url = "https://pdf.sciencedirectassets.com/example/main.pdf"
        downloader = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
        downloader._return_to_record_article_if_needed = Mock()
        downloader._click_pdf_entry = Mock(return_value=True)
        downloader._pdf_candidates = Mock(return_value=[])
        downloader._fetch_page_state_pdf = Mock(return_value=(None, "", None))
        if title is not None:
            downloader._citation_title = Mock(return_value=title)
        page = Mock()
        page.context.browser.browser_type.name = "chromium"
        session = page.context.new_cdp_session.return_value

        def send(method, params=None):
            if method == "Fetch.getResponseBody":
                if body_error:
                    raise RuntimeError("Browser response unavailable")
                return {"body": base64.b64encode(pdf_bytes).decode(), "base64Encoded": True}
            return {}

        session.send.side_effect = send

        def deliver_response(milliseconds):
            callback = session.on.call_args.args[1]
            callback({
                "requestId": "test-response",
                "request": {"url": pdf_url},
                "responseStatusCode": status,
                "responseHeaders": [{"name": "Content-Type", "value": content_type}],
            })

        page.wait_for_timeout.side_effect = deliver_response
        result = DownloadResult(doi="10.0000/example", status="failed")
        captured = downloader._capture_pdf(page, result.doi, result)
        return captured, downloader, session, pdf_bytes, pdf_url

    def test_authorized_browser_response_is_saved_without_http_replay(self):
        captured, downloader, session, body, url = self.capture()
        self.assertEqual(captured, (body, url, None))
        downloader._fetch_page_state_pdf.assert_not_called()
        session.send.assert_any_call("Fetch.continueRequest", {"requestId": "test-response"})
        session.send.assert_any_call("Fetch.disable")
        session.detach.assert_called_once()

    def test_a_pdf_naming_neither_doi_nor_title_is_saved_at_once_unconfirmed(self):
        # Science (2026-11-09): its PDF names neither on the first pages; trying the
        # page's other addresses for a confirmed copy took the rest of the minute.
        import pymupdf

        with pymupdf.open() as document:
            for _ in range(12):
                document.new_page().insert_text((40, 50), "Research article\n" + "Results\n" * 40)
            unknown = document.tobytes(deflate=False)
        (body, url, block), downloader, _, _, pdf_url = self.capture(body=unknown, title="A fixture title found nowhere")
        self.assertEqual((body, url, block), (unknown, pdf_url, None))
        downloader._fetch_page_state_pdf.assert_not_called()

    def test_denied_response_is_not_treated_as_pdf(self):
        captured, downloader, session, body, url = self.capture(status=403)
        self.assertIsNone(captured[0])
        self.assertNotIn("Fetch.getResponseBody", [call.args[0] for call in session.send.call_args_list])
        session.send.assert_any_call("Fetch.continueRequest", {"requestId": "test-response"})

    def test_native_partial_response_is_released_without_saving_a_chunk(self):
        captured, _, session, _, _ = self.capture(status=206)
        self.assertIsNone(captured[0])
        self.assertNotIn("Fetch.getResponseBody", [call.args[0] for call in session.send.call_args_list])
        session.send.assert_any_call("Fetch.continueRequest", {"requestId": "test-response"})

    def test_html_and_invalid_pdf_are_not_saved(self):
        for content_type, body in (
            ("text/html", b"<html>Sign in</html>"),
            ("application/pdf", b"<html>" + b"x" * 6000),
        ):
            with self.subTest(content_type=content_type):
                captured, downloader, session, _, _ = self.capture(content_type=content_type, body=body)
                self.assertIsNone(captured[0])
                session.send.assert_any_call("Fetch.continueRequest", {"requestId": "test-response"})

    def test_body_error_releases_the_paused_response(self):
        captured, downloader, session, body, url = self.capture(body_error=True)
        self.assertIsNone(captured[0])
        session.send.assert_any_call("Fetch.continueRequest", {"requestId": "test-response"})
        session.send.assert_any_call("Fetch.disable")
        session.detach.assert_called_once()


if __name__ == "__main__":
    unittest.main()

import base64
import unittest
from unittest.mock import Mock, patch

from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import ELSEVIER_PROFILE


def article_pdf():
    """A readable PDF naming the fixture DOI (main-text evidence)."""
    import pymupdf

    with pymupdf.open() as document:
        for index in range(12):
            document.new_page().insert_text((40, 50), "Fixture article\nDOI: 10.0000/example\n" + "Results\n" * 40)
        return document.tobytes(deflate=False)


class ChromiumPDFCaptureTests(unittest.TestCase):
    def test_stream_preserves_utf8_text_and_base64_binary_chunks(self):
        # Real Chrome IO.read returns UTF-8 text when base64Encoded is false.
        # A non-Latin PDF comment used to raise before the remaining bytes arrived.
        from paper_search_school.browser import watchdog

        plain = "%PDF-1.7\n% 测试 π €\n"
        binary = b"\x00\xff\x80\n%%EOF\n"
        chunks = iter([
            {"data": plain, "base64Encoded": False, "eof": False},
            {"data": base64.b64encode(binary).decode(), "base64Encoded": True, "eof": False},
            {"data": "", "eof": True},
        ])
        session = Mock()

        def send(method, params=None):
            if method == "Fetch.takeResponseBodyAsStream":
                return {"stream": "utf8-stream"}
            if method == "IO.read":
                return next(chunks)
            return {}

        session.send.side_effect = send
        downloader = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
        result = DownloadResult(doi="10.0000/example", status="failed")
        captured = {}
        with patch.object(watchdog, "extend_operation"):
            body = downloader._read_paused_pdf(session, "request", result, captured)
        self.assertEqual(body, plain.encode("utf-8") + binary)
        self.assertFalse(captured["receiving"])
        session.send.assert_any_call("IO.close", {"handle": "utf8-stream"})

    def capture(self, status=200, content_type="application/pdf", body=None, body_error=False, title=None,
                disposition=None, length="its own", another_copy=False):
        pdf_bytes = body if body is not None else article_pdf()
        pdf_url = "https://pdf.sciencedirectassets.com/example/main.pdf"
        downloader = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
        downloader._return_to_record_article_if_needed = Mock()
        downloader._click_pdf_entry = Mock(return_value=True)
        downloader._pdf_candidates = Mock(return_value=[])
        downloader._fetch_page_state_pdf = Mock(return_value=(None, "", None))
        if title is not None:
            downloader._citation_title = Mock(return_value=title)
        page = self.page = Mock()
        page.context.browser.browser_type.name = "chromium"
        # An ordinary page, not a verification page: its title and text are read as a browser gives them, strings
        # (the PDF step looks for a verification page of its own since 2026-11-23, 0df29dbf).
        page.title.return_value = ""
        page.locator.return_value.inner_text.return_value = ""
        session = page.context.new_cdp_session.return_value

        stream = {"at": 0}

        def send(method, params=None):
            if method == "Fetch.getResponseBody":
                if body_error:
                    raise RuntimeError("Browser response unavailable")
                return {"body": base64.b64encode(pdf_bytes).decode(), "base64Encoded": True}
            if method == "Fetch.takeResponseBodyAsStream":
                return {"stream": "body-stream"}
            if method == "IO.read":
                if body_error:
                    raise RuntimeError("Browser response unavailable")
                if another_copy and stream["at"] == 0:
                    # The same PDF paused again while this copy is read (IEEE, 2026-11-19).
                    session.on.call_args.args[1]({"requestId": "another-copy", "request": {"url": pdf_url},
                                                  "responseStatusCode": 200,
                                                  "responseHeaders": [{"name": "Content-Type", "value": content_type}]})
                at = stream["at"]
                piece = pdf_bytes[at:at + 1500]
                stream["at"] = at + len(piece)
                return {"data": base64.b64encode(piece).decode(), "base64Encoded": True,
                        "eof": stream["at"] >= len(pdf_bytes)}
            return {}

        session.send.side_effect = send

        def deliver_response(milliseconds):
            callback = session.on.call_args.args[1]
            callback({
                "requestId": "test-response",
                "request": {"url": pdf_url},
                "responseStatusCode": status,
                "responseHeaders": [{"name": "Content-Type", "value": content_type}]
                + ([{"name": "Content-Disposition", "value": disposition}] if disposition else [])
                + ([{"name": "Content-Length", "value": str(len(pdf_bytes) if length == "its own" else length)}]
                   if length else []),
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

    def test_a_pdf_sent_as_an_attachment_is_kept_out_of_the_browsers_downloads(self):
        # Science's ?download=true (2026-11-15): Chrome also downloaded the PDF the capture
        # held, a full copy in its download list. Taken, it is answered with nothing; a PDF
        # shown in the browser goes on as before.
        captured, _, session, body, url = self.capture(disposition='attachment; filename="example.pdf"')
        self.assertEqual(captured, (body, url, None))
        session.send.assert_any_call("Fetch.fulfillRequest", {
            "requestId": "test-response", "responseCode": 204, "responseHeaders": [], "body": ""})
        self.assertNotIn(("Fetch.continueRequest", {"requestId": "test-response"}),
                         [call.args for call in session.send.call_args_list])
        captured, _, session, body, url = self.capture(disposition="inline")
        self.assertEqual(captured, (body, url, None))
        session.send.assert_any_call("Fetch.continueRequest", {"requestId": "test-response"})
        # Not taken (not a PDF of this article): the browser has it as before.
        captured, _, session, _, _ = self.capture(disposition="attachment", content_type="application/pdf", body=b"<html>" + b"x" * 6000)
        self.assertIsNone(captured[0])
        session.send.assert_any_call("Fetch.continueRequest", {"requestId": "test-response"})

    def test_a_large_pdf_is_read_in_pieces_its_step_going_on_meanwhile(self):
        # Cell (2026-11-18): a 108 MB PDF read in one call was cut at the step's minute.
        from paper_search_school.browser import watchdog
        from paper_search_school.engine import batch_capture

        extended = []
        real = watchdog.extend_operation
        watchdog.extend_operation = lambda seconds: extended.append(seconds)
        try:
            captured, downloader, session, body, url = self.capture(length=batch_capture.STREAM_PDF_BYTES + 1)
        finally:
            watchdog.extend_operation = real
        self.assertEqual(captured, (body, url, None))
        calls = [call.args[0] for call in session.send.call_args_list]
        self.assertNotIn("Fetch.getResponseBody", calls)
        self.assertGreater(calls.count("IO.read"), 1)
        self.assertEqual(len(extended), calls.count("IO.read"))
        session.send.assert_any_call("IO.close", {"handle": "body-stream"})
        # Its body taken, the request is answered empty, never continued.
        session.send.assert_any_call("Fetch.fulfillRequest", {
            "requestId": "test-response", "responseCode": 204, "responseHeaders": [], "body": ""})
        self.assertNotIn(("Fetch.continueRequest", {"requestId": "test-response"}),
                         [call.args for call in session.send.call_args_list])
        # A read that fails still answers the request.
        captured, _, session, _, _ = self.capture(length=batch_capture.STREAM_PDF_BYTES + 1, body_error=True)
        self.assertIsNone(captured[0])
        session.send.assert_any_call("Fetch.fulfillRequest", {
            "requestId": "test-response", "responseCode": 204, "responseHeaders": [], "body": ""})

    def test_a_copy_of_the_pdf_paused_while_one_is_read_is_answered_empty_unread(self):
        # IEEE (2026-11-19): the stamp.jsp frame's getPDF.jsp and the address tried after it each
        # read the 37 MB PDF, 36 s each.
        from paper_search_school.browser import watchdog

        real = watchdog.extend_operation
        watchdog.extend_operation = lambda seconds: None
        try:
            captured, downloader, session, body, url = self.capture(length=None, another_copy=True)
        finally:
            watchdog.extend_operation = real
        self.assertEqual(captured, (body, url, None))
        calls = [call.args for call in session.send.call_args_list]
        self.assertEqual([args[0] for args in calls].count("Fetch.takeResponseBodyAsStream"), 1)
        self.assertIn(("Fetch.fulfillRequest", {"requestId": "another-copy", "responseCode": 204,
                                                "responseHeaders": [], "body": ""}), calls)
        self.assertNotIn(("Fetch.continueRequest", {"requestId": "another-copy"}), calls)

    def test_a_pdf_without_its_size_or_over_8_mb_is_read_in_pieces(self):
        # IEEE (2026-11-18): getPDF.jsp sent a 31.8 MB PDF and a 37 MB one without a size, each
        # read in one call (46 and 57 s of the step's 60); the step ran out.
        from paper_search_school.browser import watchdog
        from paper_search_school.engine import batch_capture

        self.assertEqual(batch_capture.STREAM_PDF_BYTES, 8 * 1024 * 1024)
        real = watchdog.extend_operation
        watchdog.extend_operation = lambda seconds: None
        try:
            for length in (None, batch_capture.STREAM_PDF_BYTES + 1):
                with self.subTest(length=length):
                    captured, _, session, body, url = self.capture(length=length)
                    self.assertEqual(captured, (body, url, None))
                    calls = [call.args[0] for call in session.send.call_args_list]
                    self.assertNotIn("Fetch.getResponseBody", calls)
                    self.assertIn("IO.read", calls)
            # A PDF that says its size, under the limit: one call, and the browser has it as before.
            captured, _, session, body, url = self.capture()
            self.assertEqual(captured, (body, url, None))
            calls = [call.args[0] for call in session.send.call_args_list]
            self.assertIn("Fetch.getResponseBody", calls)
            self.assertNotIn("IO.read", calls)
            session.send.assert_any_call("Fetch.continueRequest", {"requestId": "test-response"})
        finally:
            watchdog.extend_operation = real

    def test_a_pdf_document_goes_on_without_patchrights_script(self):
        # Cell (2026-11-18): Patchright read a 108 MB PDF whole to write its init script in,
        # and the tab went down; during the capture a PDF address is sent on as it is.
        self.capture()
        matcher, handler = self.page.route.call_args.args
        self.assertTrue(matcher("https://www.cell.com/action/showPdf?pii=S0092-8674%2826%2900165-0"))
        self.assertFalse(matcher("https://www.cell.com/cell/fulltext/S0092-8674(26)00165-0"))
        document, image = Mock(), Mock()
        document.request.resource_type, image.request.resource_type = "document", "image"
        handler(document)
        handler(image)
        document.continue_.assert_called_once_with()
        document.fallback.assert_not_called()
        image.fallback.assert_called_once_with()
        self.page.unroute.assert_called_once_with(matcher, handler)

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

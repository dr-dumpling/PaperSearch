"""Opt-in local Chrome regressions; all requests are fulfilled or aborted.

SCHOOL_LOCAL_BROWSER_TEST=1 .venv/bin/python -B \
    -m unittest discover -s tests -p test_springer_native_capture.py -v

Only synthetic, memory-generated PDFs and disposable Chrome contexts are used.
The isolated loader bypasses package startup and forbids config/socket access.
No installed package, saved profile, credentials, or publisher service is used.
"""

import json
import os
import unittest
from collections import Counter
from unittest.mock import Mock
from urllib.parse import quote


DOI = "10.1007/s00000-026-00001-1"
TITLE = "Synthetic Springer native capture fixture"
ARTICLE = "https://link.springer.com/article/" + DOI
PDF = "https://link.springer.com/content/pdf/" + quote(DOI, safe="") + ".pdf"
SUPPLEMENT = (
    "https://static-content.springer-cdn.com/esm/art%3A"
    + quote(DOI, safe="") + "/MediaObjects/00000_2026_1_MOESM1_ESM.pdf"
)


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1",
                     "local Chrome fixture requires explicit env gate")
class SpringerNativeCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright

        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser = cls.driver.chromium.launch(
            channel="chrome", headless=True, timeout=15_000,
            args=["--disable-background-networking", "--disable-component-update",
                  "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"],
        )
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        import test_wiley_capture as fixtures

        harness = fixtures.WileyCaptureTests(methodName="runTest")
        self.addCleanup(harness.doCleanups)
        harness.setUp()
        self.batch = harness.batch
        self.downloader = self.batch.PublisherBatchDownloader(
            config={}, profile=harness.profiles.SPRINGER_PROFILE,
            pdf_timeout_sec=3, login_timeout_sec=1,
        )
        # A missed native response cannot be rescued by a synthetic HTTP body.
        self.downloader._fetch_page_state_pdf = Mock(return_value=(None, "", None))
        self.downloader._fetch_pdf_url_with_browser_state = Mock(
            side_effect=AssertionError("plain HTTP fallback forbidden"))
        self.downloader._save_publisher_session = Mock(
            side_effect=AssertionError("credential I/O forbidden"))
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.context.set_default_timeout(3_000)
        self.context.set_default_navigation_timeout(3_000)
        self.pdf = self.make_pdf()

    def make_pdf(self, supplementary=False):
        import pymupdf

        with pymupdf.open() as document:
            for index in range(12):
                page = document.new_page()
                heading = TITLE if index == 0 else "Fixture continuation"
                if supplementary and index == 1:
                    heading = "Supplementary Table1"
                page.insert_text((40, 50), heading + "\nDOI: " + DOI)
                page.insert_text((40, 110), "Abstract\n" + (
                    f"Synthetic local test data, page {index}.\n" * 20))
            body = document.tobytes(deflate=False)
        self.assertGreater(len(body), 5_000)
        with pymupdf.open(stream=body, filetype="pdf") as document:
            first_page = document[0].get_text()
            self.assertIn(TITLE, first_page)
            self.assertIn(DOI, first_page)
            self.assertEqual(len(document), 12)
        return body

    def capture(self, *, url=PDF, body=None, disposition="inline", entry="link",
                reject=False, redirects=(), download_attr=False):
        data = self.pdf if body is None else body
        requests = []
        navigations = []
        navigation_url = redirects[0][0] if redirects else url
        redirect_responses = {origin: (target, headers)
                              for origin, target, headers in redirects}
        # For negative URL fixtures, a visible current-DOI link navigates to the
        # bad endpoint via script. The response guard must reject a delivered
        # response, rather than passing merely because link discovery skipped it.
        html = f"<html><title>{TITLE}</title><body>Full text access"
        if entry == "link":
            download = ' download="s00000-026-00001-1.pdf"' if download_attr else ""
            html += f'<a id="pdf" target="_blank" href="{PDF}"{download}>Download PDF</a>'
            if navigation_url != PDF:
                html += ("<script>document.getElementById('pdf').onclick = event => {"
                         "event.preventDefault(); window.location.href = "
                         + json.dumps(navigation_url) + ";};</script>")
        html += "</body></html>"

        def respond(route):
            request = route.request
            requests.append(request.url)
            if request.is_navigation_request():
                navigations.append(request.url)
            if request.url == ARTICLE:
                route.fulfill(status=200, content_type="text/html", body=html)
            elif request.url in redirect_responses:
                target, headers = redirect_responses[request.url]
                route.fulfill(status=302, headers={"Location": target, **headers}, body="")
            elif request.url == url:
                route.fulfill(status=200, headers={
                    "Content-Type": "application/pdf",
                    "Content-Disposition": disposition,
                }, body=data)
            else:
                route.abort()

        self.context.route("**/*", respond)
        page = self.context.new_page()
        downloads = []
        page.on("download", lambda download: downloads.append(download))
        page.goto(ARTICLE, wait_until="domcontentloaded")
        result = self.batch.DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        if entry == "candidate":
            self.downloader._pdf_candidates = Mock(return_value=[navigation_url])
        elif reject:
            # Exercise just the delivered rejection; canonical retries are
            # covered elsewhere. Keep negative native tests bounded/offline.
            self.downloader._pdf_candidates = Mock(return_value=[])
        body, captured_url, block = self.downloader._capture_pdf(page, DOI, result)
        # Dispatch any download event queued while capture disabled/detached CDP.
        page.wait_for_timeout(250)
        self.assertIsNone(block)
        expected_navigation = [ARTICLE, *redirect_responses, url]
        for expected_url in expected_navigation:
            self.assertEqual(requests.count(expected_url), 1, requests)
        self.assertEqual(Counter(navigations), Counter(expected_navigation))
        self.assertEqual(len(self.context.pages), 1)
        self.downloader._fetch_pdf_url_with_browser_state.assert_not_called()
        self.downloader._save_publisher_session.assert_not_called()
        events = [event["state"] for event in result.events]
        cleanup_errors = [event for event in result.events if event["state"] in {
            "browser_response_continue_error", "browser_capture_disable_error",
            "browser_capture_detach_error",
        }]
        self.assertEqual(cleanup_errors, [])
        if reject:
            self.assertTrue(body is None,
                            f"Rejected fixture returned PDF at {captured_url}; events={events}")
            self.assertEqual(captured_url, "")
            self.assertNotIn("browser_pdf_response_captured", events)
        else:
            self.assertEqual(len(downloads), 0,
                             "Accepted PDF must not also create a Chrome download")
            self.assertEqual(body, data)
            self.assertEqual(captured_url, url)
            self.downloader._fetch_page_state_pdf.assert_not_called()
            self.assertEqual(events.count("browser_pdf_response_captured"), 1, events)

    def test_inline_pdf_from_visible_link_is_captured_once(self):
        self.capture(disposition='inline; filename="s00000-026-00001-1.pdf"')

    def test_attachment_from_visible_link_is_captured_once(self):
        self.capture(disposition='attachment; filename="s00000-026-00001-1.pdf"')

    def test_download_attribute_attachment_link_does_not_create_download(self):
        self.capture(entry="link", download_attr=True,
                     disposition='attachment; filename="s00000-026-00001-1.pdf"')

    def test_download_attribute_inline_link_does_not_create_download(self):
        self.capture(entry="link", download_attr=True,
                     disposition='inline; filename="s00000-026-00001-1.pdf"')

    def test_inline_pdf_from_candidate_navigation_is_captured_once(self):
        self.capture(entry="candidate", url=PDF.replace("%2F", "/"))

    def test_attachment_navigation_abort_does_not_repeat_navigation(self):
        self.capture(entry="candidate",
                     disposition='attachment; filename="s00000-026-00001-1.pdf"')

    def test_supplementary_endpoint_is_rejected(self):
        self.capture(url=SUPPLEMENT, reject=True)

    def test_other_doi_endpoint_is_rejected_even_with_expected_doi_body(self):
        self.capture(url=PDF.replace("00001-1", "00002-2"), reject=True)

    def test_inline_supplementary_content_disposition_is_rejected(self):
        self.capture(disposition='inline; filename="00000_2026_1_MOESM1_ESM.pdf"',
                     reject=True)

    def test_attachment_supplementary_content_disposition_is_rejected(self):
        self.capture(disposition='attachment; filename="00000_2026_1_MOESM1_ESM.pdf"',
                     reject=True)

    def test_candidate_attachment_header_rejection_does_not_retry(self):
        self.capture(entry="candidate",
                     disposition='attachment; filename="00000_2026_1_MOESM1_ESM.pdf"',
                     reject=True)

    def test_main_endpoint_pdf_naming_this_doi_is_captured_whatever_its_second_page(self):
        body = self.make_pdf(supplementary=True)
        self.capture(body=body)

    def test_invalid_body_with_pdf_headers_is_rejected(self):
        self.capture(body=b"%PDF-1.7\n" + b"synthetic invalid body\n" * 400, reject=True)

    def test_redirect_other_doi_to_exact_main_endpoint_is_rejected(self):
        wrong_doi = PDF.replace("00001-1", "00002-2")
        self.capture(redirects=[(wrong_doi, PDF, {})], reject=True)

    def test_redirect_supplement_to_exact_main_endpoint_is_rejected(self):
        self.capture(redirects=[(SUPPLEMENT, PDF, {})], reject=True)

    def test_redirect_supplement_filename_on_302_is_rejected(self):
        final_url = PDF + "?download=1"
        self.capture(url=final_url, redirects=[(PDF, final_url, {
            "Content-Disposition": 'attachment; filename="00000_2026_1_MOESM1_ESM.pdf"',
        })], reject=True)

    def test_redirect_same_doi_query_is_captured_once(self):
        final_url = PDF + "?download=1"
        self.capture(url=final_url, redirects=[(PDF, final_url, {})])


if __name__ == "__main__":
    unittest.main()

"""Opt-in local Chrome fixture: intercept all traffic; no publisher requests."""
import os
import unittest
from unittest.mock import Mock

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE


@unittest.skipUnless(os.environ.get('CARSI_LOCAL_BROWSER_TEST') == '1', 'local Chrome fixture opt-in')
class NativeCaptureTests(unittest.TestCase):
    def test_blank_target_pdf_link_is_captured_in_observed_page(self):
        import fitz
        from playwright.sync_api import sync_playwright

        doc = fitz.open()
        for index in range(20):
            page = doc.new_page()
            page.insert_text((50, 60), 'DOI: 10.1000/local-fixture\n' + ('Local capture fixture %s\n' % index) * 25)
        data = doc.tobytes(deflate=False)
        doc.close()
        self.assertGreater(len(data), 5000)
        article = 'https://www.sciencedirect.com/science/article/pii/S0000000000000000'
        pdf_url = 'https://pdf.sciencedirectassets.com/fixture/main.pdf'
        html = '<html><body>Full text access<a target="_blank" href="%s">View PDF</a></body></html>' % pdf_url
        requests = []

        def local_response(route):
            url = route.request.url
            requests.append(url)
            if url == article:
                route.fulfill(status=200, content_type='text/html', body=html)
            elif url == pdf_url:
                route.fulfill(status=200, content_type='application/pdf', body=data)
            else:
                route.abort()

        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel='chrome', headless=True)
            try:
                context = browser.new_context()
                context.route('**/*', local_response)
                page = context.new_page()
                page.goto(article)
                downloader = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
                # No synthetic fallback may hide a missed native response.
                downloader._pdf_candidates = Mock(return_value=[])
                downloader._fetch_page_state_pdf = Mock(return_value=(None, '', None))
                result = DownloadResult(doi='10.1000/local-fixture', status='failed')
                body, url, block = downloader._capture_pdf(page, result.doi, result)
                self.assertEqual(body, data)
                self.assertEqual(url, pdf_url)
                self.assertIsNone(block)
                self.assertEqual(len(context.pages), 1)
                self.assertEqual(requests.count(pdf_url), 1)
                downloader._fetch_page_state_pdf.assert_not_called()
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()

"""RSC's article PDF on Silverchair's CDN; synthetic PDFs, every Chrome request intercepted."""
import os
import unittest
from unittest.mock import Mock, patch

DOI = '10.1039/d6fd99999x'
TITLE = 'Synthetic Faraday Discussions lecture'
ARTICLE = 'https://pubs.rsc.org/fd/article/doi/10.1039/D6FD99999X/1299999/Synthetic-Faraday-Discussions-lecture'
PDF = 'https://pubs.rsc.org/fd/article-pdf/doi/10.1039/D6FD99999X/13799999/d6fd99999x.pdf'
CDN = ('https://rscj.silverchair-cdn.com/rscj/content_public/journal/fd/jam/10.1039_d6fd99999x/1/'
       'd6fd99999x.pdf?Expires=1&Signature=fixture')


def synthetic_pdf():
    import pymupdf
    with pymupdf.open() as document:
        for _ in range(2):
            document.new_page().insert_text((40, 50), TITLE + '\nDOI: ' + DOI + '\nAbstract\nResults.')
        return document.tobytes() + b'\n%' + b'x' * 6000


@unittest.skipUnless(os.environ.get('CARSI_LOCAL_BROWSER_TEST') == '1', 'local Chrome fixture opt-in')
class RSCNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser = cls.driver.chromium.launch(channel='chrome', headless=True,
            args=['--disable-background-networking', '--no-proxy-server',
                  '--host-resolver-rules=MAP * ~NOTFOUND'])
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        from paper_search_carsi.engine import batch as publisher_batch
        from paper_search_carsi.publishers.profiles import RSC_PROFILE
        self.d = publisher_batch.PublisherBatchDownloader({}, profile=RSC_PROFILE, pdf_timeout_sec=2)
        self.d._fetch_page_state_pdf = Mock(return_value=(None, '', None))
        self.d._fetch_pdf_url_with_browser_state = Mock(return_value=(None, '', None))
        self.context = self.browser.new_context(service_workers='block')
        self.addCleanup(self.context.close)
        self.requests = []
        self.downloads = []
        self.main_body = synthetic_pdf()
        self.cdn = CDN

        def respond(route):
            url = route.request.url
            self.requests.append(url)
            if url == ARTICLE:
                route.fulfill(status=200, content_type='text/html', body=(
                    f'<title>{TITLE}</title><meta name="citation_doi" content="{DOI}">'
                    f'<meta name="citation_title" content="{TITLE}">'
                    f'<meta name="citation_pdf_url" content="{PDF}"><a href="{PDF}">PDF</a>'))
            elif url == PDF:
                route.fulfill(status=302, headers={'Location': self.cdn})
            elif url == self.cdn:
                route.fulfill(status=200, content_type='application/pdf', body=self.main_body)
            else:
                route.abort()
        self.context.route('**/*', respond)
        self.page = self.context.new_page()
        self.page.on('download', lambda event: self.downloads.append(event))
        self.page.goto(ARTICLE)
        self.result = publisher_batch.DownloadResult(doi=DOI, status='failed')
        self.enterContext(patch.object(publisher_batch.time, 'sleep'))

    def test_the_bound_pdfs_own_file_on_the_cdn_is_captured(self):
        """The article PDF's address redirects to the same file on Silverchair's CDN,
        which was refused and answered 204 (Faraday Discussions, 2026-11-07)."""
        body, url, block = self.d._capture_pdf(self.page, DOI, self.result)
        self.assertEqual((body, url, block), (self.main_body, CDN, None))
        self.assertEqual(self.downloads, [])

    def test_another_file_on_the_cdn_is_still_refused(self):
        self.cdn = CDN.replace('/d6fd99999x.pdf', '/d6fd88888x.pdf')
        body, _, _ = self.d._capture_pdf(self.page, DOI, self.result)
        self.assertIsNone(body)
        self.assertEqual(self.downloads, [])


if __name__ == '__main__':
    unittest.main()

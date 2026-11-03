"""JAMA正文/附件回归；合成PDF，本机Chrome请求全部拦截。"""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

DOI = '10.1001/jama.2025.99999'
TITLE = 'Synthetic JAMA randomized clinical trial'
ARTICLE = 'https://jamanetwork.com/journals/jama/fullarticle/2999999'
PDF = 'https://jamanetwork.com/journals/jama/articlepdf/2999999/jama_fixture_2025.pdf'
OTHER = PDF.replace('2999999', '2888888')
SUPPLEMENT = 'https://cdn.jamanetwork.com/ama/content_public/journal/jama/999/joi999999supp1_prod.pdf'


def profile(profiles):
    return profiles.PublisherProfile(name='JAMA', article_url_template='https://doi.org/{doi}',
        pdf_url_templates=(), success_url_markers=('jamanetwork.com/journals/',),
        auth_url_markers=('/login',), auth_title_markers=('Institutional Login',),
        sso_text_markers=('access through your institution',), base_domains=('jamanetwork.com',))


def synthetic_pdf(heading=TITLE, metadata_title='', pages=2):
    import pymupdf
    with pymupdf.open() as document:
        for _ in range(pages):
            document.new_page().insert_text((40, 50), heading + '\nDOI: ' + DOI +
                '\nAbstract\nMethods and results are reported here; see Supplement 7.')
        document.set_metadata({'title': metadata_title})
        return document.tobytes() + b'\n%' + b'x' * 6000


class JAMAGuardTests(unittest.TestCase):
    def setUp(self):
        import test_wiley_capture as fixtures
        harness = fixtures.WileyCaptureTests(methodName='runTest')
        self.addCleanup(harness.doCleanups)
        harness.setUp()
        self.batch = harness.batch
        self.d = self.batch.PublisherBatchDownloader({}, profile=profile(harness.profiles))
        self.meta = {'dois': [DOI], 'pdfs': [PDF]}
        self.page = Mock(url=ARTICLE)
        self.page.evaluate.side_effect = lambda *args: self.meta
        self.bound = frozenset({PDF})
        self.d._capture_doi = DOI

    def test_metadata_binds_exact_doi_article_id_and_host(self):
        self.assertEqual(self.d._pdf_candidates(self.page, DOI), [PDF])
        for meta in ({'dois': [], 'pdfs': [PDF]},
                     {'dois': [DOI, '10.1001/jama.2025.88888'], 'pdfs': [PDF]},
                     {'dois': ['10.1001/jama.2025.88888'], 'pdfs': [PDF]}):
            with self.subTest(meta=meta):
                self.meta = meta
                self.assertEqual(self.d._pdf_candidates(self.page, DOI), [])
        # The engine's one citation rule (batch_pdf_urls): this DOI's page names
        # the PDF; an address of another site, or an attachment, is never taken.
        # (Another article's id in the page's own metadata is the PDF's first
        # page to tell: pdf_guard refuses it.)
        for url in (SUPPLEMENT, PDF.replace('jamanetwork.com', 'jamanetwork.com.evil.example'),
                    PDF.replace('https:', 'http:'), PDF.replace('jama_fixture', 'joi999999supp1_prod'),
                    ARTICLE):
            with self.subTest(url=url):
                self.meta = {'dois': [DOI], 'pdfs': [url]}
                self.assertEqual(self.d._pdf_candidates(self.page, DOI), [])
        self.page.url = 'https://jamanetwork.com/'  # not an article page
        self.meta = {'dois': [DOI], 'pdfs': [PDF]}
        self.assertEqual(self.d._pdf_candidates(self.page, DOI), [])

    def test_response_requires_this_capture_binding_and_rejects_attachment_redirect(self):
        response = SimpleNamespace(url=PDF, status=200, headers={}, history=[])
        self.assertFalse(self.d._response_matches_article(response, DOI))
        self.assertTrue(self.d._response_matches_article(response, DOI, article_pdf_urls=self.bound))
        for url in (SUPPLEMENT, OTHER, 'https://unrelated.example/file.pdf'):
            with self.subTest(url=url):
                response.url = url
                response.history = [SimpleNamespace(url=PDF, headers={})]
                self.assertFalse(self.d._response_matches_article(response, DOI, article_pdf_urls=self.bound))
        response.url = PDF
        response.headers = {'Content-Disposition': 'attachment; filename="JOI999999%73upp1_srcpdf.pdf"'}
        self.assertFalse(self.d._response_matches_article(response, DOI, article_pdf_urls=self.bound))

    def test_the_bound_pdfs_own_file_on_its_delivery_host_is_accepted(self):
        # JAMA Network Open (2026-11-02): articlepdf redirected to Silverchair's watermarked
        # copy of the same file; another name there stays refused.
        name = PDF.rsplit("/", 1)[-1]
        response = SimpleNamespace(url="https://watermark02.silverchair.com/" + name + "?token=fixture",
                                   status=200, headers={}, history=[SimpleNamespace(url=PDF, headers={})])
        self.assertTrue(self.d._response_matches_article(response, DOI, article_pdf_urls=self.bound))
        response.url = "https://watermark02.silverchair.com/another_article_2026.pdf?token=fixture"
        self.assertFalse(self.d._response_matches_article(response, DOI, article_pdf_urls=self.bound))
        response.url = "https://watermark02.silverchair.com/" + name
        response.history = []  # not reached from this article's PDF
        self.assertFalse(self.d._response_matches_article(response, DOI, article_pdf_urls=self.bound))

    def test_attachments_are_told_apart_by_their_heading_or_url_not_by_metadata(self):
        self.assertTrue(self.d._accept_pdf_body(synthetic_pdf(), PDF))
        # A supplement's file name in the PDF metadata does not decide.
        self.assertTrue(self.d._accept_pdf_body(synthetic_pdf('Unreadable glyph map', 'JOI999999supp1_srcpdf.pdf'), PDF))
        # JAMA's supplement heading at the top: not the main text, whatever the URL.
        self.assertFalse(self.d._accept_pdf_body(synthetic_pdf('Supplementary Online Content'), PDF))
        for heading in ('Unreadable glyph map', 'Supplementary Online Content'):
            with self.subTest(heading=heading):
                self.assertFalse(self.d._accept_pdf_body(synthetic_pdf(heading), SUPPLEMENT))

    def test_missing_binding_stops_capture_without_navigation(self):
        self.meta = {'dois': ['10.1001/jama.2025.88888'], 'pdfs': [PDF]}
        result = self.batch.DownloadResult(doi=DOI, status='failed')
        self.assertEqual(self.d._capture_pdf(self.page, DOI, result), (None, '', None))
        self.page.goto.assert_not_called()

    def test_http_fallback_rejects_supplement_redirect(self):
        body = synthetic_pdf()
        response = SimpleNamespace(url=SUPPLEMENT, status_code=200, text='', content=body,
            headers={}, history=[SimpleNamespace(url=PDF, headers={})])
        self.d._pdf_request_headers = Mock(return_value={})
        with patch.object(self.batch.requests, 'get', return_value=response):
            self.assertEqual(self.d._fetch_pdf_url(PDF, doi=DOI, article_pdf_urls=self.bound),
                             (None, SUPPLEMENT, None))

    def test_redirect_origin_is_not_blacklisted_before_its_final_response(self):
        data = synthetic_pdf()
        handlers = {}
        self.page.context = SimpleNamespace(browser=None)
        self.page.on.side_effect = lambda name, fn: handlers.__setitem__(name, fn)
        self.d._institution_pdf_entitlement_missing = Mock(return_value=False)
        first = SimpleNamespace(url=PDF, status=302, headers={'location': PDF+'?download=1'},
                                body=Mock(return_value=b''))
        final = SimpleNamespace(url=PDF+'?download=1', status=200,
            headers={'content-type': 'application/pdf'}, body=lambda: data,
            history=[SimpleNamespace(url=PDF, headers={})])
        def click(*args, **kwargs):
            handlers['response'](first)
            handlers['response'](final)
            return True
        self.d._click_pdf_entry = Mock(side_effect=click)
        result = self.batch.DownloadResult(doi=DOI, status='failed')
        self.assertEqual(self.d._capture_pdf(self.page, DOI, result), (data, final.url, None))


@unittest.skipUnless(os.environ.get('CARSI_LOCAL_BROWSER_TEST') == '1', 'local Chrome fixture opt-in')
class JAMANativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser = cls.driver.chromium.launch(channel='chrome', headless=True,
            args=['--disable-background-networking', '--no-proxy-server',
                  '--host-resolver-rules=MAP * ~NOTFOUND'])
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        from paper_search_carsi.engine import batch as publisher_batch
        from paper_search_carsi.publishers import profiles as publisher_profiles
        self.batch = publisher_batch
        self.d = publisher_batch.PublisherBatchDownloader({}, profile=profile(publisher_profiles), pdf_timeout_sec=2)
        self.context = self.browser.new_context(service_workers='block')
        self.addCleanup(self.context.close)
        self.requests = []
        self.downloads = []
        self.main_body = synthetic_pdf()
        self.pdf_response_url = PDF + '?access=fixture'
        self.html = (f'<title>{TITLE}</title><meta name="citation_doi" content="{DOI}">'
            f'<meta name="citation_pdf_url" content="{PDF}">'
            f'<button aria-label="PDF" onclick="location.href=\'{SUPPLEMENT}\'">PDF</button>'
            f'<a href="{SUPPLEMENT}">Download PDF: Supplement 1</a>'
            f'<a href="{OTHER}">PDF from references</a>'
            f'<a class="js-pdfaccess" target="_blank" download href="{PDF}" '
            f'onclick="event.preventDefault();location.href=\'{self.pdf_response_url}\'">Download PDF</a>')
        def respond(route):
            url = route.request.url
            self.requests.append(url)
            if url == ARTICLE:
                route.fulfill(status=200, content_type='text/html', body=self.html)
            elif url == PDF:
                # Bypassing the publisher's click handler returns HTML.
                route.fulfill(status=200, content_type='text/html', body=self.html)
            elif url == self.pdf_response_url:
                route.fulfill(status=200, content_type='application/pdf', body=self.main_body)
            elif url == SUPPLEMENT:
                route.fulfill(status=200, content_type='application/pdf',
                    body=synthetic_pdf('Clinical Trial Protocol for Medical Devices', 'JOI999999supp1_srcpdf.pdf'))
            else:
                route.abort()
        self.context.route('**/*', respond)
        self.page = self.context.new_page()
        self.page.on('download', lambda event: self.downloads.append(event))
        self.page.goto(ARTICLE)
        self.result = publisher_batch.DownloadResult(doi=DOI, status='failed')
        self.enterContext(patch.object(publisher_batch.time, 'sleep'))

    def test_native_capture_uses_main_metadata_not_pdf_menu_or_supplements(self):
        self.d._fetch_page_state_pdf = Mock(side_effect=AssertionError('HTTP fallback cannot hide native capture failure'))
        body, url, block = self.d._capture_pdf(self.page, DOI, self.result)
        self.assertEqual((body, url, block), (self.main_body, self.pdf_response_url, None))
        self.assertEqual(self.requests, [ARTICLE, self.pdf_response_url])
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(self.downloads, [])
        self.assertIn('browser_pdf_response_captured', [e['state'] for e in self.result.events])

    def test_main_endpoint_body_naming_this_doi_is_captured_and_supplement_untouched(self):
        self.main_body = synthetic_pdf('Unreadable glyph map', 'JOI999999supp1_srcpdf.pdf')
        self.d._fetch_pdf_url_with_browser_state = Mock(return_value=(None, '', None))
        body, _, _ = self.d._capture_pdf(self.page, DOI, self.result)
        self.assertEqual(body, self.main_body)
        self.assertNotIn(SUPPLEMENT, self.requests)

    def test_owned_preview_does_not_block_native_main_pdf_capture(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from paper_search_carsi.browser import preview as browser_preview
        from paper_search_carsi import progress_reporter
        with TemporaryDirectory() as temporary, patch.dict(os.environ,
                CARSI_DATA_DIR=temporary, CARSI_PROGRESS_BAR='0'):
            progress_reporter.start_task('preview native fixture', 1, current=DOI)
            observer = browser_preview.enable(self.context, Path(temporary)/'preview')
            try:
                observer.observe(force=True)
                self.test_native_capture_uses_main_metadata_not_pdf_menu_or_supplements()
                observer.observe(force=True)
                state = browser_preview.snapshot(Path(temporary)/'preview', observer.run_id, DOI)
                self.assertEqual(state['status'], 'available')
                self.assertEqual(len(state['pages']), 1)
            finally:
                self.context.close()


if __name__ == '__main__':
    unittest.main()

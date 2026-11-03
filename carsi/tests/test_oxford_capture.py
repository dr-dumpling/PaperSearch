"""Oxford homepage/annual-report regression; synthetic fixtures only."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

DOI = '10.1093/jnci/fixture123'
ARTICLE = 'https://academic.oup.com/jnci/advance-article/doi/' + DOI + '/12345'
PDF = 'https://academic.oup.com/jnci/advance-article-pdf/doi/' + DOI + '/98765/fixture123.pdf'
CDN = 'https://watermark02.silverchair.com/fixture123.pdf?fixture-signature=local'
ANNUAL = 'https://fdslive.oup.com/www.oup.com/Group_comms/pdf/annualreport/Annual_Report_2025-26.pdf'


class OxfordViewerTests(unittest.TestCase):
    def test_the_viewer_is_read_only_at_this_articles_pdf_url(self):
        # The watermarked CDN URL names no article: its response is waited for.
        from paper_search_carsi.engine.batch import PublisherBatchDownloader
        from paper_search_carsi.publishers.profiles import infer_publisher_profile
        d = PublisherBatchDownloader({}, profile=infer_publisher_profile(DOI))
        self.assertFalse(d._native_viewer_pdf_allowed(CDN, doi=DOI, rejected_urls=set()))
        self.assertTrue(d._native_viewer_pdf_allowed(PDF, doi=DOI, rejected_urls=set()))
        self.assertFalse(d._native_viewer_pdf_allowed(PDF, doi=DOI, rejected_urls={PDF}))


class OxfordGuardTests(unittest.TestCase):
    def setUp(self):
        import test_wiley_capture as fixtures
        harness = fixtures.WileyCaptureTests(methodName='runTest')
        self.addCleanup(harness.doCleanups)
        harness.setUp()
        self.batch = harness.batch
        self.d = self.batch.PublisherBatchDownloader({}, profile=harness.profiles.OXFORD_ACADEMIC_PROFILE)

    def test_homepage_and_embedded_host_are_not_articles(self):
        for url in ('https://academic.oup.com/', 'https://academic.oup.com/journals',
                    'https://other.example/?next=' + ARTICLE,
                    'https://academic.oup.com.other.example/jnci/article/1/2/3/4'):
            with self.subTest(url=url):
                self.assertFalse(self.d._is_success_article_url(url))
        self.assertTrue(self.d._is_success_article_url(ARTICLE))
        self.assertTrue(self.d._is_success_article_url(ARTICLE.replace('/advance-article/', '/advance-article-abstract/')))

    def test_annual_wrong_doi_supplement_and_lookalike_pdf_are_rejected(self):
        for url in (ANNUAL, PDF.replace('fixture123', 'other123'),
                    PDF.replace('.pdf', '_supplementary.pdf'),
                    PDF.replace('academic.oup.com', 'academic.oup.com.other.example')):
            with self.subTest(url=url):
                self.assertFalse(self.d._article_pdf_url_matches(url, DOI))
        self.assertTrue(self.d._article_pdf_url_matches(PDF, DOI))
        self.assertTrue(self.d._article_pdf_url_matches(
            'https://academic.oup.com/jnci/article-pdf/138/1/2/98765/fixture123.pdf', DOI))
        self.assertFalse(self.d._article_pdf_url_matches(
            'https://academic.oup.com/sleep/article-pdf/138/1/2/98765/fixture123.pdf', DOI))

    def test_a_supplement_issue_is_not_supplementary_material(self):
        doi = '10.1093/eurheartjsupp/suag119.023'
        page = 'https://academic.oup.com/eurheartjsupp/article/28/Supplement_11/suag119.023/8863774'
        pdf = 'https://academic.oup.com/eurheartjsupp/article-pdf/28/Supplement_11/suag119.023/71595005/suag119.023.pdf'
        self.assertTrue(self.d._is_success_article_url(page))
        self.assertFalse(self.d._is_supplementary_url(pdf))
        self.assertTrue(self.d._article_pdf_url_matches(pdf, doi))
        self.assertTrue(self.d._is_supplementary_url(
            'https://oup.silverchair-cdn.com/oup/backfile/Content_public/Journal/eurheartjsupp/28/Supplement_11/suag119.023/1/suag119.023_supplement.docx'))

    def test_response_redirect_to_unrelated_pdf_cannot_be_captured(self):
        response = SimpleNamespace(url=ANNUAL, status=200, headers={}, history=[
            SimpleNamespace(url=PDF, headers={})])
        self.assertFalse(self.d._response_matches_article(response, DOI))

    def test_cdn_requires_current_endpoint_in_redirect_chain(self):
        response = SimpleNamespace(url=CDN, status=200, headers={}, history=[])
        self.assertFalse(self.d._response_matches_article(response, DOI))
        response.history = [SimpleNamespace(url=PDF, headers={})]
        self.assertTrue(self.d._response_matches_article(response, DOI))
        for url in (CDN.replace('fixture123', 'other'), CDN.replace('watermark02.silverchair.com', 'other.example'), ANNUAL):
            response.url = url
            self.assertFalse(self.d._response_matches_article(response, DOI))
        response.url = CDN
        response.history = [SimpleNamespace(url=PDF.replace('fixture123', 'other'), headers={})]
        self.assertFalse(self.d._response_matches_article(response, DOI))

    def test_discovery_filters_unrelated_pdf_before_navigation(self):
        page = Mock(url=ARTICLE)
        page.evaluate.return_value = {"links": [ANNUAL, PDF]}  # the page's visible links
        urls = self.d._pdf_candidates(page, DOI)
        self.assertIn(PDF, urls)
        self.assertNotIn(ANNUAL, urls)
        self.assertTrue(all(self.d._article_pdf_url_matches(url, DOI) for url in urls))


@unittest.skipUnless(os.environ.get('CARSI_LOCAL_BROWSER_TEST') == '1', 'local Chrome fixture opt-in')
class OxfordNativeTests(OxfordGuardTests):
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
        super().setUp()
        import pymupdf
        self.context = self.browser.new_context(service_workers='block')
        self.addCleanup(self.context.close)
        self.requests = []
        self.downloads = []
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((40, 50), 'Synthetic Oxford article\nDOI: ' + DOI)
            self.pdf = document.tobytes() + b'\n%' + b'x' * 6000
        self.html = ''
        self.redirect_pdf = False
        self.redirect_cdn = False
        def intercept(route):
            url = route.request.url
            self.requests.append(url)
            if url == PDF:
                if self.redirect_cdn:
                    route.fulfill(status=302, headers={'location': CDN})
                elif self.redirect_pdf:
                    route.fulfill(status=302, headers={'location': ANNUAL})
                else:
                    route.fulfill(status=200, content_type='application/pdf', body=self.pdf)
            elif url == CDN:
                route.fulfill(status=200, content_type='application/pdf', body=self.pdf)
            elif url == ANNUAL:
                route.fulfill(status=200, content_type='application/pdf', body=self.pdf)
            else:
                route.fulfill(status=200, content_type='text/html', body=self.html)
        self.context.route('**/*', intercept)
        self.page = self.context.new_page()
        self.page.on('download', lambda event: self.downloads.append(event))
        self.result = self.batch.DownloadResult(doi=DOI, status='failed', article_url=ARTICLE)
        self.d._fetch_page_state_pdf = Mock(return_value=(None, '', None))
        self.d._fetch_pdf_url_with_browser_state = Mock(side_effect=AssertionError('HTTP fallback forbidden'))
        self.d._save_publisher_session = Mock(side_effect=AssertionError('credential I/O forbidden'))

    def test_institution_link_clicks_exact_control_instead_of_header_logo(self):
        self.html = '''<header><a href="/">Oxford Academic</a>
          <a href="/institution-chooser" class="js-shibboleth-action at-institutional-sign-in">
          <span>Sign in through your institution</span></a></header>'''
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.page.wait_for_url('https://academic.oup.com/institution-chooser')
        self.assertNotIn('https://academic.oup.com/', self.requests)

    def test_credential_form_in_embedded_identity_provider_is_left_for_user(self):
        self.html = '<iframe src="https://identity.example/login"></iframe>'
        self.page.goto(ARTICLE)
        self.page.frames[-1].evaluate("() => {document.body.innerHTML='<input type=password><button>Continue</button>';}")
        self.assertEqual(self.d.adapter.login_state(self.page), 'human_login')

    def test_visible_embedded_verification_is_not_a_login_click_target(self):
        self.html = '<iframe src="https://challenges.cloudflare.com/fixture"></iframe>'
        self.page.goto(ARTICLE)
        self.assertEqual(self.d.adapter.login_state(self.page), 'verification')

    def test_visible_embedded_password_error_is_terminal_without_submission(self):
        self.html = '<input autocomplete=username><iframe src="https://identity.example/login"></iframe>'
        self.page.goto(ARTICLE)
        frame = self.page.frames[-1]
        frame.evaluate("() => {document.body.innerHTML='<input type=password><p>Incorrect username or password</p><button>Continue</button>'}")
        self.assertEqual(self.d.adapter.login_state(self.page), 'login_credentials_rejected')
        self.assertEqual(self.page.url, ARTICLE)
        self.assertNotIn('https://identity.example/submit', self.requests)

    def test_hidden_old_password_error_does_not_end_embedded_human_login(self):
        self.html = '<iframe src="https://identity.example/login"></iframe>'
        self.page.goto(ARTICLE)
        self.page.frames[-1].evaluate("() => {document.body.innerHTML='<input type=password><p hidden>Incorrect password</p><button>Continue</button>'}")
        self.assertEqual(self.d.adapter.login_state(self.page), 'human_login')

    def test_blank_article_url_is_not_ready(self):
        self.html = '<body></body>'
        self.page.goto(ARTICLE)
        self.assertEqual(self.d.adapter.login_state(self.page), 'publisher_login')

    def test_visible_credential_error_is_terminal_without_form_submission(self):
        self.html = '<input type=password><p>Incorrect username or password</p><button>Continue</button>'
        self.page.goto(ARTICLE)
        self.assertEqual(self.d.adapter.login_state(self.page), 'login_credentials_rejected')

    def test_active_login_click_uses_exact_institution_control(self):
        import time
        self.html = '<header><a href="/">Oxford Academic</a><a class="js-shibboleth-action at-institutional-sign-in" href="/chooser">Sign in through your institution</a></header>'
        self.page.goto(ARTICLE)
        self.assertTrue(self.d.adapter.advance_login(self.page, self.result, time.monotonic()+10))
        self.page.wait_for_url('https://academic.oup.com/chooser')
        self.assertNotIn('https://academic.oup.com/', self.requests)

    def test_homepage_does_not_complete_login_and_returns_to_record_once(self):
        self.html = '<h1>Oxford Academic</h1><a href="' + ANNUAL + '">Annual Report PDF</a>'
        self.page.goto('https://academic.oup.com/')
        self.assertFalse(self.d._article_access_available(self.page))
        self.assertTrue(self.d._return_to_record_article_if_needed(self.page, self.result, DOI))
        self.assertEqual(self.page.url, ARTICLE)
        self.page.goto('https://academic.oup.com/')
        self.assertFalse(self.d._return_to_record_article_if_needed(self.page, self.result, DOI))

    def test_main_pdf_captured_without_annual_report_or_extra_download(self):
        self.html = '<a href="' + ANNUAL + '">Annual Report PDF</a><a download href="' + PDF + '">PDF</a>'
        self.page.goto(ARTICLE)
        self.d._pdf_candidates = Mock(return_value=[])
        body, url, block = self.d._capture_pdf(self.page, DOI, self.result)
        self.assertEqual(body, self.pdf)
        self.assertEqual(url, PDF)
        self.assertIsNone(block)
        self.assertNotIn(ANNUAL, self.requests)
        self.assertEqual(self.downloads, [])
        self.d._fetch_page_state_pdf.assert_not_called()

    def test_current_pdf_redirect_to_silverchair_is_captured_without_native_download(self):
        self.html = '<a href="' + PDF + '">PDF</a>'
        self.page.goto(ARTICLE)
        self.redirect_cdn = True
        observed = []
        original = self.d._response_matches_article
        def check(response, doi):
            ok = original(response, doi)
            observed.append((response.url, self.d._response_urls(response), ok))
            return ok
        self.d._response_matches_article = check
        self.d._pdf_candidates = Mock(return_value=[])
        body, url, _ = self.d._capture_pdf(self.page, DOI, self.result)
        self.assertEqual(body, self.pdf, repr((observed,self.result.events)))
        self.assertEqual(url, CDN)
        self.assertEqual(self.downloads, [])
        self.d._fetch_page_state_pdf.assert_not_called()

    def test_main_endpoint_redirect_to_annual_pdf_is_not_accepted(self):
        self.html = '<a href="' + PDF + '">PDF</a>'
        self.page.goto(ARTICLE)
        self.redirect_pdf = True
        self.d._pdf_candidates = Mock(return_value=[])
        body, _, _ = self.d._capture_pdf(self.page, DOI, self.result)
        self.assertIsNone(body)
        self.assertFalse(any(e['state'] == 'browser_pdf_response_captured' for e in self.result.events))


if __name__ == '__main__':
    unittest.main()

"""Oxford homepage/annual-report regression; synthetic fixtures only."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fixture_network import network_is_the_fixture

DOI = '10.1093/jnci/fixture123'
ARTICLE = 'https://academic.oup.com/jnci/advance-article/doi/' + DOI + '/12345'
PDF = 'https://academic.oup.com/jnci/advance-article-pdf/doi/' + DOI + '/98765/fixture123.pdf'
CDN = 'https://watermark02.silverchair.com/fixture123.pdf?fixture-signature=local'
ANNUAL = 'https://fdslive.oup.com/www.oup.com/Group_comms/pdf/annualreport/Annual_Report_2025-26.pdf'


class OxfordViewerTests(unittest.TestCase):
    def test_the_viewer_is_read_only_at_this_articles_pdf_url(self):
        # The watermarked CDN URL names no article: its response is waited for.
        from paper_search_school.engine.batch import PublisherBatchDownloader
        from paper_search_school.publishers.profiles import infer_publisher_profile
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

    def test_its_own_opening_keeps_the_site_the_article_opened_on(self):
        # As the engine's flow does (_note_article_host): a personal sign-in there is no school login page (2026-11-24).
        from unittest.mock import patch
        page, result = Mock(), SimpleNamespace(article_url='https://doi.org/' + DOI, events=[], reason='')
        for name in ('_wait_past_redirect_page', '_raise_on_publisher_content_error', '_dismiss_cookie_banners',
                     '_note_article_host'):
            setattr(self.d, name, Mock())
        self.d._wait_for_challenge = Mock(return_value=True)
        self.d._institution_pdf_entitlement_missing = Mock(return_value=False)
        self.d._pdf_first_unless_signed_out = Mock(return_value=True)
        with patch('paper_search_school.adapters.oup.open_page'):
            self.assertTrue(self.d.adapter.ensure_login(page, result))
        self.d._note_article_host.assert_called_once_with(page)

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
            'https://academic.oup.com/jnci/article-pdf/138/1/2/98765/other123.pdf', DOI))

    def test_a_journal_whose_path_is_not_its_doi_code_has_its_pdf_tried(self):
        # Sexual Medicine Open Access: 10.1093/sexmed/… at /smoa/, an open article whose PDF step tried
        # nothing ("candidates: none", Windows 2026-11-23).
        doi = '10.1093/sexmed/qfaf103'
        article = 'https://academic.oup.com/smoa/article/13/6/qfaf103/8382596'
        pdf = 'https://academic.oup.com/smoa/article-pdf/13/6/qfaf103/8382596/qfaf103.pdf'
        self.assertTrue(self.d._article_pdf_url_matches(pdf, doi))
        self.assertFalse(self.d._article_pdf_url_matches(pdf.replace('qfaf103', 'qfaf095'), doi))  # another article's
        page = Mock(url=article)
        page.evaluate.return_value = {"dois": [doi], "pdfs": [pdf], "links": [pdf, ANNUAL]}
        self.assertEqual(self.d._pdf_candidates(page, doi), [pdf])
        response = SimpleNamespace(url='https://watermark02.silverchair.com/qfaf103.pdf?fixture-signature=local',
                                   status=200, headers={}, history=[SimpleNamespace(url=pdf, headers={})])
        self.assertTrue(self.d._response_matches_article(response, doi))

    def test_a_supplement_issue_is_not_supplementary_material(self):
        doi = '10.1093/eurheartjsupp/suag119.023'
        page = 'https://academic.oup.com/eurheartjsupp/article/28/Supplement_11/suag119.023/8863774'
        pdf = 'https://academic.oup.com/eurheartjsupp/article-pdf/28/Supplement_11/suag119.023/71595005/suag119.023.pdf'
        self.assertTrue(self.d._is_success_article_url(page))
        self.assertFalse(self.d._is_supplementary_url(pdf))
        self.assertTrue(self.d._article_pdf_url_matches(pdf, doi))
        self.assertTrue(self.d._is_supplementary_url(
            'https://oup.silverchair-cdn.com/oup/backfile/Content_public/Journal/eurheartjsupp/28/Supplement_11/suag119.023/1/suag119.023_supplement.docx'))

    def test_a_journal_hosted_for_another_publisher_is_matched_by_its_own_doi(self):
        # Karger's Neuroepidemiology on Oxford Academic: its DOI is Karger's (2026-11-14).
        doi = '10.1159/ned/adwag066'
        article = 'https://academic.oup.com/ned/advance-article/doi/10.1159/ned/adwag066/9022322'
        pdf = 'https://academic.oup.com/ned/advance-article-pdf/doi/10.1159/ned/adwag066/9022322/adwag066.pdf'
        self.assertTrue(self.d._article_pdf_url_matches(pdf, doi))
        self.assertFalse(self.d._article_pdf_url_matches(pdf, '10.1159/ned/adwag067'))  # another article's
        response = SimpleNamespace(url='https://watermark02.silverchair.com/adwag066.pdf?fixture-signature=local',
                                   status=200, headers={}, history=[SimpleNamespace(url=pdf, headers={})])
        self.assertTrue(self.d._response_matches_article(response, doi))
        from paper_search_school.engine.router import _append_oxford_candidates
        urls = []
        _append_oxford_candidates(urls, doi, article)
        self.assertEqual(urls, [pdf])

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


@unittest.skipUnless(os.environ.get('SCHOOL_LOCAL_BROWSER_TEST') == '1', 'local Chrome fixture opt-in')
class OxfordKeptDoiTests(unittest.TestCase):
    """Journals Oxford Academic took over, their DOIs kept (Windows, 2026-11-22: JBMR and BJS, from Wiley, and Modern
    Rheumatology, from Taylor & Francis, had no PDF tried): the article page's citation PDF is their PDF."""
    KEPT = '10.1080/14397595.2020.1868688'
    PAGE = 'https://academic.oup.com/mr/article/31/6/1215/6398418'
    OWN = 'https://academic.oup.com/mr/article-pdf/31/6/1215/40675914/mr1215.pdf'
    COPY = 'https://watermark02.silverchair.com/mr1215.pdf?fixture-signature=local'

    def setUp(self):
        import test_wiley_capture as fixtures
        harness = fixtures.WileyCaptureTests(methodName='runTest')
        self.addCleanup(harness.doCleanups)
        harness.setUp()
        self.batch = harness.batch
        self.d = self.batch.PublisherBatchDownloader({}, profile=harness.profiles.OXFORD_ACADEMIC_PROFILE)
        self.meta = {'dois': [self.KEPT], 'pdfs': [self.OWN], 'links': []}
        self.page = Mock(url=self.PAGE)
        self.page.evaluate.side_effect = lambda *args: self.meta
        self.d._track_article_for_adapter(self.page, self.KEPT)
        self.d._capture_doi = self.KEPT

    def test_a_kept_doi_takes_the_rules_for_it_and_oxfords_own_keep_theirs(self):
        from paper_search_school.adapters import adapter_class
        from paper_search_school.adapters.oup import OUPAdapter, OUPKeptDoiAdapter
        for doi in ('10.1002/jbmr.4720', '10.1002/bjs.11621', self.KEPT):
            with self.subTest(doi=doi):
                self.assertIs(adapter_class('oxford academic', doi=doi), OUPKeptDoiAdapter)
        for doi in (DOI, '10.1093/rheumatology/keae522', '10.1159/ned/adwag066'):
            with self.subTest(doi=doi):
                self.assertIs(adapter_class('oxford academic', doi=doi), OUPAdapter)
        self.assertEqual(type(self.d.adapter).__name__, 'OUPKeptDoiAdapter')  # the fixture's own copy of the package

    def test_the_citation_pdf_is_the_candidate_and_its_copy_on_the_cdn_is_accepted(self):
        self.assertEqual(self.d._pdf_candidates(self.page, self.KEPT), [self.OWN])
        self.meta = {'dois': ['10.1080/14397595.2020.1999999'], 'pdfs': [self.OWN], 'links': []}  # another article's page
        self.assertEqual(self.d._pdf_candidates(self.page, self.KEPT), [])
        bound = frozenset({self.OWN})
        response = SimpleNamespace(url=self.OWN, status=200, headers={}, history=[])
        self.assertTrue(self.d._response_matches_article(response, self.KEPT, article_pdf_urls=bound))
        copy = SimpleNamespace(url=self.COPY, status=200, headers={}, history=[SimpleNamespace(url=self.OWN, headers={})])
        self.assertTrue(self.d._response_matches_article(copy, self.KEPT, article_pdf_urls=bound))
        other = self.OWN.replace('40675914/mr1215', '40675999/mr1299')
        for url, history in ((other, []), (self.COPY.replace('mr1215', 'mr1299'), [SimpleNamespace(url=other, headers={})])):
            with self.subTest(url=url):
                self.assertFalse(self.d._response_matches_article(
                    SimpleNamespace(url=url, status=200, headers={}, history=history), self.KEPT, article_pdf_urls=bound))


class OxfordNativeTests(OxfordGuardTests):
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
        super().setUp()
        import pymupdf
        network_is_the_fixture(self)
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

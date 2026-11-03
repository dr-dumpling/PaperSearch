"""Local Chrome regression for observed LWW/Ovid controls; all traffic intercepted."""
import os
import unittest
from unittest.mock import Mock

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import PublisherProfile

ARTICLE = 'https://www.ovid.com/jnls/fixture/abstract/10.5435/fixture~title'
FULLTEXT = ARTICLE.replace('/abstract/', '/fulltext/')
LOGIN = 'https://login.wolterskluwer.com/institution-fixture'


@unittest.skipUnless(os.environ.get('CARSI_LOCAL_BROWSER_TEST') == '1', 'local Chrome fixture opt-in')
class OvidAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel='chrome', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers='block')
        self.addCleanup(self.context.close)
        self.requests = []
        self.pdfs = {}
        self.html = '''<html><head><title>Fixture article</title></head><body>
          <button class="omni-article-tool__check-access"
            onclick="document.querySelector('#access').hidden=false">Check Access</button>
          <div id="access" hidden>
            <a class="omni-sso-url" href="https://login.wolterskluwer.com/individual-fixture">Individual Subscribers</a>
            <a class="omni-sso-url" href="%s">Institutional Users<br>Access through Ovid</a>
            <a class="omni-sso-url" href="https://www.ovid.com/auth/signin">AAOS MEMBERS</a>
          </div></body></html>''' % LOGIN
        def respond(route):
            self.requests.append(route.request.url)
            if route.request.url in {ARTICLE, FULLTEXT}:
                route.fulfill(status=200, content_type='text/html', body=self.html)
            elif route.request.url == LOGIN:
                route.fulfill(status=200, content_type='text/html', body='<title>Institution login</title>')
            elif route.request.url in self.pdfs:
                route.fulfill(status=200, content_type='application/pdf', body=self.pdfs[route.request.url])
            else:
                route.abort()
        self.context.route('**/*', respond)
        self.page = self.context.new_page()
        profile = PublisherProfile(name='LWW', article_url_template='https://doi.org/{doi}',
            pdf_url_templates=(), success_url_markers=('ovid.com/jnls/', 'journals.lww.com/'),
            auth_url_markers=('/login', 'login.wolterskluwer.com'), auth_title_markers=('Institutional Login',),
            sso_text_markers=('access through ovid',), base_domains=('ovid.com', 'journals.lww.com'))
        self.downloader = PublisherBatchDownloader({}, profile=profile)

    def test_abstract_wall_opens_institutional_control_without_personal_login(self):
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._looks_logged_out(self.page))
        self.assertFalse(self.downloader._article_access_available(self.page))
        result = DownloadResult(doi='10.5435/fixture', status='failed')
        self.assertTrue(self.downloader._click_sso_entry(self.page, result))
        self.page.wait_for_url(LOGIN)
        self.assertTrue(self.downloader._looks_logged_out(self.page))
        self.assertEqual(self.requests, [ARTICLE, LOGIN])
        self.assertEqual(result.events[-1]['detail'], 'ovid-institution-control')

    def test_fulltext_with_pdf_does_not_reenter_login(self):
        self.html = '<title>Fixture article</title><body>Logout <a href="/jnls/fixture/pdf/10.5435/fixture">PDF</a>Full text</body>'
        self.page.goto(FULLTEXT)
        self.assertFalse(self.downloader._looks_logged_out(self.page))
        self.assertTrue(self.downloader._article_access_available(self.page))
        self.assertFalse(self.downloader._click_sso_entry(self.page))
        self.assertEqual(self.requests, [FULLTEXT])

    def test_other_hosts_and_login_root_are_not_article_success(self):
        for url in ('https://www.ovid.com/login', 'https://www.ovid.com/',
                    'https://www.ovid.com.evil.example/jnls/fixture/fulltext/x',
                    'https://evil.example/?next=https://www.ovid.com/jnls/fixture/fulltext/x'):
            with self.subTest(url=url):
                self.assertFalse(self.downloader._is_success_article_url(url))

    def test_target_blank_main_pdf_is_captured_once_without_extra_tab_or_download(self):
        import pymupdf
        pdf_url = ARTICLE.replace('/abstract/', '/pdf/')
        wrong_url = pdf_url.replace('10.5435/fixture', '10.5435/another')
        self.html = (f'<title>Fixture article</title><body>Logout '
                     f'<a target="_blank" href="{wrong_url}">PDF from references</a>'
                     f'<a target="_blank" download href="{pdf_url}">PDF</a></body>')
        with pymupdf.open() as document:
            for _ in range(8):
                document.new_page().insert_text((50,60), 'Fixture article DOI: 10.5435/fixture\nMain text')
            data = document.tobytes() + b'\n%' + b'x' * 6000
        self.pdfs[pdf_url] = data
        self.page.goto(FULLTEXT)
        downloads = []
        self.page.on('download', lambda event: downloads.append(event))
        self.downloader._pdf_candidates = Mock(return_value=[])
        self.downloader._fetch_page_state_pdf = Mock(side_effect=AssertionError('fallback cannot hide capture failure'))
        result = DownloadResult(doi='10.5435/fixture', status='failed')
        try:
            body, url, blocked = self.downloader._capture_pdf(self.page, result.doi, result)
        except AssertionError:
            self.fail(f'Capture did not complete: {result.events!r}; requests={self.requests!r}')
        self.assertEqual((body, url, blocked), (data, pdf_url, None))
        self.assertEqual(self.requests.count(pdf_url), 1)
        self.assertNotIn(wrong_url, self.requests)
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(downloads, [])

    def test_supplement_and_other_doi_do_not_match_the_main_endpoint(self):
        doi = '10.5435/fixture'
        for url in ('https://www.ovid.com/jnls/fixture/pdf/10.5435/another~title',
                    'https://www.ovid.com/jnls/fixture/pdf/10.5435/fixture/supplement.pdf',
                    'https://links.lww.com/fixture/supplement.pdf',
                    'https://www.ovid.com.evil.example/jnls/fixture/pdf/10.5435/fixture'):
            with self.subTest(url=url):
                self.assertFalse(self.downloader._article_pdf_url_matches(url, doi))


if __name__ == '__main__':
    unittest.main()

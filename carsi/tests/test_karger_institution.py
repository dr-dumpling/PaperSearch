"""Karger federation gateway fixtures; all browser requests are intercepted."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import PublisherProfile, RSC_PROFILE

DOI = '10.1159/000000001'
ARTICLE = 'https://karger.com/crd/article-abstract/146/6/772/123/Offline-article'
GATEWAY = 'https://karger.com/ExternalAuthentication/OpenAthensKeystoneLogin'
PDF = 'https://karger.com/crd/article-pdf/146/6/772/123/000000001.pdf'
PROFILE = PublisherProfile(name='Karger', article_url_template='https://doi.org/{doi}',
    pdf_url_templates=(), base_domains=('karger.com',), doi_prefixes=('10.1159',),
    success_url_markers=('karger.com/',), auth_url_markers=('/login', '/sso/'),
    auth_title_markers=('Institutional Login',), sso_text_markers=('openathens',))


@unittest.skipUnless(os.environ.get('CARSI_LOCAL_BROWSER_TEST') == '1', 'local browser fixture opt-in')
class KargerInstitutionTests(unittest.TestCase):
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
        self.responses = {}
        self.html = f'<title>Offline article</title><meta name="citation_doi" content="{DOI}">'
        def respond(route):
            self.requests.append(route.request.url)
            if route.request.url in self.responses:
                route.fulfill(**self.responses[route.request.url])
                return
            route.fulfill(status=200, content_type='text/html', body=self.html)
        self.context.route('**/*', respond)
        self.page = self.context.new_page()
        self.downloader = PublisherBatchDownloader({'publisher_institution_federation': 'carsi'},
            profile=PROFILE, institution_query='Synthetic University A')
        self.result = DownloadResult(doi=DOI, status='failed', article_url=ARTICLE)

    def test_login_menu_uses_observed_federation_gateway(self):
        self.html += f'''<button onclick="document.querySelector('#menu').hidden=false">LOGIN Open Menu</button>
          <div id="menu" hidden><a href="/institutional-login">Access via username and password</a>
          <a href="/ExternalAuthentication/OIDCLogin">Personal sign in</a>
          <a href="{GATEWAY}">Access via Shibboleth and OpenAthens</a></div>'''
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._click_sso_entry(self.page, self.result))
        self.page.wait_for_url(GATEWAY)
        self.assertEqual(self.requests, [ARTICLE, GATEWAY])

    def test_open_menu_is_not_toggled_closed(self):
        self.html += f'''<button onclick="document.querySelector('#menu').hidden=true">LOGIN</button>
          <div id="menu"><a href="{GATEWAY}">Access via Shibboleth and OpenAthens</a></div>'''
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._click_sso_entry(self.page, self.result))
        self.page.wait_for_url(GATEWAY)
        self.assertFalse(any(e['state'] == 'publisher_login_menu_opened' for e in self.result.events))

    def test_personal_password_and_forged_gateways_are_rejected(self):
        for href in ('https://karger.com.evil.example/ExternalAuthentication/OpenAthensKeystoneLogin',
                     'https://karger.com/institutional-login',
                     'https://karger.com/ExternalAuthentication/OIDCLogin'):
            self.html = f'<a href="{href}">Institutional login</a>'
            self.page.goto(ARTICLE)
            self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
            self.assertEqual(self.requests[-1], ARTICLE)

    def test_user_form_input_is_preserved(self):
        self.html = f'<input name="user"><input type="password"><a href="{GATEWAY}">Institution</a>'
        self.page.goto(ARTICLE)
        self.page.locator('input[name=user]').fill('User input')
        self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.locator('input[name=user]').input_value(), 'User input')
        self.downloader._select_institution(self.page, self.result)
        self.assertEqual(self.page.locator('input[name=user]').input_value(), 'User input')
        self.assertEqual(self.requests, [ARTICLE])

    def test_wayfinder_uses_only_the_configured_remembered_school(self):
        self.html = '''<button onclick="location.href='/configured'">Access through Synthetic University A</button>
          <button onclick="location.href='/other'">Access through Synthetic University B</button>'''
        chooser = 'https://wayfinder.openathens.net/fixture'
        self.page.goto(chooser)
        self.assertTrue(self.downloader._select_institution(self.page, self.result))
        self.page.wait_for_url('https://wayfinder.openathens.net/configured')
        self.assertNotIn('https://wayfinder.openathens.net/other', self.requests)
        self.assertIn('auto_remembered_entry', [e['state'] for e in self.result.events])

    def test_wayfinder_without_configured_school_opens_search_once_and_never_chooses(self):
        self.downloader.institution_query = ''
        self.html='''<button onclick="location.href='/wrong'">Access through Synthetic University A</button>
          <button onclick="document.querySelector('#panel').innerHTML='<input placeholder=Institution><button>Continue</button>'">Find another institution...</button><div id="panel"></div>'''
        chooser='https://wayfinder.openathens.net/fixture'
        self.page.goto(chooser)
        self.downloader._select_institution(self.page,self.result)
        field=self.page.get_by_placeholder('Institution')
        self.assertEqual(field.input_value(),'')
        field.fill('User-selected institution')
        self.downloader._select_institution(self.page,self.result)
        self.assertEqual(field.input_value(),'User-selected institution')
        self.assertEqual(self.requests,[chooser])
        self.assertEqual(sum(e['state']=='karger_institution_chooser_opened' for e in self.result.events),1)

    def test_school_navigation_during_observation_continues_same_login_request(self):
        from playwright.sync_api import Error
        # No configured school: the user picks one. (A configured school missing
        # from the list ends the login at once, 2026-11-01.)
        self.downloader.institution_query = ''
        self.downloader.login_timeout_sec = 3
        self.page.set_default_timeout(3_000)
        chooser = 'https://wayfinder.openathens.net/fixture'
        school = 'https://synthetic-school.example/login'
        article = ARTICLE.replace('article-abstract', 'article')
        self.html = f'<a href="{GATEWAY}">Access via Shibboleth and OpenAthens</a>'
        self.responses[GATEWAY] = {'status':200, 'content_type':'text/html',
            'body':f'<script>location.replace("{chooser}")</script>'}
        self.responses[chooser] = {'status':200, 'content_type':'text/html',
            'body':f'<input placeholder="Institution"><a href="{school}">Synthetic University B</a>'}
        self.responses[school] = {'status':200, 'content_type':'text/html',
            'body':'<input type="password"><p>School login</p>'}
        self.responses[article] = {'status':200, 'content_type':'text/html',
            'body':f'<title>Article</title><meta name="citation_doi" content="{DOI}"><h1>Full article</h1>'}
        self.page.goto(ARTICLE)
        evaluate = self.page.evaluate
        interrupted = []
        def observe(script, *args, **kwargs):
            if self.page.url == chooser and "querySelectorAll('input,textarea')" in script:
                self.page.get_by_role('link', name='Synthetic University B', exact=True).click()
                self.page.wait_for_url(school)
                interrupted.append(True)
                raise Error('Page.evaluate: Execution context was destroyed, most likely because of a navigation.')
            return evaluate(script, *args, **kwargs)
        def user_completes_login(seconds):
            # The login wait checks the page every second; the user signs in at the school meanwhile.
            if self.page.url == GATEWAY:
                self.page.wait_for_url(chooser)
            if self.page.url == school:
                self.page.goto(article)
        self.downloader._item_result = self.result  # as fetch_one sets it
        with patch.object(self.page, 'evaluate', side_effect=observe), \
                patch('paper_search_carsi.engine.batch.time.sleep', side_effect=user_completes_login):
            self.assertTrue(self.downloader._complete_login_from_current_page(self.page, self.result))
        self.assertEqual(interrupted, [True])
        self.assertFalse(self.page.is_closed())
        self.assertEqual(self.page.url, article)
        self.assertEqual(self.requests, [ARTICLE, GATEWAY, chooser, school, article])
        # The engine's read of the typed fields takes the navigation as the user's page
        # (review 2026-11-02), before the adapter's own handling saw it.
        self.assertEqual(sum(e['state']=='page_read_interrupted' for e in self.result.events), 1)

    def test_wayfinder_context_loss_preserves_page_and_next_user_input(self):
        from playwright.sync_api import Error
        chooser = 'https://wayfinder.openathens.net/fixture'
        self.html = '<input placeholder="Institution">'
        self.page.goto(chooser)
        with patch.object(self.page, 'evaluate', side_effect=Error('Cannot find context with specified id')):
            self.assertFalse(self.downloader._select_institution(self.page, self.result))
        field = self.page.get_by_placeholder('Institution')
        field.fill('User-selected school')
        self.assertFalse(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(field.input_value(), 'User-selected school')
        self.assertFalse(self.page.is_closed())
        self.assertEqual(self.requests, [chooser])

    def test_wayfinder_unrelated_errors_and_closed_pages_still_fail(self):
        from playwright.sync_api import Error
        self.page.goto('https://wayfinder.openathens.net/fixture')
        for error in (RuntimeError('Execution context was destroyed'),
                      Error('Target page, context or browser has been closed'),
                      Error('Unexpected protocol failure')):
            with self.subTest(error=str(error)), patch.object(self.page, 'evaluate', side_effect=error):
                with self.assertRaises(type(error)):
                    self.downloader._select_institution(self.page, self.result)
        self.assertFalse(any(e['state']=='login_navigation_interrupted' for e in self.result.events))

    def test_abstract_requires_access_and_login_is_not_article(self):
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._looks_logged_out(self.page))
        self.assertFalse(self.downloader._article_access_available(self.page))
        for url in (GATEWAY, 'https://karger.com/institutional-login',
                    'https://karger.com/404', ARTICLE.replace('karger.com', 'karger.com.evil.example')):
            self.assertFalse(self.downloader._is_success_article_url(url))
        self.assertTrue(self.downloader._is_success_article_url(ARTICLE.replace('article-abstract', 'article')))

    def test_only_exact_doi_main_endpoint_is_discovered(self):
        wrong = PDF.replace('000000001.pdf', '000000002.pdf')
        supplement = PDF.replace('article-pdf', 'article-supplement')
        self.html += f'<a href="{supplement}">Supplementary PDF</a><a href="{wrong}">PDF</a><meta name="citation_pdf_url" content="{PDF}">'
        self.page.goto(ARTICLE)
        self.assertEqual(self.downloader._pdf_candidates(self.page, DOI), [PDF])
        for url in (wrong, supplement, PDF.replace('karger.com', 'karger.com.evil.example'),
                    PDF.replace('https:', 'http:'), PDF.replace('000000001.pdf', '000000001_suppl.pdf')):
            self.assertFalse(self.downloader._article_pdf_url_matches(url, DOI))

    def test_redirect_or_disposition_cannot_turn_an_attachment_into_main(self):
        response = SimpleNamespace(url=PDF, status=200, headers={}, history=[])
        options={'article_pdf_urls':frozenset({PDF})}
        self.assertTrue(self.downloader._response_matches_article(response, DOI, **options))
        response.history = [SimpleNamespace(url=PDF, headers={'Content-Disposition':'attachment; filename=supplementary.pdf'})]
        self.assertFalse(self.downloader._response_matches_article(response, DOI, **options))
        response.history = [SimpleNamespace(url=PDF, headers={})]
        response.url = 'https://unobserved.example/main.pdf'
        self.assertFalse(self.downloader._response_matches_article(response, DOI, **options))

    def test_native_main_capture_saves_bytes_without_extra_download_or_http(self):
        import pymupdf
        cases = ((PROFILE, DOI, ARTICLE, PDF), (RSC_PROFILE,'10.1039/offline2026',
            'https://pubs.rsc.org/bm/article/9/4/1291/123/Offline',
            'https://pubs.rsc.org/bm/article-pdf/9/4/1291/456/offline2026.pdf'))
        for profile, doi, article, pdf in cases:
            with self.subTest(publisher=profile.name):
                with pymupdf.open() as document:
                    document.new_page().insert_text((40,50), 'Synthetic main article\nDOI: ' + doi)
                    body = document.tobytes() + b'\n%' + b'x'*6000
                self.responses[pdf] = {'status':200, 'content_type':'application/pdf', 'body':body}
                self.html = f'<meta name="citation_doi" content="{doi}"><meta name="citation_pdf_url" content="{pdf}"><a download href="{pdf}">PDF</a>'
                self.page.goto(article)
                downloads=[]
                self.page.on('download', lambda download: downloads.append(download))
                d=PublisherBatchDownloader({},profile=profile)
                d._fetch_page_state_pdf = Mock(return_value=(None,'',None))
                result=DownloadResult(doi=doi,status='failed',article_url=article)
                captured, url, blocked = d._capture_pdf(self.page,doi,result)
                self.assertEqual(captured,body)
                self.assertEqual(url,pdf)
                self.assertIsNone(blocked)
                self.assertEqual(downloads,[])
                self.assertEqual(self.requests.count(pdf),1)
                d._fetch_page_state_pdf.assert_not_called()

    def test_conflicting_or_wrong_doi_metadata_never_fetches_pdf(self):
        for metadata in (f'<meta name="citation_doi" content="{DOI}"><meta name="citation_doi" content="10.1159/other">',
                         '<meta name="citation_doi" content="10.1159/other">'):
            self.html = metadata + f'<meta name="citation_pdf_url" content="{PDF}"><a href="{PDF}">PDF</a>'
            self.page.goto(ARTICLE)
            self.assertEqual(self.downloader._pdf_candidates(self.page,DOI),[])
            self.assertIsNone(self.downloader._capture_pdf(self.page,DOI,self.result)[0])
            self.assertNotIn(PDF,self.requests)

    def test_without_metadata_the_link_naming_the_article_is_tried(self):
        """Karger 2026-11-02: no citation PDF was read; the page's link naming the
        DOI is tried instead of giving up (its first pages still decide)."""
        import pymupdf
        with pymupdf.open() as document:
            document.new_page().insert_text((40, 50), 'Synthetic main article\nDOI: ' + DOI)
            body = document.tobytes() + b'\n%' + b'x' * 6000
        self.responses[PDF] = {'status': 200, 'content_type': 'application/pdf', 'body': body}
        other = PDF.replace('000000001.pdf', '000000002.pdf')
        self.html = f'<title>Offline article</title><a href="{other}">PDF</a><a target="_blank" class="al-link pdf" href="{PDF}">PDF</a>'
        self.page.goto(ARTICLE.replace('article-abstract', 'article'))
        self.downloader._fetch_page_state_pdf = Mock(return_value=(None, '', None))
        captured, url, _ = self.downloader._capture_pdf(self.page, DOI, self.result)
        self.assertEqual((captured, url), (body, PDF))
        self.assertNotIn(other, self.requests)
        detail = next(e['detail'] for e in self.result.events if e['state'] == 'publisher_pdf_link_unverified')
        self.assertIn('citation_doi: none', detail)
        self.assertIn('1 link(s) naming the article', detail)

    def test_rejected_native_attachment_has_no_download_or_second_request(self):
        import pymupdf
        with pymupdf.open() as document:
            document.new_page().insert_text((40,50),'Disclosure form\nDOI: '+DOI)
            body=document.tobytes()+b'\n%'+b'x'*6000
        self.responses[PDF]={'status':200,'content_type':'application/pdf','body':body,
                             'headers':{'Content-Disposition':'attachment; filename=supplementary.pdf'}}
        self.html+=f'<meta name="citation_pdf_url" content="{PDF}"><a download href="{PDF}">PDF</a>'
        self.page.goto(ARTICLE)
        downloads=[]
        self.page.on('download',lambda download: downloads.append(download))
        self.downloader._fetch_pdf_url=Mock(side_effect=AssertionError('rejected PDF must not be fetched again'))
        captured,_,_=self.downloader._capture_pdf(self.page,DOI,self.result)
        self.assertIsNone(captured)
        self.assertEqual(downloads,[])
        self.assertEqual(self.requests.count(PDF),1)
        self.downloader._fetch_pdf_url.assert_not_called()

    def test_unknown_redirect_is_rejected_without_download_or_http_replay(self):
        import pymupdf
        with pymupdf.open() as document:
            document.new_page().insert_text((40,50),'Synthetic main\nDOI: '+DOI)
            body=document.tobytes()+b'\n%'+b'x'*6000
        for name in ['main.pdf','supplementary.pdf']:
            with self.subTest(destination=name):
                other='https://unobserved.example/'+name
                self.responses[PDF]={'status':302,'headers':{'Location':other},'body':''}
                self.responses[other]={'status':200,'content_type':'application/pdf','body':body}
                self.html=f'<meta name="citation_doi" content="{DOI}"><meta name="citation_pdf_url" content="{PDF}"><a href="{PDF}">PDF</a>'
                self.page.goto(ARTICLE)
                self.requests.clear()
                downloads=[]
                self.page.on('download',lambda download:downloads.append(download))
                self.downloader._fetch_pdf_url=Mock(side_effect=AssertionError('unverified redirect must not replay'))
                captured,_,_=self.downloader._capture_pdf(self.page,DOI,self.result)
                self.assertIsNone(captured)
                self.assertEqual(downloads,[])
                self.assertEqual(self.requests.count(PDF),1)
                self.assertEqual(self.requests.count(other),1)
                self.downloader._fetch_pdf_url.assert_not_called()

    def test_supplement_is_never_clicked_or_requested(self):
        supplement=PDF.replace('article-pdf','article-supplement')
        self.html += f'<a href="{supplement}">Supplementary information (PDF)</a>'
        self.page.goto(ARTICLE)
        self.assertFalse(self.downloader._click_pdf_entry(self.page,self.result,doi=DOI))
        self.assertEqual(self.downloader._pdf_candidates(self.page,DOI),[])
        self.assertEqual(self.requests,[ARTICLE])



class KargerArticlePageTests(unittest.TestCase):
    def test_doi_article_pages_are_article_pages(self):
        """Karger's DOI form (Dermatology, 2026-11-02) is an article page too: it was
        not, and the PDF step found no citation PDF on it after the login."""
        d = PublisherBatchDownloader({}, profile=PROFILE)
        for url in ('https://karger.com/drm/article/doi/10.1159/drm/ackag031/957101/Maternal-Diabetes',
                    'https://karger.com/drm/article-abstract/doi/10.1159/drm/ackag031/957101/M?redirectedFrom=fulltext',
                    'https://karger.com/crd/article-abstract/146/6/772/123/Offline-article'):
            self.assertTrue(d._is_success_article_url(url), url)
        for url in ('https://karger.com/drm/article-pdf/doi/10.1159/drm/ackag031/4596715/000554965.pdf',
                    'https://karger.com/drm/issue/doi/10.1159/x/5/'):
            self.assertFalse(d._is_success_article_url(url), url)

    def test_citation_metadata_is_awaited_only_when_missing(self):
        d = PublisherBatchDownloader({}, profile=PROFILE)
        result = DownloadResult(doi=DOI, status='failed')
        page = Mock()
        page.evaluate.return_value = True
        d._await_citation_metadata(page, result)
        page.wait_for_load_state.assert_not_called()
        self.assertEqual(result.events, [])
        page.evaluate.side_effect = [False, False, True]
        d._await_citation_metadata(page, result)
        page.wait_for_load_state.assert_called_once_with('load', timeout=10_000)
        self.assertEqual(result.events[-1]['state'], 'citation_metadata_wait')
        self.assertIn('ended: citation_doi present', result.events[-1]['detail'])


if __name__ == '__main__':
    unittest.main()

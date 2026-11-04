"""RSC Silverchair entry regression; all browser requests intercepted."""
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import RSC_PROFILE

DOI = '10.1039/offline2026'
ARTICLE = 'https://pubs.rsc.org/bm/article-abstract/9/4/1291/123/Offline-article'
CHOOSER = 'https://pubs.rsc.org/institutional-login'


@unittest.skipUnless(os.environ.get('CARSI_LOCAL_BROWSER_TEST') == '1', 'local browser fixture opt-in')
class RscInstitutionTests(unittest.TestCase):
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
        self.html = '<title>Offline article</title>'
        def respond(route):
            self.requests.append(route.request.url)
            # SeamlessAccess's own frame stays empty (it would hold a copy of the page).
            body = '' if 'seamlessaccess.org' in route.request.url else self.html
            route.fulfill(status=200, content_type='text/html', body=body)
        self.context.route('**/*', respond)
        self.page = self.context.new_page()
        self.downloader = PublisherBatchDownloader({'publisher_institution_federation': 'carsi'},
            profile=RSC_PROFILE, institution_query='Synthetic University A')
        self.result = DownloadResult(doi=DOI, status='failed', article_url=ARTICLE)

    def test_explicit_institution_link_avoids_personal_and_remembered_school_controls(self):
        self.html += f'''<a href="/ExternalAuthentication/OIDCLogin">Sign in or register</a>
          <button onclick="location.href='/wrong'">Access through Synthetic University A</button>
          <a href="{CHOOSER}">Sign in via your Institution</a>'''
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._click_sso_entry(self.page, self.result))
        self.page.wait_for_url(CHOOSER)
        self.assertEqual(self.requests, [ARTICLE, CHOOSER])

    def test_forged_or_personal_links_never_become_institution_entry(self):
        for href in ('https://pubs.rsc.org.evil.example/institutional-login',
                     'https://pubs.rsc.org/ExternalAuthentication/OIDCLogin'):
            self.html = f'<a href="{href}">Sign in via your Institution</a>'
            self.page.goto(ARTICLE)
            self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
            self.assertEqual(self.page.url, ARTICLE)

    def test_personal_form_input_is_preserved(self):
        self.html = f'<input name="user"><input type="password"><a href="{CHOOSER}">Institution</a>'
        self.page.goto(ARTICLE)
        self.page.locator('input[name=user]').fill('User input')
        self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.locator('input[name=user]').input_value(), 'User input')

    def test_abstract_requires_access_and_account_or_error_pages_are_not_articles(self):
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._looks_logged_out(self.page))
        self.assertFalse(self.downloader._article_access_available(self.page))
        for url in (CHOOSER, 'https://pubs.rsc.org/not-found',
                    'https://pubs.rsc.org/ExternalAuthentication/OIDCLogin',
                    ARTICLE.replace('pubs.rsc.org', 'pubs.rsc.org.evil.example')):
            self.assertFalse(self.downloader._is_success_article_url(url))
        self.assertTrue(self.downloader._is_success_article_url(ARTICLE.replace('article-abstract', 'article')))
        self.assertTrue(self.downloader._is_success_article_url('https://pubs.rsc.org/en/content/articlelanding/2021/bm/offline'))

    def test_remembered_configured_school_is_used(self):
        self.html = '''<button onclick="location.href='/configured'">Access through Synthetic University A</button>'''
        self.page.goto(CHOOSER)
        self.assertTrue(self.downloader._select_institution(self.page, self.result))
        self.page.wait_for_url('**/configured')
        self.assertIn('auto_remembered_entry', [e['state'] for e in self.result.events])

    def test_without_configured_school_change_institution_opens_once_and_never_chooses(self):
        self.downloader.institution_query = ''
        self.html = '''<button class="sa-button js-sa-federated-login" onclick="location.href='/wrong'">Access through Synthetic University A</button>
          <iframe src="https://service.seamlessaccess.org/ps/"></iframe>
          <a class="js-sa-change-institution" href="#" onclick="document.querySelector('#panel').innerHTML='<input placeholder=Institution><button>Continue</button>';return false">Add or change institution</a>
          <div id="panel"></div>'''
        self.page.goto(CHOOSER)
        self.downloader._select_institution(self.page, self.result)
        field = self.page.get_by_placeholder('Institution')
        self.assertEqual(field.input_value(), '')
        field.fill('User institution choice')
        self.downloader._select_institution(self.page, self.result)
        self.assertEqual(field.input_value(), 'User institution choice')
        self.assertEqual(self.requests, [CHOOSER, 'https://service.seamlessaccess.org/ps/'])
        self.assertEqual(sum(e['state']=='seamlessaccess_chooser_opened' for e in self.result.events), 1)

    def test_the_seamlessaccess_button_opens_the_search_once_it_is_ready(self):
        self.html = '''<button class="sa-button js-sa-federated-login" onclick="location.href='https://sso.rsc.org/WAYF'">
            <span>Access through</span> <span>your institution</span></button>'''
        self.page.goto(CHOOSER)
        self.assertFalse(self.downloader._select_institution(self.page, self.result))  # SeamlessAccess not loaded
        self.html += '<iframe src="https://service.seamlessaccess.org/ps/"></iframe>'
        self.page.goto(CHOOSER)
        self.assertTrue(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(self.page.url, 'https://sso.rsc.org/WAYF')
        self.assertEqual([e['detail'] for e in self.result.events if e['state'] == 'seamlessaccess_chooser_opened'], [CHOOSER])

    def test_the_configured_school_is_searched_chosen_and_continued(self):
        self.html = '''<label>Search for your institution name
          <input id="institution-search" role="combobox" placeholder="Enter your institution name"
            oninput="document.getElementById('results').innerHTML = this.value.length > 3
              ? ['Synthetic University A Hospital', 'Synthetic University A'].map(n => '<li role=option onclick=pick(this)>' + n + '</li>').join('') : ''"></label>
          <ul id="results" role="listbox"></ul>
          <button id="next" disabled aria-label="Next" onclick="location.href='https://idp.synthetic-a.example/login'"><!----><span>Next</span></button>
          <script>function pick(li) { document.getElementById('institution-search').value = li.textContent;
            document.getElementById('results').innerHTML = ''; document.getElementById('next').disabled = false; }</script>'''
        self.page.goto('https://sso.rsc.org/WAYF')
        with patch('paper_search_carsi.engine.batch.time.sleep'):
            self.assertTrue(self.downloader._select_institution(self.page, self.result))
        self.page.wait_for_url('https://idp.synthetic-a.example/login')
        states = [e['state'] for e in self.result.events]
        self.assertIn('auto_institution_search', states)
        self.assertEqual([e['detail'] for e in self.result.events if e['state'] == 'institution_selected'], ['Synthetic University A'])
        self.assertEqual([e['detail'] for e in self.result.events if e['state'] == 'institution_continue'], ['role=button[name=Next]'])

    def test_the_users_own_search_is_kept_and_left_to_them(self):
        self.html = '<label>Search for your institution name<input placeholder="Enter your institution name"></label>'
        self.page.goto('https://sso.rsc.org/WAYF')
        field = self.page.get_by_placeholder('Enter your institution name')
        field.fill('Typed by the user')
        self.assertFalse(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(field.input_value(), 'Typed by the user')
        states = [e['state'] for e in self.result.events]
        self.assertIn('institution_selection_required', states)
        self.assertNotIn('institution_selected', states)
        self.assertEqual(self.requests, ['https://sso.rsc.org/WAYF'])

    def test_a_signed_in_school_without_access_ends_as_no_entitlement_and_nothing_is_chosen(self):
        signed_in = '''<a class="dropdown-toggle" href="#" onclick="window.clicked = (window.clicked || 0) + 1; return false">SYNTHETIC UNIVERSITY A</a>
          <div class="dropdown-panel dropdown-panel-institution"><div class="dropdown-menu">
            <div class="dropdown-institution-item"> SYNTHETIC UNIVERSITY A </div></div></div>'''
        notice = '''<div class="article-top-info-user-restricted-options">You do not currently have access to this content.</div>
          <button class="sa-button js-sa-federated-login">Access through your institution</button>'''
        self.html = signed_in + notice
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._has_publisher_institution_session(self.page))
        self.assertTrue(self.downloader._institution_pdf_entitlement_missing(self.page))
        self.assertFalse(self.downloader._select_institution(self.page, self.result))
        self.assertIsNone(self.page.evaluate("window.clicked"))
        self.html = f'<a class="institutional-login-link" href="{CHOOSER}">Sign in via your Institution</a>' + notice
        self.page.goto(ARTICLE)  # signed out: the same notice is no verdict on the school
        self.assertFalse(self.downloader._has_publisher_institution_session(self.page))
        self.assertFalse(self.downloader._institution_pdf_entitlement_missing(self.page))

    def test_institution_entry_appearing_after_silent_redirect_is_opened_once(self):
        from paper_search_carsi.engine import batch_login
        # The silent sign-in callback moves on to the article by itself; the
        # article then shows the institution entry.
        self.html=('<a href="'+CHOOSER+'">Sign in via your Institution</a>'
                   "<script>if (location.pathname.startsWith('/ExternalAuthentication')) location.replace('"+ARTICLE+"')</script>")
        self.page.goto('https://pubs.rsc.org/ExternalAuthentication/SilentAuthCallback')
        loops=0
        def user_action(seconds):
            # The login wait checks the page every second; the user signs in meanwhile.
            nonlocal loops
            loops+=1
            self.assertLessEqual(loops,8,'manual login should complete')
            if self.page.url==CHOOSER:
                self.html='<title>Article</title>Full access'
                self.page.goto(ARTICLE.replace('article-abstract','article'))
        # Replacing time.sleep on the shared module also ran user_action on
        # the browser-watchdog thread, consuming this test's login-loop budget.
        # Only the login loop simulates the user's action; other threads sleep.
        with patch.object(batch_login,'time',SimpleNamespace(time=time.time,sleep=user_action)):
            self.assertTrue(self.downloader._complete_login_from_current_page(self.page,self.result))
        self.assertEqual(self.requests.count(CHOOSER),1)
        self.assertEqual(sum(e['state']=='sso_entry_clicked' for e in self.result.events),1)


if __name__ == '__main__':
    unittest.main()

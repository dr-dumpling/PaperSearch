"""Observed OpenAthens account/discovery boundary; all browser traffic local."""
import os
import unittest
from unittest.mock import Mock, patch

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import PublisherProfile

LOGIN = 'https://login.openathens.net/auth/logon'
DISCOVERY = 'https://wayfinder.openathens.net/fixture'


@unittest.skipUnless(os.environ.get('CARSI_LOCAL_BROWSER_TEST') == '1', 'local Chrome fixture opt-in')
class OpenAthensInstitutionTests(unittest.TestCase):
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
        self.html = f'''<title>OpenAthens / Sign in</title>
          <a href="/account-home">OpenAthens</a>
          <h1>Sign in with an OpenAthens account</h1>
          <form action="/credentials-submitted">
            <input name="username" value="synthetic-user">
            <input type="password" name="password" value="synthetic-password">
            <button>Sign in</button>
          </form>
          <a href="{DISCOVERY}">Find your institution</a>'''
        def respond(route):
            self.requests.append(route.request.url)
            route.fulfill(status=200, content_type='text/html',
                          body=self.html if route.request.url != DISCOVERY else '<title>Institution discovery</title>')
        self.context.route('**/*', respond)
        self.page = self.context.new_page()
        profile = PublisherProfile(name='Taylor & Francis', article_url_template='https://doi.org/{doi}',
            pdf_url_templates=(), success_url_markers=('tandfonline.com/',),
            auth_url_markers=('login.openathens.net',), auth_title_markers=('Sign In',),
            sso_text_markers=('openathens',), base_domains=('tandfonline.com',))
        self.downloader = PublisherBatchDownloader({}, profile=profile, institution_query='Example University')
        self.result = DownloadResult(doi='10.1080/fixture', status='failed')

    def test_account_page_is_not_automatically_used_for_institution_discovery(self):
        self.page.goto(LOGIN)
        self.assertFalse(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(self.requests, [LOGIN])

    def test_federation_page_never_reenters_generic_sso_or_clicks_logo(self):
        for url in (LOGIN, DISCOVERY, 'https://connect.openathens.net/fixture'):
            self.page.goto(url)
            self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.requests, [LOGIN, DISCOVERY, 'https://connect.openathens.net/fixture'])
        self.assertEqual(self.result.events, [])

    def test_missing_discovery_does_not_fill_or_submit_account_form(self):
        self.html = self.html.replace(f'<a href="{DISCOVERY}">Find your institution</a>', '')
        self.page.goto(LOGIN)
        self.assertFalse(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(self.page.locator('[name=username]').input_value(), 'synthetic-user')
        self.assertEqual(self.page.locator('[name=password]').input_value(), 'synthetic-password')
        self.assertEqual(self.requests, [LOGIN])

    def test_hidden_discovery_is_not_clicked(self):
        self.html = self.html.replace(f'<a href="{DISCOVERY}">', f'<a hidden href="{DISCOVERY}">')
        self.page.goto(LOGIN)
        self.assertFalse(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(self.requests, [LOGIN])

    def test_lookalike_host_is_not_an_openathens_discovery_page(self):
        url = 'https://login.openathens.net.evil.example/auth/logon'
        self.page.goto(url)
        self.assertFalse(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(self.requests, [url])

    def carsi_chooser(self, schools=None):
        schools = schools or ['Example University Hospital', 'EXAMPLE UNIVERSITY']
        self.html = '''<title>Shibboleth sign in</title>
          <select id="shib-search--fed" onchange="document.querySelector('#schools').hidden=this.value!=='carsi'">
            <option value="">Select your region or federation</option>
            <option value="athens">OpenAthens Federation</option>
            <option value="carsi">China CERNET Federation (CARSI)</option>
          </select><input placeholder="Type the name of your institution">
          <a href="https://login.openathens.net/auth/logon">Sign in with your OpenAthens account</a>
          <ul id="schools" hidden>''' + ''.join(
              f'<li onclick="location.href=\'https://idp.fixture.example/login\'">{name}</li>' for name in schools
          ) + '</ul>'
        self.downloader.config['publisher_institution_federation'] = 'carsi'
        self.page.goto('https://www.tandfonline.com/action/ssostart')

    def test_configured_school_is_chosen_exactly_after_the_carsi_federation(self):
        self.carsi_chooser()  # 'Example University Hospital' and 'EXAMPLE UNIVERSITY'
        self.assertTrue(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(self.page.locator('select#shib-search--fed').input_value(), 'carsi')
        self.assertTrue(self.downloader._select_institution(self.page, self.result))
        self.page.wait_for_url('https://idp.fixture.example/login')
        chosen = [e['detail'] for e in self.result.events if e['state'] == 'institution_selected']
        self.assertEqual(chosen, ['EXAMPLE UNIVERSITY'])

    def test_chooser_is_not_replaced_by_generic_sso_or_openathens(self):
        self.carsi_chooser()
        self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
        self.assertFalse(self.downloader._click_openathens_entry(self.page, self.result))
        self.assertEqual(self.requests, ['https://www.tandfonline.com/action/ssostart'])

    def test_typed_input_is_kept_and_identical_schools_are_left_to_the_user(self):
        self.carsi_chooser(['Example University', 'Example University'])
        field = self.page.get_by_placeholder('Type the name of your institution')
        field.fill('User chooses another school')
        self.assertTrue(self.downloader._select_institution(self.page, self.result))  # federation only
        self.assertEqual(field.input_value(), 'User chooses another school')
        self.assertFalse(self.downloader._select_institution(self.page, self.result))  # tie: nothing clicked
        self.assertEqual(field.input_value(), 'User chooses another school')
        self.assertEqual(self.page.url, 'https://www.tandfonline.com/action/ssostart')
        self.assertNotIn('institution_selected', [e['state'] for e in self.result.events])

    def test_login_wait_does_not_repeat_federation_choice_or_submit_user_input(self):
        self.carsi_chooser()
        # No configured school: the user picks one. (A configured school missing
        # from the list ends the login at once, 2026-11-01.)
        self.downloader.institution_query = ''
        self.downloader._click_optional_continue=Mock(side_effect=AssertionError('must wait for user'))
        loops=0
        def user_interaction(seconds):
            nonlocal loops
            if seconds != 1:  # one pass of the login wait, which checks the page every second
                return
            loops += 1
            field=self.page.get_by_placeholder('Type the name of your institution')
            if loops == 1:
                field.fill('User school choice')
                self.page.locator('select#shib-search--fed').select_option('athens')
            else:
                self.assertEqual(field.input_value(), 'User school choice')
                self.assertEqual(self.page.locator('select#shib-search--fed').input_value(), 'athens')
                raise KeyboardInterrupt
        with patch('paper_search_carsi.engine.batch.time.sleep', side_effect=user_interaction):
            with self.assertRaises(KeyboardInterrupt):
                self.downloader._complete_login_from_current_page(self.page,self.result)
        self.downloader._click_optional_continue.assert_not_called()

    def test_fresh_user_without_school_configuration_can_enter_carsi(self):
        self.carsi_chooser()
        self.downloader.institution_query=''
        self.assertTrue(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(self.page.locator('select#shib-search--fed').input_value(), 'carsi')
        self.assertEqual(self.requests, ['https://www.tandfonline.com/action/ssostart'])

    def test_only_the_configured_school_is_ever_chosen(self):
        for school, lands in (('Example University', True), ('Another Institute', False)):
            with self.subTest(school=school):
                self.downloader = PublisherBatchDownloader({}, profile=self.downloader.profile, institution_query=school)
                self.result = DownloadResult(doi='10.1080/fixture', status='failed')
                self.carsi_chooser()
                self.downloader._select_institution(self.page, self.result)
                self.downloader._select_institution(self.page, self.result)
                if lands:
                    self.page.wait_for_url('https://idp.fixture.example/login')
                else:
                    self.assertEqual(self.page.url, 'https://www.tandfonline.com/action/ssostart')
                    self.assertNotIn('institution_selected', [e['state'] for e in self.result.events])

    def test_chooser_and_other_hosts_are_not_article_ready(self):
        for url in ('https://www.tandfonline.com/action/ssostart',
                    'https://www.tandfonline.com/action/showLogin',
                    'https://www.tandfonline.com.evil.example/doi/full/10.1080/fixture',
                    'https://evil.example/?next=https://www.tandfonline.com/doi/full/10.1080/fixture'):
            self.assertFalse(self.downloader._is_success_article_url(url), url)
        self.assertTrue(self.downloader._is_success_article_url('https://www.tandfonline.com/doi/full/10.1080/fixture'))

    def test_carsi_selection_does_not_act_on_another_host(self):
        self.carsi_chooser()
        self.page.goto('https://idp.fixture.example/login')
        self.assertFalse(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(len(self.requests), 2)

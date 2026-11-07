"""Manual CARSI boundary across publishers; all Chrome traffic intercepted."""
import os
import unittest
from unittest.mock import Mock, patch

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import PublisherProfile

DOI = '10.1177/03635465231162333'
ARTICLE = 'https://journals.sagepub.com/doi/' + DOI
CHOOSER = 'https://journals.sagepub.com/action/ssostart?redirectUri=' + ARTICLE


@unittest.skipUnless(os.environ.get('CARSI_LOCAL_BROWSER_TEST') == '1', 'local Chrome fixture opt-in')
class ManualCarsiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
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
        self.article_html = f'<title>Target article</title>Restricted access <a hidden href="{CHOOSER}">Access through your institution</a>'
        self.chooser_html = '''<title>Institution selection</title>
          <form action="/should-not-submit"><input name="institution" placeholder="Institution">
          <button>Continue</button></form>
          <a href="https://login.openathens.net/auth/logon">Sign in with OpenAthens</a>'''
        def respond(route):
            self.requests.append(route.request.url)
            route.fulfill(status=200, content_type='text/html',
                          body=self.article_html if route.request.url == ARTICLE else self.chooser_html)
        self.context.route('**/*', respond)
        self.page = self.context.new_page()
        profile = PublisherProfile(name='SAGE', article_url_template='https://doi.org/{doi}',
            pdf_url_templates=(), success_url_markers=('sagepub.com/',),
            auth_url_markers=('/action/ssostart',), auth_title_markers=('Institution selection',),
            sso_text_markers=('access through your institution',), base_domains=('sagepub.com',))
        self.downloader = PublisherBatchDownloader({'publisher_institution_federation': 'carsi'},
            profile=profile, institution_query='Synthetic University A', login_timeout_sec=10)
        self.result = DownloadResult(doi=DOI, status='failed', article_url=ARTICLE)

    def test_hidden_official_current_article_link_opens_only_institution_entry(self):
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.url, CHOOSER)
        self.assertEqual(self.requests, [ARTICLE, CHOOSER])
        self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
        self.assertFalse(self.downloader._article_access_available(self.page))

    def sage_panel(self, delay_ms):
        """Access panel whose "Institution" tab only appears after ``delay_ms``."""
        self.article_html = (
            '<title>Target article</title>Restricted access '
            '<a href="#core-collateral-purchase-access" onclick="setTimeout(() => {'
            "document.querySelector('#panel').innerHTML = '<button>Institution</button>';"
            "document.querySelector('#panel button').onclick = () => {"
            "const a = document.createElement('a'); a.href = '" + CHOOSER + "';"
            "a.textContent = 'Access through your institution'; document.body.append(a); };"
            '}, ' + str(delay_ms) + '); return false;">Access</a><div id="panel"></div>')

    def test_slow_sage_access_panel_is_waited_for(self):
        # Right after a Cloudflare check the panel took longer than 5 s (in Firefox).
        self.sage_panel(7000)
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.url, CHOOSER)

    def test_missing_sage_institution_link_opens_its_address_directly(self):
        # The American Surgeon: the panel never listed the link and the item waited ~7 minutes.
        from urllib.parse import parse_qs, urlparse
        self.sage_panel(600000)
        self.page.goto(ARTICLE)
        clock = iter(range(0, 10_000, 5))
        with patch("paper_search_carsi.engine.batch.time.time", side_effect=lambda: next(clock)):
            self.assertTrue(self.downloader._click_sso_entry(self.page, self.result))
        target = urlparse(self.page.url)
        self.assertEqual((target.netloc, target.path), ("journals.sagepub.com", "/action/ssostart"))
        self.assertEqual(parse_qs(target.query)["redirectUri"], [ARTICLE])
        self.assertEqual([e["state"] for e in self.result.events][-2:], ["sage_institution_link_missing", "sso_entry_clicked"])

    def test_elsevier_carsi_opens_generic_chooser_without_configured_school(self):
        from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE
        article = 'https://www.sciencedirect.com/science/article/pii/SYNTHETIC'
        chooser = 'https://auth.elsevier.com/ShibAuth/organizationLogin'
        self.chooser_html = '''<a href="https://auth.elsevier.com/ShibAuth/institutionLogin?entityID=synthetic-school">Access through Synthetic University A</a>
          <a href="CHOOSER">Access through your organization</a>'''.replace('CHOOSER', chooser)
        for school in ('Synthetic University A', 'Synthetic College B', ''):
            downloader = PublisherBatchDownloader({'publisher_institution_federation': 'carsi'},
                profile=ELSEVIER_PROFILE, institution_query=school)
            self.page.goto(article)
            self.assertTrue(downloader._click_sso_entry(self.page, self.result))
            self.page.wait_for_url(chooser)
        self.assertEqual(self.requests, [article, chooser] * 3)

    def test_elsevier_remembered_school_link_cannot_replace_missing_generic_chooser(self):
        from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE
        article = 'https://www.sciencedirect.com/science/article/pii/SYNTHETIC'
        downloader = PublisherBatchDownloader({'publisher_institution_federation': 'carsi'},
            profile=ELSEVIER_PROFILE, institution_query='Synthetic University A')
        for href in ('https://auth.elsevier.com/ShibAuth/institutionLogin?entityID=synthetic-school',
                     'https://auth.elsevier.com/ShibAuth/organizationLogin?entityID=synthetic-school',
                     'https://auth.elsevier.com.evil.example/chooser'):
            self.chooser_html = '<a href="' + href + '">Access through your organization</a>'
            self.page.goto(article)
            self.assertFalse(downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.requests, [article] * 3)

    def test_generic_entry_never_uses_remembered_school_or_selected_idp(self):
        from dataclasses import replace
        self.downloader.profile = replace(self.downloader.profile, name='Fixture Press')
        for school in ('Synthetic University A', 'Synthetic College B', ''):
            self.downloader.institution_query = school
            for label in ('Access through your institution', 'Synthetic University A'):
                for suffix in ('?entityID=synthetic-school', '?idp=synthetic-school',
                               '?return=https%3A%2F%2Fexample.invalid%2Fsso%3FentityID%3Dsynthetic-school'):
                    self.article_html = '<a href="https://journals.sagepub.com/action/ssostart' + suffix + '">' + label + '</a>'
                    self.page.goto(ARTICLE)
                    self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
                    self.assertEqual(self.page.url, ARTICLE)

    def test_generic_entry_keeps_user_institution_input_and_can_open_neutral_chooser(self):
        from dataclasses import replace
        self.downloader.profile = replace(self.downloader.profile, name='Fixture Press')
        self.article_html = '<input placeholder="Institution" value="User chosen school"><a href="' + CHOOSER + '">Access through your institution</a>'
        self.page.goto(ARTICLE)
        self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.get_by_placeholder('Institution').input_value(), 'User chosen school')
        self.article_html = '<input placeholder="Site search"><a href="' + CHOOSER + '">Access through your institution</a>'
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._click_sso_entry(self.page, self.result))
        self.page.wait_for_url(CHOOSER)

    def test_sage_selected_idp_does_not_bypass_manual_selection(self):
        self.article_html = '<a href="' + CHOOSER + '&entityID=synthetic-school">Access through your institution</a>'
        self.page.goto(ARTICLE)
        self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.url, ARTICLE)

    def test_generic_entry_never_submits_inherited_action_or_hidden_selected_idp(self):
        from dataclasses import replace
        self.downloader.profile = replace(self.downloader.profile, name='Fixture Press')
        forms = (
            '<form action="/action/ssostart?entityID=synthetic-school"><button>Institutional access</button></form>',
            '<form action="/action/ssostart"><input type="hidden" name="idp" value="synthetic-school"><button>Institutional access</button></form>',
            '<form id="remembered" action="/action/ssostart?entityID=synthetic-school"></form><button form="remembered">Institutional access</button>',
        )
        for school in ('', 'Synthetic University A', 'Synthetic College B'):
            self.downloader.institution_query = school
            for body in forms:
                self.article_html = body
                self.page.goto(ARTICLE)
                self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
                self.assertEqual(self.page.url, ARTICLE)
        self.assertEqual(self.requests, [ARTICLE] * 9)

    def test_elsevier_legacy_shortcut_requires_matching_explicit_school(self):
        from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE
        article = 'https://www.sciencedirect.com/science/article/pii/SYNTHETIC'
        shortcut = 'https://auth.elsevier.com/ShibAuth/institutionLogin?entityID=synthetic-school'
        self.chooser_html = '<a href="' + shortcut + '">Access through Synthetic University A</a>'
        for school, expected in (('', False), ('Synthetic College B', False), ('Synthetic University A', True)):
            downloader = PublisherBatchDownloader({}, profile=ELSEVIER_PROFILE, institution_query=school)
            self.page.goto(article)
            self.assertEqual(downloader.adapter.click_institution_entry(self.page, self.result), expected)
            if expected:
                self.page.wait_for_url(shortcut)

    def test_other_article_and_lookalike_institution_links_are_rejected(self):
        for href in ('https://journals.sagepub.com.evil.example/action/ssostart?redirectUri=' + ARTICLE,
                     'https://journals.sagepub.com/action/ssostart?redirectUri=https://journals.sagepub.com/doi/10.1177/other'):
            with self.subTest(href=href):
                self.article_html = f'<a href="{href}">Access through your institution</a>'
                self.page.goto(ARTICLE)
                self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
                self.assertEqual(self.page.url, ARTICLE)

    def test_a_link_back_to_the_home_page_returns_to_this_article(self):
        # 2026-11-01: the panel's link carries the site's home page as redirectUri.
        from urllib.parse import quote
        home = 'https://journals.sagepub.com/action/ssostart?redirectUri=https://journals.sagepub.com'
        self.article_html = f'<a href="{home}">Access through your institution</a>'
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.requests[-1], 'https://journals.sagepub.com/action/ssostart?redirectUri=' + quote(ARTICLE, safe=''))

    def test_a_school_missing_from_sages_list_signs_in_through_openathens(self):
        openathens = ('https://journals.sagepub.com/action/ssostart?idp=https://idp.eduserv.org.uk/openathens'
                      '&redirectUri=' + ARTICLE)
        self.chooser_html = f'<title>Institutional Login</title><a href="{openathens}">Sign In With Your Openathens Account</a>'
        self.page.goto(CHOOSER)
        self.assertIsNone(self.downloader.adapter.choose_institution(self.page, self.result))  # own list first
        self.result.events.append({"state": "auto_institution_not_found", "detail": f"Synthetic University A @ {CHOOSER}"})
        self.assertTrue(self.downloader.adapter.choose_institution(self.page, self.result))
        self.assertEqual(self.requests[-1], openathens)

    def test_access_panel_loads_the_observed_institution_link_on_demand(self):
        self.article_html = f'''<a href="#core-collateral-purchase-access"
          onclick="document.querySelector('#panel').innerHTML='<a href=\\'{CHOOSER}\\'>Access through your institution</a>';return false">Get access</a><div id="panel"></div>'''
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.requests, [ARTICLE, CHOOSER])

    def test_access_panel_institution_accordion_loads_the_link_in_a_second_step(self):
        self.article_html = '''<a href="#core-collateral-purchase-access"
          onclick="document.querySelector('#institution').hidden=false;return false">Get access</a>
          <button id="institution" hidden onclick="document.querySelector('#panel').appendChild(Object.assign(document.createElement('a'),{href:'CHOOSER_URL',textContent:'Access through your institution'}))">Institution</button><div id="panel"></div>'''.replace('CHOOSER_URL',CHOOSER)
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._click_sso_entry(self.page, self.result))
        self.assertEqual(self.requests, [ARTICLE, CHOOSER])

    def test_two_schools_and_unconfigured_user_are_never_searched_or_submitted(self):
        for school in ('Synthetic University A', 'Synthetic College B', ''):
            with self.subTest(school=school):
                self.downloader.institution_query = school
                self.page.goto(CHOOSER)
                field = self.page.get_by_placeholder('Institution')
                field.fill('User-selected institution')
                for _ in range(2):
                    self.assertFalse(self.downloader._select_institution(self.page, self.result))
                    self.downloader._click_optional_continue(self.page, self.result)
                    self.assertFalse(self.downloader._click_openathens_entry(self.page, self.result))
                self.assertEqual(field.input_value(), 'User-selected institution')
                self.assertEqual(self.page.url, CHOOSER)
        self.assertEqual(self.requests, [CHOOSER] * 3)

    def test_external_identity_provider_and_visible_credential_forms_remain_manual(self):
        for url in ('https://identity.fixture.example/login', 'https://journals.sagepub.com/action/login'):
            with self.subTest(url=url):
                self.chooser_html = '<form action="/should-not-submit"><input type="password"><button>Continue</button></form>'
                self.page.goto(url)
                self.assertTrue(self.downloader._is_human_login_page(self.page))
                self.assertFalse(self.downloader._click_sso_entry(self.page, self.result))
                self.downloader._click_optional_continue(self.page, self.result)
                self.assertEqual(self.page.url, url)

    def test_login_wait_preserves_user_input_and_accepts_only_returned_article(self):
        # No configured school: the user picks one. (A configured school missing
        # from the list ends the login at once, 2026-11-01.)
        self.downloader.institution_query = ''
        self.page.goto(ARTICLE)
        original_entry = self.downloader._click_sso_entry
        self.downloader._click_sso_entry = Mock(wraps=original_entry)
        loops = 0
        def user_action(seconds):
            nonlocal loops
            if seconds != 1:  # one pass of the login wait, which checks the page every second
                return
            loops += 1
            if loops == 1:
                self.page.get_by_placeholder('Institution').fill('User-selected institution')
            elif loops == 2:
                self.assertEqual(self.page.get_by_placeholder('Institution').input_value(), 'User-selected institution')
                self.article_html = '<title>Target article</title>Full access'
                self.page.goto(ARTICLE)
        with patch('paper_search_carsi.engine.batch.time.sleep', side_effect=user_action):
            self.assertTrue(self.downloader._complete_login_from_current_page(self.page, self.result))
        self.downloader._click_sso_entry.assert_called_once()
        self.assertEqual(self.requests, [ARTICLE, CHOOSER, ARTICLE])

    def test_chooser_home_and_lookalike_host_cannot_complete_login(self):
        for url in (CHOOSER, 'https://journals.sagepub.com/',
                    'https://journals.sagepub.com.evil.example/doi/' + DOI):
            self.assertFalse(self.downloader._is_success_article_url(url))
        self.assertTrue(self.downloader._is_success_article_url(ARTICLE))

    def test_external_challenge_is_observed_instead_of_silent_login_wait(self):
        self.page.goto('https://identity.fixture.example/login')
        self.downloader._is_challenge_page = Mock(return_value=True)
        self.downloader._wait_for_challenge = Mock(return_value=False)
        with patch('paper_search_carsi.engine.batch.time.sleep'):
            self.assertFalse(self.downloader._complete_login_from_current_page(self.page, self.result))
        self.downloader._wait_for_challenge.assert_called_once()

    def test_visible_publisher_institution_denial_stops_without_another_login(self):
        # The configured school is named and does not subscribe: no login can help.
        self.article_html = '''<div id="core-collateral-purchase-access"><p>Access via Synthetic University A is not available as they do not subscribe to Sage Journals content.</p></div>'''
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._institution_pdf_entitlement_missing(self.page))
        self.assertFalse(self.downloader._complete_login_from_current_page(self.page, self.result))
        self.assertEqual(self.downloader._login_block_reason(self.page), 'institution_pdf_entitlement_missing')
        self.assertEqual(self.requests, [ARTICLE])
        # Another school named (an IP range's): this school's login may still give access.
        self.article_html = self.article_html.replace('Synthetic University A', 'Example College B')
        self.page.goto(ARTICLE)
        self.assertFalse(self.downloader._institution_pdf_entitlement_missing(self.page))
        self.assertTrue(self.downloader._looks_logged_out(self.page))

    def test_denial_in_help_or_a_hidden_panel_is_not_current_denial(self):
        sentence = 'Access via Synthetic College B is not available as they do not subscribe to Sage Journals content.'
        for html in (f'<p>{sentence}</p>',
                     f'<div id="core-collateral-purchase-access" hidden><p>{sentence}</p></div>',
                     f'<div id="core-collateral-purchase-access"><p>If the site says: {sentence}</p></div>'):
            self.article_html = html.replace('Synthetic College B', 'Synthetic University A')
            self.page.goto(ARTICLE)
            if 'hidden' in html or 'If the site says' in html:
                self.assertFalse(self.downloader._institution_pdf_entitlement_missing(self.page))
            else:  # the shared denial line counts wherever the page shows it
                self.assertTrue(self.downloader._institution_pdf_entitlement_missing(self.page))

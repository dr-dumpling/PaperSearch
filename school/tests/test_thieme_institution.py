"""Observed Thieme federation chain with entirely intercepted browser traffic."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from paper_search_school.engine.batch import DownloadResult, PaperRecord, PublisherBatchDownloader
from test_thieme_capture import DOI, PDF, profile

ARTICLE = 'https://www.thieme-connect.de/products/ejournals/abstract/' + DOI
LOGIN = 'https://profile.thieme.de/HTML/sso/THIEME/login.htm'
SEARCH = 'https://profile.thieme.de/HTML/sso/ejournals/shibboleth-idpsearch.htm'
CHOOSER = 'https://profile.thieme.de/HTML/sso/ejournals/shibboleth.htm'


@unittest.skipUnless(os.environ.get('SCHOOL_LOCAL_BROWSER_TEST') == '1','local Chrome fixture opt-in')
class ThiemeInstitutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver=sync_playwright().start()
        cls.browser=cls.driver.chromium.launch(channel='chrome',headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.context=self.browser.new_context(service_workers='block')
        self.addCleanup(self.context.close)
        self.requests=[]
        self.login_target=LOGIN+'?hook_url=https%3A%2F%2Fwww.thieme-connect.de%2Falerts&rdeLocaleAttr=en'
        self.article_html=f'<a href="{self.login_target}">Alert service</a><a href="/products/ejournals/buyDocument/{DOI}">Buy Article</a>'
        self.login_html=f'''<form action="/must-not-submit"><input name="user" type="text"><input type="password">
            <button>Continue</button></form><a href="{SEARCH}">E-Journals Login via Shibboleth/OpenAthens</a>
            <a href="https://profile.thieme.de/reset?hook_url={PDF}">Forgot password?</a>'''
        self.chooser_html='''<form action="/must-not-submit"><select id="federation">
            <option>Other federation</option><option>China (CARSI)</option></select>
            <input name="school" placeholder="Institution"><button>Continue</button></form>'''
        def respond(route):
            self.requests.append(route.request.url)
            target=route.request.url.split('?',1)[0]
            body=(self.article_html if target==ARTICLE else self.login_html if target==LOGIN
                  else f'<a href="{CHOOSER}">Systematic search for institutions</a>' if target==SEARCH
                  else self.chooser_html)
            route.fulfill(status=200,content_type='text/html',body=body)
        self.context.route('**/*',respond)
        self.page=self.context.new_page()
        self.downloader=PublisherBatchDownloader({'publisher_institution_federation':'carsi'},
            profile=profile(),institution_query='Synthetic University A')
        self.result=DownloadResult(doi=DOI,status='failed',article_url=ARTICLE)

    def test_official_chain_returns_to_this_article_without_submitting_accounts_or_alerts(self):
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._looks_logged_out(self.page))
        self.assertTrue(self.downloader._click_sso_entry(self.page,self.result))
        self.assertEqual(self.page.url,CHOOSER)
        self.assertEqual([url.split('?',1)[0] for url in self.requests],[ARTICLE,LOGIN,SEARCH,CHOOSER])
        self.assertEqual(parse_qs(urlparse(self.requests[1]).query)['hook_url'],[ARTICLE])
        self.assertFalse(self.downloader._article_access_available(self.page))

    def test_school_is_selected_the_configured_school_is_typed_and_user_input_is_kept(self):
        for school in ('Synthetic University A','Synthetic University B',''):
            with self.subTest(school=school):
                self.downloader.institution_query=school
                self.result.events.clear()
                self.page.goto(CHOOSER)
                # A configured school is typed into the empty search box; with no school nothing is typed.
                self.downloader._select_institution(self.page,self.result)
                self.downloader._select_institution(self.page,self.result)
                self.assertEqual(self.page.locator('#federation option:checked').inner_text(),'China (CARSI)')
                self.assertEqual(self.page.get_by_placeholder('Institution').input_value(), school)
                self.page.get_by_placeholder('Institution').fill('User choice')
                self.page.locator('#federation').select_option(label='Other federation')
                self.assertFalse(self.downloader._select_institution(self.page,self.result))
                self.assertEqual(self.page.get_by_placeholder('Institution').input_value(),'User choice')
                self.assertEqual(self.page.locator('#federation option:checked').inner_text(),'Other federation')
        self.assertTrue(all(url==CHOOSER for url in self.requests))

    def test_federation_only_step_continues_to_the_school_list(self):
        # The real Thieme page: federation select and Continue, schools on the next page.
        self.chooser_html = '''<form action="/fixture/next"><select id="federation">
            <option>Other federation</option><option>China (CARSI)</option></select>
            <button>Continue</button></form>'''
        self.page.goto(CHOOSER)
        self.assertTrue(self.downloader._select_institution(self.page, self.result))
        self.page.wait_for_url("**/fixture/next**")
        self.assertIn("institution_federation_continue", [e["state"] for e in self.result.events])

    def test_a_cookie_panels_search_box_does_not_hold_the_continue(self):
        # profile.thieme.de (2026-11-02): OneTrust's vendor search box, outside the form,
        # was taken for the page asking for the school, and the Continue never came.
        self.chooser_html = '''<form action="/fixture/next"><select id="federation">
            <option>Other federation</option><option>China (CARSI)</option></select>
            <button>Continue</button></form>
            <div id="onetrust-pc-sdk"><input type="text" id="vendor-search-handler" placeholder="Search..."></div>'''
        self.page.goto(CHOOSER)
        self.assertTrue(self.downloader._select_institution(self.page, self.result))
        self.page.wait_for_url("**/fixture/next**")

    def test_a_cookie_overlay_is_rejected_before_the_federation_continue(self):
        self.chooser_html = '''<form action="/fixture/next"><select id="federation">
            <option>Other federation</option><option>China (CARSI)</option></select>
            <button>Continue</button></form>
            <div id="cookie-consent" style="position:fixed;inset:0;z-index:9999;background:#888">
              <section><h2>We kindly request your consent</h2><p>Our website uses cookies.</p>
              <button onclick="this.closest('#cookie-consent').remove()">Accept</button>
              <button onclick="this.closest('#cookie-consent').remove()">Reject</button>
              <button>Settings</button></section></div>'''
        self.page.goto(CHOOSER)
        self.assertTrue(self.downloader._select_institution(self.page, self.result))
        states = [e["state"] for e in self.result.events]
        self.assertIn("cookie_banner_dismissed", states)
        answer = next(e for e in self.result.events if e["state"] == "cookie_banner_dismissed")
        self.assertIn('reject "Reject"', answer["detail"])
        self.assertIn("institution_federation_continue", states)
        self.page.wait_for_url("**/fixture/next**", timeout=3_000)

    def test_federation_continue_errors_are_not_hidden(self):
        from paper_search_school.browser.watchdog import BrowserOperationTimeout
        for error in (KeyError("program error"), BrowserOperationTimeout("operation expired")):
            with self.subTest(error=type(error).__name__):
                self.chooser_html = '''<form action="/fixture/next"><select id="federation">
                    <option>Other federation</option><option selected>China (CARSI)</option></select>
                    <button>Continue</button></form>'''
                self.page.goto(CHOOSER)
                self.result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
                with patch.object(self.downloader, "_click_control", side_effect=error):
                    with self.assertRaises(type(error)):
                        self.downloader._select_institution(self.page, self.result)

    def test_the_continue_is_pressed_again_while_the_page_stays_on_this_step(self):
        # The page came back on the federation step with CARSI chosen: Continue again,
        # three times at most (a second one brought the school list, 2026-11-02).
        self.chooser_html = '''<form action="/HTML/sso/ejournals/shibboleth.htm"><select id="federation">
            <option>Other federation</option><option selected>China (CARSI)</option></select>
            <button>Continue</button></form>'''
        self.page.goto(CHOOSER)
        pressed = []
        for _ in range(3):
            with self.page.expect_navigation():
                pressed.append(self.downloader._select_institution(self.page, self.result))
            self.result._federation_continue_at = 0.0  # as if the gap had passed
        for _ in range(2):
            pressed.append(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(pressed, [True, True, True, False, False])
        states = [e["state"] for e in self.result.events]
        self.assertEqual(states.count("institution_federation_continue"), 3)
        self.assertEqual(states.count("institution_selection_required"), 1)

    def test_a_reload_that_resets_the_federation_is_chosen_again(self):
        # After a Continue Thieme can reload the step with its first federation selected
        # (2026-11-02): a new page, not the user's choice; CARSI again, Continue again.
        self.chooser_html = """<form action="/HTML/sso/ejournals/shibboleth.htm"><select id="federation">
            <option>Other federation</option><option>China (CARSI)</option></select>
            <button>Continue</button></form>"""
        self.page.goto(CHOOSER)
        for _ in range(2):
            with self.page.expect_navigation():
                self.assertTrue(self.downloader._select_institution(self.page, self.result))
            self.result._federation_continue_at = 0.0  # as if the gap had passed
        states = [e["state"] for e in self.result.events]
        self.assertEqual(states.count("institution_federation_selected"), 2)
        self.assertEqual(states.count("institution_federation_continue"), 2)
        # On the same page, the user's own change stays: CARSI chosen here (its Continue
        # not due yet), then changed by the user.
        self.result._federation_continue_at = 1e18
        self.assertTrue(self.downloader._select_institution(self.page, self.result))
        self.page.locator("#federation").select_option(label="Other federation")
        self.assertFalse(self.downloader._select_institution(self.page, self.result))
        self.assertEqual(self.page.locator("#federation option:checked").inner_text(), "Other federation")

    def test_a_step_interrupted_by_the_pages_navigation_is_looked_at_again(self):
        # The engine calls the chooser step every second; a read that meets the page
        # reloading after Continue ("Execution context was destroyed") is not the end.
        from patchright.sync_api import Error as PlaywrightError
        from unittest.mock import Mock
        self.downloader.adapter.choose_institution = Mock(side_effect=PlaywrightError(
            "Locator.all_text_contents: Execution context was destroyed, most likely because of a navigation"))
        self.page.goto(CHOOSER)
        self.assertFalse(self.downloader._select_institution(self.page, self.result))
        self.assertIn("institution_step_interrupted", [e["state"] for e in self.result.events])
        self.downloader.adapter.choose_institution = Mock(side_effect=KeyError("program error"))
        with self.assertRaises(KeyError):
            self.downloader._select_institution(self.page, self.result)

    def test_input_already_entered_on_login_page_is_preserved(self):
        self.page.goto(LOGIN)
        self.page.locator('input[name=user]').fill('Synthetic operator input')
        self.assertFalse(self.downloader._click_sso_entry(self.page,self.result))
        self.assertEqual(self.page.url,LOGIN)
        self.assertEqual(self.page.locator('input[name=user]').input_value(),'Synthetic operator input')
        self.assertEqual(self.requests,[LOGIN])

    def test_forged_or_unrelated_entry_never_navigates(self):
        for target in (LOGIN.replace('profile.thieme.de','profile.thieme.de.evil.example'),
                       LOGIN.replace('login.htm','thieme_forgotten_access_data.htm')):
            self.article_html=f'<a href="{target}">E-Journals institutional login</a>'
            self.page.goto(ARTICLE)
            self.assertFalse(self.downloader._click_sso_entry(self.page,self.result))
            self.assertEqual(self.page.url,ARTICLE)
        self.page.goto('https://identity.fixture.example/login')
        self.assertFalse(self.downloader._click_sso_entry(self.page,self.result))

    def test_account_recovery_link_cannot_be_clicked_as_pdf(self):
        self.article_html=f'<a href="https://profile.thieme.de/reset?hook_url={PDF}">Download PDF</a><a href="{PDF}">Download PDF</a>'
        self.page.goto(ARTICLE)
        self.assertTrue(self.downloader._click_pdf_entry(self.page,self.result,doi=DOI))
        self.page.wait_for_url(PDF)
        self.assertEqual(self.requests,[ARTICLE,PDF])

    def test_institution_session_survives_personal_logged_out_and_buy_article_controls(self):
        for school in ('Synthetic University A', 'Synthetic University B'):
            with self.subTest(school=school):
                self.article_html=(f'<button id="userMenuToggleLoggedOut">Not Logged In</button>'
                    f'<div id="institutionName">{school}</div>'
                    f'<a href="/products/ejournals/buyDocument/{DOI}">Buy Article</a>')
                self.page.goto(ARTICLE)
                self.assertTrue(self.downloader._has_publisher_institution_session(self.page))
                self.assertFalse(self.downloader._looks_logged_out(self.page))

    def test_empty_hidden_placeholder_and_affiliation_do_not_establish_session(self):
        for label in ('<div id="institutionName"></div>',
                      '<div id="institutionName" hidden>Synthetic University A</div>',
                      '<div id="institutionName">Your institution</div>',
                      '<div class="author-affiliation">Synthetic University A</div>'):
            with self.subTest(label=label):
                self.article_html=label+f'<a href="/products/ejournals/buyDocument/{DOI}">Buy Article</a>'
                self.page.goto(ARTICLE)
                self.assertFalse(self.downloader._has_publisher_institution_session(self.page))
                self.assertTrue(self.downloader._looks_logged_out(self.page))

    def test_session_label_on_identity_or_forged_host_does_not_grant_article_session(self):
        for url in (LOGIN, ARTICLE.replace('www.thieme-connect.de', 'www.thieme-connect.de.evil.example')):
            with self.subTest(url=url):
                self.page.goto(url)
                self.page.set_content('<div id="institutionName">Synthetic University A</div>')
                self.assertFalse(self.downloader._has_publisher_institution_session(self.page))

    def test_institution_with_explicit_article_denial_does_not_restart_login(self):
        self.article_html=('<div id="institutionName">Synthetic University A</div>'
            '<p>Your institution does not have access to this article.</p>')
        with patch('paper_search_school.engine.batch.time.sleep'), patch.object(
                self.downloader, '_complete_login_from_current_page', side_effect=AssertionError('Unexpected login')) as login:
            self.assertFalse(self.downloader._ensure_login(self.page,self.result))
            self.assertTrue(self.downloader._institution_pdf_entitlement_missing(self.page))
            login.assert_not_called()

    def test_normal_fetch_reaches_capture_without_reentering_sso(self):
        import pymupdf
        title='Synthetic Thieme article'
        with pymupdf.open() as document:
            page=document.new_page()
            page.insert_text((40,50),title+'\nDOI: '+DOI)
            pdf_body=document.tobytes()+b'\n%'+b'x'*6000
        self.article_html=(f'<meta name="citation_doi" content="{DOI}">'
            '<button id="userMenuToggleLoggedOut">Not Logged In</button>'
            '<div id="institutionName">Synthetic University B</div>'
            f'<a href="/products/ejournals/buyDocument/{DOI}">Buy Article</a>'
            f'<a href="{PDF}">Download PDF</a>')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.downloader.config['cache_dir']=str(root/'cache')
            # This regression exercises real DOM/login decisions. The existing
            # PDF transport is stubbed; live route checks verify that separately.
            with patch('paper_search_school.engine.batch.time.sleep'), patch.object(
                    self.downloader,'_complete_login_from_current_page',side_effect=AssertionError('Unexpected login')) as login, patch.object(
                    self.downloader,'_capture_pdf',return_value=(pdf_body,PDF,None)) as capture:
                result=self.downloader.fetch_one(self.page,PaperRecord(doi=DOI,title=title),root/'run')
            self.assertTrue(result.ok,(result.state,result.events,self.requests))
            self.assertTrue(result.verified_match)
            self.assertEqual(Path(result.pdf_path).read_bytes(),pdf_body)
            login.assert_not_called()
            capture.assert_called_once_with(self.page,DOI,result)
        self.assertEqual(self.requests,[ARTICLE])


if __name__=='__main__':
    unittest.main()

"""Wiley CARSI controls in an ephemeral browser with all requests intercepted.

No backend startup, configuration, credential store or persistent profile is
loaded. Opt in with CARSI_LOCAL_BROWSER_TEST=1 and the existing Patchright
runtime. All institutions, forms and responses below are synthetic fixtures.
"""
import importlib
import os
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "paper_search_carsi"
PACKAGE = "_wiley_institution_test"
DOI = "10.1002/offline.2026"
ARTICLE = "https://onlinelibrary.wiley.com/doi/" + DOI
CHOOSER = "https://onlinelibrary.wiley.com/action/ssostart"
SUBMITTED = "https://onlinelibrary.wiley.com/fixture/submitted"
PERSONAL = "https://onlinelibrary.wiley.com/fixture/personal"
OPENATHENS = "https://openathens.fixture.invalid/fixture/login"
# Wiley's own SSO start for the current article: the fallback when an article
# page shows no trustworthy institution control.
SSOSTART = CHOOSER + "?redirectUri=%2Fdoi%2F" + DOI.replace("/", "%2F")
FULL_TEXT = '<title>Target article</title><section class="article-section__full">Full access</section>'


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class WileyInstitutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        # Chrome upgrades http navigations to public hosts to https (HTTPS-Upgrades
        # and the default-on balanced HTTPS-First mode); off, so the plain-http
        # Wiley fixture page actually loads over http.
        cls.browser = cls.driver.chromium.launch(
            channel="chrome", headless=True,
            args=["--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND",
                  "--disable-features=HttpsUpgrades,HttpsFirstBalancedMode"],
        )
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.enterContext(patch.dict(sys.modules))
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch.object(socket, "getaddrinfo", side_effect=AssertionError("network forbidden")))
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(SOURCE)]
        sys.modules[PACKAGE] = package
        for _sub in ("browser", "engine", "publishers", "extractors", "_core"):
            _m = types.ModuleType(PACKAGE + "." + _sub)
            _m.__path__ = [str(SOURCE / _sub)]
            sys.modules[_m.__name__] = _m

        def module(name, **attrs):
            value = types.ModuleType(PACKAGE + "." + name)
            value.__dict__.update(attrs)
            sys.modules[value.__name__] = value
            return value

        module("config", load_config=Mock(side_effect=AssertionError("config forbidden")),
               parse_proxy_pool=lambda *a, **k: [],
               DEFAULT_CONFIG={"browser_stall_notify_after": 30, "browser_page_wait_timeout": 60})
        module("progress_reporter", update=Mock(), report_stage=Mock(), read_state=Mock(return_value={}),
               has_attention=Mock(return_value=False), set_attention=Mock(),
               update_attention_deadline=Mock(), clear_attention=Mock())
        extractor = module("extractors.pdf_extractor", extract_from_bytes=Mock())
        module("extractors", pdf_extractor=extractor)
        self.batch = importlib.import_module(PACKAGE + ".engine.batch")
        profiles = importlib.import_module(PACKAGE + ".publishers.profiles")
        self.d = self.batch.PublisherBatchDownloader(
            {"publisher_institution_federation": "carsi"}, profile=profiles.WILEY_PROFILE,
            institution_query="Synthetic University A", login_timeout_sec=10,
        )
        self.d._save_publisher_session = Mock(side_effect=AssertionError("credential I/O forbidden"))
        self.result = self.batch.DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.requests = []
        self.unexpected_requests = []
        self.article_urls = {ARTICLE}
        self.chooser_urls = {CHOOSER, SSOSTART}
        self.article_html = self.article_controls()
        self.chooser_html = '''<title>Institution selection</title>
          <form action="/fixture/submitted">
            <input name="institution" placeholder="Institution">
            <button type="submit">Continue</button>
          </form>'''

        def respond(route):
            url = route.request.url
            self.requests.append(url)
            if url in self.article_urls:
                html = self.article_html
            elif url in self.chooser_urls:
                html = self.chooser_html
            elif url in (PERSONAL, OPENATHENS) or url == SUBMITTED or url.startswith(SUBMITTED + "?"):
                html = "<title>Synthetic destination</title>Fixture only"
            else:
                self.unexpected_requests.append(url)
                route.abort()
                return
            route.fulfill(status=200, content_type="text/html", body=html)

        self.context.route("**/*", respond)
        self.page = self.context.new_page()
        self.page.set_default_timeout(2000)

    def tearDown(self):
        self.assertEqual(self.unexpected_requests, [])

    @staticmethod
    def article_controls():
        # Deliberately put the unrelated routes first in document order.
        return f'''<title>Target article</title>
          <a id="openathens" href="{OPENATHENS}">Sign in with OpenAthens</a>
          <a id="personal" href="{PERSONAL}">Personal account login</a>
          <a id="institution" href="{CHOOSER}">Institutional Login</a>'''

    def test_carsi_uses_official_institution_control_before_openathens_or_personal(self):
        for host in ("onlinelibrary.wiley.com", "acrjournals.onlinelibrary.wiley.com"):
            with self.subTest(host=host):
                article = "https://" + host + "/doi/" + DOI
                self.article_urls.add(article)
                self.requests.clear()
                self.page.goto(article)
                self.assertTrue(self.d._click_sso_entry(self.page, self.result))
                self.page.wait_for_url(CHOOSER)
                self.assertEqual(self.requests, [article, CHOOSER])
                self.assertEqual(self.page.get_by_placeholder("Institution").input_value(), "")

    def test_carsi_does_not_use_standalone_openathens_or_personal_entry(self):
        fixtures = (
            f'<a href="{OPENATHENS}">Sign in with OpenAthens</a>',
            f'<a href="{PERSONAL}">Personal account login</a>',
            f'<div>Institutional Login <a href="{PERSONAL}">Personal account</a></div>',
            f'<a href="{PERSONAL}">Institutional Login / Register personal account</a>',
        )
        for html in fixtures:
            with self.subTest(html=html):
                self.article_html = "<title>Target article</title>" + html
                self.requests.clear()
                self.page.goto(ARTICLE)
                # Never the standalone/personal/forged link: only Wiley's own
                # SSO start for this article.
                self.assertTrue(self.d._click_sso_entry(self.page, self.result))
                self.page.wait_for_timeout(50)
                self.assertEqual(self.page.url, SSOSTART)
                self.assertEqual(self.requests, [ARTICLE, SSOSTART])

    def test_fixed_input_values_do_not_prevent_institution_entry(self):
        self.article_html += '''<input type="checkbox"><input type="radio">
          <input type="submit" value="Search"><input type="button" value="Go">
          <input readonly value="Fixed article text">'''
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._click_sso_entry(self.page,self.result))
        self.page.wait_for_url(CHOOSER)
        self.assertEqual(self.requests,[ARTICLE,CHOOSER])

    def test_official_href_accepts_base_and_journal_hosts_and_relative_paths(self):
        journal = "https://acrjournals.onlinelibrary.wiley.com"
        fixtures = (
            (ARTICLE, journal + "/action/ssostart", journal + "/action/ssostart"),
            (journal + "/doi/" + DOI, "/action/ssostart", journal + "/action/ssostart"),
            (ARTICLE, "//onlinelibrary.wiley.com/action/ssostart", CHOOSER),
        )
        for article, href, destination in fixtures:
            with self.subTest(article=article, href=href):
                self.article_urls.add(article)
                self.chooser_urls.add(destination)
                self.article_html = f'<a href="{href}">Institutional Login</a>'
                self.requests.clear()
                self.page.goto(article)
                self.assertTrue(self.d._click_sso_entry(self.page, self.result))
                self.page.wait_for_url(destination)
                self.assertEqual(self.requests, [article, destination])
                self.assertEqual(self.page.get_by_placeholder("Institution").input_value(), "")

    def test_untrusted_current_host_cannot_activate_even_an_official_href(self):
        origins = (
            "https://onlinelibrary.wiley.com.evil.invalid",
            "https://fakeonlinelibrary.wiley.com",
            "https://school.fixture.invalid",
            "http://onlinelibrary.wiley.com",
        )
        for origin in origins:
            with self.subTest(origin=origin):
                article = origin + "/doi/" + DOI
                self.article_urls.add(article)
                self.article_html = f'<a href="{CHOOSER}">Institutional Login</a>'
                self.requests.clear()
                self.page.goto(article)
                # Exercise the helper itself as well as its public dispatcher;
                # an off-host human-login guard must not conceal helper defects.
                self.assertFalse(self.d.adapter.open_institution_entry(self.page, self.result))
                self.assertFalse(self.d._click_sso_entry(self.page, self.result))
                self.page.wait_for_timeout(50)
                self.assertEqual(self.page.url, article)
                self.assertEqual(self.requests, [article])

    def test_institutional_label_cannot_authorize_forged_or_external_href(self):
        hrefs = (
            "https://onlinelibrary.wiley.com.evil.invalid/action/ssostart",
            "https://fakeonlinelibrary.wiley.com/action/ssostart",
            "https://onlinelibrary.wiley.com@evil.invalid/action/ssostart",
            "//onlinelibrary.wiley.com.evil.invalid/action/ssostart",
            "http://onlinelibrary.wiley.com/action/ssostart",
            OPENATHENS,
            "https://external.fixture.invalid/action/ssostart",
        )
        for href in hrefs:
            with self.subTest(href=href):
                self.article_html = f'<a href="{href}">Institutional Login</a>'
                self.requests.clear()
                self.page.goto(ARTICLE)
                # Never the standalone/personal/forged link: only Wiley's own
                # SSO start for this article.
                self.assertTrue(self.d._click_sso_entry(self.page, self.result))
                self.page.wait_for_timeout(50)
                self.assertEqual(self.page.url, SSOSTART)
                self.assertEqual(self.requests, [ARTICLE, SSOSTART])

    def test_external_institutional_label_does_not_preempt_official_entry(self):
        self.article_html = (f'<a href="{OPENATHENS}">Institutional Login</a>'
                             f'<a href="{CHOOSER}">Institutional Login</a>')
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.page.wait_for_url(CHOOSER)
        self.assertEqual(self.requests, [ARTICLE, CHOOSER])

    def test_school_page_keeps_user_input_despite_institutional_login_links(self):
        school_page = "https://school.fixture.invalid/fixture/chooser"
        self.chooser_urls.add(school_page)
        self.chooser_html += (f'<a href="{CHOOSER}">Institutional Login</a>'
                              f'<a href="{OPENATHENS}">Institutional Login</a>')
        self.page.goto(school_page)
        field = self.page.get_by_placeholder("Institution")
        field.fill("User-selected institution")
        for _ in range(2):
            self.assertFalse(self.d._click_sso_entry(self.page, self.result))
            self.assertFalse(self.d._select_institution(self.page, self.result))
            self.d._click_optional_continue(self.page, self.result)
            self.assertFalse(self.d._click_openathens_entry(self.page, self.result))
        self.assertEqual(field.input_value(), "User-selected institution")
        self.assertEqual(self.page.url, school_page)
        self.assertEqual(self.requests, [school_page])

    def test_official_school_form_is_not_submitted_as_an_institution_entry(self):
        self.chooser_html = self.chooser_html.replace('>Continue</button>', '>Institutional Login</button>')
        self.page.goto(CHOOSER)
        field = self.page.get_by_placeholder("Institution")
        field.fill("User-selected institution")
        # Count submission before any navigation; suppress it solely to retain
        # the input for the assertions, not to hide an automatic click.
        self.page.evaluate("""() => {
          window.fixtureSubmissions = 0;
          document.querySelector('form').addEventListener('submit', event => {
            window.fixtureSubmissions += 1;
            event.preventDefault();
          });
        }""")
        clicked = self.d._click_sso_entry(self.page, self.result)
        self.assertEqual(self.page.evaluate('window.fixtureSubmissions'), 0,
                         "An institution entry must not submit the user's school form")
        self.assertFalse(clicked)
        self.assertEqual(field.input_value(), "User-selected institution")
        self.assertEqual(self.requests, [CHOOSER])

    def test_hidden_institution_control_does_not_fall_back_to_openathens(self):
        self.article_html = self.article_controls().replace('id="institution"', 'id="institution" hidden')
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.page.wait_for_timeout(50)
        self.assertEqual(self.page.url, SSOSTART)
        self.assertEqual(self.requests, [ARTICLE, SSOSTART])

    def test_access_options_button_is_the_institution_entry(self):
        # The access panel Wiley shows after a PDF request (user screenshot).
        self.article_html = f'''<title>Target article</title>
          <h2>Institutional Login</h2><a href="{CHOOSER}">Access through your institution</a>
          <h2>Log in to Wiley Online Library</h2><a href="{PERSONAL}">Log in with CONNECT</a>'''
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.page.wait_for_url(CHOOSER)
        self.assertEqual(self.requests, [ARTICLE, CHOOSER])

    def test_unentitled_abstract_page_is_unknown_and_full_text_is_access(self):
        # Wiley shows "PDF" and "Read the full text" to everyone and no offer
        # without access: nothing either way, the PDF is tried first (batch.py).
        self.article_html = "<title>Target article</title>Abstract only <a href='/doi/pdf/x'>PDF</a> Read the full text"
        self.page.goto(ARTICLE)
        self.assertEqual(self.d._access_verdict(self.page), "unknown")
        self.article_html = FULL_TEXT
        self.page.goto(ARTICLE)
        self.assertEqual(self.d._access_verdict(self.page), "in")
        # Signed in, an old scanned article has no full-text sections, only the
        # "Full Access" badge by its title (J Physiol 1965, 2026-11-02).
        self.article_html = ("<title>Target article</title><div class='doi-access'>Full Access</div>"
                             "<h1>Target article</h1><a href='/doi/pdf/x'>PDF</a>")
        self.page.goto(ARTICLE)
        self.assertEqual(self.d._access_verdict(self.page), "in")
        # The school next to the logo in the page header.
        self.article_html = ("<title>Target article</title><header><div class='institution-wrapper'>"
                             "Synthetic University A</div></header><h1>Target article</h1>")
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._has_publisher_institution_session(self.page))

    def test_carsi_preserves_user_school_input_and_never_submits_or_switches_provider(self):
        self.chooser_html += f'<a href="{OPENATHENS}">Sign in with OpenAthens</a>'
        for school in ("Synthetic University A", "Synthetic College B", ""):
            with self.subTest(school=school):
                self.d.institution_query = school
                self.requests.clear()
                self.page.goto(CHOOSER)
                field = self.page.get_by_placeholder("Institution")
                field.fill("User-selected institution")
                for _ in range(2):
                    self.assertFalse(self.d._select_institution(self.page, self.result))
                    self.d._click_optional_continue(self.page, self.result)
                    self.assertFalse(self.d._click_openathens_entry(self.page, self.result))
                self.assertEqual(field.input_value(), "User-selected institution")
                self.assertEqual(self.page.url, CHOOSER)
                self.assertEqual(self.requests, [CHOOSER])
                # A test-driven user click still works: the fixture is not a
                # disabled form that would conceal an automatic-submit bug.
                self.page.get_by_role("button", name="Continue", exact=True).click()
                self.page.wait_for_url(SUBMITTED + "**")
                self.assertEqual(len(self.requests), 2)
                self.assertTrue(self.requests[-1].startswith(SUBMITTED + "?"))

    def test_login_wait_keeps_selection_manual_until_user_returns_to_article(self):
        # No configured school: the user picks one. (A configured school missing
        # from the list ends the login at once, 2026-11-01.)
        self.d.institution_query = ""
        self.page.goto(ARTICLE)
        loops = 0
        def user_action(seconds):
            nonlocal loops
            if seconds != 1:  # one pass of the login wait, which checks the page every second
                return
            loops += 1
            self.assertLessEqual(loops, 2, "must finish after the user's return")
            self.assertEqual(self.page.url, CHOOSER)
            field = self.page.get_by_placeholder("Institution")
            if loops == 1:
                field.fill("User-selected institution")
            else:
                self.assertEqual(field.input_value(), "User-selected institution")
                self.assertEqual(self.requests, [ARTICLE, CHOOSER])
                self.article_html = FULL_TEXT
                self.page.goto(ARTICLE)
        with patch.object(self.batch.time, "sleep", side_effect=user_action):
            self.assertTrue(self.d._complete_login_from_current_page(self.page, self.result))
        self.assertEqual(loops, 2)
        self.assertEqual(self.requests, [ARTICLE, CHOOSER, ARTICLE])
        self.d._save_publisher_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""After the school IdP, a publisher that lands on its home page is sent back to the article;
so too Science's login page its login ends on once the school was chosen."""
import os
import unittest
from unittest.mock import Mock, patch

from paper_search_school.engine import batch
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import infer_publisher_profile_from_url

DOI = "10.1080/01635581.2025.0000001"
CHOOSER = "https://www.tandfonline.com/action/ssostart?redirectUri=%2Fdoi%2Ffull%2F" + DOI.replace("/", "%2F")
IDP = "https://idp.fixture.example/login"
HOME = "https://www.tandfonline.com/"
SCIENCE_DOI = "10.1126/scitranslmed.example1"
SCIENCE_ARTICLE = "https://www.science.org/doi/" + SCIENCE_DOI
SCIENCE_CHOOSER = "https://www.science.org/action/ssostart?redirectUri=%2Fdoi%2F10.1126%2Fscitranslmed.example1"
SCIENCE_LANDING = "https://www.science.org/action/authenticateSharedSP"


class LoginLandingRuleTests(unittest.TestCase):
    def test_science_names_its_login_landing(self):
        from paper_search_school.adapters import adapter_for
        adapter = adapter_for(Mock(profile=infer_publisher_profile_from_url(SCIENCE_ARTICLE)))
        self.assertEqual(type(adapter).__name__, "ScienceAdapter")
        self.assertTrue(adapter.is_login_landing(SCIENCE_LANDING))
        self.assertTrue(adapter.is_login_landing("https://www.science.org/action/authenticateSharedSP?x=1"))
        self.assertFalse(adapter.is_login_landing(SCIENCE_CHOOSER))
        self.assertFalse(adapter.is_login_landing(SCIENCE_ARTICLE))
        self.assertFalse(adapter.is_login_landing("https://evil.example/action/authenticateSharedSP"))

    def test_an_atypon_sites_home_page_is_a_login_landing(self):
        """PNAS 2026-11-17: its institution search's entries end the login on its home page."""
        from paper_search_school.adapters import adapter_for
        adapter = adapter_for(Mock(profile=infer_publisher_profile_from_url("https://www.pnas.org/doi/10.1073/pnas.2610670123")))
        self.assertEqual(type(adapter).__name__, "PNASAdapter")
        self.assertTrue(adapter.is_login_landing("https://www.pnas.org/"))
        self.assertTrue(adapter.is_login_landing("https://www.pnas.org"))
        self.assertFalse(adapter.is_login_landing("https://www.pnas.org/doi/10.1073/pnas.2610670123"))
        self.assertFalse(adapter.is_login_landing("https://www.pnas.org/action/ssostart?uri=/doi/10.1073/pnas.2610670123"))
        self.assertFalse(adapter.is_login_landing("https://evil.example/"))


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class IdpReturnArticleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.requests = []
        self.home_body = "<title>Taylor &amp; Francis Online</title>Access provided by Example University"
        self.science_article_body = "<title>Target article</title>Access provided by Example University<p>Full text</p>"

        def respond(route):
            url = route.request.url
            self.requests.append(url)
            if url.startswith("https://www.science.org/doi/"):
                body = self.science_article_body
            elif url.startswith(SCIENCE_LANDING):
                body = ("<title>Login | Science | AAAS</title><h1>LOG IN</h1><p>Find your institution</p>"
                        '<input placeholder="Type the name of your institution">')
            elif url.startswith("https://www.tandfonline.com/doi/"):
                body = "<title>Target article</title>Access provided by Example University<p>Full text</p>"
            elif url == IDP:
                body = "<title>School login</title>"
            elif url == HOME:
                body = self.home_body
            else:
                body = "<title>Institution selection</title>"
            route.fulfill(status=200, content_type="text/html", body=body)

        self.context.route("**/*", respond)
        self.page = self.context.new_page()
        profile = infer_publisher_profile_from_url("https://www.tandfonline.com/doi/full/" + DOI)
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"}, profile=profile,
                                          institution_query="Example University", login_timeout_sec=60)
        for name in ("_click_sso_entry", "_select_institution", "_click_openathens_entry",
                     "_dismiss_cookie_banners", "_click_optional_continue"):
            setattr(self.d, name, Mock(return_value=False))
        # doi.org redirects to this page in production; the fixture uses it directly.
        self.result = DownloadResult(doi=DOI, status="failed",
                                     article_url="https://www.tandfonline.com/doi/full/" + DOI)

    def test_home_page_after_the_idp_returns_to_the_article(self):
        self.page.goto(CHOOSER)
        steps = iter([IDP, HOME])

        def user(seconds):
            if seconds == 1:  # one pass of the login wait, which checks the page every second
                target = next(steps, None)
                if target:
                    self.page.goto(target)

        with patch.object(batch.time, "sleep", side_effect=user):
            ok = self.d._complete_login_from_current_page(self.page, self.result)
        self.assertTrue(ok)
        self.assertTrue(self.page.url.startswith("https://www.tandfonline.com/doi/"))
        self.assertIn("idp_return_article", [e["state"] for e in self.result.events])

    def test_home_page_without_an_idp_visit_or_session_is_left_alone(self):
        # Not sent to the article; with no way to a school's login on it either, the
        # login ends there (2026-11-18: no school route, no wait).
        self.home_body = "<title>Taylor &amp; Francis Online</title>Login | Register"
        self.page.goto(HOME)
        calls = {"n": 0}

        def tick(seconds):
            calls["n"] += 1
            if calls["n"] > 8:
                raise TimeoutError("stop")

        with patch.object(batch.time, "sleep", side_effect=tick):
            ok = self.d._complete_login_from_current_page(self.page, self.result)
        self.assertFalse(ok)
        self.assertEqual(self.result.reason, "no_institution_entry")
        self.assertEqual(self.page.url, HOME)
        self.assertNotIn("idp_return_article", [e["state"] for e in self.result.events])

    def _science(self):
        profile = infer_publisher_profile_from_url(SCIENCE_ARTICLE)
        d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"}, profile=profile,
                                     institution_query="Example University", login_timeout_sec=60)
        for name in ("_click_sso_entry", "_select_institution", "_click_openathens_entry",
                     "_dismiss_cookie_banners", "_click_optional_continue"):
            setattr(d, name, Mock(return_value=False))
        return d, DownloadResult(doi=SCIENCE_DOI, status="failed", article_url=SCIENCE_ARTICLE)

    def test_science_login_landing_after_choosing_the_school_returns_to_the_article(self):
        # Windows, 2026-11-16: the school's sign-in was still valid, the IdP passed unseen
        # and Science stayed on authenticateSharedSP; choosing the school again there led
        # nowhere, while the article itself had its full text.
        d, result = self._science()
        self.page.goto(SCIENCE_CHOOSER)
        d._event(result, "institution_selected", "Example University (entityID)")
        steps = iter([SCIENCE_LANDING])

        def user(seconds):
            if seconds == 1:
                target = next(steps, None)
                if target:
                    self.page.goto(target)

        with patch.object(batch.time, "sleep", side_effect=user):
            ok = d._complete_login_from_current_page(self.page, result)
        self.assertTrue(ok)
        self.assertEqual(self.page.url, SCIENCE_ARTICLE)
        returns = [e["detail"] for e in result.events if e["state"] == "idp_return_article"]
        self.assertEqual(returns, [SCIENCE_LANDING])
        # The login counts as done, unseen as it went: the page read before it is read again
        # (PNAS via OpenAthens, 2026-11-17: the Markdown was missing).
        d._item_result = result
        self.assertTrue(d._school_login_done())

    def test_science_login_landing_before_any_school_choice_is_left_alone(self):
        d, result = self._science()
        self.page.goto(SCIENCE_LANDING)
        calls = {"n": 0}

        def tick(seconds):
            calls["n"] += 1
            if calls["n"] > 8:
                raise TimeoutError("stop")

        with patch.object(batch.time, "sleep", side_effect=tick), self.assertRaises(TimeoutError):
            d._complete_login_from_current_page(self.page, result)
        self.assertNotIn("idp_return_article", [e["state"] for e in result.events])

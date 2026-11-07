"""After the school IdP, a publisher that lands on its home page is sent back to the article."""
import os
import unittest
from unittest.mock import Mock, patch

from paper_search_carsi.engine import batch
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import infer_publisher_profile_from_url

DOI = "10.1080/01635581.2025.0000001"
CHOOSER = "https://www.tandfonline.com/action/ssostart?redirectUri=%2Fdoi%2Ffull%2F" + DOI.replace("/", "%2F")
IDP = "https://idp.fixture.example/login"
HOME = "https://www.tandfonline.com/"


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
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

        def respond(route):
            url = route.request.url
            self.requests.append(url)
            if url.startswith("https://www.tandfonline.com/doi/"):
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
        self.home_body = "<title>Taylor &amp; Francis Online</title>Login | Register"
        self.page.goto(HOME)
        calls = {"n": 0}

        def tick(seconds):
            calls["n"] += 1
            if calls["n"] > 8:
                raise TimeoutError("stop")

        with patch.object(batch.time, "sleep", side_effect=tick), self.assertRaises(TimeoutError):
            self.d._complete_login_from_current_page(self.page, self.result)
        self.assertNotIn("idp_return_article", [e["state"] for e in self.result.events])

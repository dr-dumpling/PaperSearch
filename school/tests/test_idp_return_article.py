"""After the school IdP, a publisher that lands on its home page is sent back to the article;
so too Science's login page its login ends on once the school was chosen."""
import os
import unittest
from unittest.mock import MagicMock, Mock, patch

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


class LoginLandingStillOfferedTests(unittest.TestCase):
    """NEJM Catalyst (10.1056/cat.25.0121, Windows 2026-11-23): the school's sign-in kept from
    the paper before, the IdP passed unseen, the login ended on authenticateSharedSP; the
    article opened from there still offered "Get Access", and the wait ran out on it after
    60 s (login_not_reached). The login went round: the PDF is tried once and, the page's
    offer still there, the school has no access."""

    DOI = "10.1056/cat.25.0121"
    ARTICLE = "https://catalyst.nejm.org/doi/10.1056/CAT.25.0121"
    CHOOSER = "https://catalyst.nejm.org/action/ssostart"
    LANDING = "https://catalyst.nejm.org/action/authenticateSharedSP"

    def wait(self, urls, no_access="Get Access"):
        from paper_search_school.engine import batch_login
        from paper_search_school.engine.batch_user import PdfFoundWhileWaiting
        from paper_search_school.publishers.profiles import infer_publisher_profile
        from tests.thread_clock import this_thread_only

        d = PublisherBatchDownloader({}, profile=infer_publisher_profile(self.DOI), login_timeout_sec=300)
        self.assertEqual(type(d.adapter).__name__, "NEJMAdapter")
        result = DownloadResult(doi=self.DOI, status="failed", article_url="https://doi.org/" + self.DOI)
        d._item_result = result
        d._event(result, "institution_selected", "Example University (entityID)")
        for name in ("_dismiss_cookie_banners", "_click_openathens_entry", "_select_institution",
                     "_institution_pdf_entitlement_missing", "_challenge_shell", "_follow_federated_login_option",
                     "_return_to_record_article_if_needed", "_article_access_available",
                     "_has_publisher_institution_session", "_is_challenge_page", "_click_optional_continue",
                     "_return_from_login_site", "_is_human_login_page", "_check_user_decision"):
            setattr(d, name, Mock(return_value=False))
        d._click_sso_entry = Mock(return_value=True)
        d._login_block_reason = Mock(return_value="")
        d._title = Mock(return_value="Article")
        d._looks_logged_out = Mock(return_value=True)  # "Get Access" over the abstract
        d._probe_pdf = Mock(return_value=None)
        d._no_access_after_login = Mock(return_value=no_access)
        page = MagicMock()
        page.url = urls[0]
        page.evaluate.return_value = ""
        page.locator.return_value.inner_text.return_value = ""
        clock = [1000.0]
        steps = iter(urls[1:])

        def sleep(seconds):
            clock[0] += seconds
            page.url = next(steps, page.url)

        def open_article(page, url, **options):
            page.url = self.ARTICLE

        fake_time, fake_sleep = this_thread_only(lambda: clock[0], sleep)
        with patch.object(batch.time, "sleep", fake_sleep), patch.object(batch.time, "time", fake_time), \
                patch.object(batch_login, "open_page", side_effect=open_article):
            try:
                outcome = d._complete_login_from_current_page(page, result)
            except PdfFoundWhileWaiting as found:
                outcome = found
        return d, result, outcome, clock[0] - 1000

    def test_back_through_the_landing_still_offered_ends_as_not_subscribed(self):
        for urls in ([self.CHOOSER, self.LANDING], [self.LANDING]):  # the chooser seen by a pass, or not
            with self.subTest(urls=urls):
                d, result, outcome, waited = self.wait(urls)
                self.assertIs(outcome, False)
                self.assertEqual(result.reason, "institution_pdf_entitlement_missing")
                states = [e["state"] for e in result.events]
                self.assertLess(states.index("idp_return_article"), states.index("no_access_after_login"))
                self.assertIn({"state": "pdf_probe", "detail": "after the login round trip"},
                              [{"state": e["state"], "detail": e.get("detail")} for e in result.events])
                d._probe_pdf.assert_called_once()
                self.assertLess(waited, 10)
                d._item_result = result
                self.assertTrue(d._school_login_done())

    def test_back_through_the_landing_with_nothing_conclusive_the_wait_goes_on(self):
        d, result, outcome, waited = self.wait([self.LANDING], no_access="")
        self.assertIs(outcome, False)
        self.assertNotEqual(result.reason, "institution_pdf_entitlement_missing")
        self.assertGreaterEqual(waited, 60)  # a page wait, as before


class RouteRoundTripTests(LoginLandingStillOfferedTests):
    """Springer (Windows, 2026-11-24): the chosen school, Springer's federated sign-on, straight back to the article before
    the wait could see any of it; the article still a preview, the wait ran out on it after 60 s (login_not_reached) for
    8 papers of journals the school does not subscribe to. The login's route went round: as one the wait saw."""

    DOI = "10.1134/s1061933x25600666"
    ARTICLE = "https://link.springer.com/article/10.1134/S1061933X25600666"
    ROUTE = ["https://sp.springer.com/saml/login?idp=https%3A%2F%2Fidp.example.edu.cn%2Fidp%2Fshibboleth",
             "https://fsso.springer.com/saml/SSO", ARTICLE]

    def wait(self, urls, no_access="This is a preview of subscription content", route=True):
        from paper_search_school.engine import batch_login
        from paper_search_school.engine.batch_user import PdfFoundWhileWaiting
        from paper_search_school.publishers.profiles import infer_publisher_profile
        from tests.thread_clock import this_thread_only

        # Springer Nature's profile (the batch took 10.1134/'s from its article's site, link.springer.com).
        d = PublisherBatchDownloader({"idp_entity_id": "https://idp.example.edu.cn/idp/shibboleth"},
                                     profile=infer_publisher_profile("10.1007/s00125-024-1"), login_timeout_sec=300)
        result = DownloadResult(doi=self.DOI, status="failed", article_url="https://doi.org/" + self.DOI)
        d._item_result = result
        page = MagicMock()
        page.url = urls[0]
        page.evaluate.return_value = ""
        page.locator.return_value.inner_text.return_value = ""
        d._follow_login_route(page, result)
        d._event(result, "institution_selected", "Example University (entityID)")
        if route:
            for url in self.ROUTE:
                d._note_route_hop(url, result)
        for name in ("_dismiss_cookie_banners", "_click_openathens_entry", "_select_institution",
                     "_institution_pdf_entitlement_missing", "_challenge_shell", "_follow_federated_login_option",
                     "_return_to_record_article_if_needed", "_article_access_available",
                     "_has_publisher_institution_session", "_is_challenge_page", "_click_optional_continue",
                     "_return_from_login_site", "_is_human_login_page", "_check_user_decision"):
            setattr(d, name, Mock(return_value=False))
        d._click_sso_entry = Mock(return_value=True)
        d._login_block_reason = Mock(return_value="")
        d._title = Mock(return_value="Article")
        d._looks_logged_out = Mock(return_value=True)
        d._probe_pdf = Mock(return_value=None)
        d._no_access_after_login = Mock(side_effect=lambda page, result, **kw: no_access if d._school_login_done() else "")
        clock = [1000.0]

        def sleep(seconds):
            clock[0] += seconds

        fake_time, fake_sleep = this_thread_only(lambda: clock[0], sleep)
        with patch.object(batch.time, "sleep", fake_sleep), patch.object(batch.time, "time", fake_time), \
                patch.object(batch_login, "open_page"):
            try:
                outcome = d._complete_login_from_current_page(page, result)
            except PdfFoundWhileWaiting as found:
                outcome = found
        return d, result, outcome, clock[0] - 1000

    def test_back_through_the_landing_still_offered_ends_as_not_subscribed(self):
        d, result, outcome, waited = self.wait([self.ARTICLE])
        self.assertIs(outcome, False)
        self.assertEqual(result.reason, "institution_pdf_entitlement_missing")
        self.assertIn({"state": "login_round_trip_returned", "detail": "link.springer.com (by its route)"},
                      [{"state": e["state"], "detail": e.get("detail")} for e in result.events])
        self.assertIn("after the login round trip", [e.get("detail") for e in result.events if e["state"] == "pdf_probe"])
        self.assertLess(waited, 10)

    def test_back_through_the_landing_with_nothing_conclusive_the_wait_goes_on(self):
        d, result, outcome, waited = self.wait([self.ARTICLE], no_access="")
        self.assertNotEqual(result.reason, "institution_pdf_entitlement_missing")
        self.assertGreaterEqual(waited, 60)

    def test_without_the_route_going_round_the_wait_goes_on_as_before(self):
        d, result, outcome, waited = self.wait([self.ARTICLE], route=False)
        self.assertNotEqual(result.reason, "institution_pdf_entitlement_missing")
        self.assertNotIn("login_round_trip_returned", [e["state"] for e in result.events])
        self.assertGreaterEqual(waited, 60)


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

"""After the school's login the IdP may leave the browser on the school's own site
(a school's portal after CAS, 2026-11-02): such a page,
unchanged for a while, ends the item as idp_no_return_to_publisher. Mocked pages."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from paper_search_carsi.engine import access_rules, batch, bridge
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.model import PublisherProfile

DOI = "10.1061/jsendh.steng-16404"
ARTICLE = "https://ascelibrary.org/doi/10.1061/JSENDH.STENG-16404"
CHOOSER = "https://ascelibrary.org/action/ssostart?redirectUri=%2Fdoi%2F10.1061%2FJSENDH.STENG-16404"
IDP = "https://idp.example.edu.cn/idp/profile/SAML2/Redirect/SSO?execution=e1s1"
CAS = "https://uis.example.edu.cn/login?service=https%3A%2F%2Fidp.example.edu.cn%2Fidp"
PORTAL = "https://uis.example.edu.cn/login/home.do"
CONFIG = {"publisher_institution_federation": "carsi", "idp_entity_id": "https://idp.example.edu.cn/idp/shibboleth"}
PROFILE = PublisherProfile(name="Fixture Press", article_url_template="https://ascelibrary.org/doi/{doi}",
                           pdf_url_templates=(), success_url_markers=("ascelibrary.org/doi/",), auth_url_markers=(),
                           auth_title_markers=(), sso_text_markers=(), base_domains=("ascelibrary.org",))
PORTAL_PAGE = {"ready": True, "login": False, "handover": False}


class RegistrableDomainTests(unittest.TestCase):
    def test_a_school_s_domain_keeps_its_registry_suffix(self):
        for host, domain in (("idp.example.edu.cn", "example.edu.cn"), ("uis.example.edu.cn", "example.edu.cn"),
                             ("login.example.ac.uk", "example.ac.uk"), ("idp.example.org", "example.org"),
                             ("example.edu", "example.edu")):
            self.assertEqual(access_rules.registrable_domain(host), domain, host)


class SchoolSiteTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader(CONFIG, profile=PROFILE, institution_query="Example University")
        self.result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        self.result._visited_idp = True
        self.page = Mock(url=PORTAL)
        self.state = dict(PORTAL_PAGE)
        self.page.evaluate.side_effect = lambda script, *args: self.state if script == self.d._SCHOOL_PAGE_STATE_JS else ""

    def check(self, at):
        with patch.object(batch.time, "time", return_value=at), \
             patch("paper_search_carsi.engine.batch_login.time.time", return_value=at):
            return self.d._stuck_on_school_site(self.page, self.result)

    def test_the_school_s_portal_unchanged_for_its_time_ends_the_login(self):
        self.assertEqual(self.check(100.0), "")
        self.assertEqual(self.check(105.0), "")
        self.assertEqual(self.check(112.0), PORTAL)

    def test_its_login_form_and_a_saml_hand_over_keep_the_wait(self):
        for state in ({**PORTAL_PAGE, "login": True}, {**PORTAL_PAGE, "handover": True}, {**PORTAL_PAGE, "ready": False}):
            with self.subTest(state=state):
                self.state = state
                self.assertEqual(self.check(100.0), "")
                self.assertEqual(self.check(200.0), "")

    def test_only_after_the_login_started_and_only_on_the_school_s_site(self):
        self.result._visited_idp = False
        self.check(100.0)
        self.assertEqual(self.check(200.0), "")  # no IdP, no login form seen yet
        self.state = {**PORTAL_PAGE, "login": True}
        self.check(201.0)  # the school's login form: the login has started
        self.state = dict(PORTAL_PAGE)
        self.check(202.0)
        self.assertEqual(self.check(215.0), PORTAL)
        for url in (ARTICLE, "https://www.other-school.edu.cn/home"):
            with self.subTest(url=url):
                self.page.url = url
                self.check(300.0)
                self.assertEqual(self.check(400.0), "")


class LoginLoopTests(unittest.TestCase):
    def test_the_login_wait_ends_on_the_portal_with_its_reason(self):
        d = PublisherBatchDownloader(CONFIG, profile=PROFILE, login_timeout_sec=300)
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        d._item_result = result
        for name in ("_dismiss_cookie_banners", "_click_openathens_entry", "_select_institution",
                     "_institution_pdf_entitlement_missing", "_challenge_shell", "_follow_federated_login_option",
                     "_return_to_record_article_if_needed", "_article_access_available", "_is_challenge_page",
                     "_has_publisher_institution_session", "_click_optional_continue", "_return_from_login_site",
                     "_check_user_decision"):
            setattr(d, name, Mock(return_value=False))
        d._click_sso_entry = Mock(return_value=True)
        d._login_block_reason = Mock(return_value="")
        d._title = Mock(return_value="个人桌面")
        d._looks_logged_out = Mock(return_value=True)
        page = MagicMock()
        page.url = CHOOSER
        page.locator.return_value.inner_text.return_value = ""
        page.locator.return_value.count.return_value = 0
        page.evaluate.side_effect = lambda script, *args: PORTAL_PAGE if script == d._SCHOOL_PAGE_STATE_JS else ""
        clock = [1000.0]
        steps = iter([IDP, CAS, PORTAL])

        def sleep(seconds):
            clock[0] += seconds
            page.url = next(steps, page.url)
        with patch.object(batch.time, "sleep", sleep), patch.object(batch.time, "time", lambda: clock[0]):
            self.assertFalse(d._complete_login_from_current_page(page, result))
        self.assertEqual(result.reason, "idp_no_return_to_publisher")
        self.assertLess(clock[0] - 1000, 30)
        event = next(e for e in result.events if e["state"] == "idp_no_return_to_publisher")
        self.assertTrue(event["detail"].startswith(PORTAL))
        self.assertEqual(result.events[-1]["state"], "wait")  # the login waited >10 s: how it ended
        self.assertIn("ended: idp_no_return_to_publisher", result.events[-1]["detail"])
        self.assertEqual(result._stopped_host, "uis.example.edu.cn")


class BridgeTests(unittest.TestCase):
    def test_the_code_is_a_login_failure_with_the_school_s_host(self):
        result = DownloadResult(doi=DOI, status="failed", state="idp_no_return_to_publisher",
                                reason="idp_no_return_to_publisher")
        result._stopped_host = "uis.example.edu.cn"
        self.assertEqual(bridge._failure_reason_code(result), "idp_no_return_to_publisher")
        self.assertEqual(bridge._FAILURE_KINDS["idp_no_return_to_publisher"][0], "idp_no_return_to_publisher")
        artifacts = bridge._browser_artifacts(result, SimpleNamespace(name="Fixture Press"))
        self.assertEqual(artifacts["stopped_host"], "uis.example.edu.cn")
        result._stopped_host = "uis.example.edu.cn/?token=x"
        self.assertNotIn("stopped_host", bridge._browser_artifacts(result, SimpleNamespace(name="x")))

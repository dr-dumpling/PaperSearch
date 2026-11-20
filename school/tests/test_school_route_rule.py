"""A school login only through a school route (user, 2026-11-18).

An MDPI page whose full text was not seen went on to MDPI's own account login
(auth.mdpi.com: e-mail, password, ORCID) and waited for the user. Now: a page with no
way to any school's login, or the publisher's own account sign-in, ends the login at
once (``no_institution_entry``) and the same site's later papers in the batch do not
look again; an article open to all whose page shows no full text starts no school
login. A page with an institution entry logs in as before. Mocked pages; the two page
scripts themselves on synthetic pages in a local Chrome (opt-in)."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from paper_search_school import login_routes, progress_reporter
from paper_search_school.download_diagnostics import serialize_download_result
from paper_search_school.engine import access_rules, batch, batch_login, bridge
from paper_search_school.engine.batch import DownloadResult, PaperRecord, PublisherBatchDownloader
from paper_search_school.engine.batch_login import NO_INSTITUTION_ENTRY
from paper_search_school.publishers.model import PublisherProfile
from tests.thread_clock import this_thread_only

DOI = "10.9999/oa.2026.101"
LATER = "10.9999/oa.2026.102"
ARTICLE = "https://www.openjournals.example/2026/1/101"
ACCOUNT = "https://auth.openjournals.example/login?return=%2F2026%2F1%2F101"
HOST = "www.openjournals.example"
PROFILE = PublisherProfile(name="Open Fixture Press", article_url_template="https://doi.org/{doi}",
                           pdf_url_templates=(), success_url_markers=("openjournals.example/",), auth_url_markers=(),
                           auth_title_markers=(), sso_text_markers=(),
                           base_domains=("www.openjournals.example", "openjournals.example"))
CONFIG = {"publisher_institution_federation": "carsi", "school_name": "红木兰大学",
          "school_name_en": "Hong Mu-lan University", "idp_entity_id": "https://idp.example.edu.cn/idp/shibboleth"}
NONE_SHOWN = {"signs": [], "password": False, "credential": False, "social": False, "ready": True}
PERSONAL = {**NONE_SHOWN, "password": True, "credential": True, "social": True}
ENTRY = {**NONE_SHOWN, "signs": ['control "Institutional login" -> https://www.openjournals.example/action/ssostart']}
CONTROLS = ['"Sign In / Sign Up" -> /user/login']
CC = "meta dc.rights: https://creativecommons.org/licenses/by/4.0/"


def fake_page(url=ARTICLE, route=NONE_SHOWN, opens=None, boxes=0):
    """A page answering the route script with ``route`` (a dict, or a function giving one),
    the open-access script with ``opens``, its sign-in controls with ``CONTROLS``."""
    page = MagicMock()
    page.url = url
    page.frames = []
    page.is_closed.return_value = False
    page.locator.return_value.count.return_value = boxes
    page.locator.return_value.first.is_visible.return_value = False

    def evaluate(script, *args):
        if script == PublisherBatchDownloader._SCHOOL_ROUTE_JS:
            return route() if callable(route) else route
        if script == access_rules.OPEN_SIGNS_JS:
            return opens
        if script == PublisherBatchDownloader._SIGN_IN_CONTROLS_JS:
            return list(CONTROLS)
        return None

    page.evaluate.side_effect = evaluate
    del page.new_page  # a page, not a context
    return page


class Isolated(unittest.TestCase):
    """Each test with a data folder of its own (the batch's memory is a file there)."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"SCHOOL_DATA_DIR": folder.name})
        env.start()
        self.addCleanup(env.stop)
        self.batch_id = "batch-1"
        current = patch.object(progress_reporter, "batch_id", side_effect=lambda: self.batch_id)
        current.start()
        self.addCleanup(current.stop)

    def downloader(self):
        d = PublisherBatchDownloader(CONFIG, profile=PROFILE, institution_query="红木兰大学", login_timeout_sec=300)
        for name in ("_dismiss_cookie_banners", "_institution_pdf_entitlement_missing", "_challenge_shell",
                     "_click_openathens_entry", "_select_institution"):
            setattr(d, name, Mock(return_value=False))
        d._institution_session = Mock(return_value=None)
        d._snapshot = Mock()
        d._click_sso_entry = Mock(return_value=False)
        return d

    def login(self, d, page, doi=DOI, *, retry=False, wait=False):
        """``_complete_login_from_current_page``; ``wait``: the school's wait may begin (it
        ends at once), else beginning it fails the test."""
        result = DownloadResult(doi=doi, status="failed", article_url="https://doi.org/" + doi)
        if retry:
            result._pdf_retry_login = True
        d._item_result = result
        d._school_login_deadline = Mock(return_value=0) if wait else Mock(side_effect=AssertionError("the wait began"))
        with patch.object(batch.time, "sleep"):
            signed_in = d._complete_login_from_current_page(page, result)
        return signed_in, result


class NoSchoolRouteTests(Isolated):
    def test_a_page_with_only_a_personal_sign_in_ends_at_once_and_says_why(self):
        d = self.downloader()
        signed_in, result = self.login(d, fake_page())
        self.assertFalse(signed_in)
        self.assertEqual(result.reason, NO_INSTITUTION_ENTRY)
        d._click_sso_entry.assert_called_once()  # the entry lookup ran once, nothing is hunted for again
        states = [e["state"] for e in result.events]
        self.assertNotIn("login_state", states)  # no wait for the user
        said = next(e["detail"] for e in result.events if e["state"] == NO_INSTITUTION_ENTRY)
        self.assertIn(ARTICLE, said)
        self.assertIn("access through your institution", said)  # what was looked for
        self.assertIn('"Sign In / Sign Up" -> /user/login',
                      next(e["detail"] for e in result.events if e["state"] == "login_entry_controls"))
        self.assertEqual(d._snapshot.call_args.args[2], "no school login entry")
        # Kept for the batch.
        self.assertIn("no_institution_entry_remembered", states)
        self.assertEqual(login_routes.no_entry_since(HOST, "batch-1"), {"doi": DOI, "reason": NO_INSTITUTION_ENTRY})

    def test_the_same_sites_later_paper_in_the_batch_does_not_look_again(self):
        self.login(self.downloader(), fake_page())
        d = self.downloader()
        signed_in, result = self.login(d, fake_page(ARTICLE.replace("101", "102")), LATER)
        self.assertFalse(signed_in)
        self.assertEqual(result.reason, NO_INSTITUTION_ENTRY)
        d._click_sso_entry.assert_not_called()
        self.assertIn(DOI, next(e["detail"] for e in result.events if e["state"] == NO_INSTITUTION_ENTRY))
        # The login after a failed PDF ends there too, its PDF's reason kept (as the first paper's).
        d = self.downloader()
        signed_in, result = self.login(d, fake_page(), LATER, retry=True)
        self.assertFalse(signed_in)
        self.assertEqual(result.reason, "")
        d._click_sso_entry.assert_not_called()
        # Another batch looks again.
        self.batch_id = "batch-2"
        d = self.downloader()
        self.login(d, fake_page(), LATER)
        d._click_sso_entry.assert_called_once()

    def test_a_later_page_of_the_site_that_shows_an_entry_logs_in_as_before(self):
        self.login(self.downloader(), fake_page())
        d = self.downloader()
        _, result = self.login(d, fake_page(route=ENTRY), LATER, wait=True)
        d._click_sso_entry.assert_called_once()
        d._school_login_deadline.assert_called_once()
        self.assertNotEqual(result.reason, NO_INSTITUTION_ENTRY)

    def test_a_download_on_its_own_is_not_remembered(self):
        self.batch_id = ""
        _, result = self.login(self.downloader(), fake_page())
        self.assertEqual(result.reason, NO_INSTITUTION_ENTRY)
        self.assertNotIn("no_institution_entry_remembered", [e["state"] for e in result.events])

    def test_a_page_with_an_institution_entry_still_goes_on_to_the_login(self):
        late = iter([NONE_SHOWN, ENTRY])  # drawn a moment later by the page's script
        for route in (ENTRY, None, lambda: next(late, ENTRY)):
            with self.subTest(route=route):
                d = self.downloader()
                _, result = self.login(d, fake_page(route=route), wait=True)
                d._school_login_deadline.assert_called_once()  # the school's wait began
                self.assertNotIn(NO_INSTITUTION_ENTRY, [e["state"] for e in result.events])
                self.assertEqual(login_routes.no_entry_since(HOST, "batch-1"), {})

    def test_not_judged_where_the_flow_has_its_own_ending_or_a_route(self):
        cases = {
            "the institution's session shows": lambda d, r: setattr(d, "_institution_session", Mock(return_value="ours")),
            "an adapter's login page was opened": lambda d, r: setattr(d, "_click_sso_entry", Mock(
                side_effect=lambda page, result: d._event(result, "login_page_opened", "https://login.example/x") or False)),
            "the school is not in the publisher's list": lambda d, r: setattr(d, "_select_institution", Mock(
                side_effect=lambda page, result: setattr(result, "_institution_not_listed", True))),
            "someone is typing": lambda d, r: setattr(d, "_has_visible_editable_input", Mock(return_value=True)),
        }
        for name, arrange in cases.items():
            with self.subTest(name):
                d = self.downloader()
                arrange(d, None)
                _, result = self.login(d, fake_page(), wait=True)
                self.assertNotIn(NO_INSTITUTION_ENTRY, [e["state"] for e in result.events])
        # A login or chooser page is the school's way already.
        d = self.downloader()
        _, result = self.login(d, fake_page("https://www.openjournals.example/action/ssostart?redirectUri=x"), wait=True)
        self.assertNotIn(NO_INSTITUTION_ENTRY, [e["state"] for e in result.events])
        # A document still loading may yet draw its entry: the wait goes on as before.
        _, result = self.login(self.downloader(), fake_page(route={**NONE_SHOWN, "ready": False}), wait=True)
        self.assertNotIn(NO_INSTITUTION_ENTRY, [e["state"] for e in result.events])

    def test_the_login_after_a_failed_pdf_keeps_its_own_ending(self):
        d = self.downloader()
        _, result = self.login(d, fake_page(), retry=True)
        states = [e["state"] for e in result.events]
        self.assertIn("login_entry_missing", states)
        self.assertNotIn(NO_INSTITUTION_ENTRY, states)
        self.assertEqual(login_routes.no_entry_since(HOST, "batch-1"), {})


class PersonalSignInTests(Isolated):
    def test_the_publishers_own_account_sign_in_is_not_the_schools(self):
        d = self.downloader()
        result = DownloadResult(doi=DOI, status="failed")
        d._item_result = result
        page = fake_page(ACCOUNT, PERSONAL, boxes=1)
        self.assertIn("the publisher's own account sign-in", d._personal_sign_in_only(page, result))
        self.assertFalse(d._is_human_login_page(page))  # never waited on as the school's login
        # On a sign-in address an e-mail field or ORCID alone is one too; an article page needs a password.
        self.assertTrue(d._personal_sign_in_only(fake_page(ACCOUNT, {**NONE_SHOWN, "social": True}), result))
        self.assertFalse(d._personal_sign_in_only(fake_page(ARTICLE, {**NONE_SHOWN, "credential": True}), result))
        # With a school entry beside it, after the school was chosen, while typing, or off the site: not.
        self.assertFalse(d._personal_sign_in_only(fake_page(ACCOUNT, {**PERSONAL, "signs": ENTRY["signs"]}, boxes=1),
                                                  result))
        self.assertFalse(d._personal_sign_in_only(fake_page("https://idp.example.edu.cn/idp/login", PERSONAL, boxes=1),
                                                  result))
        d._has_visible_editable_input = Mock(return_value=True)
        self.assertFalse(d._personal_sign_in_only(page, result))
        d._has_visible_editable_input = Mock(return_value=False)
        result.events.append({"state": "institution_selected", "detail": "Hong Mu-lan University"})
        self.assertFalse(d._personal_sign_in_only(page, result))

    def test_the_wait_ends_there_once_it_has_stood_for_its_time(self):
        clock = [1000.0]
        fake_time, fake_sleep = this_thread_only(lambda: clock[0], lambda s: clock.__setitem__(0, clock[0] + s))
        d = self.downloader()
        for name in ("_check_federation_school_links", "_return_from_login_site", "_accept_publisher_terms",
                     "_accept_idp_confirmation", "_is_challenge_page", "_follow_federated_login_option",
                     "_open_adapter_login_page", "_click_optional_continue", "_return_to_record_article_if_needed",
                     "_article_access_available", "_has_publisher_institution_session"):
            setattr(d, name, Mock(return_value=False))
        d._page_wait_over = Mock(side_effect=lambda page, since: (False, since))
        d._title = Mock(return_value="Log in")
        d._login_block_reason = Mock(return_value="")
        d._stuck_on_school_site = Mock(return_value="")
        d._idp_confirmation = Mock(return_value="")
        result = DownloadResult(doi=DOI, status="failed", article_url="https://doi.org/" + DOI)
        d._item_result = result
        page = fake_page(ACCOUNT, PERSONAL, boxes=1)
        with patch.object(batch_login.time, "time", fake_time), patch.object(batch_login.time, "sleep", fake_sleep), \
                patch.object(batch_login, "settle"), patch.object(progress_reporter, "set_attention") as attention:
            self.assertFalse(d._complete_login_steps(page, result))
        self.assertEqual(result.reason, NO_INSTITUTION_ENTRY)
        self.assertGreaterEqual(clock[0] - 1000.0, d.PERSONAL_SIGN_IN_SEC)
        self.assertLess(clock[0] - 1000.0, d.PERSONAL_SIGN_IN_SEC + 5)
        attention.assert_not_called()  # the user was never asked to sign in there
        self.assertIn(ACCOUNT, next(e["detail"] for e in result.events if e["state"] == NO_INSTITUTION_ENTRY))
        self.assertEqual(d._snapshot.call_args.args[2], "personal account sign-in only")


class OpenAccessTests(Isolated):
    def test_the_pages_own_licence_metadata_takes_it_as_open(self):
        d = self.downloader()
        for decision, opens, taken in ((("unknown", "", ""), CC, True), (("in", "reader", "full-text sections"), CC, True),
                                       (("unknown", "", ""), None, False), (("unknown", "", ""), "a mock's string", False)):
            with self.subTest(decision=decision, opens=opens):
                result = DownloadResult(doi=DOI, status="failed")
                d._item_result = result
                d._access_decision = Mock(return_value=decision)
                self.assertTrue(d._pdf_first_unless_signed_out(fake_page(opens=opens), result))
                self.assertEqual(bool(getattr(result, "_taken_as_open", "")), taken)
                self.assertEqual(getattr(result, "_pdf_first", False), not taken)  # no school login after its PDF
                self.assertEqual("open_access_signal" in [e["state"] for e in result.events], taken)
        # The institution's session, or a page that says the reader is signed out: not asked.
        for decision in (("in", "session", "session line: Hong Mu-lan University"), ("out", "closed", "Buy article")):
            page = fake_page(opens=CC)
            d._access_decision = Mock(return_value=decision)
            d._pdf_first_unless_signed_out(page, DownloadResult(doi=DOI, status="failed"))
            self.assertNotIn(access_rules.OPEN_SIGNS_JS, [call.args[0] for call in page.evaluate.call_args_list])

    def test_an_open_article_whose_page_shows_no_full_text_starts_no_school_login(self):
        d = PublisherBatchDownloader({"fulltext": True, "login_only": True, **CONFIG}, profile=PROFILE)
        d._school_login_done = Mock(return_value=False)
        d._complete_login_from_current_page = Mock(return_value=False)
        d._remember_fulltext_page = Mock()
        d._access_decision = Mock(return_value=("unknown", "", ""))
        page = fake_page(opens=CC)

        def read(why):
            result = DownloadResult(doi=DOI, status="started")
            d._item_result = result
            d._pdf_first_unless_signed_out(page, result)  # the access check before the page is read
            result.events.append({"state": "fulltext_page_not_saved", "detail": why})
            d._fulltext_after_login_only(page, DOI, result)
            return result

        result = read("fulltext_not_shown: www.openjournals.example main=120")
        d._complete_login_from_current_page.assert_not_called()
        self.assertIn("open_access_no_login", [e["state"] for e in result.events])
        # Reported as a page without its full text (the caller's page_no_fulltext).
        self.assertEqual(bridge._page_not_saved(result), "fulltext_not_shown")
        # A paywall on the page contradicts the licence (PNAS 2026-11-17): the school's login, once.
        read("fulltext_denied: GET ACCESS")
        d._complete_login_from_current_page.assert_called_once()
        # Not taken as open: as before, the login comes first.
        d._complete_login_from_current_page.reset_mock()
        page = fake_page(opens=None)
        read("fulltext_not_shown: www.openjournals.example main=120")
        d._complete_login_from_current_page.assert_called_once()

    def test_only_the_scripts_own_answers_are_evidence(self):
        self.assertEqual(access_rules.open_access_evidence(CC), "open licence: " + CC)
        for found in ("", None, {}, "licensed", "yes"):
            self.assertEqual(access_rules.open_access_evidence(found), "")


class ReportedTests(Isolated):
    def test_kept_for_the_batch_and_by_site(self):
        self.assertTrue(login_routes.remember_no_entry(HOST, "b1", DOI, NO_INSTITUTION_ENTRY, now=1000))
        self.assertEqual(login_routes.no_entry_since(HOST.upper(), "b1", now=1060)["doi"], DOI)
        self.assertEqual(login_routes.no_entry_since(HOST, "b2", now=1060), {})
        self.assertEqual(login_routes.no_entry_since("www.other.example", "b1", now=1060), {})
        self.assertEqual(login_routes.no_entry_since(HOST, "b1", now=1000 + login_routes.NO_ENTRY_KEEP_SEC + 1), {})
        self.assertFalse(login_routes.remember_no_entry(HOST, "", DOI, NO_INSTITUTION_ENTRY))
        # The other ledger is untouched.
        self.assertEqual(login_routes.missing_since("Open Fixture Press", login_routes.school_key(CONFIG)), "")

    def test_reported_as_its_own_code(self):
        result = DownloadResult(doi=DOI, status="failed", state=NO_INSTITUTION_ENTRY, reason=NO_INSTITUTION_ENTRY)
        self.assertEqual(bridge._failure_reason_code(result), NO_INSTITUTION_ENTRY)
        self.assertEqual(bridge._FAILURE_KINDS[NO_INSTITUTION_ENTRY][0], NO_INSTITUTION_ENTRY)
        packet = serialize_download_result(result)
        self.assertEqual((packet["state"], packet["reason"]), (NO_INSTITUTION_ENTRY, NO_INSTITUTION_ENTRY))
        downloader = MagicMock()
        downloader.fetch_one.return_value = SimpleNamespace(ok=False, pdf_path=None, state=NO_INSTITUTION_ENTRY,
                                                            reason=NO_INSTITUTION_ENTRY)
        with tempfile.TemporaryDirectory() as temp, \
                patch("paper_search_school.browser.backend.is_available", return_value=True), \
                patch("paper_search_school.engine.batch.PublisherBatchDownloader", return_value=downloader):
            failure = bridge._try_browser_batch_download(DOI, Path(temp) / "out.pdf", {}, PROFILE)
        self.assertEqual((failure["error_type"], failure["artifacts"]["state"]), (NO_INSTITUTION_ENTRY, NO_INSTITUTION_ENTRY))

    def test_a_failed_pdf_whose_login_found_only_a_personal_sign_in_says_so(self):
        d = self.downloader()
        d._write_diagnostic = Mock()
        d._hold_after_login = Mock()
        d._hold_after_run = Mock()
        d._title = Mock(return_value="Article")
        d._access_decision = Mock(return_value=("unknown", "", ""))
        d._capture_pdf = Mock(return_value=(None, "", None))
        d._reopen_article_page = Mock()
        d._login_block_reason = Mock(return_value="")
        d._wait_for_challenge = Mock(return_value=True)
        d._is_challenge_page = Mock(return_value=False)
        d._looks_logged_out = Mock(return_value=False)

        def personal(page, result):
            result.reason = NO_INSTITUTION_ENTRY
            return False

        d._complete_login_from_current_page = Mock(side_effect=personal)
        page = fake_page()
        page.locator.return_value.inner_text.return_value = ""
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"), \
                patch.object(batch, "open_page"), patch("paper_search_school.engine.batch_login.open_page"):
            result = d.fetch_one(page, PaperRecord(doi=DOI), Path(directory))
        self.assertEqual((result.reason, result.state), (NO_INSTITUTION_ENTRY, NO_INSTITUTION_ENTRY))


SYNTHETIC = "<base href='https://www.openjournals.example/'>"


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class PageScriptTests(unittest.TestCase):
    """The two page scripts on synthetic pages (no publisher's page is copied)."""

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
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def route(self, html):
        self.page.set_content(SYNTHETIC + html)
        return self.page.evaluate(PublisherBatchDownloader._SCHOOL_ROUTE_JS, [])

    def opens(self, html):
        self.page.set_content(SYNTHETIC + html)
        return access_rules.open_access_evidence(self.page.evaluate(access_rules.OPEN_SIGNS_JS))

    def test_a_personal_account_sign_in_shows_no_school_route(self):
        found = self.route("""<header><a href="/">Home</a> <a href="/ioap">Institutional Open Access Program</a></header>
            <h1>Log in to your account</h1><form><input type="email" name="email"><input type="password" name="password">
            <button type="submit">Log In</button></form><a href="https://orcid.org/oauth/authorize?client_id=x">Log in with ORCID</a>
            <a href="/register">Register</a>""")
        self.assertEqual((found["signs"], found["password"], found["credential"], found["social"]), ([], True, True, True))
        self.assertTrue(self.route("<h1>Sign in</h1><button>Sign in with ORCID</button>")["social"])

    def test_an_open_article_page_shows_no_school_route_and_its_licence(self):
        page = """<header><a href="/user/login">Sign In / Sign Up</a> <a href="/submission?entitytype=2&entityid=626">Submit</a></header>
            <h1>An open article</h1><p>Affiliation: Hong Mu-lan University Hospital, Athens.</p>
            <div id="html-copyright">This article is distributed under the terms of the
            <a href="https://creativecommons.org/licenses/by/4.0/">Creative Commons Attribution (CC BY) license</a>.</div>
            <div class="related-articles"><a href="/a/2">Single Sign-On for IoT: SSO with SAML</a></div>
            <ol class="references"><li><a href="https://www.shibboleth.net/">Shibboleth Consortium</a></li></ol>"""
        self.assertEqual(self.route(page)["signs"], [])
        self.assertEqual(self.opens(page), "open licence: licence block: https://creativecommons.org/licenses/by/4.0/")

    def test_every_kind_of_school_route_is_a_sign(self):
        for html in (
                '<a href="/action/ssostart?redirectUri=%2Fx">Institutional login</a>',
                '<div style="display:none"><a href="/signinshibboleth?returnUrl=%2Fx">Sign In</a></div>',
                '<button type="button">Access through Hong Mu-lan University</button>',
                '<input type="text" placeholder="Search for your institution">',
                '<button class="js-sa-federated-login">Access through your institution</button>',
                '<div style="cursor:pointer">Log in through your library</div>',
                '<form><input type="email" name="email"></form><a href="#org">Sign in via your organization</a>',
                '<a href="/carsi">机构登录</a>',
                '<a href="/login?entityID=https%3A%2F%2Fidp.example.edu.cn%2Fidp%2Fshibboleth">Continue</a>'):
            with self.subTest(html=html):
                self.assertTrue(self.route(f"<h1>Article</h1>{html}")["signs"])

    def test_the_pages_own_metadata_says_open_and_a_sites_or_figures_licence_does_not(self):
        self.assertEqual(self.opens('<meta name="dc.rights" content="https://creativecommons.org/licenses/by/3.0/"><h1>x</h1>'),
                         "open licence: meta dc.rights: https://creativecommons.org/licenses/by/3.0/")
        self.assertEqual(self.opens('<meta name="citation_fulltext_world_readable" content=""><h1>x</h1>'),
                         "open licence: meta citation_fulltext_world_readable")
        self.assertEqual(self.opens('<script type="application/ld+json">{"@graph":[{"isAccessibleForFree":"True"}]}</script>'),
                         "open licence: json-ld isAccessibleForFree")
        self.assertEqual(self.opens("""<meta name="dc.rights" content="© 2026 Some Publisher"><h1>Subscription article</h1>
            <figure><figcaption>Reused under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY</a></figcaption></figure>
            <footer><a rel="license" href="https://creativecommons.org/licenses/by/4.0/">Site text CC BY</a></footer>"""), "")


if __name__ == "__main__":
    unittest.main()


class LoginPromptGraceTests(Isolated):
    """The window asks for the school's sign-in only once the page has stood as the user's step
    for LOGIN_PROMPT_GRACE_SEC: a consent page accepted, or a sign-in the school's kept session
    moves past, goes by without a reminder (user, 2026-11-19)."""

    def run_wait(self, user_step):
        clock = [1000.0]
        fake_time, fake_sleep = this_thread_only(lambda: clock[0], lambda s: clock.__setitem__(0, clock[0] + s))
        d = self.downloader()
        for name in ("_check_federation_school_links", "_return_from_login_site", "_accept_publisher_terms",
                     "_accept_idp_confirmation", "_is_challenge_page", "_follow_federated_login_option",
                     "_open_adapter_login_page", "_click_optional_continue", "_return_to_record_article_if_needed",
                     "_article_access_available", "_has_publisher_institution_session", "_ended_on_personal_sign_in",
                     "_is_human_login_page", "_no_school_route", "_click_openathens_entry", "_select_institution"):
            setattr(d, name, Mock(return_value=False))
        d._page_wait_over = Mock(side_effect=lambda page, since: (clock[0] - 1000.0 > 60, since))
        d._users_login_step = Mock(side_effect=lambda page: user_step(clock[0] - 1000.0))
        d._title = Mock(return_value="Sign in")
        d._login_block_reason = Mock(return_value="")
        d._stuck_on_school_site = Mock(return_value="")
        d._idp_confirmation = Mock(return_value="")
        result = DownloadResult(doi=DOI, status="failed", article_url="https://doi.org/" + DOI)
        d._item_result = result
        asked = []
        with patch.object(batch_login.time, "time", fake_time), patch.object(batch_login.time, "sleep", fake_sleep), \
                patch.object(batch_login, "settle"), \
                patch.object(progress_reporter, "set_attention", side_effect=lambda *a, **k: asked.append(clock[0] - 1000.0)):
            d._complete_login_steps(fake_page("https://idp.example.edu.cn/idp/profile/SAML2/POST/SSO"), result)
        return d, asked

    def test_a_sign_in_page_that_stays_asks_after_the_grace(self):
        d, asked = self.run_wait(lambda elapsed: True)
        self.assertTrue(asked)
        self.assertGreaterEqual(asked[0], d.LOGIN_PROMPT_GRACE_SEC)
        self.assertLess(asked[0], d.LOGIN_PROMPT_GRACE_SEC + 3)

    def test_a_step_the_page_moves_past_by_itself_asks_nothing(self):
        # The school's consent page, accepted within two seconds; then the publisher's pages.
        _, asked = self.run_wait(lambda elapsed: elapsed < 2)
        self.assertEqual(asked, [])

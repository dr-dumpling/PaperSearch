"""PaperSearch Pro's school sign-in, the public side (school_login.py):
which pages may be given the account, how it is kept, and the login wait's one try a paper.
A made-up school (红木兰大学); Pro's own part is a stand-in here (pro/school/tests has its tests)."""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_search_school import config as config_mod
from paper_search_school import school_login
from paper_search_school.engine import batch_login
from paper_search_school.report_sanitizer import Redactor

ENTITY = "https://idp.hongmulan.example/idp/shibboleth"
SCHOOL = {"school_name": "红木兰大学", "idp_entity_id": ENTITY, "idp_login_hosts": ["sso.hongmulan-shared.example"],
          "idp_domains": ["hongmulan.example"]}
PASSWORD = "Mulan-pw-2026"


class TempConfig(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        for target, value in ((config_mod, "DATA_DIR"), (config_mod, "CONFIG_FILE")):
            patcher = patch.object(target, value, self.dir if value == "DATA_DIR" else self.dir / "config.json")
            patcher.start()
            self.addCleanup(patcher.stop)
        self.enterContext(patch.dict(os.environ, {"SCHOOL_DATA_DIR": str(self.dir)}))
        config_mod.save_config({**config_mod.load_config(), **SCHOOL})


class WherePagesMayGetTheAccount(unittest.TestCase):
    def test_only_the_schools_own_https_pages(self):
        may = lambda url: school_login.may_fill(url, SCHOOL)  # noqa: E731
        self.assertTrue(may("https://idp.hongmulan.example/idp/profile/SAML2/POST/SSO"))  # its entityID's host
        self.assertTrue(may("https://cas.hongmulan.example/cas/login"))  # under its own domain
        self.assertTrue(may("https://sso.hongmulan-shared.example/login"))  # a login host its federation lists
        self.assertFalse(may("http://cas.hongmulan.example/cas/login"))  # not https
        self.assertFalse(may("https://www.publisher.example/action/ssostart"))
        self.assertFalse(may("https://evilhongmulan.example/login"))
        self.assertFalse(may("https://hongmulan.example.attacker.example/login"))
        self.assertFalse(may(""))

    def test_a_login_page_pro_has_on_another_domain_of_the_schools(self):
        # A school whose login system sends to a login page on a second domain of its own; Pro's survey found it.
        pro = SimpleNamespace(login_hosts=lambda entity: ("login.hongmulan-campus.example",) if entity == ENTITY else ())
        also = school_login.pro_login_hosts(pro, ENTITY)
        self.assertTrue(school_login.may_fill("https://login.hongmulan-campus.example/cas/login", SCHOOL, also))
        self.assertFalse(school_login.may_fill("https://login.hongmulan-campus.example/cas/login", SCHOOL))
        self.assertFalse(school_login.may_fill("http://login.hongmulan-campus.example/cas/login", SCHOOL, also))
        self.assertFalse(school_login.may_fill("https://other.hongmulan-campus.example/login", SCHOOL, also))
        self.assertEqual(school_login.pro_login_hosts(SimpleNamespace(), ENTITY), ())  # an older Pro


class KeepingTheAccount(TempConfig):
    def test_saved_masked_kept_from_the_config_listing_and_reports(self):
        school_login.save(ENTITY, "20261234", PASSWORD)
        account = school_login.saved(config_mod.load_config(), ENTITY)
        self.assertEqual((account["username"], account["password"], account["enabled"]), ("20261234", PASSWORD, True))
        self.assertEqual(school_login.masked("20261234"), "2******4")
        self.assertEqual(config_mod.get_config_safe()["school_logins"], "***")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(config_mod.CONFIG_FILE.stat().st_mode), 0o600)
        redactor = Redactor(config_mod.load_config())
        cleaned = redactor.text(f"typed {PASSWORD} for 20261234 at the form")
        self.assertNotIn(PASSWORD, cleaned)
        self.assertNotIn("20261234", cleaned)

    def test_a_field_left_empty_keeps_what_was_saved(self):
        school_login.save(ENTITY, "20261234", PASSWORD)
        school_login.save(ENTITY, "", "", enabled=False)
        account = school_login.saved(config_mod.load_config(), ENTITY)
        self.assertEqual((account["username"], account["password"], account["enabled"]), ("20261234", PASSWORD, False))
        with self.assertRaises(ValueError):
            school_login.save(ENTITY + "/other", "", "")

    def test_turned_off_and_cleared(self):
        school_login.save(ENTITY, "20261234", PASSWORD)
        school_login.turn_off(ENTITY, "rejected")
        account = school_login.saved(config_mod.load_config(), ENTITY)
        self.assertEqual((account["enabled"], account["off"]), (False, "rejected"))
        school_login.clear(ENTITY)
        self.assertIsNone(school_login.saved(config_mod.load_config(), ENTITY))

    def test_at_most_six_an_hour(self):
        now = 1_000_000.0
        self.assertEqual([school_login.take_turn(ENTITY, now + i) for i in range(7)], [True] * 6 + [False])
        self.assertTrue(school_login.take_turn(ENTITY, now + school_login.HOUR + 10))


class LoadingProsPart(unittest.TestCase):
    def write(self, folder: Path, api: int) -> Path:
        path = folder / "school_login.py"
        path.write_text(f"API = {api}\nSCHOOLS = {{{ENTITY!r}: 'trial'}}\n"
                        "def school_status(entity_id):\n    return SCHOOLS.get(entity_id, '')\n", encoding="utf-8")
        return path

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        school_login._loaded = None
        self.addCleanup(setattr, school_login, "_loaded", None)

    def test_loaded_from_where_papersearch_wrote_it_with_pro_on(self):
        path = self.write(self.folder, school_login.API)
        with patch.dict(os.environ, {school_login.MODULE_ENV: str(path)}), \
             patch.object(school_login, "pro_features", return_value=True):
            pro = school_login.module()
            self.assertEqual(school_login.school_status(ENTITY, pro), "trial")
            self.assertFalse(school_login.fills_for(ENTITY, pro))
            with patch.dict(os.environ, {school_login.TRIAL_ENV: "1"}):
                self.assertTrue(school_login.fills_for(ENTITY, pro))
            # Surveyed (its form filled in and pressed, the school's "wrong password" read): for everyone.
            with patch.object(pro, "school_status", return_value="surveyed"):
                self.assertEqual(school_login.school_status(ENTITY, pro), "surveyed")
                self.assertTrue(school_login.fills_for(ENTITY, pro))

    def test_none_without_pro_or_with_another_interface(self):
        path = self.write(self.folder, school_login.API)
        with patch.dict(os.environ, {school_login.MODULE_ENV: str(path)}), \
             patch.object(school_login, "pro_features", return_value=False):
            self.assertIsNone(school_login.module())
        with patch.dict(os.environ, {school_login.MODULE_ENV: ""}):
            self.assertIsNone(school_login.module())
        other = self.write(self.folder, school_login.API + 1)
        with patch.dict(os.environ, {school_login.MODULE_ENV: str(other)}), \
             patch.object(school_login, "pro_features", return_value=True):
            self.assertIsNone(school_login.module())


class TheLoginWaitsTry(TempConfig):
    """``LoginMixin._school_sign_in``, with a stand-in for Pro's part."""

    def setUp(self):
        super().setUp()
        school_login.save(ENTITY, "20261234", PASSWORD)
        self.pro = SimpleNamespace(school_status=Mock(return_value="verified"), ready=Mock(return_value=True),
                                   sign_in=Mock(return_value="submitted"))
        self.enterContext(patch.object(school_login, "module", return_value=self.pro))
        self.enterContext(patch.object(school_login, "_turns_file", return_value=self.dir / "turns.json"))
        self.events: list[tuple[str, str]] = []
        self.d = SimpleNamespace(config=config_mod.load_config(), _login_wait_page=Mock(return_value="school_login"),
                                 _idp_confirmation=Mock(return_value=""),
                                 _event=lambda result, state, detail="": self.events.append((state, detail)))
        self.d._school_sign_in_survey = lambda page, result: batch_login.LoginMixin._school_sign_in_survey(self.d, page, result)
        self.page = SimpleNamespace(url="https://cas.hongmulan.example/cas/login?service=x")
        self.result = SimpleNamespace(doi="10.1000/x")

    def sign_in(self) -> bool:
        return batch_login.LoginMixin._school_sign_in(self.d, self.page, self.result)

    def test_filled_once_a_paper_and_never_the_account_in_an_event(self):
        def pro_says(page, attempt):
            attempt.event("school_sign_in_step", f"typed {attempt.password} as {attempt.username}")
            return "submitted"
        self.pro.sign_in.side_effect = pro_says
        self.assertTrue(self.sign_in())
        attempt = self.pro.sign_in.call_args.args[1]
        self.assertEqual((attempt.username, attempt.password), ("20261234", PASSWORD))
        self.assertNotIn(PASSWORD, repr(attempt))
        self.assertTrue(attempt.allowed("https://idp.hongmulan.example/x"))
        self.assertFalse(attempt.allowed("https://www.publisher.example/"))
        self.assertEqual(self.events[-1], ("school_sign_in", "submitted"))
        self.assertFalse(any(PASSWORD in detail or "20261234" in detail for _, detail in self.events))
        self.assertFalse(self.sign_in())  # once a paper
        self.assertEqual(self.pro.sign_in.call_count, 1)

    def test_what_the_reminder_says_when_a_step_is_left_to_the_user(self):
        # A second step after the form (a WeChat scan, user 2026-11-19), or a page Pro would not fill.
        self.assertTrue(self.sign_in())
        self.assertEqual(self.result._sign_in_note, batch_login.SIGN_IN_SECOND_STEP)
        self.result = SimpleNamespace(doi="10.1000/y")
        self.pro.sign_in.return_value = "needs_user"
        self.assertFalse(self.sign_in())
        self.assertEqual(self.result._sign_in_note, batch_login.SIGN_IN_FOR_THE_USER)
        # The check Pro saw named (2026-11-19), in Chinese and in English.
        def a_slider(page, attempt):
            attempt.asks = "slider"
            return "needs_user"
        self.pro.sign_in.side_effect = a_slider
        self.result = SimpleNamespace(doi="10.1000/z")
        self.assertFalse(self.sign_in())
        self.assertEqual(self.result._sign_in_note, "学校登录页要拖动滑块拼图，请在浏览器窗口完成")
        from paper_search_school import i18n
        for note in batch_login.SIGN_IN_ASKS.values():
            self.assertNotRegex(i18n.translate(note, "en"), r"[一-鿿]")

    def test_a_refused_password_turns_it_off_and_tells_the_user(self):
        self.pro.sign_in.return_value = "rejected"
        self.assertFalse(self.sign_in())
        account = school_login.saved(config_mod.load_config(), ENTITY)
        self.assertEqual((account["enabled"], account["off"]), (False, "rejected"))
        self.assertIn("更新密码", self.result._sign_in_note)

    def test_why_not_filled_said_once_a_paper(self):
        self.pro.ready.return_value = False
        self.pro.describe = Mock(return_value="cas.hongmulan.example: passwords=1 account=yes send=yes typing=yes code=0 captcha=no")
        self.assertFalse(self.sign_in())
        self.assertFalse(self.sign_in())
        said = [detail for state, detail in self.events if state == "school_sign_in_skipped"]
        self.assertEqual(said, ["no form to fill: cas.hongmulan.example: passwords=1 account=yes send=yes typing=yes code=0 captcha=no"])
        self.page.url = "https://www.publisher.example/login"
        self.sign_in()
        self.assertEqual(self.events[-1], ("school_sign_in_skipped", "not the school's page: https://www.publisher.example"))

    def test_not_filled(self):
        cases = {
            "another site": lambda: setattr(self.page, "url", "https://www.publisher.example/login"),
            "not a sign-in page": lambda: self.d._login_wait_page.configure_mock(return_value="institution_chooser"),
            "not tested": lambda: self.pro.school_status.configure_mock(return_value=""),
            "still being tested": lambda: self.pro.school_status.configure_mock(return_value="trial"),
            "no form, or someone typing": lambda: self.pro.ready.configure_mock(return_value=False),
            "turned off": lambda: school_login.save(ENTITY, "", "", enabled=False),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.setUp()
                change()
                self.d.config = config_mod.load_config()
                self.assertFalse(self.sign_in())
                self.pro.sign_in.assert_not_called()

    def test_a_survey_records_what_pro_finds_and_fills_nothing(self):
        self.pro.survey = Mock(return_value="cas.hongmulan.example: passwords=1 account=yes send=yes; send control '登 录' takes a click")
        with patch.dict(os.environ, {school_login.SURVEY_ENV: "press"}):
            self.result = SimpleNamespace(doi="10.1000/pressed")
            self.assertFalse(self.sign_in())
            self.assertTrue(self.pro.survey.call_args.kwargs["press"])
        self.result, self.events = SimpleNamespace(doi="10.1000/x"), []
        self.pro.survey.reset_mock()
        with patch.dict(os.environ, {school_login.SURVEY_ENV: "1"}):
            self.assertFalse(self.sign_in())
            self.assertFalse(self.sign_in())
        self.pro.sign_in.assert_not_called()
        self.assertEqual(self.pro.survey.call_count, 1)
        self.assertIs(self.result._survey_finished, True)  # the login wait ends: on to the next school
        self.assertEqual(self.events, [("school_sign_in_survey", self.pro.survey.return_value)])

    def test_six_an_hour_then_the_user(self):
        for _ in range(school_login.PER_HOUR):
            self.result = SimpleNamespace(doi="10.1000/x")
            self.assertTrue(self.sign_in())
        self.result = SimpleNamespace(doi="10.1000/y")
        self.assertFalse(self.sign_in())
        self.assertIn("in the last hour", self.events[-1][1])


SURVEYED = "a" * 64  # the certificate Pro's survey saw on the school's page (SHA-256, hex)


class ALoginPageWithACertificateChromeWillNotTake(TempConfig):
    """A school whose login page's certificate has expired or is not trusted (one tested had run out in 2022): Chrome's warning
    passed and the account typed in for the very certificate Pro's survey saw there only (user, 2026-11-20)."""

    def setUp(self):
        super().setUp()
        school_login.save(ENTITY, "20261234", PASSWORD)
        self.pro = SimpleNamespace(school_status=Mock(return_value="verified"), ready=Mock(return_value=True),
                                   sign_in=Mock(return_value="submitted"),
                                   certificates=Mock(return_value={"cas.hongmulan.example": SURVEYED}))
        self.enterContext(patch.object(school_login, "module", return_value=self.pro))
        self.enterContext(patch.object(school_login, "_turns_file", return_value=self.dir / "turns.json"))
        self.events: list[tuple[str, str]] = []
        self.d = SimpleNamespace(config=config_mod.load_config(), _login_wait_page=Mock(return_value="school_login"),
                                 _idp_confirmation=Mock(return_value=""),
                                 _event=lambda result, state, detail="": self.events.append((state, detail)))
        self.result = SimpleNamespace(doi="10.1000/x")
        self.certificate = self.enterContext(patch.object(school_login, "page_certificate"))
        self.passed = self.enterContext(patch.object(school_login, "pass_warning", return_value=True))
        self.enterContext(patch.object(school_login, "warning_for",
                                       side_effect=lambda page, hosts: "cas.hongmulan.example" if "cas.hongmulan.example" in hosts else ""))

    def past_warning(self, url="chrome-error://chromewebdata/") -> bool:
        self.page = SimpleNamespace(url=url)
        return batch_login.LoginMixin._past_school_certificate_warning(self.d, self.page, self.result)

    def sign_in(self, url="https://cas.hongmulan.example/cas/login") -> bool:
        self.page = SimpleNamespace(url=url)
        return batch_login.LoginMixin._school_sign_in(self.d, self.page, self.result)

    def test_which_certificates_may_get_the_account(self):
        pins = {"cas.hongmulan.example": SURVEYED}
        allows = lambda host, error, digest: school_login.certificate_allows(host, error, digest, pins)  # noqa: E731
        self.assertTrue(allows("cas.hongmulan.example", "", "b" * 64))  # one Chrome takes: as before
        self.assertTrue(allows("cas.hongmulan.example", "net::ERR_CERT_DATE_INVALID", SURVEYED))
        self.assertFalse(allows("cas.hongmulan.example", "net::ERR_CERT_DATE_INVALID", "b" * 64))
        self.assertFalse(allows("cas.hongmulan.example", "net::ERR_CERT_DATE_INVALID", ""))
        self.assertFalse(allows("idp.hongmulan.example", "net::ERR_CERT_AUTHORITY_INVALID", SURVEYED))  # another host
        self.assertFalse(allows("cas.hongmulan.example", "?", ""))  # unread, for a host with one: nothing
        self.assertTrue(allows("idp.hongmulan.example", "?", ""))  # unread elsewhere (no DevTools): as before
        # Past the warning only for the one surveyed, read on the warning itself.
        self.assertTrue(school_login.warning_certificate("CAS.hongmulan.example", "net::ERR_CERT_DATE_INVALID", SURVEYED, pins))
        self.assertFalse(school_login.warning_certificate("cas.hongmulan.example", "", SURVEYED, pins))
        self.assertFalse(school_login.warning_certificate("cas.hongmulan.example", "?", "", pins))
        self.assertEqual(school_login.pro_certificates(SimpleNamespace(), ENTITY), {})  # an older Pro
        self.assertEqual(school_login.pro_certificates(SimpleNamespace(certificates=lambda e: {"CAS.x.example ": "AB"}), ENTITY),
                         {"cas.x.example": "ab"})

    def test_the_warning_passed_for_the_certificate_surveyed(self):
        self.certificate.return_value = ("net::ERR_CERT_DATE_INVALID", SURVEYED)
        self.assertTrue(self.past_warning())
        self.passed.assert_called_once()
        self.assertEqual(self.events[-1], ("school_certificate", "cas.hongmulan.example: net::ERR_CERT_DATE_INVALID taken, the one surveyed"))
        self.assertFalse(self.past_warning())  # once a paper
        # Then filled in on that page, its certificate the one surveyed.
        self.assertTrue(self.sign_in())
        self.pro.sign_in.assert_called_once()

    def test_another_certificate_is_neither_passed_nor_given_the_account(self):
        self.certificate.return_value = ("net::ERR_CERT_AUTHORITY_INVALID", "b" * 64)
        self.assertFalse(self.past_warning())
        self.passed.assert_not_called()
        self.assertEqual(self.result._sign_in_note, batch_login.SIGN_IN_CERTIFICATE)
        self.assertFalse(self.sign_in())  # the user went past the warning: still nothing typed
        self.pro.sign_in.assert_not_called()

    def test_a_page_that_changed_its_certificate_once_past_the_warning(self):
        self.certificate.side_effect = [("net::ERR_CERT_DATE_INVALID", SURVEYED), ("net::ERR_CERT_DATE_INVALID", "b" * 64)]
        self.assertFalse(self.past_warning())
        self.assertEqual(self.result._sign_in_note, batch_login.SIGN_IN_CERTIFICATE)
        self.assertIn("not the certificate surveyed", self.events[-1][1])

    def test_nothing_done_without_the_account_on_or_a_warning_for_the_schools_page(self):
        self.certificate.return_value = ("net::ERR_CERT_DATE_INVALID", SURVEYED)
        self.assertFalse(self.past_warning("https://www.publisher.example/"))  # not Chrome's warning page
        self.pro.certificates.return_value = {"other.example": SURVEYED}
        self.assertFalse(self.past_warning())  # a warning for a page Pro has no certificate for
        self.pro.certificates.return_value = {"cas.hongmulan.example": SURVEYED}
        school_login.save(ENTITY, "", "", enabled=False)
        self.d.config = config_mod.load_config()
        self.assertFalse(self.past_warning())  # the school's sign-in turned off
        self.passed.assert_not_called()

    def test_a_page_past_the_warning_the_user_went_through_gets_nothing(self):
        # A school Pro has no certificate for: its page's certificate Chrome will not take, the user went on.
        self.pro.certificates.return_value = {}
        self.certificate.return_value = ("net::ERR_CERT_COMMON_NAME_INVALID", "b" * 64)
        self.assertFalse(self.sign_in())
        self.pro.sign_in.assert_not_called()
        self.assertEqual(self.events[-1], ("school_sign_in_skipped", "certificate not taken: net::ERR_CERT_COMMON_NAME_INVALID"))


class TheSettingsPage(TempConfig):
    def test_what_the_page_reads_and_saves(self):
        from paper_search_school.progress_capsule import Api

        api = Api.__new__(Api)
        with patch("paper_search_school.progress_capsule.pro_features", return_value=True), \
             patch.object(school_login, "module", return_value=None):
            state = api.school_login_state()
            self.assertEqual((state["ok"], state["saved"], state["school"], state["pro"]), (True, False, "红木兰大学", False))
            state = api.save_school_login("20261234", PASSWORD, True)
            self.assertEqual((state["saved"], state["username"], state["enabled"]), (True, "2******4", True))
            self.assertNotIn(PASSWORD, repr(state))
            # The page's fields: the password there, hidden until its eye shows it (user, 2026-11-19).
            self.assertEqual(api.school_login_saved(), {"username": "20261234", "password": PASSWORD})
            self.assertFalse(api.save_school_login("", "", True)["ok"] is False)
            self.assertFalse(api.clear_school_login()["saved"])
        with patch("paper_search_school.progress_capsule.pro_features", return_value=False):
            self.assertFalse(api.school_login_state()["ok"])
            self.assertEqual(api.school_login_saved(), {})


if __name__ == "__main__":
    unittest.main()

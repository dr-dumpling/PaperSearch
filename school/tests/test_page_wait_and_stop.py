"""Waits off the school's login page last a page wait; the progress window can
stop the whole task and set both waits (user's choice, 2026-11-03)."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_search_school import config, entitlements, user_settings
from paper_search_school.browser import watchdog
from paper_search_school.engine import batch_login
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.engine.bridge import _FAILURE_KINDS
from paper_search_school.entitlements import UserStoppedBatch
from paper_search_school.publishers.profiles import ELSEVIER_PROFILE

DOI = "10.1016/j.example.2026.000002"


def downloader(**config_values):
    return PublisherBatchDownloader(config=dict(config_values), profile=ELSEVIER_PROFILE, login_timeout_sec=180)


class PageWaitTests(unittest.TestCase):
    def test_the_page_wait_is_a_minute_unless_set(self):
        self.assertEqual(downloader().page_wait_sec, 60)
        self.assertEqual(downloader(browser_page_wait_timeout=30).page_wait_sec, 30)
        self.assertEqual(downloader(browser_page_wait_timeout=1).page_wait_sec, 10)  # never below 10 s
        self.assertEqual(config.DEFAULT_CONFIG["browser_page_wait_timeout"], 60)
        self.assertEqual(config.DEFAULT_CONFIG["browser_login_timeout"], 180)

    def test_a_verification_wait_ends_with_the_page_wait(self):
        d = downloader(browser_page_wait_timeout=30)
        result = DownloadResult(doi=DOI, status="failed")
        self.assertLessEqual(d._wait_deadline(result), time.time() + 30.5)
        self.assertGreater(d._user_wait_deadline(result), time.time() + 170)  # the school login keeps its 3 minutes

    def test_only_the_users_login_step_resets_the_page_wait(self):
        d, page = downloader(), object()
        with patch.object(d, "_users_login_step", return_value=True):
            over, since = d._page_wait_over(page, time.time() - 600)
            self.assertFalse(over)
            self.assertAlmostEqual(since, time.time(), delta=1)
        with patch.object(d, "_users_login_step", return_value=False):
            self.assertEqual(d._page_wait_over(page, 100.0)[1], 100.0)
            self.assertFalse(d._page_wait_over(page, time.time() - 30)[0])
            self.assertTrue(d._page_wait_over(page, time.time() - 61)[0])

    def test_the_users_login_step(self):
        class Page:
            url = "https://ds.carsi.edu.cn/login"
        d = downloader()
        with patch.object(d, "_school_password_box", return_value=True):
            self.assertTrue(d._users_login_step(Page()))
        with patch.object(d, "_school_password_box", return_value=False), \
                patch.object(d, "_is_auth_page", return_value=True):
            d.institution_query = ""
            self.assertTrue(d._users_login_step(Page()))  # no school set: the user chooses it
            d.institution_query = "红木兰大学"
            self.assertFalse(d._users_login_step(Page()))  # the program chooses it
            d._manual_school = True
            self.assertTrue(d._users_login_step(Page()))  # the user took the choice over

    def test_a_publishers_sso_hub_is_not_the_schools_login_page(self):
        class Page:
            def __init__(self, url):
                self.url = url

            def locator(self, selector):
                return type("Locator", (), {"count": lambda self: 0})()

        d = downloader(publisher_institution_federation="carsi")
        d.institution_query = "红木兰大学"
        hub = ("https://iam.atypon.com/action/ssostart?idp=https%3A%2F%2Fidp.example.edu.cn%2Fidp%2Fshibboleth"
               "&redirectUri=%2F&federationId=urn%3Amace%3Aincommon")
        self.assertFalse(d._users_login_step(Page(hub)))  # AHA's stop on 2026-11-03: a page wait, not 3 minutes
        with patch.object(d, "_idp_user_action", return_value=False):
            self.assertFalse(d._users_login_step(Page("https://idp.example.edu.cn/idp/profile/SAML2/Redirect/SSO")))
        # Where the wait ended: the hub is not the school's login, so no login_timeout for the user.
        Page.is_closed = lambda self: False
        self.assertNotEqual(d._login_wait_page(Page(hub)), "school_login")
        with patch.object(d, "_idp_user_action", return_value=False):
            self.assertEqual(d._login_wait_page(Page("https://idp.example.edu.cn/idp/profile/SAML2/Redirect/SSO")), "authentication_redirect")

    def test_a_login_wait_off_the_login_page_ends_after_the_page_wait(self):
        d = downloader()
        d.PAGE_WAIT_SEC = 0.05
        result = DownloadResult(doi=DOI, status="failed", article_url="https://doi.org/" + DOI)

        page = Mock(url="https://www.sciencedirect.com/science/article/pii/S0000000000000002")
        page.locator.return_value.first.text_content.return_value = ""

        real_sleep = time.sleep
        with patch.object(d.adapter, "complete_login", return_value=None), \
                patch.object(d, "_institution_pdf_entitlement_missing", return_value=False), \
                patch.object(d, "_dismiss_cookie_banners"), patch.object(d, "_click_sso_entry", return_value=True), \
                patch.object(d, "_is_human_login_page", return_value=False), \
                patch.object(d, "_click_openathens_entry", return_value=False), \
                patch.object(d, "_select_institution", return_value=False), \
                patch.object(d, "_check_user_decision"), patch.object(d, "_users_login_step", return_value=False), \
                patch.object(d, "_login_wait_page", return_value="publisher"), \
                patch.object(batch_login, "settle"), \
                patch.object(batch_login.time, "sleep", side_effect=lambda s: real_sleep(0.06)):
            started = time.time()
            self.assertFalse(d._complete_login_steps(page, result))
        self.assertLess(time.time() - started, 5)
        states = [e["state"] for e in result.events]
        self.assertIn("page_wait_ended", states)
        self.assertTrue(getattr(result, "_user_wait_expired", False))

    def test_a_hung_browser_call_ends_after_90_seconds(self):
        self.assertEqual(watchdog.LIMIT_SEC, 90)


class StopTaskTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"SCHOOL_DATA_DIR": tmp.name, "SCHOOL_PROGRESS_BAR": "0"})
        env.start()
        self.addCleanup(env.stop)

    def test_stop_ends_this_paper_as_batch_stopped_and_remembers_nothing(self):
        entitlements.request_action(DOI, "stop_batch")
        with self.assertRaises(UserStoppedBatch):
            entitlements.apply_user_decision(DOI, "Elsevier", 0)
        self.assertEqual(entitlements.load(), {})
        self.assertEqual(_FAILURE_KINDS["batch_stopped"], ("batch_stopped", "stopped_by_user"))

    def test_unknown_actions_are_still_refused(self):
        with self.assertRaises(ValueError):
            entitlements.request_action(DOI, "stop_everything")


class SettingsTests(unittest.TestCase):
    def test_the_dialogs_defaults_are_the_backends(self):
        for field in user_settings.FIELDS:
            self.assertEqual(config.DEFAULT_CONFIG[field.key], field.default, field.key)

    def test_current_reads_every_field(self):
        with patch.object(user_settings._config, "load_config", return_value={"browser_login_timeout": 300}):
            self.assertEqual(user_settings.current(), {"login": 300, "page": 60, "stalled": 30, "hourly": 100})

    def test_typed_values_are_checked(self):
        page = next(f for f in user_settings.FIELDS if f.name == "page")
        self.assertEqual(user_settings.check(page, " 45 "), (45, ""))
        for bad in ("5", "601", "1.5", "", "一分钟"):
            value, problem = user_settings.check(page, bad)
            self.assertIsNone(value, bad)
            self.assertEqual(problem, "请输入 10 到 600 之间的整数")
        hourly = next(f for f in user_settings.FIELDS if f.name == "hourly")
        self.assertEqual(user_settings.check(hourly, "0"), (0, ""))  # 0 = no limit

    def test_save_writes_each_value_and_refuses_a_bad_one(self):
        with patch.object(user_settings._config, "update_config") as update:
            user_settings.save({"login": 300, "page": 45})
            self.assertEqual([call.args for call in update.call_args_list],
                             [("browser_login_timeout", "300"), ("browser_page_wait_timeout", "45")])
            with self.assertRaises(ValueError):
                user_settings.save({"hourly": -1})


class StatusLineTests(unittest.TestCase):
    """The progress window says which part of the paper it is fetching."""

    def test_main_text_and_supplements_are_told_apart(self):
        from paper_search_school.progress_view import status_text as text
        base = {"phase": "第 3/7 篇：进入机构访问"}
        self.assertEqual(text({**base, "part": "main", "stage": "fetching_pdf"}, True), "正文 · 正在获取 PDF")
        self.assertEqual(text({**base, "part": "main", "stage": "waiting_login"}, True), "正文 · 等待机构登录")
        self.assertEqual(text({**base, "part": "supplements", "supplements_total": None}, True), "附录 · 正在查找附录文件")
        self.assertEqual(text({**base, "part": "supplements", "supplements_total": 5, "supplements_saved": 2}, True),
                         "附录 · 已保存 2/5")
        # Between papers, after the task, or from an older backend: the phase as before.
        self.assertEqual(text({**base, "part": "main", "awaiting_next": True}, True), base["phase"])
        self.assertEqual(text({**base, "part": "main"}, False), base["phase"])
        self.assertEqual(text(base, True), base["phase"])

    def test_supplements_report_each_file_saved(self):
        from paper_search_school.engine import supplements
        from paper_search_school.adapters.base import SupplementLink

        class Response:
            def __init__(self, ok):
                self.ok, self.status = ok, 200 if ok else 404
                self.headers = {"content-type": "application/pdf"}

            def body(self):
                return b"%PDF-1.4 supplement"

        class Request:
            def get(self, url, **kw):
                return Response("missing" not in url)

        seen = []
        links = [SupplementLink(f"https://example.org/{name}.pdf", name) for name in ("s1", "missing", "s2")]
        with tempfile.TemporaryDirectory() as out:
            files = supplements.collect(Request(), links, Path(out), DOI, progress=seen.append)
        self.assertEqual([f["status"] for f in files], ["saved", "failed", "saved"])
        self.assertEqual(seen, [1, 1, 2])


if __name__ == "__main__":
    unittest.main()

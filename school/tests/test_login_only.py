"""``login``: the download's own steps up to the article's access, then stop (2026-11-09).

The old command opened a separate browser, clicked nothing, and called a window
closed by hand a success because it captured some cookies.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_wiley_capture as wiley_fixture

DOI = "10.1016/j.arth.2022.02.032"


class TargetClosedError(Exception):
    """As the driver raises it when the user closes the download browser."""


class LoginOnlyEngineTests(unittest.TestCase):
    setUp = wiley_fixture.WileyCaptureTests.setUp
    locator = wiley_fixture.WileyCaptureTests.locator
    control = wiley_fixture.WileyCaptureTests.control
    response = wiley_fixture.WileyCaptureTests.response

    def run_item(self):
        self.d._write_diagnostic = Mock()
        with tempfile.TemporaryDirectory() as directory:
            return self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(directory))

    def test_stops_once_the_article_opens_and_says_whether_the_school_signed_in(self):
        self.d.config["login_only"] = True
        self.d._prepare_article = Mock(return_value=None)
        self.d._capture_pdf = Mock(side_effect=AssertionError("no PDF in login"))
        for signed_in in (True, False):
            with self.subTest(signed_in=signed_in):
                self.d._school_login_done = Mock(return_value=signed_in)
                result = self.run_item()
                self.assertEqual((result.state, result.signed_in, result.ok), ("access_ready", signed_in, False))
                self.assertIn("login_only_done", [event["state"] for event in result.events])
        self.d._capture_pdf.assert_not_called()

    def test_a_closed_browser_is_named_not_unexplained(self):
        self.d._prepare_article = Mock(side_effect=TargetClosedError(
            "Page.wait_for_timeout: Target page, context or browser has been closed"))
        result = self.run_item()
        self.assertEqual((result.state, result.reason), ("browser_closed", "browser_closed"))
        self.assertTrue(any(e["state"] == "browser_closed" for e in result.events))
        self.d._prepare_article = Mock(side_effect=ValueError("a program bug"))
        self.assertEqual(self.run_item().state, "unexpected_error")


class LoginReplyTests(unittest.TestCase):
    def test_success_only_when_the_school_signed_in(self):
        from paper_search_school.cli import _login_reply

        self.assertEqual(_login_reply({"success": True, "login": {"signed_in": True}})["state"], "signed_in")
        self.assertTrue(_login_reply({"success": True, "login": {"signed_in": True}})["success"])
        open_access = _login_reply({"success": True, "login": {"signed_in": False}})
        self.assertEqual((open_access["success"], open_access["state"]), (False, "access_without_login"))
        closed = _login_reply({"success": False, "error_type": "browser_closed",
                               "artifacts": {"state": "browser_closed", "diagnostic": "/d/diagnostic.json"}})
        self.assertEqual(closed, {"success": False, "state": "browser_closed",
                                  "message": "下载浏览器被关闭了，没有完成登录", "diagnostic": "/d/diagnostic.json"})
        unsubscribed = _login_reply({"success": False, "reason_code": "institution_pdf_entitlement_missing",
                                     "artifacts": {"state": "institution_pdf_entitlement_missing"}})
        self.assertIn("学校没有这篇文章的全文权限", unsubscribed["message"])
        self.assertEqual(_login_reply({"success": False, "error_type": "paywall", "artifacts": {"state": "sso_required"}})["message"],
                         "没有完成登录（sso_required）；详情见诊断文件")
        # Mac 2026-11-09: the wait ran out on the school sign-in page; the raw state stays sso_required.
        timed_out = _login_reply({"success": False, "error_type": "login_timeout", "artifacts": {"state": "sso_required"}})
        self.assertEqual((timed_out["state"], timed_out["message"]),
                         ("login_timeout", "等你登录超时了；再运行一次，在弹出的学校登录页里登录即可"))


class LoginOnlyEntryTests(unittest.TestCase):
    def test_uses_no_cached_pdf_and_takes_the_wait_for_this_run(self):
        from paper_search_school import orchestrator

        seen = {}
        reply = {"success": True, "identifier": DOI, "doi": DOI, "login": {"signed_in": True}, "artifacts": {}}

        def institutional(doi, output_path, config):
            seen.update(config)
            return dict(reply)
        with patch.object(orchestrator, "try_institutional", institutional), \
             patch.object(orchestrator, "cache_get", side_effect=AssertionError("no cache in login")), \
             tempfile.TemporaryDirectory() as directory:
            result = orchestrator.download_institutional(DOI, directory, strategy="institutional_only",
                                                         login_only=True, login_wait=40)
        self.assertEqual(result, reply)  # no file is asked of it
        self.assertEqual((seen.get("login_only"), seen.get("browser_login_timeout")), (True, 40))


if __name__ == "__main__":
    unittest.main()

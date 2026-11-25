"""The settings' 测试登录 (school_test.py; user, 2026-11-21): what a test says, the article it opens, its process as
the window runs it, and the download it is, neither from the cache nor into it."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_search_school import entitlements, orchestrator, progress_reporter, school_test

SCHOOL = "https://idp.example.edu/idp/shibboleth"


class VerdictTests(unittest.TestCase):
    def test_what_a_test_says_by_how_the_download_went(self):
        judge = school_test.judge
        self.assertEqual(judge({"success": True}, filled=True, refused=False),
                         {"ok": True, "title": "登录和下载都正常", "detail": "自动填写了账号密码，全文已下载并核对"})
        self.assertIn("浏览器里还是登录状态", judge({"success": True}, filled=False, refused=False)["detail"])
        # The password the school refused, however the download ended.
        self.assertEqual(judge({"success": False, "error_type": "login_timeout"}, filled=True, refused=True)["title"], "学校说密码不对")
        self.assertEqual(judge({"error_type": "login_credentials_rejected"}, filled=True, refused=False)["title"], "学校说密码不对")
        self.assertEqual(judge({"error_type": "paywall", "reason_code": "institution_pdf_entitlement_missing"}, filled=True,
                               refused=False)["title"], "登录成功，但这篇没有访问权限")
        unfinished = judge({"error_type": "login_timeout"}, filled=True, refused=False)
        self.assertEqual(unfinished["title"], "没有完成学校登录")
        self.assertIn("验证码", unfinished["detail"])
        self.assertIn("下载浏览器", judge({"error_type": "paywall"}, filled=False, refused=False)["detail"])
        self.assertEqual(judge({"error_type": "batch_stopped"}, filled=False, refused=False)["title"], "已停止测试")
        self.assertEqual(judge({"error_type": "idp_account_locked"}, filled=True, refused=False)["title"], "学校说账号被锁定")
        # The publisher's human verification not passed in time (captcha_required since 2026-11-23).
        self.assertEqual(judge({"error_type": "captcha_required"}, filled=False, refused=False),
                         {"ok": False, "title": "没有拿到全文", "detail": "页面或安全验证一直没有完成，换一篇或稍后再测"})
        self.assertEqual(judge({"error_type": "weird_new_kind"}, filled=False, refused=False),
                         {"ok": False, "title": "没有下载成功", "detail": "原因代码：weird_new_kind"})


class Reply:
    def __init__(self, data=None, text="", status=200):
        self.data, self.text, self.status_code = data, text, status

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


class ArticleTests(unittest.TestCase):
    def setUp(self):
        school_test._articles_path().unlink(missing_ok=True)

    def test_set_by_the_user_by_its_doi_or_its_address_none_for_them(self):
        # User, 2026-11-21: the article set by hand, by its DOI or its page's address; none set for them.
        self.assertEqual(school_test.article(SCHOOL), {"doi": ""})
        self.assertEqual(school_test.set_article(SCHOOL, "https://onlinelibrary.wiley.com/doi/full/10.1111/dom.15869"),
                         {"ok": True, "doi": "10.1111/dom.15869"})
        self.assertEqual(school_test.article("https://idp.other.edu/idp"), {"doi": ""})
        refused = school_test.set_article(SCHOOL, "Diabetologia 那篇")
        self.assertEqual(refused, {"ok": False, "error": "认不出这篇文章：请填 DOI 或文章网址"})
        self.assertEqual(school_test.article(SCHOOL)["doi"], "10.1111/dom.15869")  # kept as it was
        self.assertEqual(school_test.set_article(SCHOOL, ""), {"ok": True, "doi": ""})

    def test_the_doi_in_an_address_or_looked_up(self):
        asked = []

        def fetch(url, **kw):
            asked.append(url)
            if "esummary" in url:
                return Reply({"result": {"38000000": {"articleids": [{"idtype": "pubmed", "value": "38000000"},
                                                                       {"idtype": "doi", "value": "10.1000/pubmed"}]}}})
            if "crossref" in url:
                return Reply({"message": {"items": [{"DOI": "10.1016/S0140-6736(23)01234-5"}]}})
            if "oup.com" in url:
                return Reply(text='<meta name="citation_doi" content="10.1093/eurheartj/ehae407">')
            return Reply(text="Forbidden", status=403)

        doi = lambda text: school_test.doi_of(text, fetch)  # noqa: E731
        for text, expected in [
                ("10.1007/s00125-024-06191-8", "10.1007/s00125-024-06191-8"),
                ("doi：１０．１０５６/NEJMoa2300000。", "10.1056/NEJMoa2300000"),
                ("https://doi.org/10.1016/S0140-6736(23)01234-5", "10.1016/S0140-6736(23)01234-5"),
                ("https://link.springer.com/article/10.1007/s00125-024-06191-8", "10.1007/s00125-024-06191-8"),
                ("https://www.tandfonline.com/doi/full/10.1080/123.2024.1?scroll=top", "10.1080/123.2024.1"),
                ("https://www.frontiersin.org/articles/10.3389/fimmu.2024.1234567/full", "10.3389/fimmu.2024.1234567"),
                ("https://www.biorxiv.org/content/10.1101/2024.01.01.123456v2.full", "10.1101/2024.01.01.123456"),
                ("https://www.nature.com/articles/s41586-024-07000-1", "10.1038/s41586-024-07000-1")]:
            with self.subTest(text):
                self.assertEqual(doi(text), (expected, ""))
        self.assertEqual(asked, [])  # all in the address
        self.assertEqual(doi("https://pubmed.ncbi.nlm.nih.gov/38000000/"), ("10.1000/pubmed", ""))
        self.assertEqual(doi("https://www.thelancet.com/journals/lancet/article/PIIS0140-6736(23)01234-5/fulltext"),
                         ("10.1016/S0140-6736(23)01234-5", ""))
        self.assertIn("alternative-id:S0140673623012345", asked[-1])
        self.assertEqual(doi("https://academic.oup.com/eurheartj/article/45/38/4105/7717584"), ("10.1093/eurheartj/ehae407", ""))
        self.assertEqual(doi("https://jamanetwork.com/journals/jama/fullarticle/2812345")[0], "")


class FreshDownloadTests(unittest.TestCase):
    def test_a_test_neither_reads_nor_fills_the_cache(self):
        folder = Path(tempfile.mkdtemp())
        config = {"output_dir": str(folder), "idp_entity_id": SCHOOL}

        def fetched(doi, output_path, config):
            Path(output_path).write_bytes(b"%PDF-1.4\n" + b"x" * 2000)
            return {"success": True, "file": str(output_path), "source": "institutional"}

        cached = {"success": True, "file": __file__}
        signed = []
        with patch("paper_search_school.cold_start.before_sign_in", side_effect=lambda c, always=False: signed.append(always) or ""), \
                patch.object(orchestrator, "load_config", side_effect=lambda: dict(config)), \
                patch.object(orchestrator, "cache_get", return_value=cached) as got, \
                patch.object(orchestrator, "cache_set") as kept, patch.object(orchestrator, "try_institutional", side_effect=fetched), \
                patch.object(orchestrator, "is_pdf_file", return_value=True):
            result = orchestrator.download_institutional("10.1000/test", folder, fresh=True)
            self.assertTrue(result["success"])
            self.assertFalse(result.get("cached"))
            got.assert_not_called()
            kept.assert_not_called()
            # A download of the user's: the cache as before.
            got.return_value = None
            orchestrator.download_institutional("10.1000/mine", folder)
            got.assert_called_once()
            kept.assert_called_once()
        # A test starts signed out; a download forgets only another school's sign-in (cold_start.before_sign_in).
        self.assertEqual(signed, [True, False])
        with patch("paper_search_school.cold_start.before_sign_in", return_value="busy"), \
                patch.object(orchestrator, "load_config", side_effect=lambda: dict(config)), \
                patch.object(orchestrator, "try_institutional", side_effect=AssertionError("no download while the browser is open")):
            busy = orchestrator.download_institutional("10.1000/test", folder, fresh=True)
        self.assertEqual(busy["error_type"], "browser_busy")
        self.assertEqual(school_test.judge(busy, filled=False, refused=False)["title"], "下载浏览器还开着")


class FakeProcess:
    def __init__(self, verdict=None):
        self.ended = threading.Event()
        self.verdict = verdict
        self.terminated = False

    def wait(self, timeout=None):
        if not self.ended.wait(timeout if timeout is not None else 5):
            import subprocess

            raise subprocess.TimeoutExpired("school-test", timeout)
        return 0

    def end(self):
        if self.verdict is not None:
            school_test._write(school_test.result_path(), self.verdict)
        self.ended.set()

    def terminate(self):
        self.terminated = True
        self.ended.set()


class SchoolTestProcessTests(unittest.TestCase):
    def setUp(self):
        self.tearDown()

    def tearDown(self):
        # The data folder is the whole run's: a stop left behind stops the next test's download (Springer's, 2026-11-21).
        progress_reporter.progress_path().unlink(missing_ok=True)
        entitlements.control_path().with_name("stop.json").unlink(missing_ok=True)
        school_test.result_path().unlink(missing_ok=True)

    def _until(self, test, state):
        for _ in range(100):
            if test.state().get("state") == state:
                return test.state()
            threading.Event().wait(0.02)
        self.fail(f"never {state}: {test.state()}")

    def test_a_test_runs_reports_its_step_and_ends_with_its_verdict(self):
        process = FakeProcess({"key": SCHOOL, "doi": "10.1000/a", "ok": True, "title": "登录和下载都正常",
                               "detail": "自动填写了账号密码，全文已下载并核对", "seconds": 38})
        commands = []
        test = school_test.SchoolTest(popen=lambda command, **kw: commands.append(command) or process)
        started = test.start(SCHOOL, "10.1000/a")
        self.assertEqual((started["state"], started["key"], started["step"]), ("running", SCHOOL, 0))
        self.assertEqual(commands[0][-6:], ["paper_search_school.cli", "school-test", "--school", SCHOOL, "--doi", "10.1000/a"])
        # Where the download is, from the progress file the test's process writes.
        progress_reporter._atomic_write({"task": school_test.TASK, "current": "10.1000/a", "status": "running", "run_id": "r1",
                                         "stage": "waiting_login", "phase": "正在尝试机构登录", "attention": {}})
        self.assertEqual((test.state()["step"], test.state()["phase"]), (1, "正在尝试机构登录"))
        progress_reporter._atomic_write({"task": school_test.TASK, "current": "10.1000/a", "status": "running", "run_id": "r1",
                                         "stage": "waiting_login", "phase": "x", "attention": {"login": {"message": "请在浏览器里完成学校登录"}}})
        self.assertEqual(test.state()["phase"], "请在浏览器里完成学校登录")
        self.assertEqual(test.start(SCHOOL, "10.1000/b")["doi"], "10.1000/a")  # one at a time
        process.end()
        done = self._until(test, "done")
        self.assertEqual((done["ok"], done["title"], done["seconds"]), (True, "登录和下载都正常", 38))
        test.forget()
        self.assertEqual(test.state(), {"state": "idle"})

    def test_not_while_a_download_runs(self):
        progress_reporter._atomic_write({"task": "批量下载", "status": "running", "current": "10.1000/x"})
        test = school_test.SchoolTest(popen=lambda *a, **kw: self.fail("started"))
        self.assertEqual(test.start(SCHOOL, "10.1000/a"), {"state": "idle", "error": "正在下载，等这次下载结束再测试"})

    def test_stopped_as_the_card_stops_a_download_and_ended_if_it_goes_on(self):
        process = FakeProcess()
        test = school_test.SchoolTest(popen=lambda *a, **kw: process)
        test.start(SCHOOL, "10.1000/a")
        progress_reporter._atomic_write({"task": school_test.TASK, "current": "10.1000/a", "status": "running", "run_id": "r9",
                                         "stage": "checking_access", "phase": ""})
        with patch.object(school_test, "STOP_GRACE", 0.1):
            self.assertTrue(test.stop()["stopping"])
            stop = json.loads(entitlements.control_path().with_name("stop.json").read_text(encoding="utf-8"))
            self.assertEqual((stop["current"], stop["action"], stop["run_id"]), ("10.1000/a", "stop_batch", "r9"))
            done = self._until(test, "done")
        self.assertTrue(process.terminated)
        self.assertEqual(done["title"], "已停止测试")


if __name__ == "__main__":
    unittest.main()

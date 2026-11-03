"""The progress window's buttons act while the article runs (batch_user.py, watchdog.py)."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_search_carsi import entitlements, issues, progress_reporter
from paper_search_carsi.browser import watchdog
from paper_search_carsi.entitlements import UserSkippedArticle
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.engine.batch_user import UserProvidedPdf
from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE

DOI = "10.1016/j.example.2026.000001"
ARTICLE = "https://doi.org/" + DOI


class FakePage:
    """Just enough of a Playwright page for capturing and acting on a report."""

    def __init__(self, url="https://www.sciencedirect.com/science/article/pii/S0000000000000001"):
        self.url = url
        self.context = self
        self.pages = [self]
        self.calls = []

    def is_closed(self):
        return False

    def title(self):
        return "Some page"

    def evaluate(self, script, *args):
        return "page text"

    def screenshot(self, path=None, **kw):
        Path(path).write_bytes(b"png")

    def goto(self, url, **kw):
        self.calls.append(("goto", url))

    def reload(self, **kw):
        self.calls.append(("reload",))


class DataDirTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"CARSI_DATA_DIR": tmp.name, "CARSI_PROGRESS_BAR": "0"})
        env.start()
        self.addCleanup(env.stop)
        for name, value in (("fired", None), ("interrupted", None), ("_soon", []), ("_running_soon", False)):
            p = patch.object(watchdog, name, value)
            p.start()
            self.addCleanup(p.stop)


class WatchdogRequestTests(DataDirTest):
    def install_on(self, fake):
        from playwright._impl import _sync_base
        for p in (patch.object(_sync_base, "SyncBase", fake), patch.object(watchdog, "_installed", False),
                  patch.object(watchdog.threading, "Thread")):
            p.start()
            self.addCleanup(p.stop)
        watchdog.install()

    @staticmethod
    async def call():
        return None

    def test_an_interrupt_ends_every_browser_call_until_cleared(self):
        class Fake:
            def _sync(self, coro):
                coro.close()
                return "done"

        self.install_on(Fake)
        watchdog.interrupt(UserSkippedArticle("skip_item"))
        for _ in range(2):  # one swallowed somewhere does not let the article go on
            with self.assertRaises(UserSkippedArticle):
                Fake()._sync(self.call())
        watchdog.clear_interrupt()
        self.assertEqual(Fake()._sync(self.call()), "done")

    def test_work_runs_on_the_browser_thread_before_its_next_call(self):
        order = []

        class Fake:
            def _sync(self, coro):
                coro.close()
                order.append("call")
                return "done"

        self.install_on(Fake)
        watchdog.run_soon(lambda: (order.append("work"), Fake()._sync(self.call())))
        Fake()._sync(self.call())
        self.assertEqual(order, ["work", "call", "call"])  # the work's own call does not run it again


class SkipThisPaperTests(DataDirTest):
    def test_skip_this_paper_ends_it_and_remembers_nothing(self):
        entitlements.request_action(DOI, "skip_item")
        with self.assertRaises(UserSkippedArticle):
            entitlements.apply_user_decision(DOI, "Elsevier", 0)
        self.assertEqual(entitlements.load(), {})


class ReportTests(DataDirTest):
    def setUp(self):
        super().setUp()
        progress_reporter.start_task("机构 PDF 下载", total=1, current=DOI)
        self.d = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE, login_timeout_sec=300)
        self.result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)

    def report(self, kind, page=None, act=True):
        folder = issues.report(DOI, kind, {})
        page = page or FakePage()
        self.d._capture_reported_issues(page, self.result, act=act)
        return issues._load(folder), page

    def test_each_report_is_captured_and_acted_on(self):
        data, page = self.report("wrong_school")
        self.assertTrue(self.d._manual_school)
        self.assertIs(self.d._select_institution(page, self.result), False)
        self.assertEqual(data["handled"]["action"], "manual_school")
        self.assertEqual(data["page"]["tabs"][0]["title"], "Some page")
        self.assertEqual(progress_reporter.read_state()["notice"]["text"], "已停止自动选校，请在浏览器里选择学校")

        data, page = self.report("stuck_loading")
        self.assertEqual(page.calls, [("reload",)])

        data, page = self.report("personal_login")
        self.assertEqual(page.calls, [("goto", ARTICLE)])
        data, page = self.report("wrong_redirect")
        self.assertEqual(page.calls, [])  # back to the article once per article
        self.assertEqual(data["handled"]["action"], "captured")

    def test_wrong_page_on_the_school_login_page_is_answered_there(self):
        # ACS, 2026-11-02: the report sent the tab back while the user was at the school's CAS page.
        login = "https://cas.school.edu.cn/esc-sso/login/page"
        data, page = self.report("wrong_redirect", FakePage(login))
        self.assertEqual(page.calls, [])
        self.assertEqual(data["handled"]["action"], "login_page_kept")
        self.assertEqual(progress_reporter.read_state()["notice"]["text"], self.d.LOGIN_PAGE_NOTICE)
        self.assertIn("当前是学校登录页", self.d.LOGIN_PAGE_NOTICE)
        self.assertIn(login, self.result.events[-1]["detail"])
        data, page = self.report("wrong_redirect", FakePage(login + "?retry=1"))  # the same page, again
        self.assertEqual(page.calls, [("goto", ARTICLE)])
        self.assertEqual(data["handled"]["action"], "returned")

    def test_a_late_second_report_or_a_chooser_explains_again(self):
        chooser = "https://ds.carsi.edu.cn/discovery/carsi?entityID=x"
        data, page = self.report("wrong_redirect", FakePage(chooser))
        self.assertEqual((page.calls, data["handled"]["action"]), ([], "login_page_kept"))
        self.result._login_page_report = (self.result._login_page_report[0], time.time() - 301)
        data, page = self.report("wrong_redirect", FakePage(chooser))
        self.assertEqual((page.calls, data["handled"]["action"]), ([], "login_page_kept"))
        data, page = self.report("personal_login", FakePage(chooser))  # other kinds act as before
        self.assertEqual(page.calls, [("goto", ARTICLE)])

    def test_an_open_pdf_of_this_article_ends_the_article_with_it(self):
        self.d._open_pdf_for_record = lambda page, doi: (b"%PDF-1.7 body", "https://host/article.pdf")
        with self.assertRaises(UserProvidedPdf) as raised:
            self.report("pdf_not_captured")
        self.assertEqual(raised.exception.url, "https://host/article.pdf")
        self.assertIsInstance(watchdog.interrupted, UserProvidedPdf)

    def test_a_report_is_handled_once_when_its_own_browser_calls_run_queued_work(self):
        real_attach = issues.attach_page

        def attach(folder, page, events=None):
            self.d._capture_reported_issues(page, self.result)  # what a queued run_soon would do
            real_attach(folder, page, events)

        with patch.object(issues, "attach_page", attach):
            self.report("other")
        self.assertEqual([e["state"] for e in self.result.events].count("user_issue_report"), 1)

    def test_after_the_article_ended_a_report_is_only_captured(self):
        data, page = self.report("stuck_loading", act=False)
        self.assertEqual(page.calls, [])
        self.assertFalse(data["needs_page_capture"])
        self.assertNotIn("handled", data)


class WatchReportsTests(DataDirTest):
    def test_watch_returns_the_next_report_once_its_page_is_captured_and_acted_on(self):
        start = time.time() - 1
        folder = issues.report(DOI, "other", {})
        self.assertIsNone(issues.wait_for_new(start, 0, settle=30, poll=0.01))  # page not captured yet
        issues.attach_page(folder, FakePage(), [])
        self.assertIsNone(issues.wait_for_new(start, 0, settle=30, poll=0.01))  # not acted on yet
        issues.mark_handled(folder, "captured", "已记录页面")
        row = issues.wait_for_new(start, 0, poll=0.01)
        summary = issues.summary(row)
        self.assertEqual((summary["kind"], summary["doi"], summary["handled"]["action"]), ("other", DOI, "captured"))
        self.assertTrue(summary["tabs"][0]["screenshot"].endswith("tab1.png"))
        self.assertIsNone(issues.wait_for_new(row["reported_ts"], 0, poll=0.01))  # nothing newer


class WatchTests(DataDirTest):
    def test_a_click_reaches_the_article_within_seconds(self):
        d = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE, login_timeout_sec=300)
        d._item_started = time.time() - 1
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        seen = []
        identity = {"journal": "Example Journal", "issn": ["0000-0000"]}
        with patch.object(watchdog, "interrupt", seen.append), \
                patch.object(entitlements, "journal_identity", return_value=identity):
            stop = d._start_user_watch(FakePage(), result)
            self.addCleanup(stop.set)
            entitlements.request_action(DOI, "skip_journal")
            deadline = time.time() + 5
            while not seen and time.time() < deadline:
                time.sleep(0.1)
        self.assertEqual([type(e).__name__ for e in seen], ["UserMarkedNoEntitlement"])
        self.assertEqual(next(iter(entitlements.load().values()))["decision"], "skip")


if __name__ == "__main__":
    unittest.main()

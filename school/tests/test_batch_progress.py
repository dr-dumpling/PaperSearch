"""Serial batches: the progress window shows k / N and stays open between items."""
import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from paper_search_school import progress_reporter as pr
from paper_search_school import server

DEAD_PID = 999_999


class BatchProgressTests(unittest.TestCase):
    def setUp(self):
        pr.progress_path().unlink(missing_ok=True)
        self.new_process()

    def new_process(self):
        """Each batch item runs in a fresh backend process."""
        pr._STATE = {}

    def state(self):
        return json.loads(pr.progress_path().read_text(encoding="utf-8"))

    def test_window_shows_what_is_fetched(self):
        for content, expected in (("both", "both"), ("supplements", "supplements"), ("bogus", "main")):
            self.new_process()
            with pr.tracked_download("10.1000/x", None, content=content) as outcome:
                self.assertEqual(self.state()["content"], expected)
                outcome["result"] = {"success": True}
        self.new_process()
        with pr.tracked_download("10.1000/y", None) as outcome:
            self.assertEqual(self.state()["content"], "main")
            outcome["result"] = {"success": True}

    def item(self, index, total, ok, **counts):
        self.new_process()
        batch = pr.BatchContext.from_args("b1", index, total, *(counts.get(k) for k in ("done", "succeeded", "failed")))
        with pr.tracked_download(f"10.1000/{index}", None, batch) as outcome:
            outcome["result"] = {"success": ok}
        # the process exits: its pid is gone before the next item starts
        data = self.state(); data["owner_pid"] = DEAD_PID
        pr.progress_path().write_text(json.dumps(data), encoding="utf-8")

    def test_logging_in_to_go_on_while_another_paper_downloads(self):
        """登录并继续 pressed while the batch's other papers still download: the next report,
        sent beside the running download, carries it, and the paper keeps running (user, 2026-11-15)."""
        from unittest.mock import MagicMock
        from paper_search_school import entitlements, progress_capsule

        entitlements.resume_path().unlink(missing_ok=True)
        held = [{"key": "10.1126/", "name": "Science", "count": 1}]
        lanes = "开放下载 2 篇 · 机构下载 2 篇"
        self.new_process()
        with pr.tracked_download("10.1002/now", None, pr.BatchContext.from_args("b7", 5, 10, 4, 4, 0)) as outcome:
            self.assertEqual(json.loads(server.school_batch_progress("b7", 10, 4, 4, 0, lanes=lanes, held=held))["resume"], [])
            state = self.state()
            self.assertEqual((state["current"], state["held"]), ("10.1002/now", held))
            api = progress_capsule.Api(MagicMock(), MagicMock(), MagicMock())
            self.assertEqual(api.act("resume_held", "", state["run_id"]), "已收到：这一篇下完后接着下暂停的篇目")
            reply = json.loads(server.school_batch_progress("b7", 10, 4, 4, 0, lanes=lanes, held=held))
            self.assertEqual(reply["resume"], ["10.1126/"])
            self.assertEqual(self.state()["current"], "10.1002/now")
            outcome["result"] = {"success": True}

    def test_a_held_publisher_shows_with_its_button_and_the_users_answer_comes_back_once(self):
        # The caller holds a publisher whose school login stopped working mid-batch (2026-11-15).
        import time
        from paper_search_school import entitlements, progress_view

        entitlements.resume_path().unlink(missing_ok=True)
        entitlements.control_path().with_name("stop.json").unlink(missing_ok=True)
        reply = json.loads(server.school_batch_progress("b9", 10, 4, 4, 0, phase="其他篇目已完成", held=[
            {"key": "10.1126/", "name": "Science", "count": 3}, {"key": "not-a-doi", "name": "x", "count": 2},
            {"key": "10.1098/", "name": "Royal Society Publishing", "count": 0}]))
        self.assertEqual(reply, {"updated": True, "resume": [], "stop": False})
        state = self.state()
        self.assertEqual(state["held"], [{"key": "10.1126/", "name": "Science", "count": 3}])
        self.assertEqual(progress_view.view(state, time.time())["held"], [{"key": "10.1126/", "name": "Science", "count": 3}])
        # 登录并继续: the next report answers it, once; another batch's press is not this one's.
        entitlements.request_resume("10.1126/", "b9")
        entitlements.request_resume("10.1126/", "b8")
        self.assertEqual(json.loads(server.school_batch_progress("b9", 10, 4, 4, 0, held=[]))["resume"], [])
        entitlements.request_resume("10.1126/", "b9")
        self.assertEqual(json.loads(server.school_batch_progress("b9", 10, 4, 4, 0, held=[]))["resume"], ["10.1126/"])
        self.assertEqual(json.loads(server.school_batch_progress("b9", 10, 4, 4, 0))["resume"], [])
        self.assertEqual(self.state()["held"], [])
        # Nothing else left: the batch waits, which the window says instead of the last paper.
        wait = "其他篇目已完成，等你回来点“登录并继续”"
        held = [{"key": "10.1126/", "name": "Science", "count": 3}]
        server.school_batch_progress("b9", 10, 7, 7, 0, current="10.1126/last", phase=wait, held=held, held_wait=True)
        shown = progress_view.view(self.state(), time.time())
        self.assertTrue(shown["held_wait"])
        self.assertEqual((shown["mode"], shown["headline"], shown["line"]), ("running", "需要你操作", wait))
        self.assertEqual((shown["current"], shown["title"], shown["where"]), ("", "", ""))
        # Any other report ends it (登录并继续 pressed: the held go on); so does a download.
        server.school_batch_progress("b9", 10, 7, 7, 0, held=[])
        self.assertFalse(progress_view.view(self.state(), time.time())["held_wait"])
        server.school_batch_progress("b9", 10, 7, 7, 0, phase=wait, held=held, held_wait=True)
        with pr.tracked_download("10.1126/next", None, pr.BatchContext.from_args("b9", 8, 10, 7, 7, 0)) as outcome:
            self.assertNotIn("held_wait", self.state())
            outcome["result"] = {"success": True}
        # 终止 while the batch waits: the next report says so.
        entitlements.request_action("", entitlements.STOP_BATCH, self.state()["run_id"])
        self.assertTrue(json.loads(server.school_batch_progress("b9", 10, 4, 4, 0, phase="其他篇目已完成"))["stop"])
        entitlements.control_path().with_name("stop.json").unlink(missing_ok=True)

    def test_items_accumulate_and_the_window_waits_between_them(self):
        self.item(1, 3, True)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["total"], snap["success"]), ("running", 1, 3, 1))
        self.assertTrue(snap["awaiting_next"])
        run_id = snap["run_id"]
        self.item(2, 3, False)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["failed"], snap["run_id"]), ("running", 2, 1, run_id))
        self.item(3, 3, True)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["success"], snap["failed"]), ("done", 3, 2, 1))
        self.assertFalse(snap["awaiting_next"])

    def test_caller_counts_cover_items_finished_without_the_backend(self):
        self.item(1, 4, True)
        # items 2 and 3 were open access in the caller; item 4 reaches the backend
        self.item(4, 4, False, done=3, succeeded=3, failed=0)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["success"], snap["failed"]), ("done", 4, 3, 1))

    def test_a_saved_pdf_is_counted_by_the_caller_after_its_identity_check(self):
        """RSC's PDF awaiting review showed as a success, then a failure (Windows 2026-11-08)."""
        self.item(1, 3, True, done=0, succeeded=0, failed=0)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["done"], snap["success"], snap["failed"]), (1, 0, 0))
        # The caller's identity check failed: its totals come with the next item.
        self.item(2, 3, True, done=1, succeeded=0, failed=1)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["done"], snap["success"], snap["failed"]), (2, 0, 1))
        self.item(3, 3, True, done=2, succeeded=1, failed=1)  # the last item counts itself
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["success"], snap["failed"]), ("done", 3, 2, 1))

    def test_a_resumed_batch_starts_at_its_index(self):
        self.item(5, 10, True)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["done"], snap["total"], snap["task"]), (5, 10, "机构 PDF 批量下载"))

    def test_a_long_wait_between_items_ends_as_interrupted(self):
        self.item(1, 3, True)
        data = self.state()
        data["updated_at"] = (datetime.now() - timedelta(seconds=pr.BATCH_WAIT_STALE_SECONDS + 5)).isoformat(timespec="seconds")
        pr.progress_path().write_text(json.dumps(data), encoding="utf-8")
        snap, _ = pr.read_snapshot()
        self.assertEqual(snap["status"], "interrupted")

    def test_a_dead_owner_without_a_batch_is_still_interrupted(self):
        self.new_process()
        with pr.tracked_download("10.1000/x") as outcome:
            data = self.state(); data["owner_pid"] = DEAD_PID
            pr.progress_path().write_text(json.dumps(data), encoding="utf-8")
            snap, _ = pr.read_snapshot()
            self.assertEqual(snap["status"], "interrupted")
            outcome["result"] = {"success": True}

    def test_sync_for_items_outside_the_backend_and_the_batch_end(self):
        self.assertFalse(pr.sync_batch("b2", 3, 0, 0, 0, finished=True))
        self.assertTrue(pr.sync_batch("b2", 3, 1, 1, 0, current="10.1000/1"))
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["awaiting_next"]), ("running", 1, True))
        self.new_process()
        self.assertTrue(pr.sync_batch("b2", 3, 3, 2, 1, finished=True))
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["success"], snap["failed"]), ("done", 3, 2, 1))
        self.assertFalse(pr.sync_batch("b2", 3, 4, 4, 0))

    def test_a_batch_of_more_than_a_thousand_papers_lists_them_all(self):
        """User, 2026-11-21 (Windows, 1551 papers): 失败 1 on the card, its list empty. The lists took papers 1 to 1000
        only, the batch's old limit; the failed one was the 1211th."""
        pr.papers_path().unlink(missing_ok=True)
        folder = str(pr.papers_path().parent)
        papers = [{"index": i, "doi": f"10.1016/j.jare.{i}", "title": f"Paper {i}", "journal": "J Adv Res", "state": "ok",
                   "via": "开放下载"} for i in range(1, 1552)]
        papers[1210] = {"index": 1211, "doi": "10.1016/j.jare.1211", "title": "Paper 1211", "journal": "J Adv Res",
                        "state": "failed", "cls": "no_access", "reason": "学校没有订阅"}
        self.assertTrue(pr.sync_papers("b-big", folder, papers))
        listed = pr.read_papers()["papers"]
        self.assertEqual(len(listed), 1551)
        self.assertEqual(listed["1211"]["state"], "failed")
        # One sent alone later, past the thousandth, too.
        self.assertTrue(pr.sync_papers("b-big", folder, [{"index": 1551, "doi": "10.1016/j.jare.1551", "title": "Paper 1551",
                                                          "journal": "J Adv Res", "state": "failed", "cls": "no_access",
                                                          "reason": "学校没有订阅"}]))
        self.assertEqual(pr.read_papers()["papers"]["1551"]["state"], "failed")
        # The finished card's reasons, past a thousand failures.
        results = {"content": "main", "main": 0, "failures": [{"cls": "no_access", "reason": "学校没有订阅", "doi": f"10.1/{i}"}
                                                           for i in range(1200)]}
        self.assertEqual(len(pr._batch_results(results)["failures"]), 1200)

    def test_another_paper_does_not_keep_the_last_ones_title(self):
        """User, 2026-11-21 (Windows, 1551 papers): the card kept one paper's title and its publisher while the open-access
        lane reported other DOIs (.031, .033, .052, .053 under one title), and a paper through the school showed the last
        one's until its page opened. Another paper drops the last one's title, journal, publisher and notice."""
        from paper_search_school import progress_view

        self.new_process()
        with pr.tracked_download("10.1016/j.jare.2025.09.031", None, pr.BatchContext.from_args("b9", 1, 40, 0, 0, 0)) as outcome:
            pr.update(title="Blockchain and PUF-based secure key establishment", journal="J Adv Res", publisher="Elsevier",
                      notice={"text": "已在浏览器打开这篇文章", "current": "10.1016/j.jare.2025.09.031", "at": 0})
            outcome["result"] = {"success": True}
        data = self.state(); data["owner_pid"] = DEAD_PID
        pr.progress_path().write_text(json.dumps(data), encoding="utf-8")
        self.new_process()
        self.assertTrue(pr.sync_batch("b9", 40, 2, 2, 0, current="10.1016/j.jare.2025.09.052",
                                      phase="开放下载：已查 2/40 篇，找到 1 篇", channel="开放下载"))
        snap, _ = pr.read_snapshot()
        for field in ("title", "journal", "publisher", "notice"):
            self.assertNotIn(field, snap)
        shown = progress_view.view(snap, 0)
        self.assertEqual((shown["title"], shown["current"], shown["publisher"], shown["where"]),
                         ("", "10.1016/j.jare.2025.09.052", "开放下载", "开放下载"))
        # The same paper reported again keeps what it has.
        pr.update(title="Its own title")
        pr._write_state()
        self.assertTrue(pr.sync_batch("b9", 40, 2, 2, 0, current="10.1016/J.JARE.2025.09.052", channel="开放下载"))
        self.assertEqual(pr.read_snapshot()[0]["title"], "Its own title")
        # A paper through the school: none of the last one's until its own page says.
        data = self.state(); data["owner_pid"] = DEAD_PID
        pr.progress_path().write_text(json.dumps(data), encoding="utf-8")
        self.new_process()
        with pr.tracked_download("10.1016/j.jare.2025.09.053", None, pr.BatchContext.from_args("b9", 3, 40, 2, 2, 0)) as outcome:
            snap, _ = pr.read_snapshot()
            self.assertEqual((snap.get("title"), snap["current"]), (None, "10.1016/j.jare.2025.09.053"))
            outcome["result"] = {"success": True}

    def test_open_access_stretch_shows_its_phase_and_channel(self):
        from paper_search_school import progress_view

        self.assertTrue(pr.sync_batch("b5", 40, 3, 3, 0, current="10.1000/3",
                                      phase="开放获取：已查 5/40 篇，\n找到 3 篇", channel="开放获取"))
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["total"], snap["awaiting_next"]), ("running", 3, 40, True))
        self.assertEqual((snap["phase"], snap["channel"]), ("开放获取：已查 5/40 篇， 找到 3 篇", "开放获取"))
        shown = progress_view.view(snap, 0)
        self.assertEqual((shown["publisher"], shown["line"], shown["done"], shown["total"]),
                         ("开放获取", "开放获取：已查 5/40 篇， 找到 3 篇", 3, 40))
        self.assertFalse(shown["actions"])
        self.assertTrue(pr.sync_batch("b5", 40, 3, 3, 0, phase=["not", "text"]))
        self.assertEqual(pr.read_snapshot()[0]["phase"], "已完成 3/40 篇，等待下一篇")
        self.assertEqual(len(pr._short_line("长" * 200)), 80)

        # The first paper through the school continues the count and drops the channel.
        self.new_process()
        batch = pr.BatchContext.from_args("b5", 4, 40, 3, 3, 0)
        with pr.tracked_download("10.1000/4", None, batch) as outcome:
            snap, _ = pr.read_snapshot()
            self.assertEqual((snap["channel"], snap["phase"]), ("", "第 4/40 篇：进入机构访问"))
            self.assertEqual(progress_view.view(snap, 0)["publisher"], "")
            outcome["result"] = {"success": True}
        self.assertEqual(pr.read_snapshot()[0]["done"], 4)

        self.new_process()
        self.assertTrue(pr.sync_batch("b5", 40, 40, 39, 1, finished=True, channel="开放获取"))
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["channel"]), ("done", ""))

    def test_the_open_access_lane_beside_a_running_download(self):
        """Open access checked while the school's lane downloads (2026-11-09): the running
        paper keeps its stage, line and prompt; the counts and the lanes line follow. The card
        does not show the lanes line (the user, 2026-11-11: too much while downloading)."""
        from paper_search_school import progress_view

        self.assertTrue(pr.sync_batch("b7", 40, 3, 3, 0, current="10.1000/3", phase="开放获取：已查 5/40 篇，找到 3 篇",
                                      channel="开放获取", lanes="开放下载 3 篇 · 机构下载 0 篇"))
        self.new_process()
        with pr.tracked_download("10.1000/4", None, pr.BatchContext.from_args("b7", 4, 40, 3, 3, 0)) as outcome:
            pr.set_attention("login", "请在浏览器窗口完成机构登录", current="10.1000/4")
            before = pr.read_snapshot()[0]
            self.assertEqual(before["lanes"], "开放下载 3 篇 · 机构下载 0 篇")
            self.assertTrue(pr.sync_batch("b7", 40, 6, 6, 0, current="10.1000/9", phase="开放获取：已查 9/40 篇，找到 6 篇",
                                          channel="开放获取", lanes="开放下载 6 篇 · 机构下载 0 篇"))
            snap = pr.read_snapshot()[0]
            self.assertEqual((snap["done"], snap["success"], snap["lanes"]), (6, 6, "开放下载 6 篇 · 机构下载 0 篇"))
            for key in ("current", "stage", "phase", "channel", "attention", "awaiting_next", "run_id"):
                self.assertEqual(snap.get(key), before.get(key), key)
            shown = progress_view.view(snap, 0)
            self.assertEqual((shown["actions"], shown["attention"]["short"]), (True, "请登录学校"))
            self.assertNotIn("lanes", shown)
            pr.clear_attention("login")
            outcome["result"] = {"success": False}
        # Between the school's papers the lane's update shows as before, with its line.
        self.assertTrue(pr.sync_batch("b7", 40, 8, 6, 1, current="10.1000/11", phase="开放获取：已查 11/40 篇，找到 7 篇",
                                      channel="开放获取", lanes="开放下载 7 篇 · 机构下载 0 篇"))
        snap = pr.read_snapshot()[0]
        self.assertEqual((snap["current"], snap["channel"], snap["awaiting_next"], snap["lanes"]),
                         ("10.1000/11", "开放获取", True, "开放下载 7 篇 · 机构下载 0 篇"))
        self.assertTrue(pr.sync_batch("b7", 40, 40, 38, 2, finished=True))
        self.assertEqual(pr.read_snapshot()[0]["lanes"], "")
        self.assertNotIn("lanes", progress_view.view(pr.read_snapshot()[0], 0))

    def test_the_lane_never_writes_over_a_download_in_another_process(self):
        pr._atomic_write({"batch_id": "b8", "status": "running", "awaiting_next": False, "current": "10.1000/1",
                          "owner_pid": os.getppid(), "total": 9, "done": 1, "success": 1, "failed": 0, "revision": 4})
        self.new_process()
        self.assertFalse(pr.sync_batch("b8", 9, 3, 3, 0, current="10.1000/3", lanes="开放下载 3 篇 · 机构下载 0 篇"))
        snap = pr.read_snapshot()[0]
        self.assertEqual((snap["current"], snap["done"], snap["revision"]), ("10.1000/1", 1, 4))

    def test_the_batch_end_keeps_the_batchs_start_time(self):
        self.item(1, 2, True)
        data = self.state(); data["started_at"] = "2026-11-07T10:00:00"
        pr.progress_path().write_text(json.dumps(data), encoding="utf-8")
        self.item(2, 2, False)
        run_id = self.state()["run_id"]
        self.new_process()
        # The caller's batch end arrives after the last item already finished the report.
        self.assertTrue(pr.sync_batch("b1", 2, 2, 1, 1, finished=True))
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["started_at"], snap["run_id"]), ("done", "2026-11-07T10:00:00", run_id))

    def test_the_callers_summary_reaches_the_finished_window(self):
        self.item(1, 2, True)
        started = datetime.now() - timedelta(minutes=30)
        folder = os.path.abspath("batch-downloads")
        results = {
            "content": "both", "folder": folder, "started": started.timestamp(), "stopped": False, "main": 1, "supplements": 3,
            "no_supplements": 0, "sources": [["机构下载", 1], ["bad", -1], "x"],
            "source_details": [["开放下载", "出版社 <b>API</b> 1"], ["", "x"], ["机构下载"], "x"],
            "failures": [{"cls": "no_access", "reason": "学校没有订阅", "title": "A  <i>paper</i>\n", "journal": "Arthritis &amp; Rheumatology",
                          "doi": "10.1000/2", "extra": "dropped"},
                         {"cls": "made_up", "reason": "下载时程序出错"}, {"cls": "no_access"}, "x"],
            "supplement_failures": [{"cls": "publisher_or_network", "reason": "网站人机验证拦截", "title": "B", "doi": "10.1000/1"},
                                    {"reason": ""}],
        }
        self.new_process()
        self.assertTrue(pr.sync_batch("b1", 2, 2, 1, 1, finished=True, results=results))
        snap, _ = pr.read_snapshot()
        self.assertEqual(snap["started_at"], started.isoformat(timespec="seconds"))
        self.assertEqual(snap["output_dir"], folder)  # the folder button opens the whole batch
        self.assertEqual(snap["results"], {
            "content": "both", "main": 1, "supplements": 3, "no_supplements": 0, "sources": [["机构下载", 1]],
            "source_details": {"开放下载": "出版社 API 1"},
            "failures": [
                {"cls": "no_access", "reason": "学校没有订阅", "title": "A paper", "journal": "Arthritis & Rheumatology",
                 "doi": "10.1000/2", "note": ""},
                {"cls": "unexplained", "reason": "下载时程序出错", "title": "", "journal": "", "doi": "", "note": ""},
            ],
            "supplement_failures": [
                {"cls": "publisher_or_network", "reason": "网站人机验证拦截", "title": "B", "journal": "", "doi": "10.1000/1", "note": ""},
            ]})
        # A next item of the same batch starts without the old summary.
        self.item(3, 3, True, done=2, succeeded=1, failed=1)
        self.assertNotIn("results", self.state())

    def test_a_relative_folder_is_not_trusted(self):
        self.item(1, 1, True)
        before = self.state().get("output_dir")
        self.new_process()
        self.assertTrue(pr.sync_batch("b1", 1, 1, 1, 0, finished=True, results={"folder": "papers"}))
        self.assertEqual(self.state().get("output_dir"), before)

    def test_a_lone_download_is_a_batch_of_one(self):
        """PaperSearch runs a single download as a batch of one so its finished card gets the reason."""
        batch = pr.BatchContext.from_args("solo", 1, 1, 0, 0, 0)
        with pr.tracked_download("10.1000/solo", None, batch) as outcome:
            snap = self.state()
            self.assertEqual((snap["task"], snap["phase"]), ("机构 PDF 下载", "进入机构访问"))
            # The publisher's hourly limit pauses a batch item; a lone download ends with the summary.
            outcome["paused"] = "到了每小时下载上限"
        self.assertEqual((self.state()["status"], self.state()["awaiting_next"]), ("running", True))
        self.new_process()
        failure = {"cls": "publisher_or_network", "reason": "到了每小时下载上限", "doi": "10.1000/solo"}
        self.assertTrue(pr.sync_batch("solo", 1, 1, 0, 1, finished=True, results={"failures": [failure]}))
        snap = pr.read_snapshot()[0]
        self.assertEqual((snap["status"], snap["done"], snap["failed"]), ("done", 1, 1))
        self.assertEqual(snap["results"]["failures"][0]["reason"], "到了每小时下载上限")

    def test_the_hourly_limit_holds_the_window_until_its_time(self):
        """An article held by the hourly limit the user set keeps the capsule saying so,
        whatever the other lane reports, until its time or the next article (2026-11-12)."""
        import time
        from paper_search_school import progress_view

        self.item(1, 3, True)
        batch = pr.BatchContext.from_args("b1", 2, 3, 1, 1, 0)
        until = time.time() + 600
        self.new_process()
        with pr.tracked_download("10.1000/2", None, batch) as outcome:
            outcome["paused"] = "Wiley 一小时内已打开 100 篇（每小时上限），01:09 继续这一篇"
            outcome["hourly_wait"] = {"publisher": "Wiley", "limit": 100, "until": until, "phase": outcome["paused"]}
        # The notice says it; the same words do not follow it as the status line (2026-11-13).
        self.assertEqual(progress_view.view(pr.read_snapshot()[0], time.time())["line"], "")
        # The open-access lane goes on reporting meanwhile, and its line shows.
        self.assertTrue(pr.sync_batch("b1", 3, 2, 2, 0, current="10.1000/3",
                                      phase="开放下载：已查 3/3 篇，找到 1 篇", channel="开放下载"))
        resume = time.strftime("%H:%M", time.localtime(until))
        shown = progress_view.view(pr.read_snapshot()[0], time.time())
        self.assertEqual((shown["part"], shown["publisher"], shown["notice"]),
                         ("已达每小时上限", f"{resume} 继续", f"Wiley 已达设置的每小时 100 篇，{resume} 重新计数"))
        self.assertEqual(shown["line"], "开放下载：已查 3/3 篇，找到 1 篇")
        later = progress_view.view(pr.read_snapshot()[0], until + 1)
        self.assertEqual((later["part"], later["notice"]), ("PDF", ""))
        # A longer publisher name is left out, to keep the card's line to one line.
        long_name = {**pr.read_snapshot()[0], "hourly_wait": {"publisher": "Springer Nature", "limit": 100, "until": until}}
        self.assertEqual(progress_view.view(long_name, time.time())["notice"], f"已达设置的每小时 100 篇，{resume} 重新计数")
        # The held article runs again: the hold is gone.
        with pr.tracked_download("10.1000/2", None, pr.BatchContext.from_args("b1", 3, 3, 2, 2, 0)) as outcome:
            self.assertNotIn("hourly_wait", self.state())
            outcome["result"] = {"success": True}

    def test_a_wait_for_the_hourly_limit_is_not_read_as_stopped(self):
        """A batch held by the hourly limit waits up to an hour without a report; it was
        read as stopped ("下载中断") after 30 minutes (Windows, 2026-11-13)."""
        import time

        self.item(1, 3, True)
        batch = pr.BatchContext.from_args("b1", 2, 3, 1, 1, 0)
        self.new_process()
        with pr.tracked_download("10.1000/2", None, batch) as outcome:
            outcome["paused"] = "Wiley 一小时内已打开 100 篇（每小时上限），10:00 继续这一篇"
            outcome["hourly_wait"] = {"publisher": "Wiley", "limit": 100, "until": time.time() + 25 * 60}
        data = self.state()
        # Its last report 35 minutes ago, held until 25 minutes from now.
        data["updated_at"] = (datetime.now() - timedelta(minutes=35)).isoformat(timespec="seconds")
        data["hourly_wait"]["until"] = time.time() + 25 * 60
        pr.progress_path().write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(pr.read_snapshot()[0]["status"], "running")
        # Without the hold the same silence still reads as stopped.
        data.pop("hourly_wait")
        pr.progress_path().write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(pr.read_snapshot()[0]["status"], "interrupted")

    def test_a_stopped_batch_ends_as_stopped(self):
        self.item(1, 3, False)
        self.new_process()
        self.assertTrue(pr.sync_batch("b1", 3, 3, 0, 3, finished=True,
                                      results={"stopped": True, "failures": [{"cls": "user_side", "reason": "任务已终止"}]}))
        self.assertEqual(pr.read_snapshot()[0]["status"], "cancelled")

    def test_a_summary_never_opens_a_window_for_a_batch_it_did_not_show(self):
        self.assertFalse(pr.sync_batch("unseen", 2, 2, 2, 0, finished=True, results={"main": 2}))
        self.assertFalse(pr.progress_path().exists())

    def test_invalid_batch_arguments_fall_back_to_a_single_download(self):
        for args in (("", 1, 2), ("b", 0, 2), ("b", 3, 2), ("b", True, 2), ("b" * 200, 1, 2), (None, 1, 2), ("b", 1, "2")):
            with self.subTest(args=args):
                self.assertIsNone(pr.BatchContext.from_args(*args))
        self.assertIsNone(pr.BatchContext.from_args("b", 1, 2, -1).done)

    def test_server_passes_the_batch_to_the_report(self):
        with patch.object(server, "download", return_value={"success": True, "file": "x.pdf"}):
            server.school_download("10.1000/1", None, batch_id="b3", batch_index=1, batch_total=2)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["batch_id"], snap["done"], snap["total"], snap["status"]), ("b3", 1, 2, "running"))
        self.assertEqual(json.loads(server.school_batch_progress(
            "b3", 2, 2, 2, 0, finished=True, results={"main": 2, "sources": [["开放获取", 2]]})), {"updated": True, "resume": [], "stop": False})
        snap = pr.read_snapshot()[0]
        self.assertEqual((snap["status"], snap["results"]["sources"]), ("done", [["开放获取", 2]]))

    def test_server_passes_the_phase_and_channel(self):
        self.assertEqual(json.loads(server.school_batch_progress(
            "b6", 10, 2, 2, 0, current="10.1000/2", phase="开放获取：已查 3/10 篇，找到 2 篇",
            channel="开放获取")), {"updated": True, "resume": [], "stop": False})
        snap = pr.read_snapshot()[0]
        self.assertEqual((snap["phase"], snap["channel"]), ("开放获取：已查 3/10 篇，找到 2 篇", "开放获取"))
        self.assertEqual(json.loads(server.school_batch_progress(
            "b6", 10, 3, 3, 0, current="10.1000/4", lanes="开放下载 3 篇 · 机构下载 0 篇")), {"updated": True, "resume": [], "stop": False})
        self.assertEqual(pr.read_snapshot()[0]["lanes"], "开放下载 3 篇 · 机构下载 0 篇")


class JournalNameTests(unittest.TestCase):
    def test_the_cards_journal_looked_up_when_none_was_given(self):
        # User, 2026-11-21: a list of DOIs, the card said Elsevier (the publisher) for a paper of Metabolism.
        pr.start_task("机构 PDF 下载", total=2, current="10.1016/j.metabol.2026.156850", phase="")
        pr.update(publisher="Elsevier")
        thread = pr.name_journal("10.1016/j.metabol.2026.156850", look_up=lambda doi: {"journal": "Metabolism"})
        thread.join(2)
        self.assertEqual(pr.read_state()["journal"], "Metabolism")
        # Given already, or another paper on the card by then: left as it is.
        self.assertIsNone(pr.name_journal("10.1016/j.metabol.2026.156850", look_up=lambda doi: {"journal": "X"}))
        pr.update(current="10.1016/j.metabol.2026.000001", journal="")
        late = pr.name_journal("10.1016/j.metabol.2026.000001", look_up=lambda doi: (pr.update(current="10.9/other"), {"journal": "Late"})[1])
        late.join(2)
        self.assertEqual(pr.read_state()["journal"], "")
        pr.finish()


if __name__ == "__main__":
    unittest.main()

"""The progress capsule: what it shows in each state, its buttons and settings,
where it sits, its notifications, and the classic window as the fallback.
No window opens here: pywebview is never started."""
import importlib.util
import os
import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from paper_search_carsi import progress_capsule as capsule
from paper_search_carsi import progress_view as pv

NOW = 1_800_000_000.0


def at(offset: float) -> str:
    return datetime.fromtimestamp(NOW + offset).isoformat(timespec="seconds")


def running(**changes):
    state = {
        "status": "running", "run_id": "r1", "total": 40, "done": 12, "success": 10, "failed": 1,
        "content": "both", "part": "main", "stage": "fetching_pdf", "publisher": "Wiley",
        "journal": "Eur J Heart Fail", "current": "10.1002/ejhf.1", "title": "Empagliflozin in HFpEF",
        "started_at": at(-192), "output_dir": "/tmp/out",
    }
    state.update(changes)
    return state


class ViewTests(unittest.TestCase):
    def test_no_task_is_idle(self):
        self.assertEqual(pv.view(None, NOW), {"mode": "idle"})

    def test_running_main_text(self):
        v = pv.view(running(), NOW)
        self.assertEqual((v["mode"], v["tone"], v["headline"]), ("running", "accent", "下载中"))
        self.assertEqual((v["done"], v["total"], v["pct"], v["left"]), (12, 40, 30, 28))
        self.assertEqual((v["part"], v["publisher"], v["where"]), ("正文", "Wiley", "Eur J Heart Fail · Wiley"))
        self.assertEqual(v["step"], {"index": 2, "label": "取 PDF"})
        self.assertEqual(v["elapsed"], "3:12")
        self.assertTrue(v["actions"])
        self.assertTrue(v["browser"])  # the paper on the card shows its browser
        self.assertEqual(v["stop_left"], 27)
        self.assertTrue(v["folder"])

    def test_no_browser_to_show_between_papers_or_in_the_open_access_stretch(self):
        self.assertFalse(pv.view(running(awaiting_next=True), NOW)["browser"])
        self.assertFalse(pv.view(running(publisher="", channel="开放获取"), NOW)["browser"])
        self.assertFalse(pv.view(running(status="done"), NOW)["browser"])

    def test_supplements_part(self):
        v = pv.view(running(part="supplements", supplements_total=5, supplements_saved=2), NOW)
        self.assertEqual((v["part"], v["step"]), ("附录", {"index": 4, "label": "附录 2/5"}))
        v = pv.view(running(part="supplements", supplements_total=None), NOW)
        self.assertEqual(v["step"], {"index": 4, "label": "查找附录"})

    def test_between_papers_shows_the_phase_and_no_buttons(self):
        v = pv.view(running(awaiting_next=True, phase="第 13/40 篇：进入机构访问"), NOW)
        self.assertIsNone(v["step"])
        self.assertFalse(v["actions"])
        self.assertEqual(v["part"], "正文+附录")
        self.assertEqual(v["line"], "第 13/40 篇：进入机构访问")

    def test_login_prompt_with_countdown(self):
        state = running(stage="waiting_login", attention={
            "k": {"message": "请在浏览器里登录学校", "current": "10.1002/ejhf.1", "since": at(-5), "deadline": NOW + 161}})
        v = pv.view(state, NOW)
        self.assertEqual((v["mode"], v["tone"], v["headline"]), ("attention", "warn", "需要你操作"))
        self.assertEqual(v["attention"], {"message": "请在浏览器里登录学校", "short": "请登录学校", "more": 0,
                                          "remaining": "2:41", "login": True})

    def test_verification_prompt_without_deadline_and_more_items(self):
        state = running(stage="", attention={
            "a": {"message": "请在浏览器窗口完成安全验证", "since": at(-9)},
            "b": {"message": "请在浏览器窗口完成安全验证", "since": at(-2)}})
        a = pv.view(state, NOW)["attention"]
        self.assertEqual((a["short"], a["remaining"], a["more"], a["login"]), ("请完成验证", "", 1, False))

    def test_attention_describes_the_request_not_the_surrounding_stage(self):
        for stage in ("waiting_login", "waiting_verification", "checking_access"):
            for message, short in (
                ("页面持续没有进展，请查看浏览器，可能需要手动操作", "页面暂时无进展"),
                ("页面持续无进展，请查看浏览器", "页面暂时无进展"),
                ("请在 CARSI 页面自行选择学校并完成登录", "请选择学校"),
                ("请在浏览器里确认学校认证页的提示（二次验证）", "请完成验证"),
                ("", "需要你处理"),
            ):
                with self.subTest(stage=stage, message=message):
                    a = pv.view(running(stage=stage, attention={"k": {"message": message}}), NOW)["attention"]
                    self.assertEqual(a["short"], short)
                    self.assertFalse(a["login"])

    def test_finished_states(self):
        cases = [({"success": 40, "failed": 0}, "ok", "下载完成"),
                 ({"success": 38, "failed": 2}, "warn", "下载结束，部分失败"),
                 ({"success": 0, "failed": 3}, "bad", "下载未成功")]
        for counts, tone, headline in cases:
            with self.subTest(counts=counts):
                v = pv.view(running(status="done", done=40, finished_at=at(-1), **counts), NOW)
                self.assertEqual((v["mode"], v["tone"], v["headline"]), ("done", tone, headline))
                self.assertEqual(v["elapsed"], "3:11")
                self.assertFalse(v["actions"])
        stopped = pv.view(running(status="cancelled"), NOW)
        self.assertEqual((stopped["headline"], stopped["finished"]), ("已终止任务", "已终止"))
        self.assertEqual(pv.view(running(status="done"), NOW)["finished"], "完成")
        self.assertEqual([pv.fmt_clock(s) for s in (9, 161, 3723)], ["0:09", "2:41", "1:02:03"])

    def test_finished_card_lists_failures_by_reason_not_by_paper(self):
        def fail(cls, reason, journal="", n=1, **extra):
            return [{"cls": cls, "reason": reason, "title": f"{reason} {i}", "journal": journal, "doi": "", "note": "",
                     **extra} for i in range(n)]
        failures = (fail("user_or_external", "等学校登录超时", "Thieme", 3)
                    + fail("no_access", "学校没有订阅", "Spine", 4) + fail("no_access", "学校没有订阅", "JBJS", 8)
                    + fail("unsupported", "找不到机构登录入口", "Emerald", 2)
                    + fail("unexplained", "下载时程序出错") + fail("unexplained", "页面处理超时"))
        results = {"content": "both", "main": 182, "supplements": 350, "no_supplements": 0,
                   "sources": [["机构订阅", 140], ["开放获取", 42]], "failures": failures}
        v = pv.view(running(status="done", total=200, done=200, success=182, failed=19, results=results), NOW)
        groups = v["summary"]["groups"]
        # Most papers first; past five rows the rest share one row, each paper keeping its reason.
        self.assertEqual([(g["reason"], g["count"]) for g in groups],
                         [("学校没有订阅", 12), ("等学校登录超时", 3), ("找不到机构登录入口", 2),
                          ("下载时程序出错", 1), ("页面处理超时", 1)])
        self.assertEqual(groups[0]["where"], "JBJS 8 · Spine 4")
        self.assertEqual(len(groups[0]["papers"]), 12)
        self.assertFalse(any(g["open"] for g in groups))
        self.assertEqual(v["summary"]["saved"], ["正文 182 篇 · 附录 350 个", "机构订阅 140 · 开放获取 42"])

        crowded = results | {"failures": failures + fail("unsupported", "没有有效 DOI", "", 1)}
        groups = pv.view(running(status="done", results=crowded), NOW)["summary"]["groups"]
        self.assertEqual([g["reason"] for g in groups][-1], "其他原因")
        self.assertEqual(groups[-1]["count"], 2)
        self.assertEqual(groups[-1]["papers"][0]["where"], "下载时程序出错")

    def test_a_few_failures_open_at_once_and_supplement_batches_count_files(self):
        few = {"content": "supplements", "main": 0, "supplements": 5, "no_supplements": 2, "sources": [],
               "failures": [{"cls": "unexplained", "reason": "附录没下载成功", "title": "", "journal": "Spine",
                             "doi": "10.1/x", "note": ""}]}
        summary = pv.view(running(status="done", results=few), NOW)["summary"]
        self.assertTrue(summary["groups"][0]["open"])
        # "10.1/x" is no DOI to open: the title falls back to it, the link does not.
        self.assertEqual(summary["groups"][0]["papers"], [{"title": "10.1/x", "where": "Spine", "doi": ""}])
        self.assertEqual(summary["saved"], ["附录 5 个 · 2 篇未列出附录"])
        main_only = few | {"content": "main", "main": 3, "sources": [["开放获取", 3]]}
        self.assertEqual(pv.view(running(status="done", results=main_only), NOW)["summary"]["saved"],
                         ["正文 3 篇", "开放获取 3"])
        # Without the caller's summary (a single paper, an older caller) the card shows the totals only.
        self.assertIsNone(pv.view(running(status="done"), NOW)["summary"])
        self.assertIsNone(pv.view(running(results=few), NOW)["summary"])

    def test_main_text_and_supplementary_files_apart_and_short(self):
        """Papers whose main text was saved but not every file: a section of their own,
        its rows closed (user, 2026-11-08)."""
        def item(reason, cls, journal):
            return {"cls": cls, "reason": reason, "title": "T", "journal": journal, "doi": "", "note": ""}
        results = {"content": "both", "main": 7, "supplements": 4, "no_supplements": 0, "sources": [],
                   "failures": [item("学校没有订阅", "no_access", "Spine")],
                   "supplement_failures": [item("网站人机验证拦截", "user_or_external", "APL")] * 2
                                          + [item("网站暂不支持附录", "unsupported", "SIAM J")]}
        summary = pv.view(running(status="done", results=results), NOW)["summary"]
        self.assertTrue(summary["groups"][0]["open"])  # one main-text failure: open as before
        self.assertEqual([(g["reason"], g["count"], g["open"]) for g in summary["supplement_groups"]],
                         [("网站人机验证拦截", 2, False), ("网站暂不支持附录", 1, False)])
        self.assertEqual(summary["supplement_missing"], 3)
        main_only = results | {"content": "main", "supplement_failures": []}
        summary = pv.view(running(status="done", results=main_only), NOW)["summary"]
        self.assertEqual(summary["supplement_groups"], [])

    def test_the_downloads_answer_to_a_click_shows_briefly_for_the_same_paper(self):
        notice = {"text": "已跳过本篇", "at": NOW - 3, "current": "10.1002/ejhf.1"}
        self.assertEqual(pv.view(running(notice=notice), NOW)["notice"], "已跳过本篇")
        self.assertEqual(pv.view(running(notice={**notice, "at": NOW - 11}), NOW)["notice"], "")
        self.assertEqual(pv.view(running(notice={**notice, "current": "10.1/other"}), NOW)["notice"], "")

    def test_classic_window_status_line_is_unchanged(self):
        self.assertEqual(pv.status_text(running(), True), "正文 · 正在获取 PDF")
        self.assertEqual(pv.status_text(running(part="supplements", supplements_total=5, supplements_saved=2), True),
                         "附录 · 已保存 2/5")


class AutoCloseRuleTests(unittest.TestCase):
    def test_a_fully_saved_task_closes_after_the_linger(self):
        ac = pv.AutoClose(enabled=True, linger=8)
        done = running(status="done", failed=0)
        self.assertFalse(ac.should_close(done, 0))
        self.assertTrue(ac.should_close(done, 8))

    def test_failures_a_stop_or_an_interruption_stay_until_closed(self):
        for state in (running(status="done", failed=2), running(status="failed"),
                      running(status="cancelled"), running(status="interrupted")):
            with self.subTest(status=state["status"], failed=state["failed"]):
                ac = pv.AutoClose(enabled=True, linger=0)
                self.assertFalse(ac.should_close(state, 0))
                self.assertFalse(ac.should_close(state, 3600))

    def test_the_pointer_on_the_window_keeps_it_and_the_linger_restarts_after(self):
        ac = pv.AutoClose(enabled=True, linger=8)
        done = running(status="done", failed=0)
        self.assertFalse(ac.should_close(done, 0))
        self.assertFalse(ac.should_close(done, 9, hovering=True))
        self.assertFalse(ac.should_close(done, 16))
        self.assertTrue(ac.should_close(done, 17))


def api(placement=None, notifier=None, close_after=None):
    auto = pv.AutoClose(enabled=close_after is not None, linger=close_after or 0)
    return capsule.Api(placement or MagicMock(corner="top"), notifier or MagicMock(), auto)


class ApiTests(unittest.TestCase):
    def setUp(self):
        areas = patch.object(capsule, "_screen_areas", return_value=[
            capsule.ScreenArea("main", capsule.Rect(0, 0, 1440, 900), capsule.Rect(0, 24, 1440, 830))])
        areas.start()
        self.addCleanup(areas.stop)

    def test_notification_switch_persists_immediately_without_changing_other_settings(self):
        from paper_search_carsi import config, user_settings
        with TemporaryDirectory() as directory, \
                patch.object(config, 'DATA_DIR', Path(directory)), \
                patch.object(config, 'CONFIG_FILE', Path(directory) / 'config.json'), \
                patch.object(capsule, 'read_state', return_value=running()):
            a = api()
            self.assertFalse(user_settings.notify_enabled())
            before = user_settings.current()
            self.assertEqual(a.set_notifications(True), {'ok': True, 'notify': True})
            self.assertTrue(user_settings.notify_enabled())
            self.assertEqual(a.set_notifications(False), {'ok': True, 'notify': False})
            self.assertFalse(user_settings.notify_enabled())
            self.assertEqual(user_settings.current(), before)
            self.assertFalse(a.set_notifications('false')['ok'])
            self.assertFalse(user_settings.notify_enabled())

    def test_browser_focus_only_targets_the_current_running_prompt(self):
        state = running(attention={'login': {'message': '请登录学校'}}, run_id='r1', browser_pid=101)
        with patch.object(capsule, 'read_state', return_value=state), \
                patch('paper_search_carsi.browser.foreground.activate_mac', return_value=True) as activate, \
                patch('paper_search_carsi.entitlements.request_action') as request:
            self.assertEqual(api().act('show_browser', state['current'], 'r1'), pv.ACTION_FEEDBACK['show_browser'])
            request.assert_called_once_with(state['current'], 'show_browser', 'r1')
            request.reset_mock()
            api().act('show_browser', state['current'], 'old-run')
            api().act('show_browser', '10.1000/other', 'r1')
            state['status'] = 'done'
            api().act('show_browser', state['current'], 'r1')
            request.assert_not_called()

    def test_the_paper_on_the_card_shows_its_browser_without_a_reminder(self):
        """A click on the downloading paper brings its browser up at any time (user
        request, 2026-11-08), but not while the open-access stretch has none."""
        state = running(run_id='r1', browser_pid=101)
        with patch.object(capsule, 'read_state', return_value=state), \
                patch('paper_search_carsi.browser.foreground.activate_mac', return_value=True), \
                patch('paper_search_carsi.entitlements.request_action') as request:
            self.assertEqual(api().act('show_browser', state['current'], 'r1'), pv.ACTION_FEEDBACK['show_browser'])
            request.assert_called_once_with(state['current'], 'show_browser', 'r1')
            request.reset_mock()
            state.update(publisher='', channel='开放获取')
            self.assertIn('没有打开浏览器', api().act('show_browser', state['current'], 'r1'))
            request.assert_not_called()

    def test_failed_native_activation_does_not_report_a_successful_request(self):
        state = running(attention={'login': {'message': '请登录学校'}}, run_id='r1', browser_pid=101)
        with patch.object(capsule, 'read_state', return_value=state), \
                patch.object(capsule.sys, 'platform', 'darwin'), \
                patch('paper_search_carsi.browser.foreground.activate_mac', return_value=False), \
                patch('paper_search_carsi.entitlements.request_action') as request:
            self.assertIn('未能切到', api().act('show_browser', state['current'], 'r1'))
            request.assert_not_called()

    def test_js_bridge_never_walks_the_native_window_object_graph(self):
        a = api()
        a._window = MagicMock()
        # pywebview recursively inspects public attributes when generating its JS API.
        public_values = [getattr(a, name) for name in dir(a) if not name.startswith("_")]
        self.assertTrue(all(callable(value) for value in public_values))

    def test_buttons_ask_the_running_download(self):
        with patch("paper_search_carsi.entitlements.request_action") as request:
            text = api().act("skip_journal", "10.1/x", "r1")
        request.assert_called_once_with("10.1/x", "skip_journal", "r1")
        self.assertEqual(text, pv.ACTION_FEEDBACK["skip_journal"])
        with patch("paper_search_carsi.entitlements.request_action", side_effect=ValueError("unknown action")):
            self.assertEqual(api().act("nope", "10.1/x"), "记录失败：ValueError")

    def test_problem_report(self):
        with patch("paper_search_carsi.issues.report") as report, \
             patch.object(capsule, "read_state", return_value={"run_id": "r1"}):
            text = api().report("wrong_school", "10.1/x")
        report.assert_called_once_with("10.1/x", "wrong_school", {"run_id": "r1"})
        self.assertEqual(text, "已收到：选错了学校，正在处理")
        self.assertIn(["other", "其他问题"], api().issue_kinds())

    def test_a_settings_page_is_all_checked_before_any_of_it_is_saved(self):
        from paper_search_carsi import user_settings

        with patch.object(user_settings, "save") as save, patch.object(user_settings, "set_notify") as set_notify:
            result = api().save_settings({"login": "5", "page": "60", "stalled": "30"})
            self.assertFalse(result["ok"])
            self.assertIn("login", result["errors"])
            save.assert_not_called()
            result = api().save_settings({"login": "240", "page": "45", "stalled": "0"})
            self.assertEqual(result["errors"], {"stalled": "请输入 1 到 600 之间的整数"})
            save.assert_not_called()
            result = api().save_settings({"login": "240", "page": "45", "stalled": "40"})
            self.assertEqual(result, {"ok": True})
            save.assert_called_once_with({"login": 240, "page": 45, "stalled": 40})  # the other page's limit untouched
            save.reset_mock()
            self.assertEqual(api().save_settings({"hourly": "0"}), {"ok": True})
            save.assert_called_once_with({"hourly": 0})
        set_notify.assert_not_called()  # the switch saves itself

    def test_settings_shown_with_their_defaults_pages_and_the_notification_switch(self):
        from paper_search_carsi import user_settings

        with patch.object(user_settings, "current", return_value={"login": 180, "page": 60, "stalled": 30, "hourly": 100}), \
             patch.object(user_settings, "notify_enabled", return_value=True):
            shown = api().settings()
        self.assertTrue(shown["notify"])
        self.assertEqual([(f["name"], f["value"], f["default"], f["page"]) for f in shown["fields"]],
                         [("login", 180, 180, "wait"), ("page", 60, 60, "wait"), ("stalled", 30, 30, "wait"),
                          ("hourly", 100, 100, "download")])

    def test_a_request_to_show_the_settings_reaches_the_page_once(self):
        request = {"page": "keys", "service": "easyscholar", "new_window": True}
        with patch("paper_search_carsi.progress_capsule.read_state", return_value=None), \
             patch("paper_search_carsi.progress_capsule.take_settings_request", side_effect=[request, None]):
            a = api()
            self.assertEqual(a.state(), {"mode": "idle", "lang": a._lang, "open_settings": request})
            self.assertEqual(a.state(), {"mode": "idle", "lang": a._lang})

    def test_open_settings_keep_a_finished_auto_window(self):
        finished = running(status="done", done=40, success=40, failed=0)
        a = api(close_after=0)
        with patch("paper_search_carsi.progress_capsule.read_state", return_value=finished), \
             patch("paper_search_carsi.progress_capsule.take_settings_request", return_value=None):
            a.state(True)  # the page passes "keep open" while its settings show
        with patch.object(a, "close") as close:
            a.watch_once(finished, 100.0)
            close.assert_not_called()

    def test_the_watcher_notifies_and_closes_a_finished_auto_window(self):
        notifier = MagicMock()
        finished = running(status="done", done=40, success=40, failed=0)
        a = api(notifier=notifier, close_after=0)
        a._window = MagicMock()
        with patch.object(pv, "release_window_lock"):
            a.watch_once(finished, 0)
        notifier.observe.assert_called_once_with(finished)
        a._window.destroy.assert_called_once()

    def test_the_pointer_on_the_capsule_keeps_a_finished_window(self):
        a = api(close_after=0)
        a._window = MagicMock()
        with patch.object(capsule, "read_state", return_value=running(status="done", failed=0)):
            self.assertEqual(a.state(hovering=True)["mode"], "done")
        a.watch_once(running(status="done", failed=0), 0)
        a._window.destroy.assert_not_called()

    def test_page_close_reply_precedes_native_disposal(self):
        a = api()
        a._window = MagicMock()
        with patch.object(capsule.time, "monotonic", return_value=5):
            a.request_close()
        a._window.destroy.assert_not_called()
        a.watch_once(running(), 5.1)
        a._window.destroy.assert_not_called()
        with patch.object(pv, "release_window_lock"):
            a.watch_once(running(), 5.3)
        a._window.destroy.assert_called_once()

    def test_minimize_sends_it_to_the_dock_or_taskbar(self):
        a = api()
        a._window = MagicMock()
        a.minimize()
        a._window.minimize.assert_called_once()

    def test_drag_keeps_geometry_stable_and_saves_only_the_actual_drop(self):
        with TemporaryDirectory() as directory:
            placement = capsule.Placement(Path(directory) / "capsule.json", "top")
            a = api(placement=placement)
            a._window = MagicMock(x=320, y=180, width=260, height=56)
            def move(x, y):
                a._window.x, a._window.y = x, y
            a._window.move.side_effect = move
            a.set_dragging(True, 340, 200)
            a.move_drag(100, 100)
            with patch.object(capsule, "_set_window_frame") as apply:
                a.resize(350, 320)
                apply.assert_not_called()
                self.assertFalse(placement.path.exists())
                # The mouse-up at the edge arrives without a final mouse-move.
                a.set_dragging(False, 18, 100)
                apply.assert_called_once_with(a._window, capsule.Rect(0, 80, 260, 56))
            self.assertEqual(placement.home, capsule.Rect(0, 80, 260, 56))

    def test_dragging_keeps_a_completed_window_from_auto_closing(self):
        a = api(close_after=0)
        a._window = MagicMock()
        a.set_dragging(True)
        done = running(status="done", failed=0)
        with patch.object(capsule, "read_state", return_value=done):
            a.state(hovering=False)
        a.watch_once(done, 0)
        a._window.destroy.assert_not_called()

    def test_drag_uses_pointer_delta_and_ignores_late_moves_after_release(self):
        with TemporaryDirectory() as directory:
            a = api(placement=capsule.Placement(Path(directory) / "capsule.json", "top"))
            a._window = MagicMock(x=320, y=180, width=260, height=56)
            a.set_dragging(True, 500, 200)
            a.move_drag(580, 245)
            a._window.move.assert_called_once_with(400, 225)
            a.set_dragging(False)
            a.move_drag(700, 300)
            a._window.move.assert_called_once()

    def test_mac_cross_screen_drag_ignores_webkit_coordinate_rebasing(self):
        a=api()
        a._window=MagicMock()
        a._native_geometry=True
        appkit=MagicMock()
        appkit.NSScreen.screens.return_value=[types.SimpleNamespace(frame=lambda:
            types.SimpleNamespace(size=types.SimpleNamespace(height=900)))]
        appkit.NSPoint.side_effect=lambda x,y:(x,y)
        with patch.object(capsule.sys,'platform','darwin'), patch.dict(sys.modules,{'AppKit':appkit}), \
                patch.object(capsule,'_window_geometry',return_value=(320,180,260,56)), \
                patch.object(capsule,'_mac_pointer',side_effect=[(500,200),(510,-100),(520,-110)]), \
                patch.object(capsule,'_mac_button_held',return_value=True), \
                patch.object(capsule,'_set_window_frame'), \
                patch.object(capsule,'_cocoa_call',side_effect=lambda action:action()):
            a.set_dragging(True,500,200)
            a.move_drag(-2000,18000)
            a._window.native.setFrameTopLeftPoint_.assert_called_with((330,1020))
            a.move_drag(9000,-5000)
            a._window.native.setFrameTopLeftPoint_.assert_called_with((340,1030))
            a.set_dragging(False)
            a.move_drag(10000,10000)
            self.assertEqual(a._window.native.setFrameTopLeftPoint_.call_count,2)

    def test_mac_release_keeps_the_window_where_it_was_let_go(self):
        # The page's mouse-up arrives after the user has already moved on.
        a = api()
        a._window = MagicMock()
        a._native_geometry = True
        appkit = MagicMock()
        appkit.NSScreen.screens.return_value = [types.SimpleNamespace(frame=lambda:
            types.SimpleNamespace(size=types.SimpleNamespace(height=900)))]
        appkit.NSPoint.side_effect = lambda x, y: (x, y)
        with patch.object(capsule.sys, 'platform', 'darwin'), patch.dict(sys.modules, {'AppKit': appkit}), \
                patch.object(capsule, '_window_geometry', return_value=(330, 170, 350, 219)), \
                patch.object(capsule, '_mac_pointer', side_effect=[(500, 200), (510, 190), (560, 180)]), \
                patch.object(capsule, '_mac_button_held', side_effect=[True, False]), \
                patch.object(capsule, '_set_window_frame'), \
                patch.object(capsule, '_cocoa_call', side_effect=lambda action: action()):
            a.set_dragging(True, 500, 200)
            a.move_drag(510, 190)
            a.set_dragging(False, 560, 180)
        a._window.native.setFrameTopLeftPoint_.assert_called_once_with((340, 740))
        self.assertEqual(a._placement.dragged.call_args.args[2], (510, 190))

    def test_a_listed_paper_opens_its_doi_page_and_nothing_else(self):
        a = api()
        with patch("webbrowser.open", return_value=True) as browse:
            self.assertEqual(a.open_article("10.1364/ol.621126"), "已在浏览器打开这篇文章")
            browse.assert_called_once_with("https://doi.org/10.1364/ol.621126")
            browse.reset_mock()
            self.assertEqual(a.open_article("10.1016/s0140-6736(75)92262-x"), "已在浏览器打开这篇文章")
            browse.assert_called_once_with("https://doi.org/10.1016/s0140-6736(75)92262-x")
            browse.reset_mock()
            for bad in ("", "javascript:alert(1)", "https://evil.example/10.1/x", "10.1/x y", None):
                self.assertEqual(a.open_article(bad), "打开失败：不是有效的 DOI")
            browse.assert_not_called()
        summary = pv.summary_view({"failures": [
            {"cls": "no_access", "reason": "学校没有订阅", "title": "A", "journal": "J", "doi": "10.1000/a"},
            {"cls": "no_access", "reason": "学校没有订阅", "title": "B", "journal": "J", "doi": "not a doi"}]})
        self.assertEqual([p["doi"] for p in summary["groups"][0]["papers"]], ["10.1000/a", ""])

    def test_windows_release_keeps_the_window_where_it_was_let_go(self):
        a = api()
        a._window = MagicMock()
        with patch.object(capsule.sys, 'platform', 'win32'), \
                patch.object(capsule, '_window_scale', return_value=1.25), \
                patch.object(capsule, '_window_geometry', return_value=(400, 300, 260, 56)), \
                patch.object(capsule, '_windows_pointer', side_effect=[(1000, 500), (1050, 480), (1200, 420)]), \
                patch.object(capsule, '_windows_button_held', side_effect=[True, False]), \
                patch.object(capsule, '_set_window_frame'):
            a.set_dragging(True, 800, 400)
            a.move_drag(840, 384)
            a.set_dragging(False, 960, 336)
        a._window.move.assert_called_once_with(440, 284)
        self.assertEqual(a._placement.dragged.call_args.args[2], (1050 / 1.25, 480 / 1.25))

    def test_windows_drop_uses_physical_pointer_after_a_dpi_change(self):
        with TemporaryDirectory() as directory:
            placement = capsule.Placement(Path(directory) / "capsule.json", "top")
            a = api(placement=placement)
            a._window = MagicMock()
            screens = [capsule.ScreenArea('main', capsule.Rect(0, 0, 1280, 720), capsule.Rect(0, 0, 1280, 690)),
                       capsule.ScreenArea('left', capsule.Rect(-1280, 0, 1280, 720), capsule.Rect(-1280, 0, 1280, 690))]
            scale = 1.25
            def move(x, y):
                nonlocal scale
                self.assertEqual((x, y), (-14, 288))
                scale = 1.5
            a._window.move.side_effect = move
            with patch.object(capsule.sys, 'platform', 'win32'), \
                    patch.object(capsule, '_window_scale', side_effect=lambda window: scale), \
                    patch.object(capsule, '_windows_pointer', side_effect=[(1100, 400), (-8, 400)]), \
                    patch.object(capsule, '_windows_button_held', return_value=True), \
                    patch.object(capsule, '_screen_areas', return_value=screens), \
                    patch.object(capsule, '_window_geometry', side_effect=[(872, 288, 260, 56), (-200, 240, 260, 56)]), \
                    patch.object(capsule, '_set_window_frame') as frame:
                a.set_dragging(True, 800, 200)
                a.set_dragging(False, 9000, -4000)  # WebView coordinates were rebased
                frame.assert_called_once_with(a._window, capsule.Rect(-260, 240, 260, 56))
            self.assertEqual(placement.screen.name, 'left')

    def test_atomic_animation_ignores_stale_frames_and_returns_home(self):
        with TemporaryDirectory() as directory:
            placement = capsule.Placement(Path(directory) / 'capsule.json', 'top')
            a = api(placement=placement)
            a._window = MagicMock(x=10, y=30, width=260, height=56)
            def apply(window, frame):
                window.x, window.y, window.width, window.height = frame.x, frame.y, frame.width, frame.height
            with patch.object(capsule, '_set_window_frame', side_effect=apply) as native:
                plan = a.begin_layout(True, 350, 320, 1)
                self.assertEqual((plan['vertical'], plan['horizontal']), ('down', 'right'))
                a.resize(350, 320, 0.5, 1)
                self.assertEqual(native.call_args.args[1], capsule.Rect(10, 30, 305, 188))
                a.resize(350, 320, 1, 1)
                a.finish_layout(1)
                a.begin_layout(True, 350, 550, 2)  # settings keeps the same home/direction
                a.resize(350, 550, 1, 2)
                a.finish_layout(2)
                a.begin_layout(False, 260, 56, 3)
                a.resize(350, 550, 1, 2)  # stale page animation
                a.finish_layout(2)
                a.resize(260, 56, 1, 3)
                a.finish_layout(3)
                self.assertEqual(native.call_args.args[1], capsule.Rect(10, 30, 260, 56))
                self.assertFalse(placement.expanded)
                self.assertEqual(json.loads(placement.path.read_text())['x'], 10)



class IntegrationTests(unittest.TestCase):
    def test_checked_supplements_keep_their_explanation_in_the_completed_card(self):
        state = running(status="done", content="supplements", part="supplements",
                        stage="supplements_checked", phase="已检查，页面未列出补充材料")
        self.assertEqual(pv.view(state, NOW)["completion_detail"], state["phase"])
        self.assertEqual(pv.view(running(), NOW)["completion_detail"], "")

    def test_old_window_cannot_remove_another_windows_lock(self):
        with TemporaryDirectory() as directory:
            lock = Path(directory) / "bar.pid"
            with patch.object(pv, "_lock_path", return_value=lock):
                lock.write_text(str(os.getpid() + 1))
                pv.release_window_lock()
                self.assertTrue(lock.exists())
                lock.write_text(str(os.getpid()))
                pv.release_window_lock()
                self.assertFalse(lock.exists())

    def test_windows_rounding_preserves_a_64_bit_window_handle(self):
        import ctypes
        from ctypes import wintypes
        window = MagicMock()
        window.native.Handle.ToInt64.return_value = 0x100000001
        dll = MagicMock()
        with patch.object(ctypes, "WinDLL", return_value=dll, create=True):
            capsule._round_windows_corners(window)
        window.native.Handle.ToInt32.assert_not_called()
        self.assertEqual(dll.DwmSetWindowAttribute.call_args.args[0], 0x100000001)
        self.assertEqual(dll.DwmSetWindowAttribute.argtypes[0], wintypes.HWND)


class PlacementTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "capsule.json"
        self.screens = [capsule.ScreenArea("main", capsule.Rect(0, 0, 1440, 900), capsule.Rect(0, 24, 1440, 830))]

    def test_default_corners_and_work_area(self):
        self.assertEqual(capsule.Placement(self.path, "top").start(self.screens, (260, 56)), (1160, 44))
        self.assertEqual(capsule.Placement(self.path, "bottom").start(self.screens, (260, 56)), (1160, 788))
        self.screens[0] = capsule.ScreenArea('main', capsule.Rect(0, 0, 1440, 900), capsule.Rect(0, 70, 1440, 710))
        self.assertEqual(capsule.Placement(self.path, "top").start(self.screens, (260, 56))[1], 70)
        self.assertEqual(capsule.Placement(self.path, "bottom").start(self.screens, (260, 56))[1], 724)

    def test_card_opens_down_and_away_from_the_nearer_side_and_collapses_home(self):
        # The work area ends at 854, so a 300 px card fits below a pill at
        # y <= 554; sideways it opens away from the half the pill is in.
        for x, y, direction in [(0, 24, ('down', 'right')), (1180, 24, ('down', 'left')),
                                (0, 798, ('up', 'right')), (1180, 798, ('up', 'left')),
                                (590, 24, ('down', 'left')), (589, 24, ('down', 'right')),
                                (590, 798, ('up', 'left')),
                                (0, 411, ('down', 'right')), (1180, 411, ('down', 'left')),
                                (1180, 554, ('down', 'left')), (1180, 555, ('up', 'left')),
                                (200, 300, ('down', 'right')), (900, 300, ('down', 'left'))]:
            with self.subTest(x=x, y=y):
                p = capsule.Placement(self.path, 'top')
                home = capsule.Rect(x, y, 260, 56)
                p.begin(True, home, self.screens)
                card = p.target(350, 300, True)
                self.assertEqual(p.direction, direction)
                self.assertEqual(card.y if direction[0] == 'down' else card.bottom, home.y if direction[0] == 'down' else home.bottom)
                self.assertEqual(card.right if direction[1] == 'left' else card.x, home.right if direction[1] == 'left' else home.x)
                p.finish(True, card)
                p.begin(True, card, self.screens)
                settings = p.target(350, 600, True)
                self.assertEqual(p.direction, direction)
                self.assertGreaterEqual(settings.x, 0)
                self.assertGreaterEqual(settings.y, 24)
                self.assertLessEqual(settings.right, 1440)
                self.assertLessEqual(settings.bottom, 854)
                p.begin(False, settings, self.screens)
                self.assertEqual(p.target(260, 56, False), home)
                p.finish(False, home)
                self.assertFalse(p.expanded)

    def test_clamping_does_not_overwrite_home_or_drift_after_repeated_expansions(self):
        p = capsule.Placement(self.path, 'top')
        home = capsule.Rect(600, 440, 260, 56)
        for _ in range(4):
            p.begin(True, home, self.screens)
            large = p.target(1000, 800, True)
            self.assertEqual(large.y, 24)
            p.finish(True, large)
            p.begin(False, large, self.screens)
            self.assertEqual(p.target(260, 56, False), home)
            p.finish(False, home)
        self.assertEqual(capsule.Placement(self.path, 'top').start(self.screens, (260, 56)), (600, 440))

    def test_oversized_page_is_limited_to_work_area(self):
        p = capsule.Placement(self.path, 'top')
        p.begin(True, capsule.Rect(100, 50, 260, 56), self.screens)
        self.assertEqual(p.target(2000, 1500, True), self.screens[0].work)

    def test_legacy_top_and_bottom_positions_migrate_on_next_save(self):
        for corner, edge in [('top', 200), ('bottom', 256)]:
            self.path.write_text(json.dumps({'corner': corner, 'right': 560, 'edge': edge}))
            p = capsule.Placement(self.path, 'top')
            self.assertEqual(p.start(self.screens, (260, 56)), (300, 200))
            p.save()
            self.assertEqual(json.loads(self.path.read_text())['version'], 2)

    def test_invalid_or_disconnected_saved_position_uses_default(self):
        for data in [{'corner':'top','right':-9000,'edge':100}, {'version':2,'x':'bad'},
                     {'corner':'top','right':float('nan'),'edge':100}, [], {'version':2,'x':0,'y':0,'width':0,'height':56}]:
            self.path.write_text(json.dumps(data))
            self.assertEqual(capsule.Placement(self.path, 'top').start(self.screens, (260, 56)), (1160, 44))

    def test_negative_secondary_monitor_survives_restart_and_work_area_changes(self):
        extra = capsule.ScreenArea('secondary', capsule.Rect(-1600, -200, 1600, 1000), capsule.Rect(-1600, -176, 1600, 920))
        screens = self.screens + [extra]
        p = capsule.Placement(self.path, 'top')
        p.begin(False, capsule.Rect(-1200, -100, 260, 56), screens)
        p.finish(False, p.home)
        restored = capsule.Placement(self.path, 'top')
        self.assertEqual(restored.start(screens, (260, 56)), (-1200, -100))
        self.assertEqual(restored.screen.name, 'secondary')
        self.assertEqual(capsule.Placement(self.path, 'top').start(self.screens, (260, 56)), (1160, 44))

    def test_drag_reanchors_an_open_card_at_the_new_edge(self):
        p = capsule.Placement(self.path, 'top')
        p.begin(True, capsule.Rect(1180, 798, 260, 56), self.screens)
        for after, expected, home in [
                (capsule.Rect(0,24,350,300), ('down','right'), capsule.Rect(0,24,260,56)),
                (capsule.Rect(1090,554,350,300), ('up','left'), capsule.Rect(1180,798,260,56))]:
            p.dragged(after,self.screens)
            self.assertEqual(p.direction,expected)
            self.assertEqual(p.home,home)
            self.assertEqual(p.target(350,300,True),after)
            p.begin(True,after,self.screens)
            self.assertEqual(p.direction,expected)  # settings updates do not flip it
            self.assertEqual(p.target(260,56,False),home)

    def test_expanded_drag_to_above_left_monitor_uses_its_work_area(self):
        p = capsule.Placement(self.path,'top')
        p.begin(True,capsule.Rect(1180,798,260,56),self.screens)
        secondary=capsule.ScreenArea('other',capsule.Rect(-1600,-1000,1600,1000),
                                     capsule.Rect(-1600,-976,1600,920))
        screens=self.screens+[secondary]
        after=capsule.Rect(-1600,-976,350,300)
        p.dragged(after,screens)
        self.assertEqual(p.screen.name,'other')
        self.assertEqual(p.direction,('down','right'))
        self.assertEqual(p.target(350,300,True),after)
        p.begin(False,after,screens)
        self.assertEqual(p.target(260,56,False),capsule.Rect(-1600,-976,260,56))
        restored=capsule.Placement(self.path,'top')
        self.assertEqual(restored.start(screens,(260,56)),(-1600,-976))

    def test_near_all_four_edges_snaps_only_the_relevant_axis(self):
        for x, y, sx, sy in [(9, 300, 0, 300), (1080, 300, 1090, 300),
                             (400, 34, 400, 24), (400, 543, 400, 554),
                             (400, 300, 400, 300)]:
            with self.subTest(x=x, y=y):
                p = capsule.Placement(self.path, 'top')
                p.begin(True, capsule.Rect(600, 440, 260, 56), self.screens)
                card = p.dragged(capsule.Rect(x, y, 350, 300), self.screens)
                self.assertEqual(card, capsule.Rect(sx, sy, 350, 300))
                self.assertEqual(p.target(350, 300, True), card)

    def test_display_seam_uses_the_display_holding_most_of_the_card(self):
        screens = self.screens + [capsule.ScreenArea(
            'left', capsule.Rect(-1200, 0, 1200, 900), capsule.Rect(-1200, 24, 1200, 830))]
        p = capsule.Placement(self.path, 'top')
        p.begin(True, capsule.Rect(600, 440, 260, 56), screens)
        # The pointer has crossed the seam, but the card has not.
        card = p.dragged(capsule.Rect(-14, 300, 350, 300), screens, (-4, 315))
        self.assertEqual(p.screen.name, 'main')
        self.assertEqual(card, capsule.Rect(0, 300, 350, 300))
        card = p.dragged(capsule.Rect(-300, 300, 350, 300), screens, (-250, 315))
        self.assertEqual(p.screen.name, 'left')
        self.assertEqual(card, capsule.Rect(-350, 300, 350, 300))
        self.assertEqual(p.target(470, 500, True).right, 0)
        self.assertEqual(p.target(190, 48, False).right, 0)

    def test_pill_released_at_the_top_of_a_display_under_another_docks_to_its_top(self):
        # A MacBook with a wider display above it; the menu bar is 38 px.
        screens = [capsule.ScreenArea('1', capsule.Rect(0, 0, 1512, 982), capsule.Rect(0, 38, 1512, 944)),
                   capsule.ScreenArea('2', capsule.Rect(0, -1080, 1920, 1080), capsule.Rect(0, -1080, 1920, 1080))]
        for pill_y, pointer_y in [(-20, -5), (-20, 20), (10, 30)]:
            with self.subTest(pill_y=pill_y, pointer_y=pointer_y):
                p = capsule.Placement(self.path, 'top')
                p.begin(False, capsule.Rect(1300, 400, 124, 59), screens)
                p.dragged(capsule.Rect(1300, pill_y, 124, 59), screens, (1360, pointer_y))
                self.assertEqual((p.screen.name, p.edges, p.home.y), ('1', (0, -1), 38))
                p.finish(False, p.home)
                p.begin(True, p.home, screens)
                self.assertEqual(p.target(350, 300, True), capsule.Rect(1074, 38, 350, 300))
        p = capsule.Placement(self.path, 'top')
        p.begin(False, capsule.Rect(1300, 400, 124, 59), screens)
        p.dragged(capsule.Rect(1300, -45, 124, 59), screens, (1360, -30))
        self.assertEqual((p.screen.name, p.edges, p.home.y), ('2', (0, 1), -59))

    def test_pill_keeps_the_side_nearest_the_screen_edge_when_its_width_changes(self):
        for x, fixed in [(1100, 'right'), (200, 'x')]:
            with self.subTest(x=x):
                p = capsule.Placement(self.path, 'top')
                home = capsule.Rect(x, 300, 180, 56)
                p.begin(True, home, self.screens)
                card = p.target(350, 300, True)
                self.assertEqual(getattr(card, fixed), getattr(home, fixed))
                p.begin(False, card, self.screens)
                pill = p.target(124, 56, False)
                self.assertEqual(getattr(pill, fixed), getattr(home, fixed))
                self.assertEqual(pill.y, home.y)
                p.finish(False, pill)
                p.begin(False, pill, self.screens)
                wider = p.target(260, 56, False)
                self.assertEqual(getattr(wider, fixed), getattr(home, fixed))

    def test_expanded_card_can_drop_at_every_height_along_either_side(self):
        work = self.screens[0].work
        for edge, x in [(-1, 0), (1, 1090)]:
            for grab_x in (x + (10 if edge == -1 else 340), x + 175):
                for y in (*range(52, 826, 11), 826):
                    with self.subTest(edge=edge, x=grab_x, y=y):
                        p = capsule.Placement(self.path, 'top')
                        p.begin(True, capsule.Rect(600, 440, 260, 56), self.screens)
                        card = p.dragged(capsule.Rect(x, y - 18, 350, 300), self.screens, (grab_x, y))
                        self.assertEqual(p.edges, (edge, 0))
                        self.assertEqual(p.target(350, 300, True), card)
                        p.begin(False, card, self.screens)
                        pill = p.target(260, 56, False)
                        self.assertEqual(pill.y, card.y)
                        self.assertEqual(pill.x, work.x if edge == -1 else work.right - 260)
                        p.finish(False, pill)
                        p.begin(True, pill, self.screens)
                        p.finish(False, p.target(260, 56, False))
                        self.assertEqual(p.home, pill)

    def test_expanded_card_snaps_only_the_edge_indicated_by_release(self):
        p = capsule.Placement(self.path, 'top')
        p.begin(True, capsule.Rect(600, 440, 260, 56), self.screens)
        # The tall card extends off the bottom, but the release is along
        # the left edge, not in the corner.
        card = p.dragged(capsule.Rect(8, 690, 350, 300), self.screens, (120, 715))
        self.assertEqual(card, capsule.Rect(0, 554, 350, 300))
        self.assertEqual(p.target(260, 56, False), capsule.Rect(0, 554, 260, 56))

    def test_card_dropped_on_the_top_edge_collapses_into_its_outer_corner(self):
        # Grabbed in the middle of its header, not at a corner.
        for x, pill_x in [(300, 300), (900, 990)]:
            with self.subTest(x=x):
                p = capsule.Placement(self.path, 'top')
                p.begin(True, capsule.Rect(600, 440, 260, 56), self.screens)
                card = p.dragged(capsule.Rect(x, 30, 350, 300), self.screens, (x + 175, 45))
                self.assertEqual(card, capsule.Rect(x, 24, 350, 300))
                p.begin(False, card, self.screens)
                pill = p.target(260, 56, False)
                self.assertEqual(pill, capsule.Rect(pill_x, 24, 260, 56))
                p.finish(False, pill)
                p.begin(True, pill, self.screens)
                self.assertEqual(p.target(350, 300, True), card)

    def test_right_and_bottom_stay_attached_when_the_pill_changes_size_or_restarts(self):
        p = capsule.Placement(self.path, 'bottom')
        p.begin(True, capsule.Rect(600, 440, 260, 56), self.screens)
        p.dragged(capsule.Rect(1081, 546, 350, 300), self.screens)
        pill = p.target(200, 48, False)
        self.assertEqual(pill, capsule.Rect(1240, 806, 200, 48))
        p.finish(False, pill)
        smaller = [capsule.ScreenArea('main', capsule.Rect(0, 0, 1280, 800),
                                     capsule.Rect(0, 30, 1280, 714))]
        restored = capsule.Placement(self.path, 'bottom')
        self.assertEqual(restored.start(smaller, (260, 56)), (1080, 696))
        self.assertEqual(restored.target(360, 200, True), capsule.Rect(920, 544, 360, 200))

    def test_saved_measured_pill_size_and_windows_dpi_survive_restart(self):
        p = capsule.Placement(self.path, 'bottom')
        p.scale = 1.25
        home = capsule.Rect(900, 700, 200, 40)
        p.begin(False, home, self.screens)
        p.finish(False, home)
        same = capsule.Placement(self.path, 'bottom')
        self.assertEqual(same.start(self.screens, (260,56), 1.25), (900,700))
        self.assertEqual(same.home, home)
        changed = capsule.Placement(self.path, 'bottom')
        changed.start(self.screens, (260,56), 1.5)
        self.assertEqual(changed.home.x, 750)
        self.assertEqual(changed.home.width, 200)
        same.rescale(1.5)
        self.assertEqual(same.home.x, 750)
        self.assertEqual(same.home.height, 40)

    def test_interrupted_collapse_keeps_original_corner_until_it_finishes(self):
        p = capsule.Placement(self.path, 'top')
        home = capsule.Rect(0, 24, 260, 56)
        p.begin(True, home, self.screens)
        card = p.target(350,500,True)
        p.begin(False,card,self.screens)
        partial = capsule.Rect(0,24,300,250)
        p.begin(True,partial,self.screens)
        self.assertEqual(p.home,home)
        self.assertEqual(p.direction,('down','right'))
        self.assertEqual(p.target(260,56,False),home)



class _Now:
    """threading.Thread stand-in that runs its target at once."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class NotifierTests(unittest.TestCase):
    def test_windows_notification_failure_is_logged_without_native_error_output(self):
        from paper_search_carsi import user_settings
        failure = capsule.subprocess.CalledProcessError(1, 'powershell', stderr='private native output')
        with patch.object(user_settings, 'notify_enabled', return_value=True), \
                patch.object(capsule.sys, 'platform', 'win32'), \
                patch.object(capsule, 'os', types.SimpleNamespace(name='nt', environ={})), \
                patch.object(capsule.subprocess, 'run', side_effect=failure) as run, \
                self.assertLogs(capsule.__name__, level='WARNING') as logs:
            capsule.notify('PaperSearch', '需要处理', {})
        self.assertTrue(run.call_args.kwargs['check'])
        self.assertIn('CalledProcessError', logs.output[0])
        self.assertNotIn('private native output', logs.output[0])

    def observe(self, notifier, prompts, enabled=True):
        from paper_search_carsi import user_settings

        state = running(attention={k: {"message": m, "since": s} for k, (m, s) in prompts.items()})
        with patch.object(capsule.threading, "Thread", _Now), \
             patch.object(user_settings, "notify_enabled", return_value=enabled):
            notifier.observe(state)

    def test_once_per_prompt(self):
        sent = []
        n = capsule.Notifier(send=lambda title, body, state: sent.append(body))
        self.observe(n, {"a": ("请在浏览器里登录学校", "t1")})
        self.observe(n, {"a": ("请在浏览器里登录学校", "t1")})
        self.observe(n, {"a": ("请在浏览器窗口完成安全验证", "t2")})
        self.assertEqual(sent, ["请在浏览器里登录学校", "请在浏览器窗口完成安全验证"])

    def test_switched_off(self):
        sent = []
        n = capsule.Notifier(send=lambda title, body, state: sent.append(body))
        self.observe(n, {"a": ("请在浏览器里登录学校", "t1")}, enabled=False)
        self.assertEqual(sent, [])

    def test_enable_during_an_existing_prompt_sends_once_and_keeps_the_amber_reminder(self):
        sent = []
        n = capsule.Notifier(send=lambda title, body, state: sent.append(body))
        prompts = {"a": ("请在浏览器里登录学校", "t1")}
        self.observe(n, prompts, enabled=False)
        self.observe(n, prompts, enabled=True)
        self.observe(n, prompts, enabled=True)
        self.assertEqual(sent, ["请在浏览器里登录学校"])
        self.observe(n, prompts, enabled=False)
        state = running(attention={'a':{'message':prompts['a'][0],'since':'t1'}})
        self.assertEqual(pv.view(state, NOW)['tone'], 'warn')
        self.assertEqual(sent, ["请在浏览器里登录学校"])

    def test_new_run_is_not_deduplicated_against_an_old_prompt(self):
        from paper_search_carsi import user_settings

        sent = []
        notifier = capsule.Notifier(send=lambda title, body, state: sent.append(state['run_id']))
        state = running(attention={'a': {'message': '请登录学校', 'since': 'same-second'}})
        with patch.object(capsule.threading, 'Thread', _Now), \
                patch.object(user_settings, 'notify_enabled', return_value=True), \
                patch('paper_search_carsi.progress_macos.clear_notifications') as clear:
            notifier.observe(state)
            notifier.observe({**state, 'run_id': 'r2'})
        self.assertEqual(sent, ['r1', 'r2'])
        if sys.platform == 'darwin':
            clear.assert_called_once()


class WindowsGeometryTests(unittest.TestCase):
    def test_work_areas_include_negative_monitors_and_scale_like_the_window(self):
        import ctypes

        user = MagicMock()
        user.MonitorFromWindow.return_value = 2
        def info(handle, pointer):
            value = pointer._obj
            value.szDevice = 'main' if handle == 1 else 'secondary'
            value.rcMonitor = (0, 0, 1920, 1080) if handle == 1 else (-1920, -300, 0, 780)
            value.rcWork = (0, 0, 1920, 1040) if handle == 1 else (-1920, -260, 0, 780)
            value.dwFlags = int(handle == 1)
            return True
        user.GetMonitorInfoW.side_effect = info
        user.EnumDisplayMonitors.side_effect = lambda dc, rect, callback, data: (
            callback(1, None, None, 0) and callback(2, None, None, 0))
        for scale in (1.25, 1.5):
            with self.subTest(scale=scale), patch.object(capsule.sys, 'platform', 'win32'), \
                    patch.object(ctypes, 'windll', types.SimpleNamespace(user32=user), create=True), \
                    patch.object(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE, create=True):
                window = MagicMock()
                window.native._scale = scale
                window.native.Handle.ToInt64.return_value = 0x100000001
                areas = capsule._windows_screen_areas(window)
                self.assertEqual(areas[0].name, 'secondary')
                self.assertEqual(areas[0].work, capsule.Rect(-1920/scale, -260/scale, 1920/scale, 1040/scale))
                self.assertEqual(areas[1].work.height, 1040/scale)
                user.MonitorFromWindow.assert_called_with(0x100000001, 2)

    def test_animation_and_drag_keep_dpi_and_anchor_without_activating_the_window(self):
        import ctypes
        from webview.window import FixPoint

        class Event(list):
            def __iadd__(self, callback):
                self.append(callback)
                return self

            def __isub__(self, callback):
                self.remove(callback)
                return self

        user = MagicMock()
        user.GetWindowLongPtrW.return_value = 0x0008
        before = Event()
        native = MagicMock(_scale=1.25, Width=325, Height=70,
                           Location=types.SimpleNamespace(X=500, Y=200))
        native.Handle.ToInt64.return_value = 100
        native.Activated = Event()
        native.Shown = Event([native.on_shown])
        window = types.SimpleNamespace(native=native, events=types.SimpleNamespace(before_show=before, shown=MagicMock()))
        with patch.object(capsule.sys, 'platform', 'win32'), \
                patch.object(capsule, 'os', types.SimpleNamespace(name='nt')), \
                patch.object(ctypes, 'windll', types.SimpleNamespace(user32=user), create=True):
            capsule._prepare_nonactivating_start(window)
            before[0]()
        native.resize(200, 40, FixPoint.EAST | FixPoint.SOUTH)
        user.SetWindowPos.assert_called_with(100, None, 575, 220, 250, 50, 0x0054)
        native.move(120, 80)
        user.SetWindowPos.assert_called_with(100, None, 150, 100, 0, 0, 0x0055)
        for scale in (1.25, 1.5):
            native._scale = scale
            window._capsule_set_frame(capsule.Rect(-400, 24, 350, 300))
            user.SetWindowPos.assert_called_with(100, None, round(-400*scale), round(24*scale),
                                                round(350*scale), round(300*scale), 0x0014)
        user.SetForegroundWindow.assert_not_called()
        native.Shown[0]()
        user.SetForegroundWindow.assert_not_called()
        self.assertEqual(native.Activated, [])
        window._capsule_activate_on_input()
        user.SetWindowLongPtrW.assert_called_with(100, -20, 0x0008)
        user.SetForegroundWindow.assert_called_once_with(100)
        window._capsule_activate_on_input()
        user.SetForegroundWindow.assert_called_once_with(100)


class MacGeometryTests(unittest.TestCase):
    def test_visible_frame_converts_cocoa_coordinates_using_primary_screen_top(self):
        def frame(x, y, w, h):
            return types.SimpleNamespace(origin=types.SimpleNamespace(x=x, y=y),
                                         size=types.SimpleNamespace(width=w, height=h))
        main = MagicMock()
        main.frame.return_value = frame(0, 0, 1440, 900)
        main.visibleFrame.return_value = frame(0, 50, 1440, 826)
        main.deviceDescription.return_value = {'NSScreenNumber': 1}
        extra = MagicMock()
        extra.frame.return_value = frame(-1600, 100, 1600, 1000)
        extra.visibleFrame.return_value = frame(-1600, 100, 1600, 976)
        extra.deviceDescription.return_value = {'NSScreenNumber': 2}
        appkit = MagicMock()
        appkit.NSScreen.screens.return_value = [main, extra]
        appkit.NSMakeRect.side_effect = lambda *args: args
        with patch.object(capsule.sys, 'platform', 'darwin'), patch.dict(sys.modules, {'AppKit': appkit}), \
                patch.object(capsule, '_cocoa_call', side_effect=lambda action: action()):
            areas = capsule._screen_areas(MagicMock())
            self.assertEqual(areas[0].work, capsule.Rect(0, 24, 1440, 826))
            self.assertEqual(areas[1].work, capsule.Rect(-1600, -176, 1600, 976))
            window = MagicMock()
            capsule._set_window_frame(window, capsule.Rect(-1200, -100, 350, 500))
            window.native.setFrame_display_.assert_called_once_with((-1200, 500, 350, 500), True)
            window.native.makeKeyAndOrderFront_.assert_not_called()

    def test_a_window_not_yet_on_a_screen_reads_its_moves_against_the_primary_screen(self):
        """pywebview read a moved window's screen, found none for one remembered on a
        second display, and the capsule never opened (2026-11-07)."""
        def frame(x, y, w, h):
            return types.SimpleNamespace(origin=types.SimpleNamespace(x=x, y=y),
                                         size=types.SimpleNamespace(width=w, height=h))
        primary, upper = MagicMock(), MagicMock()
        primary.frame.return_value = frame(0, 0, 1512, 982)
        upper.frame.return_value = frame(0, 982, 1920, 1080)
        appkit = MagicMock()
        appkit.NSScreen.screens.return_value = [primary, upper]
        ns_window = MagicMock()
        ns_window.frame.return_value = frame(1620, 1977, 278, 60)
        ns_window.screen.return_value = None
        with patch.dict(sys.modules, {'AppKit': appkit}):
            self.assertEqual(capsule._moved_origin(ns_window), (1620, 982 - 60 - 1977))
            ns_window.screen.return_value = upper
            self.assertEqual(capsule._moved_origin(ns_window), (1620, 1080 - 60 - 1977))


class FallbackTests(unittest.TestCase):
    def setUp(self):
        screens = patch.object(capsule, '_screen_areas', return_value=[capsule.ScreenArea(
            'main', capsule.Rect(0, 0, 1440, 900), capsule.Rect(0, 24, 1440, 830))])
        screens.start()
        self.addCleanup(screens.stop)
        scale = patch.object(capsule, "_window_scale", return_value=1.0)
        scale.start()
        self.addCleanup(scale.stop)
        quiet_start = patch.object(capsule, "_prepare_nonactivating_start")
        quiet_start.start()
        self.addCleanup(quiet_start.stop)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"CARSI_DATA_DIR": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        # Lifecycle unit tests must not register a real app or touch macOS settings.
        for name in ('install_notification_handler', 'close'):
            native_notifications = patch('paper_search_carsi.progress_macos.' + name)
            native_notifications.start()
            self.addCleanup(native_notifications.stop)

    def test_without_pywebview_the_classic_window_opens(self):
        with patch.dict(sys.modules, {"webview": None}), patch.object(capsule, "_classic") as classic:
            capsule.main()
        classic.assert_called_once()

    @staticmethod
    def fake_webview(**start):
        return types.SimpleNamespace(screens=[types.SimpleNamespace(width=1440, height=900)],
                                     create_window=MagicMock(return_value=MagicMock()), start=MagicMock(**start))

    def test_a_closed_window_ends_the_process_without_waiting_for_page_calls(self):
        fake = self.fake_webview()
        with patch.dict(sys.modules, {"webview": fake}), patch.object(capsule, "_classic") as classic, \
             patch.object(pv, "dark_mode", return_value=False), \
             patch.object(pv, "release_window_lock") as release, \
             patch.object(capsule.os, "_exit") as leave:
            capsule.main()
        classic.assert_not_called()
        release.assert_called()
        leave.assert_called_once_with(0)
        self.assertEqual(fake.start.call_args.kwargs["icon"], str(capsule.ICON) if sys.platform == "darwin" else None)
        self.assertTrue(callable(fake.start.call_args.kwargs["func"]))
        self.assertTrue(capsule.ICON.is_file())

    def test_windows_does_not_pass_a_png_to_the_winforms_ico_loader(self):
        fake = self.fake_webview()
        with patch.dict(sys.modules, {"webview": fake}), patch.object(capsule.sys, "platform", "win32"), \
             patch.object(capsule.os, "_exit"), patch.object(pv, "dark_mode", return_value=False):
            capsule.main()
        self.assertIsNone(fake.start.call_args.kwargs["icon"])

    def test_without_a_usable_web_engine_the_classic_window_opens(self):
        fake = self.fake_webview(side_effect=RuntimeError("no WebView2"))
        with patch.dict(sys.modules, {"webview": fake}), patch.object(capsule, "_classic") as classic, \
             patch.object(pv, "dark_mode", return_value=False), \
             patch.object(pv, "release_window_lock") as release:
            capsule.main()
        classic.assert_called_once()
        release.assert_called()
        kwargs = fake.create_window.call_args.kwargs
        self.assertTrue(kwargs["frameless"] and kwargs["on_top"])
        self.assertIn("pywebviewready", kwargs["html"])

    def test_on_macos_the_capsule_places_its_window_not_pywebview(self):
        """pywebview's x/y count from the screen with the active window, and its first
        move failed for a place on a second display (2026-11-07): the capsule sets
        its remembered place itself on the first show."""
        fake = self.fake_webview()
        with patch.dict(sys.modules, {"webview": fake}), patch.object(capsule.sys, "platform", "darwin"), \
             patch.object(capsule.os, "_exit"), patch.object(pv, "dark_mode", return_value=False):
            capsule.main()
        kwargs = fake.create_window.call_args.kwargs
        self.assertEqual((kwargs["x"], kwargs["y"]), (None, None))
        home = fake.create_window.return_value._capsule_home
        self.assertIsInstance(home, capsule.Rect)
        self.assertLessEqual(home.x + home.width, 1440)  # the default corner of the only screen

    def test_on_macos_a_failed_start_opens_the_classic_window_in_its_own_process(self):
        fake = self.fake_webview(side_effect=RuntimeError("no web engine"))
        with patch.dict(sys.modules, {"webview": fake}), patch.object(capsule.sys, "platform", "darwin"), \
             patch.object(capsule, "_classic") as classic, patch.object(pv, "dark_mode", return_value=False), \
             patch.object(pv, "release_window_lock"):
            capsule.main()
        classic.assert_called_once_with(separate=True)
        with patch("subprocess.run") as run:
            capsule._classic(separate=True)
        run.assert_called_once_with([sys.executable, "-m", "paper_search_carsi.progress_bar"], check=False)

    def test_the_page_loads_nothing_from_the_network(self):
        page = capsule.PAGE.read_text(encoding="utf-8")
        self.assertNotRegex(page, r"(src|href)=[\"']?https?://")
        self.assertNotIn("@import", page)


if __name__ == "__main__":
    unittest.main()

"""The progress capsule: what it shows in each state, its buttons and settings,
where it sits, its notifications, and the classic window as the fallback.
No window opens here: pywebview is never started."""
import importlib.util
import os
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
        self.assertEqual(v["stop_left"], 27)
        self.assertTrue(v["folder"])

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

    def test_settings_are_all_checked_before_any_is_saved(self):
        from paper_search_carsi import user_settings

        with patch.object(user_settings, "save") as save, patch.object(user_settings, "set_notify") as set_notify:
            result = api().save_settings({"login": "5", "page": "60", "hourly": "100"}, True)
            self.assertFalse(result["ok"])
            self.assertIn("login", result["errors"])
            save.assert_not_called()
            result = api().save_settings({"login": "240", "page": "45", "hourly": "0"}, False)
        self.assertEqual(result, {"ok": True})
        save.assert_called_once_with({"login": 240, "page": 45, "hourly": 0})
        set_notify.assert_called_once_with(False)

    def test_settings_shown_with_their_defaults_and_the_notification_switch(self):
        from paper_search_carsi import user_settings

        with patch.object(user_settings, "current", return_value={"login": 180, "page": 60, "hourly": 100}), \
             patch.object(user_settings, "notify_enabled", return_value=True):
            shown = api().settings()
        self.assertTrue(shown["notify"])
        self.assertEqual([(f["name"], f["value"], f["default"]) for f in shown["fields"]],
                         [("login", 180, 180), ("page", 60, 60), ("hourly", 100, 100)])

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

    @unittest.skipUnless(importlib.util.find_spec("webview"), "pywebview not installed")
    def test_resize_keeps_the_anchored_corner(self):
        from webview.window import FixPoint

        for corner, vertical in (("top", FixPoint.NORTH), ("bottom", FixPoint.SOUTH)):
            with self.subTest(corner=corner):
                a = api(placement=MagicMock(corner=corner))
                a._window = MagicMock()
                a.resize(330, 280.4)
                a.resize(330, 280)
                a._window.resize.assert_called_once_with(330, 280, fix_point=vertical | FixPoint.EAST)


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

    def test_default_corners(self):
        self.assertEqual(capsule.Placement(self.path, "top").start(1440, 900, (260, 56)), (1160, 44))
        self.assertEqual(capsule.Placement(self.path, "bottom").start(1920, 1080, (260, 56)), (1640, 968))

    def test_a_dragged_spot_is_remembered_and_ignored_when_off_screen(self):
        capsule.Placement(self.path, "top").moved(300, 200, 260, 56)
        self.assertEqual(capsule.Placement(self.path, "top").start(1440, 900, (330, 280)), (230, 200))
        self.assertEqual(capsule.Placement(self.path, "top").start(500, 400, (260, 56))[1], 44)
        self.assertEqual(capsule.Placement(self.path, "bottom").start(1440, 900, (260, 56)), (1160, 788))


class _Now:
    """threading.Thread stand-in that runs its target at once."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class NotifierTests(unittest.TestCase):
    def observe(self, notifier, prompts, enabled=True):
        from paper_search_carsi import user_settings

        state = running(attention={k: {"message": m, "since": s} for k, (m, s) in prompts.items()})
        with patch.object(capsule.threading, "Thread", _Now), \
             patch.object(user_settings, "notify_enabled", return_value=enabled):
            notifier.observe(state)

    def test_once_per_prompt(self):
        sent = []
        n = capsule.Notifier(send=lambda title, body: sent.append(body))
        self.observe(n, {"a": ("请在浏览器里登录学校", "t1")})
        self.observe(n, {"a": ("请在浏览器里登录学校", "t1")})
        self.observe(n, {"a": ("请在浏览器窗口完成安全验证", "t2")})
        self.assertEqual(sent, ["请在浏览器里登录学校", "请在浏览器窗口完成安全验证"])

    def test_switched_off(self):
        sent = []
        n = capsule.Notifier(send=lambda title, body: sent.append(body))
        self.observe(n, {"a": ("请在浏览器里登录学校", "t1")}, enabled=False)
        self.assertEqual(sent, [])


class FallbackTests(unittest.TestCase):
    def setUp(self):
        quiet_start = patch.object(capsule, "_prepare_nonactivating_start")
        quiet_start.start()
        self.addCleanup(quiet_start.stop)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"CARSI_DATA_DIR": tmp.name})
        env.start()
        self.addCleanup(env.stop)

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

    def test_the_page_loads_nothing_from_the_network(self):
        page = capsule.PAGE.read_text(encoding="utf-8")
        self.assertNotRegex(page, r"(src|href)=[\"']?https?://")
        self.assertNotIn("@import", page)


if __name__ == "__main__":
    unittest.main()

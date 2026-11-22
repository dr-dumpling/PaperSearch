"""One version and one update in the settings window (updates.py; user, 2026-11-21: PaperSearch and Pro updated by one
button, the window opening again with the new one)."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_search_school import progress_reporter, updates


def until(get, state):
    for _ in range(300):
        if get().get("state") == state:
            return get()
        threading.Event().wait(0.01)
    raise AssertionError(f"never {state}: {get()}")


class VersionTests(unittest.TestCase):
    def test_the_version_installed_is_the_extensions_record(self):
        root = Path(tempfile.mkdtemp())
        (root / "venv").mkdir()
        with patch.object(updates.sys, "prefix", str(root / "venv")):
            self.assertEqual(updates.installed_version(), "")
            (root / "install.json").write_text(json.dumps({"paperSearchVersion": "0.7.3"}), encoding="utf-8")
            self.assertEqual(updates.installed_version(), "0.7.3")
            (root / "install.json").write_text(json.dumps({"paperSearchVersion": "latest"}), encoding="utf-8")
            self.assertEqual(updates.installed_version(), "")


class VersionCheckTests(unittest.TestCase):
    def test_paper_searchs_newest_and_pros_with_it(self):
        asked = []
        answers = {"update": '{"ok":true,"source":"github","current":"0.7.2-preview.4","latest":"0.7.2-preview.5","update":true,'
                             '"releaseNotesUrl":"https://github.com/o/r/blob/main/CHANGELOG.md"}',
                   "pro": '{"ok":true,"installed":true,"version":"0.3.3","latest":"0.3.4","update":true}'}
        run = lambda argv, timeout: (asked.append(argv[1:]), (0, answers["update" if argv[1] == "update" else "pro"]))[1]  # noqa: E731
        now = [1000.0]
        check = updates.VersionCheck(command_of=lambda: ["paper-search"], run=run, pro_installed=lambda: True, now=lambda: now[0])
        self.assertEqual(check.start(), {"state": "running"})
        self.assertEqual(until(check.state, "done"), {"state": "done", "current": "0.7.2-preview.4", "latest": "0.7.2-preview.5",
                                                      "update": True, "notes": "https://github.com/o/r/blob/main/CHANGELOG.md",
                                                      "pro_update": True, "pro_latest": "0.3.4"})
        self.assertEqual(asked, [["update", "check", "--format", "json"], ["pro", "check"]])
        # An hour's answer kept, unless asked again.
        self.assertEqual(check.start()["state"], "done")
        self.assertEqual(len(asked), 2)
        check.start(again=True)
        until(check.state, "done")
        self.assertEqual(len(asked), 4)

    def test_npms_answer_and_no_pro_and_a_failure(self):
        npm = '{"ok":true,"currentVersion":"0.7.2","latestVersion":"0.7.2","updateAvailable":false,"releaseNotesUrl":"https://x"}'
        check = updates.VersionCheck(command_of=lambda: ["ps"], run=lambda argv, t: (0, npm), pro_installed=lambda: False)
        check.start()
        self.assertEqual(until(check.state, "done")["update"], False)
        failed = updates.VersionCheck(command_of=lambda: ["ps"], pro_installed=lambda: False,
                                      run=lambda argv, t: (1, '{"ok":false,"code":"github_login_required","message":"请先在终端运行 gh auth login 登录 GitHub"}'))
        failed.start()
        self.assertEqual(until(failed.state, "failed"), {"state": "failed", "message": "请先在终端运行 gh auth login 登录 GitHub"})
        missing = updates.VersionCheck(command_of=lambda: None)
        missing.start()
        self.assertEqual(until(missing.state, "failed")["message"], "找不到 paper-search 命令")


class UpdateAllTests(unittest.TestCase):
    def setUp(self):
        progress_reporter.progress_path().unlink(missing_ok=True)

    def tearDown(self):
        progress_reporter.progress_path().unlink(missing_ok=True)

    def test_what_is_behind_one_step_after_another_then_the_window_again(self):
        ran = []
        update = updates.UpdateAll(command_of=lambda: ["paper-search"], run=lambda argv, t: (ran.append(argv[1:]), (0, '{"ok":true}'))[1])
        started = update.start(core=True, pro=True, target="0.7.3")
        self.assertIn(started["state"], ("running", "done"))  # quick steps may be over already
        self.assertEqual(started["steps"], ["paper_search", "school", "skills", "pro"])
        done = until(update.state, "done")
        self.assertEqual((done["step"], done["reopen"], done["target"]), (4, True, "0.7.3"))
        self.assertEqual(ran, [["update", "install"], ["school", "update"], ["skills", "update"], ["pro", "install"]])
        # Pro alone: its install, no window to open again.
        ran.clear()
        alone = updates.UpdateAll(command_of=lambda: ["paper-search"], run=lambda argv, t: (ran.append(argv[1:]), (0, ""))[1])
        alone.start(core=False, pro=True)
        self.assertEqual(until(alone.state, "done")["reopen"], False)
        self.assertEqual(ran, [["pro", "install"]])
        self.assertEqual(updates.UpdateAll(command_of=lambda: ["x"]).start(core=False, pro=False), {"state": "idle"})

    def test_a_step_that_fails_stops_it_saying_why(self):
        answers = iter([(0, '{"ok":true}'), (1, '{"ok":false,"message":"没有权限更新全局安装的 PaperSearch，请在终端运行更新命令"}')])
        update = updates.UpdateAll(command_of=lambda: ["paper-search"], run=lambda argv, t: next(answers))
        update.start(core=True, pro=False)
        failed = until(update.state, "failed")
        self.assertEqual((failed["step"], failed["message"]), (1, "没有权限更新全局安装的 PaperSearch，请在终端运行更新命令"))
        quiet = updates.UpdateAll(command_of=lambda: ["paper-search"], run=lambda argv, t: (2, "not json"))
        quiet.start(core=False, pro=True)
        self.assertEqual(until(quiet.state, "failed")["message"], "更新Pro出错")

    def test_not_while_a_download_runs(self):
        progress_reporter._atomic_write({"task": "批量下载", "status": "running"})
        update = updates.UpdateAll(command_of=lambda: ["paper-search"], run=lambda argv, t: self.fail("ran"))
        self.assertEqual(update.start(core=True, pro=False), {"state": "idle", "error": "正在下载，等这次下载结束再更新"})


class ReopenTests(unittest.TestCase):
    def test_the_settings_opened_again_once_this_window_has_closed(self):
        started = []
        self.assertTrue(updates.reopen("about", command_of=lambda: ["node", "cli.js"], popen=lambda argv, **kw: started.append(argv)))
        argv = started[0]
        self.assertEqual(argv[1], "-c")
        self.assertEqual(json.loads(argv[4]), ["node", "cli.js", "settings", "about"])
        self.assertEqual(int(argv[3]), __import__("os").getpid())
        self.assertFalse(updates.reopen("about", command_of=lambda: None, popen=lambda argv, **kw: self.fail("started")))


if __name__ == "__main__":
    unittest.main()

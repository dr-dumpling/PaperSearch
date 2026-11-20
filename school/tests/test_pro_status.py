"""Whether PaperSearch Pro is installed, as the settings window's Markdown page shows it."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from paper_search_school import pro_status


class ProStatusTests(unittest.TestCase):
    def test_the_path_the_command_line_hands_or_pros_place_in_the_data_folder(self):
        self.assertEqual(pro_status.entry({"PAPER_SEARCH_PRO_PATH": "/opt/pro/index.js"}), Path("/opt/pro/index.js"))
        self.assertEqual(pro_status.entry({"XDG_DATA_HOME": "/data"}),
                         Path("/data").resolve() / "paper-search-cli" / "pro" / "index.js")

    def test_installed_with_its_version_or_not(self):
        nothing_yet = {"sites": [], "converted": 0, "complete": 0, "access": {"mode": "free", "until": ""}}
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / "pro" / "index.js"
            env = {"PAPER_SEARCH_PRO_PATH": str(entry), "XDG_DATA_HOME": tmp}
            self.assertEqual(pro_status.status(env), {"installed": False, "version": ""})
            entry.parent.mkdir()
            entry.write_text("export {};", encoding="utf-8")
            self.assertEqual(pro_status.status(env), {"installed": True, "version": "", **nothing_yet})
            (entry.parent / "pro.json").write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
            self.assertEqual(pro_status.status(env), {"installed": True, "version": "0.1.0", **nothing_yet})

    def test_the_sites_the_markdown_counted_and_whether_it_is_free(self):
        # The Markdown page drawn on 2026-11-19 (user): from pro.json, pro/stats.json, pro/access.json.
        import time
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_DATA_HOME": tmp}
            folder = pro_status.data_home(env) / "pro"
            folder.mkdir(parents=True)
            (folder / "index.js").write_text("export {};", encoding="utf-8")
            (folder / "pro.json").write_text(json.dumps({"version": "0.1.1", "sites": ["Science", "NEJM", 3]}), encoding="utf-8")
            (folder / "stats.json").write_text(json.dumps({"schemaVersion": 1, "converted": 12, "complete": 40}), encoding="utf-8")
            until = time.mktime((2027, 3, 1, 12, 0, 0, 0, 0, -1)) * 1000
            (folder / "access.json").write_text(json.dumps({"mode": "free", "until": until, "firstSeen": 1}), encoding="utf-8")
            self.assertEqual(pro_status.status(env), {"installed": True, "version": "0.1.1", "sites": ["Science", "NEJM"],
                                                      "converted": 12, "complete": 12,
                                                      "access": {"mode": "free", "until": "2027-03-01"}})
            (folder / "stats.json").write_text("{broken", encoding="utf-8")
            (folder / "access.json").write_text(json.dumps({"mode": "key"}), encoding="utf-8")
            status = pro_status.status(env)
            self.assertEqual((status["converted"], status["complete"], status["access"]), (0, 0, {"mode": "key", "until": ""}))

    def test_check_for_updates_says_the_newest_or_why_not(self):
        import time
        answers = iter(['{"ok":true,"installed":true,"version":"0.1.1","latest":"0.1.2","update":true}\n',
                        '{"ok":false,"code":"pro_github_login_required","message":"请先在终端运行 gh auth login 登录 GitHub"}\n',
                        "not json"])
        calls = []
        checker = pro_status.ProCheck(command_of=lambda: ["paper-search"],
                                      run=lambda argv: (calls.append(argv), next(answers))[1])

        def checked():
            self.assertEqual(checker.start(), {"state": "running"})
            for _ in range(200):
                if checker.state()["state"] != "running":
                    return checker.state()
                time.sleep(0.01)
            self.fail("the check did not end")

        self.assertEqual(checked(), {"state": "done", "latest": "0.1.2", "update": True})
        self.assertEqual(calls[0], ["paper-search", "pro", "check"])
        self.assertEqual(checked(), {"state": "failed", "message": "请先在终端运行 gh auth login 登录 GitHub"})
        self.assertEqual(checked(), {"state": "failed", "message": "检查更新出错"})
        self.assertEqual(pro_status.ProCheck(command_of=lambda: None).start(), {"state": "running"})

    def test_the_issue_page_is_the_public_trackers_with_its_title_begun(self):
        self.assertTrue(pro_status.ISSUE_URL.startswith("https://github.com/dr-dumpling/PaperSearch/issues/new?title="))
        self.assertTrue(unquote(pro_status.ISSUE_URL).endswith("Markdown 全文："))


class ProInstallTests(unittest.TestCase):
    """The settings window's 安装: `paper-search pro install --progress` in the background."""

    class FakeProcess:
        def __init__(self, lines):
            self.stdout = iter(lines)

        def wait(self, timeout=None):
            return 0

    def install(self, lines, command=("paper-search",)):
        import time

        calls = []

        def popen(argv, **kwargs):
            calls.append((argv, kwargs))
            return self.FakeProcess(lines)

        installer = pro_status.ProInstall(command_of=lambda: list(command) if command else None, popen=popen)
        self.assertEqual(installer.start()["state"], "running")
        deadline = time.time() + 5
        while installer.state()["state"] == "running" and time.time() < deadline:
            time.sleep(0.01)
        return installer.state(), calls

    def test_reads_its_progress_and_says_the_version_installed(self):
        state, calls = self.install(['{"event":"progress","done":1048576,"total":2207116}\n',
                                 '{"ok":true,"version":"0.1.0","path":"/data/pro/index.js"}\n'])
        self.assertEqual(state, {"state": "done", "version": "0.1.0"})
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["paper-search", "pro", "install", "--progress"])
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["env"]["PAPER_SEARCH_SKILL_AUTO_UPDATE"], "false")

    def test_a_failed_install_says_why_in_the_commands_words(self):
        state, _ = self.install(['{"event":"progress","done":10,"total":100}\n',
                             '{"ok":false,"code":"pro_install_failed","message":"网络连接中断","exitCode":1}\n'])
        self.assertEqual(state, {"state": "failed", "message": "网络连接中断"})
        state, _ = self.install([], command=None)
        self.assertEqual(state, {"state": "failed", "message": "找不到 paper-search 命令"})

    def test_a_second_click_while_it_runs_starts_nothing(self):
        import threading

        release = threading.Event()
        started = []

        class Slow:
            def __init__(self):
                self.stdout = self.lines()

            def lines(self):
                release.wait(5)
                yield '{"ok":true,"version":"0.1.0"}\n'

            def wait(self, timeout=None):
                return 0

        installer = pro_status.ProInstall(command_of=lambda: ["paper-search"], popen=lambda argv, **kw: started.append(argv) or Slow())
        installer.start()
        self.assertEqual(installer.start()["state"], "running")
        release.set()
        for _ in range(500):
            if installer.state()["state"] != "running":
                break
            threading.Event().wait(0.01)
        self.assertEqual(len(started), 1)
        self.assertEqual(installer.state()["state"], "done")


class ProFeaturesSwitchTests(unittest.TestCase):
    """The settings' Markdown page is one of PaperSearch Pro's features (edition.py, user 2026-11-19)."""

    def settings(self, target, given):
        import argparse
        import contextlib
        import io
        import sys
        from unittest import mock
        from paper_search_school import cli, progress_reporter

        out = io.StringIO()
        with mock.patch.dict(os.environ, {"PAPER_SEARCH_PRO_FEATURES": given, "SSH_CONNECTION": ""}), contextlib.redirect_stdout(out), \
                mock.patch.object(sys, "platform", "darwin"), mock.patch.dict(sys.modules, {"webview": mock.Mock()}), \
                mock.patch.object(progress_reporter, "open_settings", return_value="opened") as opened:
            code = cli._cmd_settings(argparse.Namespace(target=target))
        return code, json.loads(out.getvalue()), opened

    def test_the_markdown_page_opens_only_with_pros_features(self):
        code, reply, opened = self.settings("markdown", "1")
        self.assertEqual((code, reply["page"]), (0, "markdown"))
        opened.assert_called_once_with("markdown", "")
        code, reply, opened = self.settings("markdown", "0")
        self.assertEqual((code, reply), (2, {"ok": False, "error": "没有这一项设置：markdown"}))
        opened.assert_not_called()
        self.assertEqual(self.settings("keys", "0")[:2], (0, {"ok": True, "window": "opened", "page": "keys"}))


if __name__ == "__main__":
    unittest.main()

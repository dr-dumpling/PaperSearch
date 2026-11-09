"""API keys entered in the progress window's settings: saved in PaperSearch's CLI
config like `paper-search setup` does, and never shown back in full."""
import json
import os
import stat
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from paper_search_carsi import api_keys, cli
from paper_search_carsi.progress_capsule import Api

SECRET = "sk-" + "0123456789abcdef9f3c"  # a made-up key, joined at run time so secret scanners do not flag it


class ApiKeyTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.config = Path(tmp.name) / "config.json"
        self.config.write_text(json.dumps({"DEFAULT_DOWNLOAD_PATH": "/papers", "PUBMED_API_KEY": "abcd1234efgh"}))
        env = patch.dict(os.environ, {"PAPER_SEARCH_CONFIG_FILE": str(self.config)}); env.start(); self.addCleanup(env.stop)

    def saved(self):
        return json.loads(self.config.read_text())

    def service(self, listing, service_id):
        return next(s for g in listing["groups"] for s in g["services"] if s["id"] == service_id)

    def test_the_list_shows_whether_each_key_is_set_and_only_its_last_four_characters(self):
        listing = api_keys.listing()
        self.assertEqual((listing["filled"], listing["total"]), (1, 10))
        self.assertEqual([g["title"] for g in listing["groups"]], ["查期刊、搜正文", "出版社接口", "增加检索来源", "提高限额"])
        pubmed = self.service(listing, "pubmed")
        self.assertEqual((pubmed["set"], pubmed["masked"]), (True, "••••efgh"))
        self.assertNotIn("abcd1234efgh", json.dumps(listing, ensure_ascii=False))
        # Elsevier's institution token only reaches institutions: the window asks for the API key alone.
        self.assertEqual([k["key"] for k in self.service(listing, "elsevier")["keys"]], ["ELSEVIER_API_KEY"])
        self.assertEqual(self.service(listing, "semantic_scholar")["guide_label"], "申请教程")
        every = [s for g in listing["groups"] for s in g["services"]]
        self.assertEqual([s["id"] for s in every if not s["use"]], [])  # each says what it is for

    def test_saving_trims_the_key_and_keeps_every_other_setting(self):
        api_keys.save("elsevier", {"ELSEVIER_API_KEY": f"  {SECRET}\n"})
        saved = self.saved()
        self.assertEqual(api_keys.saved("elsevier"), {"ELSEVIER_API_KEY": SECRET})
        self.assertEqual((saved["DEFAULT_DOWNLOAD_PATH"], saved["PUBMED_API_KEY"]), ("/papers", "abcd1234efgh"))
        if sys.platform != "win32":
            self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_what_cannot_be_saved(self):
        for service, values, problem in (
            ("easyscholar", {"EASYSCHOLAR_KEY": "  "}, "请先粘贴 key"),
            ("easyscholar", {"EASYSCHOLAR_KEY": "abc def"}, "key 里不能有空格、换行或中文字符"),
            ("easyscholar", {"EASYSCHOLAR_KEY": "密钥1234"}, "key 里不能有空格、换行或中文字符"),
            ("easyscholar", {"EASYSCHOLAR_KEY": "x" * 513}, "太长了，请确认粘贴的是 key"),
            ("elsevier", {"ELSEVIER_API_KEY": ""}, "请先粘贴 key"),
            ("EASYSCHOLAR_KEY", {"EASYSCHOLAR_KEY": SECRET}, "没有这一项"),
            ("nope", {}, "没有这一项"),
        ):
            with self.subTest(service=service, values=values):
                with self.assertRaisesRegex(ValueError, problem):
                    api_keys.save(service, values)
        self.assertEqual(self.saved(), {"DEFAULT_DOWNLOAD_PATH": "/papers", "PUBMED_API_KEY": "abcd1234efgh"})

    def test_clearing_removes_every_key_of_the_service_only(self):
        self.config.write_text(json.dumps({"ELSEVIER_API_KEY": SECRET, "PUBMED_API_KEY": "p"}))
        api_keys.clear("elsevier")
        self.assertEqual(self.saved(), {"PUBMED_API_KEY": "p"})

    def test_a_service_is_found_by_its_id_or_by_any_of_its_keys(self):
        self.assertEqual(api_keys.find("ELSEVIER_API_KEY")["id"], "elsevier")
        self.assertIsNone(api_keys.find("ELSEVIER_INSTTOKEN"))
        self.assertEqual(api_keys.find("openalex_api_key")["id"], "openalex")
        self.assertEqual(api_keys.find("springer")["id"], "springer")
        self.assertIsNone(api_keys.find("NCBI_EMAIL"))

    def test_the_list_shows_only_the_end_of_a_key_and_an_opened_row_gets_its_values(self):
        a = Api(MagicMock(), MagicMock(), MagicMock())
        reply = a.save_api_key("easyscholar", {"EASYSCHOLAR_KEY": SECRET})
        self.assertTrue(reply["ok"])
        self.assertEqual(self.service(reply, "easyscholar")["masked"], "••••9f3c")
        self.assertNotIn(SECRET, json.dumps(reply, ensure_ascii=False))
        self.assertEqual(a.api_key_values("easyscholar"), {"ok": True, "values": {"EASYSCHOLAR_KEY": SECRET}})
        self.assertFalse(a.api_key_values("EASYSCHOLAR")["ok"])
        self.assertEqual(a.save_api_key("easyscholar", {"EASYSCHOLAR_KEY": "a b"}),
                         {"ok": False, "error": "key 里不能有空格、换行或中文字符"})
        self.assertFalse(self.service(a.clear_api_key("easyscholar"), "easyscholar")["set"])
        self.config.write_text("{broken")
        self.assertFalse(a.api_keys()["ok"])

    def test_only_a_listed_sign_up_page_opens(self):
        a = Api(MagicMock(), MagicMock(), MagicMock())
        with patch("webbrowser.open", return_value=True) as opened:
            self.assertEqual(a.open_signup("openalex"), {"ok": True})
            self.assertEqual(a.open_signup("https://example.com")["ok"], False)
            self.assertEqual(a.open_signup("semantic_scholar", True), {"ok": True})
            self.assertEqual(a.open_signup("pubmed", True)["ok"], False)  # no guide listed
        self.assertEqual([c.args[0] for c in opened.call_args_list],
                         ["https://openalex.org/settings/api", api_keys.find("semantic_scholar")["guide"]])


class ApiKeyTestButtonTests(unittest.TestCase):
    def test_a_key_is_tested_by_paper_search_with_the_values_on_stdin(self):
        done = MagicMock(stdout='{"ok": true, "key": "ELSEVIER_API_KEY", "status": "valid", "message": "可以用"}\n')
        with patch.dict(os.environ, {"PAPER_SEARCH_CLI": json.dumps(["/usr/bin/node", "/pkg/dist/cli.js"])}), \
             patch("subprocess.run", return_value=done) as run:
            result = Api(MagicMock(), MagicMock(), MagicMock()).test_api_key("elsevier", {"ELSEVIER_API_KEY": f" {SECRET} "})
        self.assertEqual(result, {"status": "valid", "message": "可以用"})
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["/usr/bin/node", "/pkg/dist/cli.js", "config", "test", "ELSEVIER_API_KEY", "--stdin"])
        self.assertEqual(json.loads(kwargs["input"]), {"ELSEVIER_API_KEY": SECRET})
        self.assertEqual(kwargs["env"]["PAPER_SEARCH_SKILL_AUTO_UPDATE"], "false")

    def test_without_paper_search_the_test_names_the_terminal_command(self):
        with patch.dict(os.environ, {"PAPER_SEARCH_CLI": ""}), patch("shutil.which", return_value=None):
            result = api_keys.test("easyscholar", {"EASYSCHOLAR_KEY": SECRET})
        self.assertEqual(result["status"], "error")
        self.assertIn("paper-search config test EASYSCHOLAR_KEY", result["message"])


class SettingsCommandTests(unittest.TestCase):
    def run_cli(self, *argv, env=None):
        screen = {"DISPLAY": ":0", "SSH_CONNECTION": ""}
        with patch("paper_search_carsi.progress_reporter.open_settings", return_value="opened") as open_settings, \
             patch.dict(os.environ, {**screen, **(env or {})}), patch("builtins.print") as printed:
            code = cli.main(["settings", *argv])
        return code, json.loads(printed.call_args[0][0]), open_settings

    def test_a_key_name_opens_its_service_and_a_page_name_its_page(self):
        code, reply, open_settings = self.run_cli("ELSEVIER_API_KEY")
        self.assertEqual((code, reply), (0, {"ok": True, "window": "opened", "page": "keys", "service": "elsevier"}))
        open_settings.assert_called_once_with("keys", "elsevier")
        code, reply, open_settings = self.run_cli("wait")
        open_settings.assert_called_once_with("wait", "")
        code, reply, open_settings = self.run_cli()
        open_settings.assert_called_once_with("home", "")

    def test_without_a_screen_the_terminal_is_named_instead(self):
        with patch.object(cli.sys, "platform", "linux"):
            code, reply, open_settings = self.run_cli("EASYSCHOLAR_KEY", env={"DISPLAY": "", "WAYLAND_DISPLAY": ""})
        self.assertEqual(code, 1)
        self.assertIn("paper-search setup EASYSCHOLAR_KEY", reply["error"])
        open_settings.assert_not_called()

    def test_over_ssh_the_reply_says_where_the_window_is(self):
        code, reply, _ = self.run_cli("wait", env={"SSH_CONNECTION": "10.0.0.2 50000 10.0.0.1 22"})
        self.assertEqual(code, 0)
        self.assertIn("paper-search setup <KEY>", reply["note"])

    def test_an_unknown_target_opens_nothing(self):
        code, reply, open_settings = self.run_cli("NCBI_EMAIL")
        self.assertEqual(code, 2)
        self.assertFalse(reply["ok"])
        open_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()

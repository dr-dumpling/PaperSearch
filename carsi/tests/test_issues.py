"""Problem reports from the progress window: written at once, enriched with the live page, reviewed."""
import json
import unittest
from unittest.mock import patch

from paper_search_carsi import issues


class FakeTab:
    def __init__(self, url, title):
        self.url, self._title = url, title
        self.context = None

    def title(self):
        return self._title

    def is_closed(self):
        return False

    def evaluate(self, script):
        return "Institutional Login page text"

    def locator(self, selector):
        return selector

    def screenshot(self, path, full_page=False, timeout=None, mask=None, **kwargs):
        assert mask == ["input, textarea, select, [contenteditable]"]
        open(path, "wb").write(b"png")


class IssueReportTests(unittest.TestCase):
    def setUp(self):
        import shutil
        shutil.rmtree(issues.issues_dir(), ignore_errors=True)

    def test_report_is_written_then_enriched_with_the_live_page_and_reviewed(self):
        folder = issues.report("10.1103/x", "personal_login",
                               {"journal": "PRL", "publisher": "APS", "phase": "机构登录", "run_id": "r1"})
        data = json.loads((folder / "issue.json").read_text(encoding="utf-8"))
        self.assertEqual((data["status"], data["label"], data["needs_page_capture"]),
                         ("open", "跳到了个人账号登录", True))
        self.assertEqual([p.name for p in issues.pending_captures("10.1103/X")], [folder.name])
        self.assertEqual(issues.pending_captures("10.1103/other"), [])

        page = FakeTab("https://journals.aps.org/login", "Sign in")
        other = FakeTab("https://journals.aps.org/prl/abstract/x", "Article")
        page.context = other.context = type("Ctx", (), {"pages": [page, other]})()
        issues.attach_page(folder, page, [{"state": "sso_start", "detail": "x", "at": "22:10:00"}])
        data = json.loads((folder / "issue.json").read_text(encoding="utf-8"))
        self.assertFalse(data["needs_page_capture"])
        self.assertEqual([t["url"] for t in data["page"]["tabs"]],
                         ["https://journals.aps.org/login", "https://journals.aps.org/prl/abstract/x"])
        self.assertTrue(data["page"]["tabs"][0]["working_tab"])
        self.assertTrue((folder / "tab1.png").exists())
        self.assertEqual(issues.pending_captures("10.1103/x"), [])

        self.assertEqual([r["id"] for r in issues.list_issues()], [folder.name])
        self.assertTrue(issues.resolve(folder.name, "APS entry fixed"))
        self.assertEqual(issues.list_issues(), [])
        self.assertEqual(issues.list_issues(None)[0]["review"]["note"], "APS entry fixed")

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            issues.report("10.1/x", "delete")

    def test_cli_lists_and_resolves(self):
        from paper_search_carsi import cli
        folder = issues.report("10.1/x", "wrong_redirect", {})
        with patch("builtins.print") as out:
            self.assertEqual(cli.main(["issues"]), 0)
            self.assertEqual(json.loads(out.call_args.args[0])[0]["id"], folder.name)
            self.assertEqual(cli.main(["issues", "resolve", folder.name, "--note", "checked"]), 0)
            self.assertEqual(cli.main(["issues"]), 0)
            self.assertEqual(json.loads(out.call_args.args[0]), [])

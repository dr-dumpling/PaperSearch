"""Remembered entitlement decisions: window buttons, skip before any browser, CLI."""
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_search_carsi import entitlements as ent
from paper_search_carsi.engine import bridge
from paper_search_carsi.engine.batch import (
    DownloadResult, PublisherBatchDownloader, UserMarkedNoEntitlement)

HEP = {"issn": ["0270-9139", "1527-3350"], "journal": "Hepatology", "publisher": "Ovid Technologies"}
GUT = {"issn": ["0017-5749"], "journal": "Gut", "publisher": "BMJ"}


class EntitlementMemoryTests(unittest.TestCase):
    def setUp(self):
        for path in (ent.entitlements_path(), ent.control_path(), ent._data_dir() / "journal_cache.json"):
            path.unlink(missing_ok=True)
        ids = {"10.1097/hep.1": HEP, "10.1097/hep.2": HEP, "10.1136/gut.1": GUT}
        patcher = patch.object(ent, "journal_identity", side_effect=lambda doi, lookup=True: ids.get(doi, {"issn": [], "journal": "", "publisher": ""}))
        patcher.start(); self.addCleanup(patcher.stop)

    def test_journal_decisions_apply_to_other_papers_of_the_journal(self):
        self.assertIsNone(ent.decision_for("10.1097/hep.2", "LWW"))
        entry = ent.record("10.1097/hep.1", "LWW", "skip_journal")
        self.assertEqual(entry["key"], "issn:0270-9139")
        self.assertEqual(ent.decision_for("10.1097/hep.2", "LWW")["decision"], "skip")
        self.assertIsNone(ent.decision_for("10.1136/gut.1", "BMJ"))

    def test_journal_access_overrides_a_publisher_skip(self):
        ent.record("10.1136/gut.1", "BMJ", "skip_publisher")
        self.assertEqual(ent.decision_for("10.1136/gut.1", "BMJ")["key"], "publisher:bmj")
        ent.record("10.1136/gut.1", "BMJ", "allow_journal")
        self.assertEqual(ent.decision_for("10.1136/gut.1", "BMJ")["decision"], "allow")
        self.assertTrue(ent.clear("issn:0017-5749"))
        self.assertEqual(ent.decision_for("10.1136/gut.1", "BMJ")["decision"], "skip")

    def test_window_request_is_taken_once_for_the_current_paper(self):
        started = time.time() - 1
        ent.request_action("10.1097/hep.1", "skip_journal")
        self.assertIsNone(ent.take_action("10.1136/gut.1", started))          # other paper
        self.assertIsNone(ent.take_action("10.1097/hep.1", time.time() + 5))  # older than this item
        self.assertEqual(ent.take_action("10.1097/hep.1", started), "skip_journal")
        self.assertIsNone(ent.take_action("10.1097/hep.1", started))          # consumed
        with self.assertRaises(ValueError):
            ent.request_action("10.1097/hep.1", "delete_everything")

    def test_downloader_applies_the_button_and_stops_the_paper(self):
        d = PublisherBatchDownloader({}, profile=SimpleNamespace(name="LWW", article_url=lambda doi: doi))
        d._item_started = time.time() - 1
        result = DownloadResult(doi="10.1097/hep.1", status="failed")
        ent.request_action("10.1097/hep.1", "skip_publisher")
        with self.assertRaises(UserMarkedNoEntitlement):
            d._check_user_decision(result)
        self.assertEqual(ent.load()["publisher:lww"]["decision"], "skip")
        ent.request_action("10.1097/hep.1", "allow_journal")
        d._check_user_decision(result)  # allow: recorded, no exception
        self.assertEqual(ent.load()["issn:0270-9139"]["decision"], "allow")

    def test_remembered_no_access_is_skipped_before_any_browser(self):
        ent.record("10.1097/hep.1", "LWW", "skip_journal")
        profile = SimpleNamespace(name="LWW")
        with patch.object(bridge, "_resolve_doi", return_value="https://journals.lww.com/hep/x"), \
             patch.object(bridge, "_try_browser_batch_download") as browser:
            result = bridge._try_builtin_institutional("10.1097/hep.2", Path("/tmp/x.pdf"),
                                                       {"publisher_institution_federation": "carsi"}, profile)
        browser.assert_not_called()
        self.assertEqual((result["error_type"], result["reason"]), ("no_entitlement", "user_marked_no_entitlement"))
        self.assertEqual(result["entitlement"]["key"], "issn:0270-9139")

    def test_a_journal_whose_site_blocked_the_network_is_answered_at_once_for_a_while(self):
        # BMJ's Gut behind a Cloudflare block page (2026-11-02): its later items need no
        # browser; another journal of the same publisher is still tried. The data
        # directory keeps it: PaperSearch starts the backend anew for every article.
        import importlib
        from paper_search_carsi import blocked_journals
        blocked_journals.ledger_path().unlink(missing_ok=True)
        self.addCleanup(blocked_journals.ledger_path().unlink, missing_ok=True)
        profile = SimpleNamespace(name="BMJ")
        blocked = {"success": False, "error_type": "access_blocked", "reason": "publisher_access_blocked",
                   "action": "review_access"}
        config = {"publisher_institution_federation": "carsi", "publisher_hourly_limit": 0}
        with patch.object(bridge, "_resolve_doi", return_value="https://gut.bmj.com/x"), \
             patch.object(bridge, "_try_browser_batch_download", return_value=blocked) as browser:
            first = bridge._try_builtin_institutional("10.1136/gut.1", Path("/tmp/x.pdf"), config, profile)
            importlib.reload(blocked_journals)  # as a new backend process would
            again = bridge._try_builtin_institutional("10.1136/gut.1", Path("/tmp/y.pdf"), config, profile)
            other = bridge._try_builtin_institutional("10.1097/hep.1", Path("/tmp/z.pdf"), config, profile)
        self.assertEqual(first["error_type"], "access_blocked")
        self.assertEqual((again["reason"], again["blocked_by"]), ("journal_blocked_earlier", "10.1136/gut.1"))
        self.assertEqual(browser.call_count, 2)  # the first Gut item and the Hepatology item
        self.assertEqual(other["reason"], "publisher_access_blocked")
        # Half an hour later the journal is tried again, and the old entry is gone.
        later = time.time() + blocked_journals.KEEP_SEC + 1
        self.assertEqual(blocked_journals.blocked_by(GUT, now=later), "")
        self.assertFalse(blocked_journals.any_recent(now=later))

    def test_cli_lists_sets_and_clears(self):
        from paper_search_carsi import cli
        with patch("builtins.print") as out:
            self.assertEqual(cli.main(["entitlements", "set", "--doi", "10.1136/gut.1", "--decision", "skip_journal", "--publisher", "BMJ"]), 0)
            self.assertEqual(cli.main(["entitlements"]), 0)
            listed = json.loads(out.call_args.args[0])
            self.assertIn("issn:0017-5749", listed)
            self.assertEqual(cli.main(["entitlements", "clear", "issn:0017-5749"]), 0)
        self.assertEqual(ent.load(), {})


    def test_apply_user_decision_records_and_raises_on_skip(self):
        started = time.time() - 1
        ent.request_action("10.1097/hep.1", "allow_journal")
        self.assertEqual(ent.apply_user_decision("10.1097/hep.1", "LWW", started), "allow_journal")
        ent.request_action("10.1097/hep.1", "skip_journal")
        with self.assertRaises(ent.UserMarkedNoEntitlement):
            ent.apply_user_decision("10.1097/hep.1", "LWW", started)
        self.assertEqual(ent.load()["issn:0270-9139"]["decision"], "skip")

if __name__ == "__main__":
    unittest.main()


class CrossrefTitleTests(unittest.TestCase):
    def test_html_entities_in_journal_titles_are_decoded(self):
        from unittest.mock import MagicMock
        from paper_search_carsi import entitlements
        response = MagicMock(status_code=200)
        response.json.return_value = {"message": {"ISSN": ["2326-5191"], "container-title": ["Arthritis &amp; Rheumatology"], "publisher": "Wiley"}}
        with patch("requests.get", return_value=response):
            identity = entitlements.journal_identity("10.1002/entity-test")
        self.assertEqual(identity["journal"], "Arthritis & Rheumatology")

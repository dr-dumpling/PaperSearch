"""Stage reports reflect file persistence and explicit browser events."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from paper_search_carsi import progress_reporter as progress
from paper_search_carsi import server
from paper_search_carsi.engine.batch import DownloadResult, PaperRecord, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE

DOI = "10.1000/progress-fixture"


class MachineProgressEventsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {"CARSI_DATA_DIR": tmp.name, "CARSI_PROGRESS_BAR": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(lambda: setattr(progress, "_STATE", {}))
        progress.start_task("fixture", 1, current=DOI)

    def downloader(self):
        d = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
        page = Mock(spec=["url", "close", "wait_for_load_state", "on", "remove_listener"])
        page.url = "https://www.sciencedirect.com/science/article/pii/fixture"
        d._ensure_login = Mock(return_value=True)
        d._looks_logged_out = Mock(return_value=False)
        d._access_decision = Mock(return_value=("in", "session", ""))  # signed in
        d._title = Mock(return_value="Fixture title")
        d._hold_after_login = Mock()
        d._hold_after_run = Mock()
        d._write_diagnostic = Mock()
        d._save_publisher_session = Mock()
        d._capture_pdf = Mock(return_value=(b"%PDF-1.7\nfixture", "https://example.invalid/article.pdf", None))
        return d, page

    def test_saved_stage_only_follows_successful_file_write(self):
        d, page = self.downloader()
        observed = []
        real_event = d._event
        def event(result, name, detail=""):
            if name == "pdf_saved":
                files = list((self.root/"run"/"pdfs").glob("*.pdf"))
                self.assertEqual(len(files), 1)
                self.assertTrue(files[0].read_bytes().startswith(b"%PDF-"))
            real_event(result, name, detail)
            observed.append(progress.read_state()["stage"])
        with patch.object(d, "_event", side_effect=event), patch(
            "paper_search_carsi.engine.batch.time.sleep"
        ), patch("paper_search_carsi.engine.batch.pdf_extractor.extract_from_bytes", return_value="Fixture title"):
            result = d.fetch_one(page, PaperRecord(doi=DOI), self.root/"run")
        self.assertTrue(result.ok)
        self.assertIn("opening_article", observed)
        self.assertIn("checking_access", observed)
        self.assertEqual(progress.read_state()["stage"], "saved_pending_verification")
        self.assertNotIn("verified", progress.read_state())

    def test_write_error_after_capture_never_reports_saved(self):
        d, page = self.downloader()
        PublisherBatchDownloader._event(DownloadResult(doi=DOI, status="failed"), "browser_pdf_response_captured")
        self.assertEqual(progress.read_state()["stage"], "pdf_captured")
        with patch("paper_search_carsi.engine.batch.time.sleep"), patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            result = d.fetch_one(page, PaperRecord(doi=DOI), self.root/"run")
        self.assertFalse(result.ok)
        self.assertEqual(progress.read_state()["stage"], "route_failed")
        self.assertNotIn("pdf_saved", [e["state"] for e in result.events])

    def test_login_challenge_resolution_changes_machine_stage_without_secrets(self):
        result = DownloadResult(doi=DOI, status="failed")
        for event, expected in [("sso_start", "waiting_login"),
                                ("challenge_wait", "checking_access"),
                                ("challenge_manual_wait", "waiting_verification"),
                                ("challenge_resolved", "checking_access"),
                                ("browser_pdf_response_captured", "pdf_captured"),
                                ("publisher_access_blocked", "route_failed")]:
            PublisherBatchDownloader._event(result, event, "https://example.invalid/?token=private-fixture")
            state = progress.read_state()
            self.assertEqual(state["stage"], expected)
            self.assertEqual(state["current"], DOI)
            self.assertNotIn("private-fixture", json.dumps(state))
            self.assertEqual(state["done"], 0)

    def test_mcp_final_result_keeps_identity_pending_and_exception_fails(self):
        with patch.object(server, "download", return_value={"success": True, "file": "/tmp/fixture.pdf"}):
            server.carsi_download(DOI)
        state = progress.read_state()
        self.assertEqual((state["status"], state["stage"]), ("done", "saved_pending_verification"))
        with patch.object(server, "download", side_effect=RuntimeError("private-fixture")):
            with self.assertRaises(RuntimeError):
                server.carsi_download(DOI)
        state = progress.read_state()
        self.assertEqual((state["status"], state["stage"]), ("done", "failed"))
        self.assertNotIn("private-fixture", json.dumps(state))

    def test_mcp_terminal_block_keeps_fixed_failure_message(self):
        with patch.object(server, "download", return_value={
                "success": False, "error_type": "access_blocked", "reason": "token=private-fixture"}):
            server.carsi_download(DOI)
        state = progress.read_state()
        self.assertEqual((state['status'], state['stage'], state['failed']), ('done', 'failed', 1))
        self.assertEqual(state['phase'], '网站已阻止当前访问，未取得 PDF')
        self.assertNotIn('private-fixture', json.dumps(state))

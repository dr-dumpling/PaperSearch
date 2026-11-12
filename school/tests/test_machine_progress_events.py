"""Stage reports reflect file persistence and explicit browser events."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from paper_search_school import progress_reporter as progress
from paper_search_school import server
from paper_search_school.engine.batch import DownloadResult, PaperRecord, PublisherBatchDownloader
from paper_search_school.publishers.profiles import ELSEVIER_PROFILE

DOI = "10.1000/progress-fixture"


class MachineProgressEventsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {"SCHOOL_DATA_DIR": tmp.name, "SCHOOL_PROGRESS_BAR": "0"})
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
            "paper_search_school.engine.batch.time.sleep"
        ), patch("paper_search_school.engine.batch.pdf_extractor.extract_from_bytes", return_value="Fixture title"):
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
        with patch("paper_search_school.engine.batch.time.sleep"), patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            result = d.fetch_one(page, PaperRecord(doi=DOI), self.root/"run")
        self.assertFalse(result.ok)
        self.assertEqual(progress.read_state()["stage"], "route_failed")
        self.assertNotIn("pdf_saved", [e["state"] for e in result.events])

    def test_login_challenge_resolution_changes_machine_stage_without_secrets(self):
        result = DownloadResult(doi=DOI, status="failed")
        for event, expected in [("sso_start", "checking_access"),
                                ("challenge_wait", "checking_access"),
                                ("challenge_manual_wait", "checking_access"),
                                ("challenge_resolved", "checking_access"),
                                ("browser_pdf_response_captured", "pdf_captured"),
                                ("publisher_access_blocked", "route_failed")]:
            PublisherBatchDownloader._event(result, event, "https://example.invalid/?token=private-fixture")
            state = progress.read_state()
            self.assertEqual(state["stage"], expected)
            self.assertEqual(state["current"], DOI)
            self.assertNotIn("private-fixture", json.dumps(state))
            self.assertEqual(state["done"], 0)

    def test_automatic_login_steps_do_not_request_school_credentials(self):
        result = DownloadResult(doi=DOI, status="failed")
        for event, detail in [("sso_start", ""), ("institution_federation_selected", ""),
                              ("institution_entry_unresolved", ""), ("institution_selection_required", "carsi"),
                              ("login_state", ""),
                              ("login_attempt_started", "1/3"), ("login_retry_wait", ""),
                              ("login_navigation_interrupted", ""), ("login_observed", "publisher")]:
            PublisherBatchDownloader._event(result, event, detail)
            self.assertEqual(progress.read_state()["stage"], "checking_access", event)
            self.assertFalse(progress.read_state()["attention"], event)
        d = PublisherBatchDownloader({})
        d._set_login_attention(result, "请在浏览器里登录学校")
        self.assertEqual(progress.read_state()["stage"], "waiting_login")
        self.assertTrue(progress.read_state()["attention"])
        d._event(result, "login_state", "school account page")
        self.assertEqual(progress.read_state()["stage"], "waiting_login")
        d._set_login_attention(result, "")
        d._event(result, "login_state", "publisher article")
        self.assertEqual(progress.read_state()["stage"], "checking_access")

    def test_mcp_final_result_keeps_identity_pending_and_exception_fails(self):
        with patch.object(server, "download", return_value={"success": True, "file": "/tmp/fixture.pdf"}):
            server.school_download(DOI)
        state = progress.read_state()
        self.assertEqual((state["status"], state["stage"]), ("done", "saved_pending_verification"))
        with patch.object(server, "download", side_effect=RuntimeError("private-fixture")):
            with self.assertRaises(RuntimeError):
                server.school_download(DOI)
        state = progress.read_state()
        self.assertEqual((state["status"], state["stage"]), ("done", "failed"))
        self.assertNotIn("private-fixture", json.dumps(state))

    def test_mcp_terminal_block_keeps_fixed_failure_message(self):
        with patch.object(server, "download", return_value={
                "success": False, "error_type": "access_blocked", "reason": "token=private-fixture"}):
            server.school_download(DOI)
        state = progress.read_state()
        self.assertEqual((state['status'], state['stage'], state['failed']), ('done', 'failed', 1))
        self.assertEqual(state['phase'], '网站已阻止当前访问，未取得 PDF')
        self.assertNotIn('private-fixture', json.dumps(state))

    def test_supplements_completion_does_not_report_a_main_pdf_failure(self):
        for files, stage, succeeded in [([], 'supplements_checked', 1),
                ([{'status': 'saved', 'file': '/tmp/S1.pdf'}], 'supplements_checked', 1),
                ([{'status': 'failed', 'reason': 'http_404'}], 'failed', 0),
                ([{'status': 'skipped', 'reason': 'user_skipped'}], 'failed', 0)]:
            with self.subTest(files=files):
                payload = {'success': False, 'error_type': 'supplements_only', 'supplements': files}
                with patch.object(server, 'download', return_value=payload):
                    result = json.loads(server.school_download(DOI, supplements='only'))
                state = progress.read_state()
                self.assertEqual((state['stage'], state['success']), (stage, succeeded))
                self.assertFalse(result['success'])  # no main PDF was downloaded
                if stage == 'supplements_checked':
                    self.assertNotIn('下载未完成', state['phase'])
                    self.assertNotIn('PDF', state['phase'])

    def test_empty_files_do_not_hide_an_incomplete_check(self):
        with patch.object(server, 'download', return_value={
                'success': False, 'error_type': 'source_exception', 'supplements': []}):
            server.school_download(DOI, supplements='only')
        state = progress.read_state()
        self.assertEqual((state['stage'], state['success'], state['failed']), ('failed', 0, 1))

    def test_saved_supplements_remain_completed_even_with_a_main_error(self):
        with patch.object(server, 'download', return_value={
                'success': False, 'error_type': 'source_exception',
                'supplements': [{'status': 'saved', 'file': '/tmp/S1.pdf'}]}):
            server.school_download(DOI, supplements='only')
        state = progress.read_state()
        self.assertEqual((state['stage'], state['success']), ('supplements_checked', 1))

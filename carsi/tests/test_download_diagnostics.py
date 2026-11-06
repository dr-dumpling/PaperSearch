import copy
import csv
import io
import json
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from paper_search_carsi.download_diagnostics import serialize_download_result, serialize_download_summary
from paper_search_carsi.engine.batch import DownloadResult, PaperRecord, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE


class DownloadDiagnosticsTests(unittest.TestCase):
    def record(self, **extra):
        return dict(doi="10.1000/fixture", status="success", state="pdf_response_captured",
                    reason="", size_bytes=12345, text_length=500, verified_match=True,
                    article_url="https://pubs.rsc.org/article/fixture",
                    final_url="https://sso.rsc.org/WAYF", pdf_url=None,
                    events=[{"state": "pdf_saved", "detail": "navigation evidence"}], **extra)

    def test_normal_data_and_public_url_categories(self):
        output = serialize_download_result(self.record())
        self.assertEqual(output["doi"], "10.1000/fixture")
        self.assertEqual(output["size_bytes"], 12345)
        self.assertTrue(output["verified_match"])
        self.assertEqual(output["article_url_role"], "publisher")
        self.assertEqual(output["final_url_role"], "authentication")
        self.assertEqual(output["events"], [{"state": "pdf_saved"}])

    def test_authentication_values_never_survive_any_url_field(self):
        for field in ("article_url", "final_url", "pdf_url"):
            with self.subTest(field=field):
                record = self.record()
                record[field] = "https://identity.example.invalid/SAML?SAMLResponse=CANARY_SAML&code=CANARY_OIDC&token=CANARY_TOKEN#CANARY_FRAGMENT"
                output = json.dumps(serialize_download_result(record))
                for forbidden in ("CANARY_", "identity.example.invalid", "SAMLResponse", "?", "#"):
                    self.assertNotIn(forbidden, output)

    def test_unknown_fields_and_event_payloads_are_not_recursively_serialized(self):
        record = self.record(password="CANARY_PASSWORD", token="CANARY_TOKEN",
                             body_excerpt="CANARY_BODY", title="CANARY_TITLE",
                             full_text="CANARY_IMPLICIT_TEXT", pdf_path="/CANARY_USER/file.pdf")
        record["reason"] = "RuntimeError: CANARY_EXCEPTION"
        record["events"] = [{"state": "sso_entry_clicked", "detail": {"password": "CANARY_FORM"}},
                            {"state": "CANARY_EVENT", "detail": "CANARY_DETAIL"}]
        output = serialize_download_result(record)
        self.assertEqual(output["reason"], "request_failed")
        self.assertEqual(output["events"][1], {"state": "unknown"})
        self.assertNotIn("CANARY", json.dumps(output))

    def test_input_dataclass_like_object_and_nested_events_are_unchanged(self):
        record = SimpleNamespace(**self.record())
        before = copy.deepcopy(vars(record))
        serialize_download_result(record)
        self.assertEqual(vars(record), before)
        self.assertEqual(record.events[0]["detail"], "navigation evidence")

    def test_fixed_classifications_and_known_observation_are_preserved(self):
        for reason in ("login_timeout", "login_page_closed", "login_credentials_rejected",
                       "login_retries_exhausted", "institution_not_registered",
                       "institution_pdf_entitlement_missing",
                       "publisher_temporarily_unavailable"):
            record = self.record()
            record.update(status="failed", state=reason, reason=reason,
                          events=[{"state": "login_stopped", "detail": reason}])
            output = serialize_download_result(record)
            self.assertEqual(output["reason"], reason)
            self.assertEqual(output["events"][0]["category"], reason)

    def test_arbitrary_snake_case_values_are_not_accepted_as_status_or_stage(self):
        record = self.record()
        record.update(status="canary_status", state="canary_state", reason="canary_reason")
        output = serialize_download_result(record)
        self.assertEqual((output["status"], output["state"], output["reason"]),
                         ("unknown", "unknown", "request_failed"))
        record.update(state="login_credentials_rejected", reason="RuntimeError: CANARY")
        self.assertEqual(serialize_download_result(record)["reason"], "login_credentials_rejected")

    def test_full_text_is_explicit_and_requires_verified_success(self):
        body = "Verified article body discussing SAML and token terminology."
        record = self.record(full_text="CANARY_IMPLICIT")
        self.assertNotIn("full_text", serialize_download_result(record))
        self.assertEqual(serialize_download_result(record, full_text=body)["full_text"], body)
        for status, verified in (("failed", True), ("success", False), ("success", "true")):
            record.update(status=status, verified_match=verified)
            self.assertNotIn("full_text", serialize_download_result(record, full_text=body))

    def test_invalid_doi_cannot_carry_authentication_payload(self):
        for value in ("10.1000/fixture?token=CANARY", "10.1000/fixture#CANARY",
                      "10.1000/fixture\nCANARY", {"password": "CANARY"}, None):
            record = self.record()
            record["doi"] = value
            self.assertIsNone(serialize_download_result(record)["doi"])

    def test_host_boundary_and_userinfo_never_produce_public_host_disclosure(self):
        for value, role in (("https://pubs.rsc.org.evil.invalid/article", "external"),
                            ("https://CANARY:CANARY@pubs.rsc.org/article", "invalid"),
                            ("file:///CANARY", "invalid"), ("https://[broken", "invalid"),
                            ("https://pubs.rsc.org:bad/article", "invalid"),
                            ("https://watermark02.silverchair.com/file.pdf?token=CANARY", "pdf_delivery")):
            record = self.record()
            record["final_url"] = value
            output = serialize_download_result(record)
            self.assertEqual(output["final_url_role"], role)
            self.assertNotIn("CANARY", json.dumps(output))

    def test_numeric_and_boolean_types_do_not_copy_arbitrary_payloads(self):
        for value in (True, -1, 1.5, "CANARY", {"token": "CANARY"}, 2**60):
            record = self.record()
            record.update(size_bytes=value, text_length=value, verified_match="CANARY")
            output = serialize_download_result(record)
            self.assertIsNone(output["size_bytes"])
            self.assertIsNone(output["text_length"])
            self.assertIsNone(output["verified_match"])

    def test_attempt_and_manifest_csv_share_scalar_allowlist(self):
        record = self.record()
        record.update(reason="CANARY_EXCEPTION", pdf_path="/CANARY_USER/file.pdf")
        output = serialize_download_result(record, phase="retry", include_events=False,
                                           artifact_name="10.1000_fixture.pdf")
        self.assertEqual(output["phase"], "retry")
        self.assertEqual(output["artifact_name"], "10.1000_fixture.pdf")
        self.assertNotIn("events", output)
        target = io.StringIO()
        writer = csv.DictWriter(target, fieldnames=list(output))
        writer.writeheader()
        writer.writerow(output)
        self.assertNotIn("CANARY", target.getvalue())
        self.assertNotIn("pdf_path", output)
        bad = serialize_download_result(record, phase="CANARY", artifact_name="../CANARY.pdf")
        self.assertEqual(bad["phase"], "unknown")
        self.assertNotIn("artifact_name", bad)

    def test_event_cap_is_explicit_and_not_a_mutation(self):
        record = self.record()
        record["events"] = [{"state": "challenge_wait", "detail": "CANARY"}] * 300
        output = serialize_download_result(record)
        self.assertEqual(len(output["events"]), 256)
        self.assertTrue(output["events_truncated"])
        self.assertEqual(len(record["events"]), 300)
        self.assertNotIn("CANARY", json.dumps(output))


class DownloadArtifactIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.downloader = PublisherBatchDownloader({}, profile=ELSEVIER_PROFILE)
        self.result = DownloadResult(doi="10.1000/fixture", status="failed",
            state="login_timeout", reason="CANARY_EXCEPTION",
            final_url="https://identity.example/SAML/CANARY_PATH?token=CANARY_TOKEN",
            title="CANARY_TITLE", events=[{"state": "sso_start", "detail": "CANARY_DETAIL"}])

    def test_results_and_attempt_writers_drop_raw_diagnostics_without_mutating_state(self):
        before = copy.deepcopy(self.result)
        self.downloader._write_results(self.root / "results.json", [self.result])
        self.downloader._append_attempt(self.root / "attempts.jsonl", self.result, "retry")
        for name in ("results.json", "attempts.jsonl"):
            body = (self.root / name).read_text()
            self.assertNotIn("CANARY", body)
            self.assertNotIn("identity.example", body)
            self.assertIn("login_timeout", body)
        self.assertEqual(self.downloader._read_attempted_dois(self.root / "attempts.jsonl"),
                         {"10.1000/fixture"})
        self.assertEqual(self.result, before)

    def test_diagnostic_is_unmasked_and_page_capture_does_not_replace_live_result(self):
        page = Mock(url=self.result.final_url)
        with patch.object(self.downloader, "_body_text") as body, patch.object(
            self.downloader, "_title", return_value="Captured page title") as title:
            self.downloader._write_diagnostic(page, self.result, self.root)
        body.assert_not_called()
        title.assert_called_once()
        # User decision 2026-10-29: diagnostic files keep everything unmasked.
        diagnostic = Path(self.result.diagnostic_path).read_text()
        self.assertIn("CANARY_TOKEN", diagnostic)
        self.assertIn("CANARY_DETAIL", diagnostic)
        self.assertEqual(self.result.title, "CANARY_TITLE")
        self.assertIn("CANARY_TOKEN", self.result.final_url)

    def test_stopped_items_write_existing_evidence_without_more_browser_calls(self):
        for state in ("user_skipped", "batch_stopped", "user_marked_no_entitlement", "browser_unresponsive"):
            with self.subTest(state=state):
                self.result.state = self.result.reason = state
                page = Mock(url=self.result.final_url)
                with patch.object(self.downloader, "_access_state") as probe:
                    self.downloader._write_diagnostic(page, self.result, self.root)
                probe.assert_not_called()
                page.screenshot.assert_not_called()
                packet = json.loads(Path(self.result.diagnostic_path).read_text())
                self.assertEqual(packet["raw_state"], state)
                self.assertEqual(packet["access_evidence"], ["probe skipped: item stopped"])
                self.assertIn("CANARY_DETAIL", packet["events"][0]["detail"])

    def test_complete_manifest_preserves_batch_pdf_lookup_and_fixed_csv_columns(self):
        source = self.root / "10.1000_fixture.pdf"
        source.write_bytes(b"%PDF-fixture")
        self.result.status = "success"
        self.result.pdf_path = str(source)
        records = [PaperRecord("10.1000/missing"), PaperRecord("10.1000/fixture")]
        with patch("paper_search_carsi.engine.batch.pdf_extractor.extract_text", return_value="10.1000/fixture"):
            summary = self.downloader._write_complete_artifacts(records, [self.result], self.root,
                         missing_reasons={"10.1000/missing": "CANARY_FAILURE"})
        manifest = json.loads((self.root / "complete/manifest.json").read_text())
        self.assertEqual(manifest[1]["status"], "success")
        self.assertEqual(Path(manifest[1]["pdf_path"]).read_bytes(), source.read_bytes())
        self.assertEqual(summary["success"], 1)
        for name in ("manifest.json", "manifest.csv"):
            self.assertNotIn("CANARY", (self.root / "complete" / name).read_text())
        rows = list(csv.DictReader((self.root / "complete/manifest.csv").read_text(encoding="utf-8-sig").splitlines()))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["pdf_path"], manifest[1]["pdf_path"])

    def test_success_sidecar_retains_verified_pdf_text_and_unmasked_urls(self):
        page = Mock(spec=["url", "close", "wait_for_load_state", "on", "remove_listener"])
        page.url = "https://www.sciencedirect.com/article/fixture"
        d = self.downloader
        d._ensure_login = Mock(return_value=True)
        d._looks_logged_out = Mock(return_value=False)
        d._access_decision = Mock(return_value=("in", "session", ""))  # signed in
        d._title = Mock(return_value="CANARY_TITLE")
        d._hold_after_login = Mock()
        d._hold_after_run = Mock()
        d._save_publisher_session = Mock()
        d._capture_pdf = Mock(return_value=(b"%PDF-fixture", "https://www.sciencedirect.com/file.pdf?token=CANARY_TOKEN", None))
        with patch("paper_search_carsi.engine.batch.time.sleep"), patch(
            "paper_search_carsi.engine.batch.pdf_extractor.extract_from_bytes", return_value="10.1000/fixture verified article"):
            result = d.fetch_one(page, PaperRecord("10.1000/fixture"), self.root)
        self.assertTrue(result.ok)
        sidecar = (self.root / "10.1000_fixture.json").read_text()
        self.assertIn("CANARY_TOKEN", json.loads(sidecar)["pdf_url"])
        self.assertEqual(json.loads(sidecar)["full_text"], "10.1000/fixture verified article")

    def test_summary_drops_proxy_credentials_and_unknown_nested_values(self):
        output = serialize_download_summary({"count": 2, "success": 1,
            "proxy_pool": ["https://CANARY_USER:CANARY_PASSWORD@proxy.example"],
            "browser_profile_dir": "/CANARY_USER/profile", "stop_reason": "CANARY_EXCEPTION",
            "primary": {"count": 2, "success": 1, "failed": "CANARY", "token": "CANARY"}})
        self.assertEqual(output["count"], 2)
        self.assertEqual(output["primary"]["success"], 1)
        self.assertNotIn("CANARY", json.dumps(output))

    def test_empty_manifest_still_has_batch_lookup_header(self):
        self.downloader._write_complete_artifacts([], [], self.root)
        header = (self.root / "complete/manifest.csv").read_text(encoding="utf-8-sig")
        self.assertIn("pdf_path", header)
        self.assertIn("doi", header)

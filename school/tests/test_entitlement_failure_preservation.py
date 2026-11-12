"""Offline bridge/orchestrator contract: denial, login and route-error triples survive every layer.

The orchestrator has no source race and no second aggregator: whatever the
bridge decides is what PaperSearch receives. These tests pin the bridge
priority rules and prove the orchestrator neither rewrites nor caches them.
"""
import json
from contextlib import ExitStack
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from paper_search_school import orchestrator
from paper_search_school.engine import bridge


DENIAL = "institution_pdf_entitlement_missing"
LOGIN_CODES = (
    "login_timeout", "login_page_closed", "login_credentials_rejected",
    "login_retries_exhausted", "institution_not_registered",
)
ROUTE_ERRORS = ("source_exception", "publisher_content_error", "access_blocked", "download_timeout")


def denial():
    """The exact denial triple a driver reports for a recognised school without subscription."""
    return {"success": False, "identifier": "10.1016/offline-fixture", "doi": "10.1016/offline-fixture",
            "source": "institutional:browser", "error_type": "paywall", "reason": DENIAL,
            "action": "review_entitlement", "reason_code": DENIAL}


class EntitlementPreservationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.doi = "10.1016/offline-fixture"
        self.output = self.root / "paper.pdf"
        self.profile = SimpleNamespace(name="Wiley")
        self.stack.enter_context(patch("requests.sessions.Session.request",
                                      side_effect=AssertionError("Network forbidden")))
        self.stack.enter_context(patch("socket.create_connection",
                                      side_effect=AssertionError("Network forbidden")))

    def browser_result(self, state=DENIAL, reason=DENIAL):
        downloader = MagicMock()
        downloader.fetch_one.return_value = SimpleNamespace(
            ok=False, pdf_path=None, state=state, reason=reason)
        with patch("paper_search_school.browser.backend.is_available", return_value=True), \
             patch("paper_search_school.engine.batch.PublisherBatchDownloader", return_value=downloader):
            result = bridge._try_browser_batch_download(self.doi, self.output, {}, self.profile)
        downloader._launch_context.return_value.close.assert_called_once()
        return result

    def builtin_result(self, browser, broker=None):
        calls = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(bridge, "_resolve_doi", return_value="https://example.org/article"))
            for name, value in [("_try_session_broker", broker),
                                ("_try_browser_batch_download", browser)]:
                def run(*args, _name=name, _value=value):
                    calls.append(_name)
                    return _value
                stack.enter_context(patch.object(bridge, name, side_effect=run))
            result = bridge._try_builtin_institutional(self.doi, self.output, {
                "carsi_enabled": True, "school_name": "Fixture University",
            }, self.profile)
        return result, calls

    def final_result(self, route_result):
        """Run the real orchestrator around a stubbed bridge; failures are never cached."""
        with ExitStack() as stack:
            stack.enter_context(patch.object(orchestrator, "load_config", return_value={"output_dir": str(self.root)}))
            stack.enter_context(patch.object(orchestrator, "cache_get", return_value=None))
            cache = stack.enter_context(patch.object(orchestrator, "cache_set"))
            route = stack.enter_context(patch.object(orchestrator, "try_institutional", return_value=route_result))
            result = orchestrator.download_institutional(self.doi, self.root)
            route.assert_called_once()
            if not result.get("success"):
                cache.assert_not_called()
        return result

    def assert_denial(self, result):
        self.assertFalse(result["success"])
        self.assertEqual((result["error_type"], result["reason_code"], result["action"]),
                         ("paywall", DENIAL, "review_entitlement"))

    def test_browser_builtin_final_preserve_exact_triple(self):
        browser = self.browser_result()
        self.assert_denial(browser)
        builtin, calls = self.builtin_result(browser, broker={"success": False, "error_type": "not_found"})
        self.assert_denial(builtin)
        self.assertEqual(calls, ["_try_session_broker", "_try_browser_batch_download"])
        self.assertEqual(builtin["source_failures"][1]["reason_code"], DENIAL)
        final = self.final_result(builtin)
        self.assert_denial(final)
        self.assertEqual(final["source_failures"][1]["reason_code"], DENIAL)
        self.assertEqual(final["identifier"], self.doi)

    def test_mixed_bridge_error_keeps_nested_denial_without_promoting_it(self):
        # The publisher driver's denial is final for the driver step, and
        # another route's error must not erase that evidence.
        builtin, calls = self.builtin_result(denial(), broker={"success": False, "error_type": "source_exception"})
        self.assertEqual(calls, ["_try_session_broker", "_try_browser_batch_download"])
        final = self.final_result(builtin)
        self.assertEqual(final["error_type"], "source_exception")
        self.assertNotIn("reason_code", final)
        self.assertNotIn("reason_code", final["source_failures"][0])
        self.assertEqual(final["source_failures"][1]["reason_code"], DENIAL)

    def test_browser_stale_reason_does_not_override_terminal_state(self):
        for state, code in [("unexpected_error", "source_exception"),
                            ("challenge_or_viewer_timeout", "download_timeout"),
                            ("sso_required", "paywall"), ("spinner", "download_failed"),
                            ("pdf_not_captured", "download_failed")]:
            with self.subTest(state=state):
                result = self.browser_result(state)
                self.assertEqual(result["error_type"], code)
                self.assertNotIn("reason_code", result)
                self.assertNotEqual(result.get("action"), "review_entitlement")

    def test_browser_unknown_reason_is_not_forwarded(self):
        result = self.browser_result("spinner", "https://example.org/?token=fixture-secret")
        self.assertEqual(result["error_type"], "download_failed")
        self.assertNotIn("fixture-secret", json.dumps(result))

    def test_login_outcomes_survive_browser_bridge_and_final(self):
        for code in LOGIN_CODES:
            with self.subTest(code=code):
                browser = self.browser_result(code, "cookie=fixture-secret")
                self.assertEqual((browser["error_type"], browser["action"]), (code, "review_browser"))
                builtin, _ = self.builtin_result(browser, broker={"success": False, "error_type": "not_found"})
                final = self.final_result(builtin)
                for result in (browser, builtin, final):
                    self.assertEqual((result["error_type"], result["action"]), (code, "review_browser"))
                    self.assertNotIn("reason_code", result)
                    self.assertNotIn("fixture-secret", json.dumps(result))
                child = final["source_failures"][-1]
                self.assertEqual((child["error_type"], child["reason"], child["action"]),
                                 (code, code, "review_browser"))

    def test_login_outcome_overrides_plain_miss_and_generic_timeout_in_either_order(self):
        for code in LOGIN_CODES:
            login = {"success": False, "error_type": code,
                     "reason": "cookie=fixture-secret", "action": "token=fixture-secret"}
            for other in ({"success": False, "error_type": "download_timeout"},
                          {"success": False, "error_type": "not_found"},
                          {"success": False, "error_type": "paywall", "action": "login_required"}):
                for first, last in permutations([login, other]):
                    with self.subTest(code=code, other=other["error_type"], first=first["error_type"]):
                        builtin, _ = self.builtin_result(last, broker=first)
                        for result in (builtin, self.final_result(builtin)):
                            self.assertEqual((result["error_type"], result["action"]), (code, "review_browser"))
                            self.assertNotIn("reason_code", result)
                            self.assertNotIn("fixture-secret", json.dumps(result))

    def test_login_lookalikes_and_free_text_do_not_create_classification_or_denial(self):
        for code in LOGIN_CODES:
            for state, reason in (("spinner", "raw " + code),
                                  (code + "_unknown", "cookie=fixture-secret"),
                                  ("unexpected_error", code)):
                result = self.browser_result(state, reason)
                self.assertEqual(result["error_type"],
                                 "source_exception" if state == "unexpected_error" else "download_failed")
                self.assertNotIn("reason_code", result)
                self.assertNotIn("fixture-secret", json.dumps(result))

    def test_login_failure_never_reuses_a_stale_entitlement_reason_or_action(self):
        for code in LOGIN_CODES:
            with self.subTest(code=code):
                browser = self.browser_result(code, DENIAL)
                injected = {**denial(), "error_type": code, "reason": "cookie=fixture-secret"}
                builtin, _ = self.builtin_result(injected)
                for result in (browser, builtin, self.final_result(builtin)):
                    self.assertEqual((result["error_type"], result["action"]), (code, "review_browser"))
                    self.assertNotIn("reason_code", result)
                    self.assertNotIn("fixture-secret", json.dumps(result))

    def test_production_download_routes_empty_school_school_to_the_publisher_driver(self):
        from paper_search_school import progress_reporter as progress
        from paper_search_school import server

        for code in LOGIN_CODES:
            with self.subTest(code=code), ExitStack() as stack:
                config = {"publisher_institution_federation": "carsi", "school_name": "",
                          "carsi_enabled": True, "cache_dir": str(self.root / "cache"),
                          "output_dir": str(self.root)}
                downloader = MagicMock()
                downloader.fetch_one.return_value = SimpleNamespace(
                    ok=False, pdf_path=None, state=code, reason="cookie=fixture-secret")
                stack.enter_context(patch.dict("os.environ", {
                    "SCHOOL_DATA_DIR": str(self.root), "SCHOOL_PROGRESS_BAR": "0"}))
                stack.enter_context(patch.object(progress, "_STATE", {}))
                stack.enter_context(patch.object(orchestrator, "load_config", return_value=config))
                stack.enter_context(patch.object(orchestrator, "cache_get", return_value=None))
                cache = stack.enter_context(patch.object(orchestrator, "cache_set"))
                stack.enter_context(patch.object(bridge, "_resolve_doi", return_value="https://example.org/article"))
                legacy = [stack.enter_context(patch.object(bridge, name)) for name in
                          ("_try_external_instsci", "_try_session_broker")]
                stack.enter_context(patch("paper_search_school.browser.backend.is_available", return_value=True))
                factory = stack.enter_context(patch("paper_search_school.engine.batch.PublisherBatchDownloader",
                                                    return_value=downloader))
                result = json.loads(server.school_download(
                    self.doi, str(self.root), strategy="institutional_only"))
                self.assertEqual((result["error_type"], result["action"]), (code, "review_browser"))
                self.assertEqual([child["source"] for child in result["source_failures"]],
                                 ["institutional:browser"])
                self.assertEqual(result["source_failures"][0]["error_type"], code)
                self.assertNotIn("fixture-secret", json.dumps(result))
                self.assertNotIn("reason_code", result)
                self.assertNotIn("agent_hint", result)
                for route in legacy:
                    route.assert_not_called()
                self.assertEqual(factory.call_args.kwargs["institution_query"], "")
                self.assertEqual(factory.call_args.kwargs["config"]["publisher_institution_federation"], "carsi")
                downloader.fetch_one.assert_called_once()
                downloader._launch_context.return_value.close.assert_called_once()
                cache.assert_not_called()
                self.assertEqual(progress.read_state()["status"], "done")

    def test_route_errors_outrank_denial_in_either_order(self):
        for code in ROUTE_ERRORS:
            error = {"success": False, "error_type": code}
            for first, last in permutations([denial(), error]):
                with self.subTest(code=code, first=first["error_type"]):
                    builtin, _ = self.builtin_result(last, broker=first)
                    for result in (builtin, self.final_result(builtin)):
                        self.assertEqual(result["error_type"], code)
                        self.assertNotIn("reason_code", result)
                        self.assertTrue(any(f.get("reason_code") == DENIAL for f in result["source_failures"]))

    def test_program_error_has_highest_priority(self):
        program = {"success": False, "error_type": "source_exception"}
        for code in ("publisher_content_error", "access_blocked", "download_timeout", *LOGIN_CODES):
            for first, last in permutations([program, {"success": False, "error_type": code}]):
                with self.subTest(code=code, first=first["error_type"]):
                    builtin, _ = self.builtin_result(last, broker=first)
                    self.assertEqual(builtin["error_type"], "source_exception")
                    self.assertEqual(self.final_result(builtin)["error_type"], "source_exception")

    def test_plain_miss_or_login_does_not_erase_denial(self):
        for other in ({"success": False, "error_type": "not_found"},
                      {"success": False, "error_type": "paywall", "action": "login_required"}):
            for first, last in permutations([denial(), other]):
                with self.subTest(other=other["error_type"], first=first["error_type"]):
                    builtin, _ = self.builtin_result(last, broker=first)
                    self.assert_denial(builtin)
                    self.assert_denial(self.final_result(builtin))

    def test_partial_or_mismatched_triples_are_not_upgraded(self):
        fixtures = [
            {"success": False, "error_type": "paywall", "reason": DENIAL, "action": "review_entitlement"},
            {**denial(), "action": "login_required"},
            {**denial(), "error_type": "download_timeout"},
            {**denial(), "reason_code": "spinner"},
            {"success": False, "error_type": "not_found", "source_failures": [denial()]},
        ]
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                builtin, _ = self.builtin_result(fixture)
                self.assertNotIn("reason_code", builtin)
                final = self.final_result(builtin)
                self.assertNotIn("reason_code", final)
                self.assertTrue(all("reason_code" not in f for f in final["source_failures"]))

    def test_current_pdf_miss_is_download_failed(self):
        # The publisher capture has no fixed action for a plain miss.
        browser = self.browser_result("pdf_not_captured", "pdf_not_captured")
        result = self.final_result(browser)
        self.assertEqual((result["error_type"], result["action"]), ("download_failed", ""))
        self.assertNotIn("reason_code", result)

    def test_no_route_result_is_generic_paywall_login_required(self):
        result = self.final_result(None)
        self.assertEqual((result["error_type"], result["action"]), ("paywall", "login_required"))
        self.assertNotIn("reason_code", result)

    def test_success_without_readable_pdf_is_not_success(self):
        result = self.final_result({"success": True, "file": str(self.root / "missing.pdf"), "source": "institutional:browser"})
        self.assertFalse(result["success"])
        self.assertEqual((result["error_type"], result["action"]), ("source_exception", "review_logs"))

    def test_readable_pdf_success_is_normalized_and_cached(self):
        import fitz

        with fitz.open() as doc:
            for number in range(3):  # is_pdf_file() needs a real-sized file, not a stub
                doc.new_page().insert_text((72, 72), f"Offline fixture page {number}\n" * 40)
            doc.save(self.output)
        self.assertGreater(self.output.stat().st_size, 1000)
        with ExitStack() as stack:
            stack.enter_context(patch.object(orchestrator, "load_config", return_value={"output_dir": str(self.root)}))
            stack.enter_context(patch.object(orchestrator, "cache_get", return_value=None))
            cache = stack.enter_context(patch.object(orchestrator, "cache_set"))
            stack.enter_context(patch.object(orchestrator, "try_institutional",
                                             return_value={"success": True, "file": str(self.output), "source": "institutional:browser:Wiley"}))
            result = orchestrator.download_institutional(self.doi, self.root)
        self.assertTrue(result["success"])
        self.assertEqual((result["identifier"], result["doi"], result["file"]), (self.doi, self.doi, str(self.output)))
        self.assertGreater(result["size_kb"], 0)
        cache.assert_called_once()


if __name__ == "__main__":
    unittest.main()

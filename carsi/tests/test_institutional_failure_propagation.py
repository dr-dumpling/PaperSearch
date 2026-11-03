"""Browser-route failures keep fixed, secret-free categories through bridge and orchestrator."""
import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from paper_search_carsi import orchestrator
from paper_search_carsi.engine import bridge


class InstitutionalFailureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.doi = "10.1016/test"
        self.output = self.root / "paper.pdf"
        self.profile = SimpleNamespace(name="Elsevier")
        self.content_error = {
            "success": False, "error_type": "publisher_content_error",
            "reason": "publisher_content_error", "action": "review_publisher_error",
        }

    def browser_result(self, result=None, exception=None):
        downloader = MagicMock()
        downloader.fetch_one.return_value = result
        downloader.fetch_one.side_effect = exception
        context = downloader._launch_context.return_value
        with patch("paper_search_carsi.browser.backend.is_available", return_value=True), \
             patch("paper_search_carsi.engine.batch.PublisherBatchDownloader", return_value=downloader):
            actual = bridge._try_browser_batch_download(self.doi, self.output, {}, self.profile)
        context.close.assert_called_once()
        return actual

    def builtin_result(self, broker=None):
        calls = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(bridge, "_resolve_doi", return_value="https://www.sciencedirect.com/science/article/pii/example"))
            for name, value in [("_try_session_broker", broker),
                                ("_try_browser_batch_download", self.content_error)]:
                def run(*args, _name=name, _value=value):
                    calls.append(_name)
                    return _value
                stack.enter_context(patch.object(bridge, name, side_effect=run))
            result = bridge._try_builtin_institutional(self.doi, self.output, {
                "carsi_enabled": True, "carsi_idp_name": "Test University",
            }, self.profile)
        return result, calls

    def final_result(self, route_result=None, exception=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(orchestrator, "load_config", return_value={"output_dir": str(self.root)}))
            stack.enter_context(patch.object(orchestrator, "cache_get", return_value=None))
            self.cache = stack.enter_context(patch.object(orchestrator, "cache_set"))
            stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network access")))
            stack.enter_context(patch.object(orchestrator, "try_institutional", return_value=route_result, side_effect=exception))
            return orchestrator.download_institutional(self.doi, self.root)

    def test_browser_failures_keep_safe_categories_and_close_context(self):
        for state, code, action in [
            ("publisher_content_error", "publisher_content_error", "review_publisher_error"),
            ("publisher_access_blocked", "access_blocked", "review_access"),
            ("sso_required", "paywall", "login_required"),
            ("institution_pdf_entitlement_missing", "paywall", "review_entitlement"),
            ("challenge_or_viewer_timeout", "download_timeout", "review_browser"),
            ("ip_blocked", "access_blocked", "review_access"),
            ("unexpected_error", "source_exception", ""),
            ("unknown", "download_failed", ""),
        ]:
            with self.subTest(state=state):
                result = self.browser_result(SimpleNamespace(
                    ok=False, pdf_path=None, state=state, reason="token=secret"))
                self.assertEqual((result["error_type"], result["action"]), (code, action))
                self.assertNotIn("secret", json.dumps(result))

    def test_publisher_block_propagates_through_all_failed_routes_and_final_download(self):
        self.content_error = self.browser_result(SimpleNamespace(
            ok=False, pdf_path=None, state="publisher_access_blocked", reason="cookie=secret"))
        result, _ = self.builtin_result()
        self.assertEqual((result["error_type"], result["action"]), ("access_blocked", "review_access"))
        self.assertNotIn("secret", json.dumps(result))
        final = self.final_result(result)
        self.assertEqual((final["error_type"], final["action"]), ("access_blocked", "review_access"))
        self.assertEqual(final["source_failures"][0]["source"], "institutional:browser")
        self.cache.assert_not_called()

    def test_browser_exception_does_not_leak_exception_text(self):
        result = self.browser_result(exception=RuntimeError("cookie=secret"))
        self.assertEqual(result["error_type"], "source_exception")
        self.assertNotIn("secret", json.dumps(result))

    def test_all_routes_failed_preserves_content_error(self):
        result, calls = self.builtin_result(broker={"success": False, "error_type": "not_found"})
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "publisher_content_error")
        # One driver per publisher: Elsevier's specialized driver ran, so the generic CARSI driver does not.
        self.assertEqual(calls, ["_try_session_broker", "_try_browser_batch_download"])

    def test_generic_broker_failure_cannot_hide_specific_browser_failure(self):
        for code in ["access_blocked", "source_exception", "download_timeout"]:
            with self.subTest(code=code):
                self.content_error = {"success": False, "error_type": code, "reason": code}
                result, _ = self.builtin_result(broker={"success": False, "error_type": "not_found"})
                self.assertEqual(result["error_type"], code)

    def test_final_download_preserves_explicit_errors_over_generic_paywall(self):
        for code, action in [("publisher_content_error", "review_publisher_error"),
                             ("access_blocked", "review_access"),
                             ("source_exception", ""), ("download_timeout", "review_browser")]:
            with self.subTest(code=code):
                route = {"success": False, "identifier": self.doi, "doi": self.doi, "source": "institutional",
                         "error_type": code, "reason": code, "action": action,
                         "source_failures": [{"source": "institutional:browser", "error_type": code, "reason": code, "action": action}]}
                result = self.final_result(route)
                self.assertFalse(result["success"])
                self.assertEqual((result["error_type"], result.get("action", "")), (code, action))
                self.assertEqual(result["source_failures"][0]["source"], "institutional:browser")
                self.cache.assert_not_called()

    def test_unfinished_browser_is_not_cached_as_success(self):
        timeout = {"success": False, "error_type": "download_timeout",
                   "reason": "browser_route_timeout", "action": "review_browser"}
        result = self.final_result(dict(timeout))
        self.assertEqual(result, {**timeout, "identifier": self.doi, "doi": self.doi})
        self.cache.assert_not_called()

    def test_route_exception_is_source_exception_without_exception_text(self):
        result = self.final_result(exception=ValueError("https://example.test/?token=secret"))
        self.assertEqual((result["error_type"], result["action"]), ("source_exception", "review_logs"))
        self.assertNotIn("secret", json.dumps(result))
        self.cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()

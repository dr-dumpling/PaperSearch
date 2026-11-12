"""Orchestrator guards: one in-flight attempt per DOI, no routes for bad input."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from paper_search_school import orchestrator


class InflightGuardTests(unittest.TestCase):
    def test_same_doi_is_rejected_while_first_attempt_runs_then_allowed_again(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def slow(doi, output_dir):
            calls.append(doi)
            entered.set()
            self.assertTrue(release.wait(3))
            return {"success": False, "identifier": doi, "doi": doi, "reason": "fixture"}

        with patch.object(orchestrator, "_download_impl", side_effect=slow), ThreadPoolExecutor(2) as pool:
            first = pool.submit(orchestrator.download_institutional, "10.1000/a")
            self.assertTrue(entered.wait(2))
            busy = orchestrator.download_institutional("https://doi.org/10.1000/a")
            self.assertEqual(busy["error_type"], "in_progress")
            self.assertEqual(busy["doi"], "10.1000/a")
            other = pool.submit(orchestrator.download_institutional, "10.1000/b")
            release.set()
            first.result(timeout=3)
            other.result(timeout=3)
        self.assertEqual(sorted(calls), ["10.1000/a", "10.1000/b"])
        with patch.object(orchestrator, "_download_impl", return_value={"success": False, "identifier": "10.1000/a", "doi": "10.1000/a", "reason": "fixture"}):
            self.assertNotEqual(orchestrator.download_institutional("10.1000/a").get("error_type"), "in_progress")

    def test_failed_attempt_releases_the_slot(self):
        with patch.object(orchestrator, "_download_impl", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                orchestrator.download_institutional("10.1000/a")
        self.assertNotIn("10.1000/a", orchestrator._INFLIGHT)

    def test_bad_input_never_reaches_a_route(self):
        with patch.object(orchestrator, "_download_impl", side_effect=AssertionError("route forbidden")):
            self.assertEqual(orchestrator.download_institutional("10.1000/a", strategy="smart")["action"], "review_strategy")
            self.assertEqual(orchestrator.download_institutional("arXiv:2401.00001")["error_type"], "not_found")
            self.assertEqual(orchestrator.download_institutional("not a doi")["error_type"], "not_found")


if __name__ == "__main__":
    unittest.main()

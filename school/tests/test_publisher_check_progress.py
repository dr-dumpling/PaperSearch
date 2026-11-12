"""publisher-check registers the same reported task as the MCP tool (window + preview)."""
import argparse
import os
import unittest
from unittest.mock import patch

from paper_search_school import cli, progress_reporter


class PublisherCheckProgressTests(unittest.TestCase):
    def test_data_dir_is_isolated_from_the_user(self):
        self.assertNotEqual(os.environ["SCHOOL_DATA_DIR"], os.path.expanduser("~/.local/share/paper-search-cli/school"))

    def test_publisher_check_runs_as_a_reported_task(self):
        seen = {}

        def fake_download(doi, output_dir, strategy=None):
            seen["state"] = progress_reporter.read_state()
            return {"doi": doi, "success": False, "error_type": "paywall"}

        with patch("paper_search_school.orchestrator.download_institutional", fake_download), \
             patch("builtins.print"):
            cli._cmd_publisher_check(argparse.Namespace(doi="10.1000/x", output_dir=None))
        self.assertEqual(seen["state"]["status"], "running")
        self.assertEqual(seen["state"]["current"], "10.1000/x")
        final = progress_reporter.read_state()
        self.assertEqual((final["done"], final["failed"]), (1, 1))
        self.assertNotEqual(final["status"], "running")


if __name__ == "__main__":
    unittest.main()


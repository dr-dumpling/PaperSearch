"""Tool results point at the browser run's record/diagnostic files, without free text."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from paper_search_carsi.engine import bridge
from paper_search_carsi.engine.batch import DownloadResult


class RunArtifactsTests(unittest.TestCase):
    def test_failure_carries_the_diagnostic_path_and_survives_aggregation(self):
        profile = SimpleNamespace(name="Wiley", driver="publisher")
        result = DownloadResult(doi="10.1002/x", status="failed", state="sso_required",
                                reason="cookie=fixture-secret", diagnostic_path="/runs/diag/diagnostic.json")
        downloader = MagicMock(); downloader.fetch_one.return_value = result
        with patch("paper_search_carsi.engine.batch.PublisherBatchDownloader", return_value=downloader), \
             patch("paper_search_carsi.browser.backend.is_available", return_value=True):
            single = bridge._try_browser_batch_download("10.1002/x", Path("/tmp/out/x.pdf"), {}, profile)
        self.assertEqual(single["artifacts"]["diagnostic"], "/runs/diag/diagnostic.json")
        self.assertEqual(single["artifacts"]["state"], "sso_required")
        self.assertNotIn("fixture-secret", json.dumps(single))
        with patch.object(bridge, "_resolve_doi", return_value="https://onlinelibrary.wiley.com/doi/10.1002/x"), \
             patch.object(bridge, "_try_session_broker", return_value=None), \
             patch.object(bridge, "_try_browser_batch_download", return_value=single):
            final = bridge._try_builtin_institutional("10.1002/x", Path("/tmp/out/x.pdf"),
                                                      {"publisher_institution_federation": "carsi"}, profile)
        self.assertEqual(final["artifacts"]["diagnostic"], "/runs/diag/diagnostic.json")

    def test_backend_log_file_is_written_under_the_data_dir(self):
        import os
        from paper_search_carsi import log as log_module
        handler = log_module._file_handler()
        self.assertIsNotNone(handler)
        self.assertTrue(str(handler.baseFilename).startswith(os.environ["CARSI_DATA_DIR"]))
        handler.close()

"""The live preview is on by default for institutional downloads, bounded and readable from the CLI."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from paper_search_school.browser import preview


class PreviewDefaultsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_default_directory_is_under_the_data_dir_unless_configured(self):
        with patch("paper_search_school.config.DATA_DIR", self.root):
            self.assertEqual(preview.default_directory({}), self.root / "previews")
        self.assertEqual(preview.default_directory({"browser_preview_dir": str(self.root / "x")}), self.root / "x")

    def test_turned_off_or_no_owned_task_never_raises(self):
        ctx = MagicMock()
        self.assertIsNone(preview.ensure_enabled(ctx, {"browser_preview": False}))
        with patch.object(preview, "enable", side_effect=ValueError("browser preview requires an owned DOI task")):
            self.assertIsNone(preview.ensure_enabled(ctx, {"browser_preview_dir": str(self.root)}))

    def test_enabled_by_default_with_the_default_directory(self):
        ctx = MagicMock()
        with patch.object(preview, "enable", return_value="observer") as enable:
            self.assertEqual(preview.ensure_enabled(ctx, {"browser_preview_dir": str(self.root)}), "observer")
        enable.assert_called_once_with(ctx, self.root)

    def test_prune_keeps_the_newest_runs_and_never_an_active_one(self):
        runs = []
        for index in range(7):
            run = self.root / str(uuid.uuid4()); run.mkdir()
            os.utime(run, (time.time() - 100 + index, time.time() - 100 + index))
            runs.append(run)
        (self.root / "not-a-run").mkdir()
        preview._ACTIVE[str(runs[0].resolve())] = "ctx"  # oldest, but still in use
        self.addCleanup(preview._ACTIVE.pop, str(runs[0].resolve()), None)
        removed = preview.prune(self.root, keep=3)
        left = {p.name for p in self.root.iterdir()}
        self.assertEqual(len(removed), 3)
        self.assertTrue({r.name for r in runs[-3:]} <= left)
        self.assertIn(runs[0].name, left)
        self.assertIn("not-a-run", left)

    def test_latest_snapshot_without_a_task_is_unavailable(self):
        with patch("paper_search_school.progress_reporter.read_snapshot", return_value=(None, "missing")):
            self.assertEqual(preview.latest_snapshot({})["reason"], "no_task")

    def test_cli_preview_prints_json(self):
        env = {**os.environ, "SCHOOL_DATA_DIR": str(self.root), "SCHOOL_PROGRESS_BAR": "0",
               "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        out = subprocess.run([sys.executable, "-m", "paper_search_school.cli", "preview"],
                             env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 1)
        self.assertEqual(json.loads(out.stdout)["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()

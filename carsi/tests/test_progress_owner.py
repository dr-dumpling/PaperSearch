"""Progress readers never invent completion and never overwrite another writer's file."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from paper_search_carsi import progress_reporter as progress


class ProgressOwnerTests(unittest.TestCase):
    def test_live_owner_with_stale_progress_remains_visible_without_fake_updates(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"CARSI_DATA_DIR": temp}):
            path = progress.progress_path(); path.parent.mkdir()
            original = {"status": "running", "owner_pid": os.getpid(), "done": 0,
                        "total": 1, "updated_at": "2000-01-01T00:00:00", "phase": "打开论文页面"}
            path.write_text(json.dumps(original))
            state = progress.read_state()
            self.assertEqual(state["status"], "running")
            self.assertTrue(state["stale"])
            self.assertEqual(state["done"], 0)
            self.assertEqual(state["updated_at"], original["updated_at"])
            self.assertEqual(json.loads(path.read_text()), original)

    def test_legacy_report_without_owner_still_expires(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"CARSI_DATA_DIR": temp}):
            path = progress.progress_path(); path.parent.mkdir()
            path.write_text(json.dumps({"status": "running", "updated_at": "2000-01-01T00:00:00"}))
            self.assertIsNone(progress.read_state())

    def test_dead_owner_is_interrupted_without_inventing_completion(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"CARSI_DATA_DIR": temp}):
            p = progress.progress_path(); p.parent.mkdir()
            original = {"status": "running", "owner_pid": 999999, "done": 0, "total": 1,
                        "success": 0, "failed": 0, "attention": {"login": {"message": "waiting"}}}
            p.write_text(json.dumps(original))
            with patch.object(progress, "_pid_alive", return_value=False):
                state = progress.read_state()
            self.assertEqual(state["status"], "interrupted")
            self.assertEqual((state["done"], state["success"], state["failed"]), (0, 0, 0))
            self.assertEqual(state["attention"], {})
            self.assertEqual(json.loads(p.read_text()), original, "Reader must not overwrite another writer")


if __name__ == "__main__":
    unittest.main()

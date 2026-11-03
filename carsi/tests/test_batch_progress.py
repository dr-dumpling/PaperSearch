"""Serial batches: the progress window shows k / N and stays open between items."""
import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from paper_search_carsi import progress_reporter as pr
from paper_search_carsi import server

DEAD_PID = 999_999


class BatchProgressTests(unittest.TestCase):
    def setUp(self):
        pr.progress_path().unlink(missing_ok=True)
        self.new_process()

    def new_process(self):
        """Each batch item runs in a fresh backend process."""
        pr._STATE = {}

    def state(self):
        return json.loads(pr.progress_path().read_text(encoding="utf-8"))

    def test_window_shows_what_is_fetched(self):
        for content, expected in (("both", "both"), ("supplements", "supplements"), ("bogus", "main")):
            self.new_process()
            with pr.tracked_download("10.1000/x", None, content=content) as outcome:
                self.assertEqual(self.state()["content"], expected)
                outcome["result"] = {"success": True}
        self.new_process()
        with pr.tracked_download("10.1000/y", None) as outcome:
            self.assertEqual(self.state()["content"], "main")
            outcome["result"] = {"success": True}

    def item(self, index, total, ok, **counts):
        self.new_process()
        batch = pr.BatchContext.from_args("b1", index, total, *(counts.get(k) for k in ("done", "succeeded", "failed")))
        with pr.tracked_download(f"10.1000/{index}", None, batch) as outcome:
            outcome["result"] = {"success": ok}
        # the process exits: its pid is gone before the next item starts
        data = self.state(); data["owner_pid"] = DEAD_PID
        pr.progress_path().write_text(json.dumps(data), encoding="utf-8")

    def test_items_accumulate_and_the_window_waits_between_them(self):
        self.item(1, 3, True)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["total"], snap["success"]), ("running", 1, 3, 1))
        self.assertTrue(snap["awaiting_next"])
        run_id = snap["run_id"]
        self.item(2, 3, False)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["failed"], snap["run_id"]), ("running", 2, 1, run_id))
        self.item(3, 3, True)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["success"], snap["failed"]), ("done", 3, 2, 1))
        self.assertFalse(snap["awaiting_next"])

    def test_caller_counts_cover_items_finished_without_the_backend(self):
        self.item(1, 4, True)
        # items 2 and 3 were open access in the caller; item 4 reaches the backend
        self.item(4, 4, False, done=3, succeeded=3, failed=0)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["success"], snap["failed"]), ("done", 4, 3, 1))

    def test_a_resumed_batch_starts_at_its_index(self):
        self.item(5, 10, True)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["done"], snap["total"], snap["task"]), (5, 10, "机构 PDF 批量下载"))

    def test_a_long_wait_between_items_ends_as_interrupted(self):
        self.item(1, 3, True)
        data = self.state()
        data["updated_at"] = (datetime.now() - timedelta(seconds=pr.BATCH_WAIT_STALE_SECONDS + 5)).isoformat(timespec="seconds")
        pr.progress_path().write_text(json.dumps(data), encoding="utf-8")
        snap, _ = pr.read_snapshot()
        self.assertEqual(snap["status"], "interrupted")

    def test_a_dead_owner_without_a_batch_is_still_interrupted(self):
        self.new_process()
        with pr.tracked_download("10.1000/x") as outcome:
            data = self.state(); data["owner_pid"] = DEAD_PID
            pr.progress_path().write_text(json.dumps(data), encoding="utf-8")
            snap, _ = pr.read_snapshot()
            self.assertEqual(snap["status"], "interrupted")
            outcome["result"] = {"success": True}

    def test_sync_for_items_outside_the_backend_and_the_batch_end(self):
        self.assertFalse(pr.sync_batch("b2", 3, 0, 0, 0, finished=True))
        self.assertTrue(pr.sync_batch("b2", 3, 1, 1, 0, current="10.1000/1"))
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["awaiting_next"]), ("running", 1, True))
        self.new_process()
        self.assertTrue(pr.sync_batch("b2", 3, 3, 2, 1, finished=True))
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["status"], snap["done"], snap["success"], snap["failed"]), ("done", 3, 2, 1))
        self.assertFalse(pr.sync_batch("b2", 3, 4, 4, 0))

    def test_invalid_batch_arguments_fall_back_to_a_single_download(self):
        for args in (("", 1, 2), ("b", 0, 2), ("b", 3, 2), ("b", True, 2), ("b" * 200, 1, 2), (None, 1, 2), ("b", 1, "2")):
            with self.subTest(args=args):
                self.assertIsNone(pr.BatchContext.from_args(*args))
        self.assertIsNone(pr.BatchContext.from_args("b", 1, 2, -1).done)

    def test_server_passes_the_batch_to_the_report(self):
        with patch.object(server, "download", return_value={"success": True, "file": "x.pdf"}):
            server.carsi_download("10.1000/1", None, batch_id="b3", batch_index=1, batch_total=2)
        snap, _ = pr.read_snapshot()
        self.assertEqual((snap["batch_id"], snap["done"], snap["total"], snap["status"]), ("b3", 1, 2, "running"))
        self.assertEqual(json.loads(server.carsi_batch_progress("b3", 2, 2, 2, 0, finished=True)), {"updated": True})
        self.assertEqual(pr.read_snapshot()[0]["status"], "done")


if __name__ == "__main__":
    unittest.main()

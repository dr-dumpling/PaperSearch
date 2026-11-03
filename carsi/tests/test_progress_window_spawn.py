"""The floating progress window is spawned for real runs and never under tests or when disabled."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from paper_search_carsi import progress_reporter as pr


class ProgressWindowSpawnTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.env = {"CARSI_DATA_DIR": tmp.name}
        self.lock = Path(tmp.name) / "progress" / "bar.pid"

    def spawn(self, env=None, config=None):
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("CARSI_PROGRESS_BAR", "CARSI_PROGRESS_BAR_CHILD", "PYTEST_CURRENT_TEST")}
        with patch.dict(os.environ, {**clean, **self.env, **(env or {})}, clear=True), \
             patch("subprocess.Popen") as popen:
            pr.ensure_progress_bar(config)
        return popen

    def test_real_run_spawns_the_window_module_detached(self):
        popen = self.spawn(config={"progress_bar_auto": True})
        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(args[0][1:], ["-m", "paper_search_carsi.progress_bar"])
        self.assertEqual(kwargs["env"]["CARSI_PROGRESS_BAR_CHILD"], "1")

    def test_disabled_by_env_config_child_and_pytest(self):
        for env, config in (({"CARSI_PROGRESS_BAR": "0"}, None), ({}, {"progress_bar_auto": False}),
                            ({"CARSI_PROGRESS_BAR_CHILD": "1"}, None), ({"PYTEST_CURRENT_TEST": "x"}, None)):
            with self.subTest(env=env, config=config):
                self.spawn(env, config).assert_not_called()

    def test_live_window_lock_prevents_a_second_window_and_stale_lock_is_reclaimed(self):
        self.lock.parent.mkdir(parents=True)
        self.lock.write_text(str(os.getpid()))
        self.spawn().assert_not_called()
        self.lock.write_text("999999")
        with patch.object(pr, "_pid_alive", return_value=False):
            self.spawn().assert_called_once()

    def test_window_module_imports_without_opening_a_window(self):
        import importlib
        module = importlib.import_module("paper_search_carsi.progress_bar")
        self.assertTrue(callable(module.main))


class AutoCloseTests(unittest.TestCase):
    def ac(self, enabled=True, linger=8.0):
        from paper_search_carsi.progress_bar import AutoClose
        return AutoClose(enabled=enabled, linger=linger)

    def test_finished_task_closes_after_the_linger_period(self):
        ac = self.ac()
        running = {"status": "running", "run_id": "a"}
        done = {"status": "done", "run_id": "a"}
        self.assertFalse(ac.should_close(running, 0))
        self.assertFalse(ac.should_close(done, 10))
        self.assertFalse(ac.should_close(done, 17.9))
        self.assertTrue(ac.should_close(done, 18))

    def test_every_terminal_status_counts(self):
        for status in ("done", "failed", "cancelled", "interrupted"):
            ac = self.ac(linger=0)
            self.assertTrue(ac.should_close({"status": status, "run_id": "x"}, 1), status)

    def test_a_new_task_during_the_linger_keeps_the_window(self):
        ac = self.ac()
        self.assertFalse(ac.should_close({"status": "done", "run_id": "a"}, 0))
        self.assertFalse(ac.should_close({"status": "running", "run_id": "b"}, 5))
        self.assertFalse(ac.should_close({"status": "done", "run_id": "b"}, 9))
        self.assertTrue(ac.should_close({"status": "done", "run_id": "b"}, 17))

    def test_manually_opened_window_never_closes_and_idle_state_is_kept(self):
        self.assertFalse(self.ac(enabled=False, linger=0).should_close({"status": "done", "run_id": "a"}, 99))
        ac = self.ac(linger=0)
        self.assertFalse(ac.should_close(None, 99))

    def test_from_env_only_enables_for_auto_spawned_windows(self):
        from paper_search_carsi.progress_bar import AutoClose
        with patch.dict(os.environ, {"CARSI_PROGRESS_BAR_CHILD": "1", "CARSI_PROGRESS_BAR_LINGER": "3"}):
            ac = AutoClose.from_env()
        self.assertTrue(ac.enabled); self.assertEqual(ac.linger, 3.0)
        with patch.dict(os.environ, {"CARSI_PROGRESS_BAR_LINGER": "bad"}, clear=False):
            os.environ.pop("CARSI_PROGRESS_BAR_CHILD", None)
            ac = AutoClose.from_env()
        self.assertFalse(ac.enabled); self.assertEqual(ac.linger, 8.0)


if __name__ == "__main__":
    unittest.main()

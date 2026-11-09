"""The floating progress window is spawned for real runs and never under tests or when disabled."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from types import SimpleNamespace

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
        self.assertEqual(args[0][1:], ["-m", "paper_search_carsi.progress_capsule"])
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
        with patch.object(pr, "_pid_alive", return_value=False) as alive:
            self.spawn().assert_called_once()
        alive.assert_called_once_with(999999, created_before=self.lock.stat().st_mtime + 1)

    def open_settings(self, *args):
        with patch.dict(os.environ, self.env), patch("subprocess.Popen") as popen:
            window = pr.open_settings(*args)
            request = pr.take_settings_request()
        return window, request, popen

    def test_settings_start_a_window_when_none_is_open(self):
        window, request, popen = self.open_settings("keys", "easyscholar")
        self.assertEqual(window, "opened")
        self.assertEqual(request, {"page": "keys", "service": "easyscholar", "new_window": True})
        popen.assert_called_once()
        self.assertEqual(popen.call_args.kwargs["env"]["CARSI_PROGRESS_BAR_CHILD"], "1")

    def test_settings_go_to_the_open_window_and_each_request_is_taken_once(self):
        self.lock.parent.mkdir(parents=True)
        self.lock.write_text(str(os.getpid()))
        window, request, popen = self.open_settings("wait", "")
        self.assertEqual((window, request), ("existing", {"page": "wait", "service": "", "new_window": False}))
        popen.assert_not_called()
        with patch.dict(os.environ, self.env):
            self.assertIsNone(pr.take_settings_request())

    def test_an_old_request_is_dropped_and_a_failed_start_leaves_none(self):
        with patch.dict(os.environ, self.env), patch("subprocess.Popen"), \
             patch.object(pr.time, "time", side_effect=[1000.0, 1000.0 + pr.SETTINGS_REQUEST_SECONDS + 1]):
            pr.open_settings("home", "")
            self.assertIsNone(pr.take_settings_request())
        with patch.dict(os.environ, self.env), patch("subprocess.Popen", side_effect=OSError("no python")):
            with self.assertRaises(RuntimeError):
                pr.open_settings("home", "")
            self.assertIsNone(pr.take_settings_request())

    def test_window_module_imports_without_opening_a_window(self):
        import importlib
        for name in ("paper_search_carsi.progress_capsule", "paper_search_carsi.progress_bar"):
            module = importlib.import_module(name)
            self.assertTrue(callable(module.main))


class WindowsProcessLivenessTests(unittest.TestCase):
    def probe(self, wait_result, *, created_before=None, created_at=100):
        import ctypes
        from ctypes import wintypes
        handle = 0x100000001
        kernel = SimpleNamespace(OpenProcess=Mock(return_value=handle),
                                 CloseHandle=Mock(return_value=True),
                                 WaitForSingleObject=Mock(return_value=wait_result),
                                 GetProcessTimes=Mock(return_value=True))
        def times(_handle, created, *_rest):
            ticks = int((created_at + 11644473600) * 10_000_000)
            value = ctypes.cast(created, ctypes.POINTER(wintypes.FILETIME)).contents
            value.dwLowDateTime, value.dwHighDateTime = ticks & 0xffffffff, ticks >> 32
            return True
        kernel.GetProcessTimes.side_effect = times
        os_stub = SimpleNamespace(name="nt", kill=Mock())
        with patch.object(pr, "os", os_stub), patch.object(ctypes, "WinDLL", return_value=kernel, create=True):
            result = pr._pid_alive(123, created_before=created_before)
        os_stub.kill.assert_not_called()
        kernel.WaitForSingleObject.assert_called_once_with(handle, 0)
        kernel.CloseHandle.assert_called_once_with(handle)
        return result

    def test_an_openable_terminated_process_is_not_a_live_window(self):
        self.assertFalse(self.probe(0))

    def test_running_process_is_alive_and_wait_failure_is_not(self):
        self.assertTrue(self.probe(258))
        self.assertFalse(self.probe(0xffffffff))

    def test_reused_pid_newer_than_the_window_lock_does_not_block_reopening(self):
        self.assertFalse(self.probe(258, created_before=150, created_at=200))
        self.assertTrue(self.probe(258, created_before=150, created_at=100))


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

    def test_only_a_fully_saved_task_closes_by_itself(self):
        self.assertTrue(self.ac(linger=0).should_close({"status": "done", "run_id": "x"}, 1))
        for state in ({"status": "done", "run_id": "x", "failed": 2}, {"status": "failed", "run_id": "x"},
                      {"status": "cancelled", "run_id": "x"}, {"status": "interrupted", "run_id": "x"}):
            self.assertFalse(self.ac(linger=0).should_close(state, 99), state)

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

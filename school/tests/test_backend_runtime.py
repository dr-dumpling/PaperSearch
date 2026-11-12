import os
import unittest
from unittest.mock import patch
from paper_search_school import cli


class BackendRuntimeTests(unittest.TestCase):
    def test_cli_sets_a_bounded_worker_pool_before_loading_the_server(self):
        with patch.dict(os.environ), patch.object(cli, "_cmd_run") as run:
            os.environ.pop("OPENBLAS_NUM_THREADS", None)
            run.side_effect = lambda args: int(os.environ["OPENBLAS_NUM_THREADS"]) - 1
            self.assertEqual(cli.main(["run"]), 0)
            run.assert_called_once()

    def test_explicit_thread_setting_is_preserved(self):
        with patch.dict(os.environ, {"OPENBLAS_NUM_THREADS": "2"}), patch.object(cli, "_cmd_run", return_value=0):
            cli.main(["run"])
            self.assertEqual(os.environ["OPENBLAS_NUM_THREADS"], "2")

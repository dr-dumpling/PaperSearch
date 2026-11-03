"""A hung backend can be asked for its Python stacks (kill -USR1 <pid>)."""
import faulthandler
import os
import signal
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import tempfile

from paper_search_carsi import log


@unittest.skipUnless(hasattr(signal, "SIGUSR1"), "POSIX signal")
class StackDumpTests(unittest.TestCase):
    def test_usr1_writes_the_stacks_to_the_log_directory(self):
        with tempfile.TemporaryDirectory() as data_dir, \
                patch.dict(os.environ, {"CARSI_DATA_DIR": data_dir}), patch.object(log, "_stack_file", None):
            log.enable_stack_dump()
            try:
                os.kill(os.getpid(), signal.SIGUSR1)
                time.sleep(0.2)
                log._stack_file.flush()
                text = "".join(p.read_text() for p in (Path(data_dir) / "logs").glob("stacks-*.txt"))
            finally:
                faulthandler.unregister(signal.SIGUSR1)
                log._stack_file.close()
        self.assertIn("test_usr1_writes_the_stacks_to_the_log_directory", text)


if __name__ == "__main__":
    unittest.main()

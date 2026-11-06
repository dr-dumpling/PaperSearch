"""Ensure tests import the repo's own source tree, not an installed copy."""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
import atexit
import logging
import os
import shutil
import tempfile

os.environ.setdefault("CARSI_PROGRESS_BAR", "0")  # pytest 不得弹出 GUI
# Progress state, previews and config live under the data dir; tests get a
# throwaway one so they never overwrite or prune the user's real runs. Removed
# when the run ends, only this run's own (hundreds had piled up in $TMPDIR, 2026-11-02).
_DATA_DIR = tempfile.mkdtemp(prefix="carsi-test-data-")
os.environ["CARSI_DATA_DIR"] = _DATA_DIR
def _cleanup_test_data():
    # Windows cannot unlink an open backend log. pytest imports logging before
    # this hook, so its automatic shutdown otherwise runs after our cleanup.
    logging.shutdown()
    shutil.rmtree(_DATA_DIR)


atexit.register(_cleanup_test_data)

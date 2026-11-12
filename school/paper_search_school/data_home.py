"""Where the backend keeps its data: the school, logins, progress and runs."""
from __future__ import annotations

import os
from pathlib import Path

#: The directory's name before PaperSearch 0.6.1, named for CARSI, the first federation.
LEGACY_NAME = "carsi"


def default_data_dir() -> Path:
    """``SCHOOL_DATA_DIR``, as PaperSearch passes it (``CARSI_DATA_DIR`` before 0.6.1).
    Without it (the backend run by hand): ``~/.local/share/paper-search-cli/school``, or
    0.6.0's ``carsi`` directory beside it while PaperSearch has not renamed it yet."""
    given = os.environ.get("SCHOOL_DATA_DIR") or os.environ.get("CARSI_DATA_DIR")
    if given:
        return Path(given)
    base = Path.home() / ".local" / "share" / "paper-search-cli"
    current, legacy = base / "school", base / LEGACY_NAME
    return legacy if not current.exists() and legacy.exists() else current

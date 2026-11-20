"""PaperSearch Pro's features: the settings window's Markdown page (user, 2026-11-19).

On in the private repository; the public export (maintainer/release-public.py) writes False here
until Pro is public at 1.0.0. The command line has the same switch (package.json's paperSearch.proFeatures) and
gives its answer in PAPER_SEARCH_PRO_FEATURES to the backend it starts, which takes it over this.
"""
from __future__ import annotations

import os

PRO_FEATURES = False

PRO_FEATURES_ENV = "PAPER_SEARCH_PRO_FEATURES"


def pro_features() -> bool:
    given = os.environ.get(PRO_FEATURES_ENV, "").strip().lower()
    if given in ("1", "true"):
        return True
    if given in ("0", "false"):
        return False
    return PRO_FEATURES

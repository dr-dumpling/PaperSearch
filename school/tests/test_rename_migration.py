"""School subscription downloads were named for CARSI before 0.6.1: the backend finds and
reads what 0.6.0 left (its data directory, its environment variable, its config keys)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_search_school import config, data_home


class DataDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="psc-home-"))
        self.base = self.home / ".local" / "share" / "paper-search-cli"
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for name in ("SCHOOL_DATA_DIR", "CARSI_DATA_DIR"):
            os.environ.pop(name, None)
        self.addCleanup(self.env.stop)

    def directory(self):
        with patch.object(Path, "home", return_value=self.home):
            return data_home.default_data_dir()

    def test_the_variable_passed_wins_and_the_old_one_still_counts(self):
        os.environ["CARSI_DATA_DIR"] = "/old/place"
        self.assertEqual(self.directory(), Path("/old/place"))
        os.environ["SCHOOL_DATA_DIR"] = "/new/place"
        self.assertEqual(self.directory(), Path("/new/place"))

    def test_the_old_directory_until_paper_search_renames_it(self):
        self.assertEqual(self.directory(), self.base / "school")
        (self.base / "carsi").mkdir(parents=True)
        self.assertEqual(self.directory(), self.base / "carsi")
        (self.base / "school").mkdir()
        self.assertEqual(self.directory(), self.base / "school")


class OldConfigTests(unittest.TestCase):
    def test_the_school_under_the_new_keys_and_paths_under_the_renamed_directory(self):
        base = Path(tempfile.mkdtemp(prefix="psc-data-"))
        new, old = base / "school", base / "carsi"
        saved = {"carsi_idp_name": "红木兰大学", "carsi_idp_name_en": "Hongmulan University",
                 "output_dir": str(old / "papers"), "cache_dir": str(old / "cache"), "elsewhere": "/data/papers"}
        with patch.object(config, "DATA_DIR", new):
            migrated = config._from_before_rename(dict(saved))
        self.assertEqual(migrated, {"school_name": "红木兰大学", "school_name_en": "Hongmulan University",
                                    "output_dir": str(new / "papers"), "cache_dir": str(new / "cache"),
                                    "elsewhere": "/data/papers"})

    def test_a_new_key_already_saved_wins(self):
        with patch.object(config, "DATA_DIR", Path("/x/school")):
            self.assertEqual(config._from_before_rename({"carsi_idp_name": "旧", "school_name": "新"}), {"school_name": "新"})


if __name__ == "__main__":
    unittest.main()

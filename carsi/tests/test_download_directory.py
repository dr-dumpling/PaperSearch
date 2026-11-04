import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from paper_search_carsi import download_directory as directory
from paper_search_carsi.progress_capsule import Api
from unittest.mock import MagicMock


class DownloadDirectoryTests(unittest.TestCase):
    def test_gui_and_code_share_one_config_preserving_other_settings(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
            os.environ.pop(directory.KEY, None)
            config = Path(tmp) / "config.json"
            os.environ["PAPER_SEARCH_CONFIG_FILE"] = str(config)
            config.write_text(json.dumps({"PAPER_SEARCH_CARSI_ENABLED": "true"}))
            output = Path(tmp) / "论文 下载"
            directory.save(str(output))
            self.assertTrue(output.is_dir())
            self.assertEqual(directory.configured(), str(output))
            self.assertEqual(json.loads(config.read_text())["PAPER_SEARCH_CARSI_ENABLED"], "true")
            config.write_text(json.dumps({directory.KEY: str(Path(tmp) / "changed-by-cli")}))
            self.assertEqual(directory.configured(), str(Path(tmp) / "changed-by-cli"))

    def test_invalid_folder_is_rejected_before_settings_are_saved(self):
        with TemporaryDirectory() as tmp:
            file = Path(tmp) / "file.pdf"
            file.write_text("fixture")
            a = Api(MagicMock(), MagicMock(), MagicMock())
            with patch("paper_search_carsi.user_settings.save") as save:
                for value in ("", "relative/path", str(file), "bad\0path"):
                    result = a.save_settings({"login": "180", "page": "60", "hourly": "100"}, True, value)
                    self.assertFalse(result["ok"])
                    self.assertIn("download_dir", result["errors"])
                save.assert_not_called()

    def test_cancelled_picker_does_not_write_config(self):
        a = Api(MagicMock(), MagicMock(), MagicMock())
        a._window = MagicMock()
        a._window.create_file_dialog.return_value = None
        with patch.object(directory, "current", return_value="/example"), patch.object(directory, "save") as save:
            self.assertIsNone(a.choose_download_directory())
            save.assert_not_called()

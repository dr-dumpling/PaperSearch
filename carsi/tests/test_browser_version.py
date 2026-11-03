"""The pinned Camoufox build is launched by path, and every download records its browser (ADR 0013)."""
import json
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_search_carsi.browser import backend
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import get_publisher_profile


class PinnedCamoufoxTests(unittest.TestCase):
    def setUp(self):
        backend._launched.clear()
        self.addCleanup(backend._launched.clear)
        self.cache = Path(tempfile.mkdtemp())
        official = self.cache / "browsers" / "official"
        # A newer prerelease is installed next to it; only the pinned stable build counts.
        for name in ("158.0-beta.40-1a2b3c4d", f"{backend.CAMOUFOX_BROWSER}-0ad5663e"):
            (official / name).mkdir(parents=True)

    def options(self):
        with patch("camoufox.pkgman.INSTALL_DIR", self.cache), \
                patch("camoufox.pkgman.launch_path", side_effect=lambda path: str(path / "camoufox")):
            return backend._camoufox_options(False, None, None, True, {})

    def test_the_pinned_build_is_launched_by_path_and_recorded(self):
        with patch("camoufox.pkgman.INSTALL_DIR", self.cache):
            self.assertEqual(backend.pinned_camoufox_dir().name, f"{backend.CAMOUFOX_BROWSER}-0ad5663e")
        opts = self.options()
        self.assertTrue(opts["executable_path"].endswith(f"{backend.CAMOUFOX_BROWSER}-0ad5663e/camoufox"))
        self.assertEqual(backend.browser_info(), {"backend": "camoufox", "pinned": "yes",
                                                  "version": f"{backend.CAMOUFOX_BROWSER}-0ad5663e"})

    def test_without_the_pinned_build_the_active_one_is_used_and_said_so(self):
        (self.cache / "browsers" / "official" / f"{backend.CAMOUFOX_BROWSER}-0ad5663e").rmdir()
        with patch.object(backend, "_active_camoufox_version", return_value="158.0-beta.40"):
            opts = self.options()
            self.assertNotIn("executable_path", opts)
            self.assertEqual(backend.browser_info(), {"backend": "camoufox", "pinned": "no", "version": "158.0-beta.40"})


class EgoVersionTests(unittest.TestCase):
    def test_ego_lites_own_version_is_read_from_its_bundle(self):
        app = Path(tempfile.mkdtemp()) / "ego lite.app"
        (app / "Contents").mkdir(parents=True)
        with open(app / "Contents" / "Info.plist", "wb") as handle:
            plistlib.dump({"CFBundleShortVersionString": "0.6.2.5"}, handle)
        self.assertEqual(backend.ego_app_version({"ego_app": str(app)}), "0.6.2.5")
        self.assertEqual(backend.ego_app_version({"ego_app": str(app.parent / "missing.app")}), "")


class RecordedBrowserTests(unittest.TestCase):
    def test_the_diagnostic_keeps_the_browser(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("taylor & francis"))
        d.browser = {"backend": "camoufox", "pinned": "yes", "version": "156.0.1-beta.36-0ad5663e"}
        d._access_state = Mock(return_value=("unknown", []))
        page = Mock(url="https://www.tandfonline.com/doi/full/10.1080/x")
        result = DownloadResult(doi="10.1080/x", status="failed", reason="pdf_not_captured", state="pdf_not_captured")
        d._write_diagnostic(page, result, Path(tempfile.mkdtemp()))
        saved = json.loads(Path(result.diagnostic_path).read_text(encoding="utf-8"))
        self.assertEqual(saved["browser"], d.browser)


if __name__ == "__main__":
    unittest.main()

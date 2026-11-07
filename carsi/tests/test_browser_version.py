"""The user's Chrome is recorded with every download, and checked against the tested version (ADR 0013)."""
import json
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_search_carsi.browser import backend
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import get_publisher_profile


def mac_app(root: Path, name: str, version: str) -> Path:
    app = root / f"{name}.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    with open(app / "Contents" / "Info.plist", "wb") as handle:
        plistlib.dump({"CFBundleShortVersionString": version}, handle)
    executable = app / "Contents" / "MacOS" / name
    executable.write_text("")
    return executable


class ChromeVersionTests(unittest.TestCase):
    def setUp(self):
        backend._launched.clear()
        self.addCleanup(backend._launched.clear)
        self.root = Path(tempfile.mkdtemp())

    def test_the_mac_bundle_says_the_version_without_a_launch(self):
        executable = mac_app(self.root, "Google Chrome", "156.0.8078.81")
        with patch.object(backend.sys, "platform", "darwin"):
            self.assertEqual(backend.chrome_version(executable), "156.0.8078.81")
            with patch.object(backend, "find_chrome", return_value=executable), \
                    patch.object(backend, "patchright_version", return_value="1.64.4"):
                self.assertEqual(backend.browser_info({}), {"backend": "chrome", "app": "Google Chrome",
                                                            "version": "156.0.8078.81", "driver": "patchright 1.64.4"})

    def test_windows_takes_the_newest_version_folder_next_to_the_program(self):
        application = self.root / "Google" / "Chrome" / "Application"
        for name in ("155.0.7000.10", "156.0.8078.80", "SetupMetrics"):
            (application / name).mkdir(parents=True)
        (application / "chrome.exe").write_text("")
        with patch.object(backend.sys, "platform", "win32"):
            self.assertEqual(backend.chrome_version(application / "chrome.exe"), "156.0.8078.80")

    def test_chrome_older_than_the_tested_version_is_reported(self):
        for version, outdated in (("156.0.8078.81", False), ("156.0.8078.80", False), ("156.0.8000.1", True),
                                  ("155.0.7000.1", True), ("", False)):
            executable = mac_app(Path(tempfile.mkdtemp()), "Google Chrome", version)
            with self.subTest(version=version), patch.object(backend.sys, "platform", "darwin"), \
                    patch.object(backend, "find_chrome", return_value=executable), \
                    patch.object(backend, "patchright_version", return_value="1.64.4"):
                check = backend.browser_check({})
                self.assertEqual((check["browser"], check["version"], check["outdated"]),
                                 ("Google Chrome", version, outdated))
                self.assertEqual((check["tested"], check["path"], check["driver"]),
                                 (backend.TESTED_CHROME, str(executable), "patchright 1.64.4"))

    def test_without_a_browser_the_check_finds_none(self):
        with patch.object(backend, "find_chrome", return_value=None):
            check = backend.browser_check({})
        self.assertEqual((check["browser"], check["outdated"]), ("", False))


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
        d.browser = {"backend": "chrome", "app": "Google Chrome", "version": "156.0.8078.81", "driver": "patchright 1.64.4"}
        d._access_state = Mock(return_value=("unknown", []))
        page = Mock(url="https://www.tandfonline.com/doi/full/10.1080/x")
        result = DownloadResult(doi="10.1080/x", status="failed", reason="pdf_not_captured", state="pdf_not_captured")
        d._write_diagnostic(page, result, Path(tempfile.mkdtemp()))
        saved = json.loads(Path(result.diagnostic_path).read_text(encoding="utf-8"))
        self.assertEqual(saved["browser"], d.browser)


if __name__ == "__main__":
    unittest.main()

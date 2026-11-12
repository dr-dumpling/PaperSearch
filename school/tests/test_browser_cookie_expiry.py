"""Cookie expiry regressions using synthetic values and an in-memory store only."""

import copy
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "paper_search_school" / "browser" / "cookies.py"
NOW = 1_800_000_000


class BrowserCookieValidityTests(unittest.TestCase):
    def setUp(self):
        # Avoid package startup and real config/credential discovery.
        self.enterContext(patch.dict(sys.modules))
        package = types.ModuleType("_cookie_validity_test")
        package.__path__ = []
        sys.modules[package.__name__] = package
        log = types.ModuleType(f"{package.__name__}.log")
        log.get_logger = Mock(return_value=Mock())
        sys.modules[log.__name__] = log
        config = types.ModuleType(f"{package.__name__}.config")
        config.DATA_DIR = Path("/synthetic-unused-data")
        sys.modules[config.__name__] = config
        _browser = types.ModuleType(package.__name__ + ".browser")
        _browser.__path__ = [str(SOURCE.parent)]
        sys.modules[_browser.__name__] = _browser
        spec = importlib.util.spec_from_file_location(f"{package.__name__}.browser.cookies", SOURCE)
        self.cookies = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.cookies
        spec.loader.exec_module(self.cookies)

    def test_minus_one_and_zero_session_cookies_are_retained_unchanged(self):
        for expires in (-1, 0, -1.0, 0.0):
            with self.subTest(expires=expires):
                cookie = {"name": "synthetic_session", "value": "synthetic", "expires": expires}
                original = copy.deepcopy(cookie)
                self.assertTrue(self.cookies._is_cookie_valid(cookie, NOW))
                self.assertEqual(cookie, original)
                self.assertIs(type(cookie["expires"]), type(expires))

    def test_persistent_expiry_boundary_is_unchanged(self):
        for expires, expected in ((NOW - 1, False), (NOW, False), (NOW + 1, True), (-2, False)):
            with self.subTest(expires=expires):
                cookie = {"expires": expires}
                self.assertIs(self.cookies._is_cookie_valid(cookie, NOW), expected)
                self.assertEqual(cookie["expires"], expires)

    def test_missing_expiry_keeps_existing_session_behavior(self):
        for cookie in ({}, {"expires": None}):
            with self.subTest(cookie=cookie):
                self.assertTrue(self.cookies._is_cookie_valid(cookie, NOW))

    def test_session_cookie_needs_no_clock_or_expiry_extension(self):
        with patch.object(self.cookies.time, "time", side_effect=AssertionError("session has no absolute expiry")):
            self.assertTrue(self.cookies._is_cookie_valid({"expires": -1}))
            self.assertTrue(self.cookies._is_cookie_valid({"expires": 0}))

    def test_persistent_cookie_uses_current_clock_when_now_is_omitted(self):
        with patch.object(self.cookies.time, "time", return_value=NOW) as clock:
            self.assertFalse(self.cookies._is_cookie_valid({"expires": NOW - 1}))
            self.assertFalse(self.cookies._is_cookie_valid({"expires": NOW}))
            self.assertTrue(self.cookies._is_cookie_valid({"expires": NOW + 1}))
            self.assertEqual(clock.call_count, 3)

    def test_store_load_retains_sessions_and_drops_expired_without_mutation(self):
        fixtures = [
            {"name": name, "value": "synthetic", "domain": ".example.invalid", "path": "/", "expires": expires}
            for name, expires in (("chromium_session", -1), ("session", 0), ("expired", NOW - 1),
                                  ("boundary", NOW), ("future", NOW + 1), ("other_negative", -2))
        ]
        serialized = json.dumps(fixtures)
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "read_text", return_value=serialized) as read, \
             patch.object(Path, "write_text", side_effect=AssertionError("no store writes")), \
             patch.object(self.cookies.time, "time", return_value=NOW):
            loaded = self.cookies.load_saved_cookies({"cache_dir": "/synthetic-unused-cache"})
        self.assertEqual(loaded, [fixtures[0], fixtures[1], fixtures[4]])
        self.assertEqual([cookie["expires"] for cookie in loaded], [-1, 0, NOW + 1])
        read.assert_called_once_with(encoding="utf-8")
        self.assertEqual(serialized, json.dumps(fixtures))


if __name__ == "__main__":
    unittest.main()

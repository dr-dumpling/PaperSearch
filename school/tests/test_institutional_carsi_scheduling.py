"""Explicit CARSI is a browser entry: no preset school, no legacy enable flag; the publisher driver is the only driver."""
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from paper_search_school import orchestrator
from paper_search_school.engine import bridge

# A site without a publisher profile.
NO_PROFILE_URL = "https://journals.unprofiled.example/article/example"


class CARSISchedulingTests(unittest.TestCase):
    def test_explicit_school_is_a_browser_entry_without_school_or_legacy_enable_flag(self):
        for school in ("", "Fixture University A", "Fixture University B"):
            for enabled in (False, True):
                config = {"publisher_institution_federation": "carsi",
                          "carsi_enabled": enabled, "school_name": school}
                with self.subTest(school=school, enabled=enabled):
                    self.assertTrue(bridge._any_institutional_configured(config))

    def test_publisher_driver_runs_alone_with_configured_school(self):
        for school in ("", "Fixture University A", "Fixture University B"):
            config = {"publisher_institution_federation": "carsi", "carsi_enabled": True,
                      "school_name": school}
            with self.subTest(school=school), tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
                config["cache_dir"] = temp
                calls = []
                stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))
                stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Network forbidden")))
                stack.enter_context(patch.object(bridge, "_resolve_doi", return_value="https://example.org/article"))
                legacy = [stack.enter_context(patch.object(bridge, name)) for name in
                          ("_try_external_instsci", "_try_session_broker")]
                stack.enter_context(patch("paper_search_school.browser.backend.is_available", return_value=True))
                downloader = MagicMock()
                def publisher_result(*args):
                    calls.append("publisher")
                    return SimpleNamespace(ok=False, pdf_path=None, state="login_timeout", reason="login_timeout")
                downloader.fetch_one.side_effect = publisher_result
                factory = stack.enter_context(patch("paper_search_school.engine.batch.PublisherBatchDownloader",
                                                    return_value=downloader))
                result = bridge.try_institutional("10.1016/example", Path(temp) / "out.pdf", config)
                for route in legacy:
                    route.assert_not_called()
                self.assertEqual(calls, ["publisher"])
                # The browser capture receives the user's own institution name (empty = manual).
                self.assertEqual(factory.call_args.kwargs["institution_query"], school)
                self.assertEqual(config["school_name"], school)
                downloader.fetch_one.assert_called_once()
                self.assertEqual(result["error_type"], "login_timeout")

    def no_profile_run(self, landing):
        config = {"publisher_institution_federation": "carsi", "carsi_enabled": True,
                  "school_name": ""}
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            config["cache_dir"] = temp
            stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))
            stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Network forbidden")))
            stack.enter_context(patch.object(bridge, "_try_external_instsci", return_value=None))
            stack.enter_context(patch.object(bridge, "_resolve_doi", return_value=landing))
            stack.enter_context(patch("paper_search_school.browser.backend.is_available", return_value=True))
            downloader = MagicMock()
            downloader.fetch_one.return_value = SimpleNamespace(ok=False, pdf_path=None, state="sso_required",
                                                                reason="sso_required")
            factory = stack.enter_context(patch("paper_search_school.engine.batch.PublisherBatchDownloader",
                                                return_value=downloader))
            broker = stack.enter_context(patch.object(bridge, "_try_session_broker"))
            result = bridge.try_institutional("10.99999/example", Path(temp) / "out.pdf", config)
        broker.assert_not_called()  # manual CARSI: never the broker
        return result, factory, downloader

    def test_a_site_without_publisher_profile_runs_the_publisher_driver_with_the_shared_rules(self):
        result, factory, downloader = self.no_profile_run(NO_PROFILE_URL)
        profile = factory.call_args.kwargs["profile"]
        self.assertEqual((profile.name, profile.base_domains, profile.doi_prefixes),
                         ("site:unprofiled.example", ("unprofiled.example",), ("10.99999",)))
        self.assertTrue(profile.generic)
        downloader.fetch_one.assert_called_once()
        self.assertEqual(result["error_type"], "paywall")  # the driver's own outcome

    def test_a_doi_leading_to_no_site_is_unsupported_without_any_browser(self):
        for landing in (None, "https://journals.unprofiled.example/content/article.pdf",
                        "https://chooser.crossref.org/?doi=10.99999%2Fexample", "https://kns.cnki.net/kcms/detail"):
            with self.subTest(landing=landing):
                result, factory, _ = self.no_profile_run(landing)
                factory.assert_not_called()
                self.assertEqual((result["success"], result["error_type"], result["reason"], result["action"]),
                                 (False, "unsupported_publisher", "unsupported_publisher", "review_publisher_profiles"))
                self.assertNotIn("source_failures", result)

    def test_unselected_federation_and_metadata_keys_do_not_enable_browser_entry(self):
        for config in ({}, {"carsi_enabled": True},
                       {"publisher_institution_federation": "openathens"},
                       {"publisher_institution_federation": "school-unknown"},
                       {"openalex_api_key": "fixture-key", "wos_api_key": "fixture-key"},
                       # Keys of the WebVPN / EZProxy routes left in an old config file.
                       {"vpnsci_enabled": True, "vpnsci_school": "Fixture University",
                        "vpnsci_base_url": "https://vpn.fixture.example"},
                       {"ezproxy_enabled": True, "ezproxy_login_url": "https://ezproxy.fixture.example/login?url="}):
            with self.subTest(config=config), ExitStack() as stack:
                stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))
                stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Network forbidden")))
                self.assertFalse(bridge._any_institutional_configured(config))
                self.assertIsNone(bridge.try_institutional("10.1016/example", Path("unused.pdf"), config))

    def test_unconfigured_backend_reports_login_required_without_any_route(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))
            stack.enter_context(patch.object(orchestrator, "load_config", return_value={"output_dir": temp}))
            stack.enter_context(patch.object(orchestrator, "cache_get", return_value=None))
            cache = stack.enter_context(patch.object(orchestrator, "cache_set"))
            builtin = stack.enter_context(patch.object(bridge, "_try_builtin_institutional"))
            result = orchestrator.download_institutional("10.1016/example", temp)
        builtin.assert_not_called()
        cache.assert_not_called()
        self.assertEqual((result["error_type"], result["action"]), ("paywall", "login_required"))


if __name__ == "__main__":
    unittest.main()

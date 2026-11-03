"""Configured publisher profiles traverse the real bridge without live routes.

External routes, browser construction and config/cache are isolated; only a
temporary profiles JSON and staged routing output are read or written.
"""
from __future__ import annotations

import copy
import json
import socket
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_search_carsi.engine import bridge
from paper_search_carsi.publishers import extensions, profiles


DOI = "10.99991/routing-fixture"
LANDING = "https://journals.fixture.example/doi/" + DOI
STAGED_BYTES = b"synthetic routing output; not a PDF validation fixture"


class PublisherExtensionWiringTests(unittest.TestCase):
    def setUp(self):
        self.connect = self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.dns = self.enterContext(patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.load_config = self.enterContext(patch("paper_search_carsi.config.load_config",
                                                   side_effect=AssertionError("config forbidden")))
        self.launch = self.enterContext(patch("paper_search_carsi.browser.backend.launch_persistent_context",
                                              side_effect=AssertionError("browser forbidden")))
        self.enterContext(patch("paper_search_carsi.browser.backend.is_available", return_value=True))
        self.downloader = Mock()
        self.downloader.fetch_one.side_effect = self.stage_single_result
        self.constructor = self.enterContext(patch("paper_search_carsi.engine.batch.PublisherBatchDownloader",
                                                   return_value=self.downloader))
        self.external = self.enterContext(patch.object(bridge, "_try_external_instsci", return_value=None))
        self.resolve = self.enterContext(patch.object(bridge, "_resolve_doi", return_value=LANDING))
        self.broker = self.enterContext(patch.object(bridge, "_try_session_broker", return_value=None))
        self.loaded = []
        real_load = extensions.load_publisher_profiles
        def load(config):
            catalog = real_load(config)
            self.loaded.append(catalog)
            return catalog
        self.load_profiles = self.enterContext(patch.object(extensions, "load_publisher_profiles", side_effect=load))
        self.builtin = self.enterContext(patch.object(bridge, "_try_builtin_institutional",
                                                      wraps=bridge._try_builtin_institutional))
        self.infer = self.enterContext(patch.object(profiles, "infer_publisher_profile",
                                                    wraps=profiles.infer_publisher_profile))
        self.from_url = self.enterContext(patch.object(profiles, "infer_publisher_profile_from_url",
                                                       wraps=profiles.infer_publisher_profile_from_url))
        self.config = self.fixture_config("fixture", "Fixture Press", "journals.fixture.example", "10.99991")

    def tearDown(self):
        self.connect.assert_not_called()
        self.dns.assert_not_called()
        self.load_config.assert_not_called()
        self.launch.assert_not_called()
        self.assertFalse((self.root / "unused-cache").exists())

    def fixture_config(self, key, name, domain, prefix):
        path = self.root / (key + ".json")
        path.write_text(json.dumps({"schema_version": 1, "profiles": {key: {
            "name": name, "aliases": [key + "-alias"], "base_domains": [domain],
            "doi_prefixes": [prefix], "article_url_template": "https://" + domain + "/doi/{doi}",
            "pdf_url_templates": [], "success_url_markers": [domain + "/doi/"],
            "auth_url_markers": [], "auth_title_markers": [], "sso_text_markers": [],
        }}}))
        return {"publisher_profiles_file": str(path), "carsi_enabled": True,
                "carsi_idp_name": "Offline Fixture Institution", "cache_dir": str(self.root / "unused-cache")}

    def stage_single_result(self, context, record, run_dir):
        path = run_dir / "staged-output.pdf"
        path.write_bytes(STAGED_BYTES)
        return types.SimpleNamespace(ok=True, pdf_path=str(path), size_bytes=len(STAGED_BYTES), text_length=0)

    def run_source(self, doi=DOI, config=None, output="out.pdf"):
        config = self.config if config is None else config
        return bridge.try_institutional(doi, self.root / output, config)

    def assert_no_routes(self):
        for route in (self.external, self.resolve, self.broker, self.constructor):
            route.assert_not_called()

    def test_configured_profile_reaches_builtin_browser_with_the_same_mapping(self):
        original = copy.deepcopy(self.config)
        result = self.run_source()
        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "institutional:browser:Fixture Press")
        self.assertEqual((self.root / "out.pdf").read_bytes(), STAGED_BYTES)
        self.load_profiles.assert_called_once_with(self.config)
        catalog = self.loaded[0]
        self.assertIs(self.infer.call_args.kwargs["profiles"], catalog)
        self.assertIs(self.builtin.call_args.kwargs["profiles"], catalog)
        self.assertIs(self.builtin.call_args.args[3], catalog["fixture"])
        self.assertIs(self.constructor.call_args.kwargs["profile"], catalog["fixture"])
        self.assertIs(self.constructor.call_args.kwargs["config"], self.config)
        self.assertEqual(self.config, original)
        self.from_url.assert_not_called()
        self.downloader._launch_context.return_value.close.assert_called_once()

    def test_unknown_doi_uses_known_landing_host_in_the_same_loaded_mapping(self):
        unknown = "10.99999/unknown-prefix"
        result = self.run_source(unknown)
        self.assertTrue(result["success"])
        self.assertIsNone(self.builtin.call_args.args[3])
        self.resolve.assert_called_once_with(unknown)
        self.from_url.assert_called_once_with(LANDING, profiles=self.loaded[0])
        self.assertIs(self.constructor.call_args.kwargs["profile"], self.loaded[0]["fixture"])
        self.assertEqual(self.downloader.fetch_one.call_args.args[1].doi, unknown)

    def test_unknown_doi_with_spoofed_landing_never_selects_extension(self):
        # The landing's own host decides: a profile for evil.example with the
        # shared rules only, never the extension named in its query.
        self.resolve.return_value = "https://evil.example/?next=" + LANDING
        result = self.run_source("10.99999/unknown-prefix")
        profile = self.constructor.call_args.kwargs["profile"]
        self.assertEqual((profile.name, profile.base_domains), ("site:evil.example", ("evil.example",)))
        self.assertTrue(profile.generic)
        self.assertNotIn(profile, self.loaded[0].values())
        self.assertEqual(result["source"], "institutional:browser:site:evil.example")

    def test_invalid_explicit_config_stops_before_any_route_and_sanitizes_reason(self):
        secret = "synthetic-secret-do-not-echo"
        filename = self.root / (secret + ".json")
        for payload in (None, '{"profiles":' + secret, json.dumps({"schema_version": 1, "profiles": {"bad": {"cookie": secret}}})):
            with self.subTest(payload=payload):
                if payload is not None:
                    filename.write_text(payload)
                config = {**self.config, "publisher_profiles_file": str(filename)}
                result = self.run_source(config=config)
                self.assertEqual(result, {
                    "success": False, "identifier": DOI, "source": "institutional:profiles",
                    "error_type": "source_exception", "reason": "publisher_profile_config_invalid",
                    "action": "review_publisher_profiles",
                })
                self.assertNotIn(secret, json.dumps(result))
                self.assert_no_routes()
                self.builtin.assert_not_called()

    def test_extension_request_does_not_poison_later_default_unknown_or_builtin_request(self):
        builtin = dict(profiles.PUBLISHER_PROFILES)
        aliases = dict(profiles._PROFILE_ALIASES)
        self.assertTrue(self.run_source()["success"])
        defaults = {key: value for key, value in self.config.items() if key != "publisher_profiles_file"}
        self.constructor.reset_mock()
        # Without the extension the same site gets the shared rules only.
        self.assertTrue(self.run_source(config=defaults, output="default-unknown.pdf")["success"])
        self.assertEqual(self.constructor.call_args.kwargs["profile"].name, "site:fixture.example")
        self.assertNotIn("profiles", self.builtin.call_args.kwargs)
        self.constructor.reset_mock()
        self.resolve.return_value = "https://pubs.acs.org/doi/10.1021/offline-fixture"
        result = self.run_source("10.1021/offline-fixture", defaults, "default-acs.pdf")
        self.assertTrue(result["success"])
        self.assertIs(self.constructor.call_args.kwargs["profile"], profiles.ACS_PROFILE)
        self.assertEqual(profiles.PUBLISHER_PROFILES, builtin)
        self.assertEqual(profiles._PROFILE_ALIASES, aliases)
        self.assertEqual(self.load_profiles.call_count, 1)

    def test_two_explicit_configs_use_independent_profiles_and_no_default_cache(self):
        other = self.fixture_config("other", "Other Press", "other.fixture.example", "10.99992")
        self.assertTrue(self.run_source()["success"])
        first_profile = self.constructor.call_args.kwargs["profile"]
        self.resolve.return_value = "https://other.fixture.example/doi/10.99992/fixture"
        self.assertTrue(self.run_source("10.99992/fixture", other, "other.pdf")["success"])
        second_profile = self.constructor.call_args.kwargs["profile"]
        self.assertEqual((first_profile.name, second_profile.name), ("Fixture Press", "Other Press"))
        self.assertIsNot(self.loaded[0], self.loaded[1])
        self.assertNotIn("other", self.loaded[0])
        self.assertNotIn("fixture", self.loaded[1])


if __name__ == "__main__":
    unittest.main()

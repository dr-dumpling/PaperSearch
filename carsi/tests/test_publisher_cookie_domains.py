"""Publisher cookie authority and scoped merging, using only temporary stores.

python -B -m unittest discover -s tests -p test_publisher_cookie_domains.py -v
No real config, cookie cache, browser, credential store, DNS or network access.
"""
from __future__ import annotations

import copy
import importlib
import json
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "paper_search_carsi"
PACKAGE = "_publisher_cookie_domains_test"


def cookie(name, domain, value="synthetic-new", path="/"):
    return dict(name=name, value=value, domain=domain, path=path, expires=-1,
                secure=True, httpOnly=True, sameSite="None")


class PublisherCookieDomainsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(sys.modules))
        self.connect = self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.dns = self.enterContext(patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / "fixture-cache"
        self.config = {"cache_dir": str(self.cache)}
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(SOURCE)]
        sys.modules[PACKAGE] = package
        for _sub in ("browser", "engine", "publishers", "extractors", "_core"):
            _m = types.ModuleType(PACKAGE + "." + _sub)
            _m.__path__ = [str(SOURCE / _sub)]
            sys.modules[_m.__name__] = _m
        config = types.ModuleType(PACKAGE + ".config")
        config.DATA_DIR = self.root / "unused-default-data"
        config.load_config = Mock(side_effect=AssertionError("user config forbidden"))
        sys.modules[config.__name__] = config
        log = types.ModuleType(PACKAGE + ".log")
        log.get_logger = lambda: Mock()
        sys.modules[log.__name__] = log
        self.cookies = importlib.import_module(PACKAGE + ".browser.cookies")
        self.config_module = config

    def tearDown(self):
        self.connect.assert_not_called()
        self.dns.assert_not_called()
        self.config_module.load_config.assert_not_called()
        self.assertFalse(self.config_module.DATA_DIR.exists())
        self.assertNotIn(PACKAGE + ".browser.backend", sys.modules)

    def seed(self, cookies):
        self.cache.mkdir()
        (self.cache / "publisher_cookies.json").write_text(json.dumps(cookies))

    def assert_saved(self, expected):
        self.assertEqual(json.loads((self.cache / "publisher_cookies.json").read_text()), expected)
        self.assertEqual(self.cookies.load_saved_cookies(self.config), expected)
        rows = [line.split("\t") for line in (self.cache / "publisher_cookies.txt").read_text().splitlines()
                if line and not line.startswith("#")]
        self.assertEqual({(row[0], row[2], row[5], row[6]) for row in rows},
                         {(item["domain"], item["path"], item["name"], item["value"]) for item in expected})

    def test_builtin_domains_accept_exact_host_and_subdomains_with_case_normalization(self):
        for domain in ("acs.org", ".acs.org", "pubs.acs.org", ".PUBS.ACS.ORG", "archive.pubs.acs.org",
                       ".sciencedirect.com", ".nature.com", ".onlinelibrary.wiley.com"):
            with self.subTest(domain=domain):
                self.assertTrue(self.cookies._is_publisher_cookie(cookie("session", domain)))

    def test_builtin_boundary_rejects_lookalikes_suffix_attacks_and_idp(self):
        for domain in ("evilacs.org", ".evilacs.org", "notacs.org", "acs.org.evil.example",
                       "pubs.acs.org.evil.example", ".sciencedirect.com.evil.example",
                       "evilnature.com", "login.university.example", "acs.org:443",
                       "https://acs.org", "", "org"):
            with self.subTest(domain=domain):
                self.assertFalse(self.cookies._is_publisher_cookie(cookie("session", domain)))

    def test_scoped_merge_filters_incoming_idp_other_publisher_and_lookalikes(self):
        old = [cookie("session", ".acs.org", "synthetic-old"),
               cookie("wiley", ".wiley.com", "synthetic-saved-wiley")]
        self.seed(old)
        incoming = [cookie("session", ".acs.org"), cookie("subdomain", "PUBS.ACS.ORG"),
                    cookie("idp", ".login.university.example"),
                    cookie("wiley", ".wiley.com", "synthetic-must-not-replace"),
                    cookie("nature", ".nature.com"), cookie("lookalike", ".evilacs.org"),
                    cookie("suffix-attack", ".acs.org.evil.example")]
        original = copy.deepcopy(incoming)
        merged = self.cookies.merge_cookies(incoming, self.config, publisher_domains=("acs.org",))
        expected = [incoming[0], old[1], incoming[1]]
        self.assertEqual(merged, expected)
        self.assertEqual(incoming, original)
        self.assertEqual(old[0]["value"], "synthetic-old")
        self.assert_saved(expected)

    def test_scoped_merge_preserves_other_publishers_previously_saved(self):
        existing = [cookie("nature", ".nature.com", "synthetic-saved-nature"),
                    cookie("wiley", ".onlinelibrary.wiley.com", "synthetic-saved-wiley"),
                    cookie("acs", ".acs.org", "synthetic-saved-acs")]
        self.seed(existing)
        incoming = cookie("new-acs", ".pubs.acs.org")
        merged = self.cookies.merge_cookies([incoming], self.config, publisher_domains=("acs.org",))
        self.assertEqual(merged, existing + [incoming])
        self.assert_saved(merged)

    def test_default_merge_keeps_builtin_multi_publisher_behavior(self):
        incoming = [cookie("acs", ".acs.org"), cookie("wiley", ".wiley.com"),
                    cookie("nature", ".nature.com"), cookie("idp", ".login.university.example"),
                    cookie("custom", ".journals.fixture.example"), cookie("lookalike", ".evilacs.org")]
        merged = self.cookies.merge_cookies(incoming, self.config)
        self.assertEqual(merged, incoming[:3])
        self.assert_saved(merged)
        self.assertEqual(self.cookies.merge_cookies(incoming, self.config, publisher_domains=None), merged)

    def test_domain_scope_does_not_collapse_cookie_paths_or_other_host_values(self):
        old = [cookie("session", ".acs.org", "synthetic-old-root"),
               cookie("session", ".acs.org", "synthetic-article-path", path="/article"),
               cookie("session", ".nature.com", "synthetic-other-host")]
        self.seed(old)
        incoming = cookie("session", ".acs.org", "synthetic-new-root")
        merged = self.cookies.merge_cookies([incoming], self.config, publisher_domains=("acs.org",))
        self.assertEqual(merged, [incoming, old[1], old[2]])
        self.assert_saved(merged)

    def test_declared_custom_profile_scope_accepts_only_its_domains_and_subdomains(self):
        document = {"schema_version": 1, "profiles": {"fixture": {
            "name": "Fixture Press", "base_domains": ["journals.fixture.example"],
            "doi_prefixes": ["10.99991"], "article_url_template": "https://journals.fixture.example/doi/{doi}",
            "pdf_url_templates": [], "success_url_markers": ["journals.fixture.example/doi/"],
            "auth_url_markers": [], "auth_title_markers": [], "sso_text_markers": [],
        }}}
        path = self.root / "profile.json"
        path.write_text(json.dumps(document))
        extensions = importlib.import_module(PACKAGE + ".publishers.extensions")
        profile = extensions.load_publisher_profiles({"publisher_profiles_file": str(path)})["fixture"]
        incoming = [cookie("custom", ".journals.fixture.example"),
                    cookie("subdomain", ".archive.journals.fixture.example"),
                    cookie("parent", ".fixture.example"),
                    cookie("lookalike", ".eviljournals.fixture.example"),
                    cookie("suffix-attack", ".journals.fixture.example.evil.example"),
                    cookie("idp", ".idp.university.example"), cookie("acs", ".acs.org")]
        self.assertFalse(self.cookies._is_publisher_cookie(incoming[0]))
        merged = self.cookies.merge_cookies(incoming, self.config, publisher_domains=profile.base_domains)
        self.assertEqual(merged, incoming[:2])
        self.assert_saved(merged)

    def test_empty_explicit_scope_rejects_every_incoming_cookie_but_keeps_saved(self):
        old = [cookie("saved", ".nature.com", "synthetic-saved")]
        self.seed(old)
        merged = self.cookies.merge_cookies([cookie("new", ".acs.org")], self.config, publisher_domains=())
        self.assertEqual(merged, old)
        self.assert_saved(old)

    def test_all_rejected_without_prior_store_does_not_create_files(self):
        merged = self.cookies.merge_cookies([cookie("idp", ".university.example"), cookie("evil", ".evilacs.org")],
                                           self.config, publisher_domains=("acs.org",))
        self.assertEqual(merged, [])
        self.assertFalse(self.cache.exists())


if __name__ == "__main__":
    unittest.main()

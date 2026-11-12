"""Data-only profile extensions: real routing, isolated config, no network.

python -B -m unittest discover -s tests -p test_publisher_profile_extensions.py -v
"""
from __future__ import annotations

import copy
import importlib
import json
import socket
import sys
import tempfile
import traceback
import types
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "paper_search_school"
PACKAGE = "_profile_extensions_test"
DOI = "10.99991/Synthetic.Article.1"


def profile(name="Fixture Press", domain="journals.fixture.example", prefix="10.99991"):
    return {
        "name": name,
        "article_url_template": f"https://{domain}/doi/{{doi}}",
        "pdf_url_templates": [f"https://{domain}/doi/pdf/{{doi_quoted}}", f"https://{domain}/article/{{doi_suffix}}.pdf"],
        "base_domains": [domain],
        "doi_prefixes": [prefix],
        "success_url_markers": [domain + "/doi/"],
        "auth_url_markers": ["/saml/", "/login"],
        "auth_title_markers": ["Institutional Login"],
        "sso_text_markers": ["access through your institution"],
        "aliases": ["fixture-press"],
    }


class PublisherProfileExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(sys.modules))
        self.connect = self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.dns = self.enterContext(patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")))
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(SOURCE)]
        sys.modules[PACKAGE] = package
        for _sub in ("browser", "engine", "publishers", "extractors", "_core"):
            _m = types.ModuleType(PACKAGE + "." + _sub)
            _m.__path__ = [str(SOURCE / _sub)]
            sys.modules[_m.__name__] = _m
        self.profiles = importlib.import_module(PACKAGE + ".publishers.profiles")
        self.extension = importlib.import_module(PACKAGE + ".publishers.extensions")
        self.error = self.extension.PublisherProfileConfigError
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "profiles.json"
        self.document = {"schema_version": 1, "profiles": {"fixture": profile()}}

    def load(self, document=None, *, file=None):
        target = file or self.file
        target.write_text(json.dumps(self.document if document is None else document), encoding="utf-8")
        return self.extension.load_publisher_profiles({"publisher_profiles_file": str(target)})

    def reject_profile(self, **fields):
        value = copy.deepcopy(self.document)
        value["profiles"]["fixture"].update(fields)
        with self.assertRaises(self.error):
            self.load(value)

    def test_builtin_default_has_no_config_or_filesystem_access(self):
        p = self.profiles
        with patch.object(Path, "open", side_effect=AssertionError("unexpected file read")), \
             patch.object(Path, "is_file", side_effect=AssertionError("unexpected stat")):
            catalog = self.extension.load_publisher_profiles({"other_config_key": "unused"})
            self.assertEqual(p.list_publisher_profiles(), sorted(p.PUBLISHER_PROFILES))
            self.assertEqual(catalog, p.PUBLISHER_PROFILES)
            self.assertIsNot(catalog, p.PUBLISHER_PROFILES)
            for key, builtin in catalog.items():
                self.assertIs(p.get_publisher_profile(key), builtin)
                for alias in (builtin.name, *builtin.aliases):
                    self.assertIs(p.get_publisher_profile(alias), builtin)
                for doi in builtin.sample_dois:
                    self.assertIs(p.infer_publisher_profile(doi), builtin)
                    self.assertIs(p.infer_publisher_profile(doi, profiles=catalog), builtin)
        self.assertNotIn(PACKAGE + ".config", sys.modules)
        self.connect.assert_not_called()
        self.dns.assert_not_called()

    def test_empty_explicit_mapping_does_not_fall_back_to_builtin(self):
        p = self.profiles
        self.assertEqual(p.list_publisher_profiles(profiles={}), [])
        self.assertIsNone(p.infer_publisher_profile("10.1021/fixture", profiles={}))
        self.assertIsNone(p.infer_publisher_profile_from_url("https://pubs.acs.org/doi/fixture", profiles={}))
        with self.assertRaises(ValueError):
            p.get_publisher_profile("acs", profiles={})

    def test_extension_matches_key_display_name_alias_and_actual_host(self):
        catalog = self.load()
        p = self.profiles
        expected = catalog["fixture"]
        for name in ("fixture", "Fixture Press", "FIXTURE-PRESS", " fixture "):
            self.assertIs(p.get_publisher_profile(name, profiles=catalog), expected)
        self.assertIn("fixture", p.list_publisher_profiles(profiles=catalog))
        self.assertIs(p.infer_publisher_profile(DOI, profiles=catalog), expected)
        for url in ("https://journals.fixture.example/doi/" + DOI,
                    "https://archive.journals.fixture.example/article/123",
                    "https://JOURNALS.FIXTURE.EXAMPLE/doi/" + DOI):
            self.assertIs(p.infer_publisher_profile_from_url(url, profiles=catalog), expected)
        self.assertEqual(expected.article_url(DOI), "https://journals.fixture.example/doi/" + DOI)
        self.assertEqual(expected.pdf_urls(DOI), ["https://journals.fixture.example/doi/pdf/10.99991%2FSynthetic.Article.1",
                                                "https://journals.fixture.example/article/Synthetic.Article.1.pdf"])

    def test_extension_cannot_shadow_a_builtin_publisher(self):
        bmj = profile("BMJ", "bmj.com", "10.1136")
        with self.assertRaises(self.extension.PublisherProfileConfigError):
            self.load({"schema_version": 1, "profiles": {"bmj-copy": bmj}})

    def test_real_publisher_mapping_is_offline_not_authorization(self):
        cup = profile("Cambridge University Press", "cambridge.org", "10.1017")
        cup["aliases"] = ["cambridge-core"]
        cup["article_url_template"] = "https://doi.org/{doi}"
        cup["pdf_url_templates"] = []
        catalog = self.load({"schema_version": 1, "profiles": {"cambridge": cup}})
        self.assertEqual(self.profiles.infer_publisher_profile("10.1017/s0000000000000000", profiles=catalog).name, "Cambridge University Press")
        self.assertEqual(self.profiles.infer_publisher_profile_from_url("https://www.cambridge.org/core/journals/x", profiles=catalog).name, "Cambridge University Press")
        self.assertEqual(catalog["cambridge"].pdf_urls("10.1017/s0000000000000000"), [])
        self.connect.assert_not_called()
        self.dns.assert_not_called()

    def test_existing_source_path_router_consumes_extension_without_code_plugin(self):
        self.document["profiles"]["fixture"]["pdf_source_path_templates"] = [{
            "domain": "journals.fixture.example", "path_prefix": "/landing/",
            "path_template": "/pdf/{source_path_after_prefix}",
        }]
        catalog = self.load()
        router = importlib.import_module(PACKAGE + ".engine.router")
        urls = router.build_pdf_candidates(catalog["fixture"], DOI, source_url="https://journals.fixture.example/landing/article-id")
        self.assertEqual(urls[0], "https://journals.fixture.example/pdf/article-id")
        self.assertIn(catalog["fixture"].pdf_urls(DOI)[0], urls)
        self.assertIsInstance(catalog["fixture"].pdf_source_path_templates[0], self.profiles.PdfSourcePathTemplate)

    def test_two_configs_and_builtin_registry_never_pollute_each_other(self):
        builtin = dict(self.profiles.PUBLISHER_PROFILES)
        aliases = dict(self.profiles._PROFILE_ALIASES)
        a = self.load()
        b_data = {"schema_version": 1, "profiles": {"other": profile("Other Press", "other.example", "10.99992")}}
        b_data["profiles"]["other"]["aliases"] = ["other-press"]
        b = self.load(b_data, file=self.file.with_name("other.json"))
        self.assertNotIn("other", a)
        self.assertNotIn("fixture", b)
        self.assertNotIn("fixture", self.profiles.list_publisher_profiles())
        self.assertEqual(self.profiles.PUBLISHER_PROFILES, builtin)
        self.assertEqual(self.profiles._PROFILE_ALIASES, aliases)
        del a["acs"]
        self.assertIn("acs", b)
        self.assertIn("acs", builtin)
        with self.assertRaises(FrozenInstanceError):
            a["fixture"].name = "changed"
        with self.assertRaises(TypeError):
            a["fixture"].aliases[0] = "changed"
        with self.assertRaises(ValueError):
            self.profiles.get_publisher_profile("Fixture Press")

    def test_lookup_after_load_has_no_file_dependency(self):
        catalog = self.load()
        with patch.object(Path, "open", side_effect=AssertionError("lookup must not reread")):
            self.assertEqual(self.profiles.get_publisher_profile("Fixture Press", profiles=catalog).name, "Fixture Press")
            self.assertIsNotNone(self.profiles.infer_publisher_profile(DOI, profiles=catalog))
            self.assertIsNotNone(self.profiles.infer_publisher_profile_from_url("https://journals.fixture.example/", profiles=catalog))

    def test_success_marker_fallback_preserves_real_builtin_hosts_only(self):
        p = self.profiles
        self.assertIs(p.infer_publisher_profile_from_url("https://www.elsevier.com/physical-sciences"), p.ELSEVIER_PROFILE)
        for builtin in p.PUBLISHER_PROFILES.values():
            for marker in builtin.success_url_markers:
                self.assertIs(p.infer_publisher_profile_from_url("https://" + marker.rstrip("/") + "/fixture"), builtin)

    def test_url_host_spoofing_never_selects_profile(self):
        catalog = self.load()
        for host_path in ("journals.fixture.example/doi/" + DOI, "pubs.acs.org/doi/10.1021/fixture", "elsevier.com/"):
            for url in ("https://evil.example/?next=https://" + host_path,
                        "https://evil.example/" + host_path,
                        "https://evil.example/#https://" + host_path,
                        "https://" + host_path.split("/", 1)[0] + ".evil.example/doi/x",
                        "https://" + host_path.split("/", 1)[0] + "@evil.example/doi/x"):
                with self.subTest(url=url):
                    self.assertIsNone(self.profiles.infer_publisher_profile_from_url(url, profiles=catalog))
        for url in ("javascript://pubs.acs.org/doi/x", "https://[bad-ip/", "not a URL"):
            self.assertIsNone(self.profiles.infer_publisher_profile_from_url(url, profiles=catalog))

    def test_doi_matching_requires_registrant_boundary(self):
        catalog = self.load()
        for doi in ("10.999910/not-this-registrant", "10.10210/not-acs", "https://evil.example/10.99991/a", "prefix10.99991/a"):
            self.assertIsNone(self.profiles.infer_publisher_profile(doi, profiles=catalog))
        self.assertIs(self.profiles.infer_publisher_profile("10.1021/fixture"), self.profiles.ACS_PROFILE)

    def test_explicit_missing_empty_or_invalid_file_never_falls_back(self):
        for filename in (None, "", 42, [], str(self.file), str(self.file.parent)):
            with self.subTest(filename=filename), self.assertRaises(self.error):
                self.extension.load_publisher_profiles({"publisher_profiles_file": filename})
        for contents in (b"{", b"[]", b"null", b"\xff", b'{"schema_version":NaN,"profiles":{}}',
                         b" " * (self.extension.MAX_FILE_BYTES + 1)):
            self.file.write_bytes(contents)
            with self.assertRaises(self.error):
                self.extension.load_publisher_profiles({"publisher_profiles_file": str(self.file)})

    def test_json_schema_and_unknown_fields_are_strict(self):
        for document in ({}, {"schema_version": True, "profiles": {}}, {"schema_version": 2, "profiles": {}},
                         {"schema_version": 1, "profiles": []}, {"schema_version": 1, "profiles": {}, "config": {}},
                         {"schema_version": 1, "profiles": {"Bad Key": profile()}},
                         {"schema_version": 1, "profiles": {"fixture": None}}):
            with self.subTest(document=document), self.assertRaises(self.error):
                self.load(document)
        for field in self.extension._REQUIRED:
            value = copy.deepcopy(self.document)
            del value["profiles"]["fixture"][field]
            with self.subTest(missing=field), self.assertRaises(self.error):
                self.load(value)
        for field in ("cookie", "school", "institution_result_selectors", "python_module", "api_key", "typo"):
            self.reject_profile(**{field: "synthetic-secret"})

    def test_auth_title_markers_is_optional_and_ignored(self):
        # No code reads it (review 2026-11-02); files with it still load.
        value = copy.deepcopy(self.document)
        del value["profiles"]["fixture"]["auth_title_markers"]
        self.assertEqual(self.load(value)["fixture"].auth_title_markers, ())
        self.assertEqual(self.load()["fixture"].auth_title_markers, ("Institutional Login",))
        builtin = importlib.import_module(PACKAGE + ".publishers.loader")
        raw = {k: v for k, v in profile().items() if k != "auth_title_markers"}
        self.assertEqual(builtin.profile_from_mapping(raw, "fixture.json").auth_title_markers, ())
        self.assertNotIn("auth_title_markers", builtin.PROFILE_REQUIRED)

    def test_driver_is_no_longer_a_profile_field(self):
        # The publisher driver is the only one; the old field is unknown now.
        for value in ("publisher", "carsi"):
            with self.subTest(driver=value):
                self.reject_profile(driver=value)

    def test_duplicate_json_keys_rejected_at_every_level(self):
        raw_profile = json.dumps(profile())
        for contents in ('{"schema_version":1,"schema_version":1,"profiles":{}}',
                         '{"schema_version":1,"profiles":{"fixture":' + raw_profile + ',"fixture":' + raw_profile + '}}',
                         '{"schema_version":1,"profiles":{"fixture":' + raw_profile[:-1] + ',"name":"Replacement"}}}'):
            self.file.write_text(contents)
            with self.assertRaises(self.error):
                self.extension.load_publisher_profiles({"publisher_profiles_file": self.file})

    def test_limits_and_empty_extension_map(self):
        self.assertEqual(self.load({"schema_version": 1, "profiles": {}}), self.profiles.PUBLISHER_PROFILES)
        self.reject_profile(name="x" * 2049)
        self.reject_profile(aliases=[f"alias-{index}" for index in range(65)])
        with self.assertRaises(self.error):
            self.load({"schema_version": 1, "profiles": {f"fixture-{index}": {} for index in range(129)}})

    def test_errors_do_not_echo_file_contents_or_path(self):
        secret = "synthetic-secret-do-not-echo"
        path = self.file.with_name(secret)
        path.write_text('{"profiles":' + secret)
        try:
            self.extension.load_publisher_profiles({"publisher_profiles_file": path})
        except self.error as error:
            self.assertNotIn(secret, str(error))
            self.assertNotIn(secret, "".join(traceback.format_exception(error)))
        else:
            self.fail("invalid explicit file accepted")

    def test_builtin_key_display_alias_prefix_and_domain_conflicts_rejected(self):
        value = copy.deepcopy(self.document)
        value["profiles"] = {"acs": profile()}
        with self.assertRaises(self.error):
            self.load(value)
        for fields in ({"name": "ACS"}, {"name": "Springer Nature"}, {"aliases": ["NaTuRe"]},
                       {"doi_prefixes": ["10.1021"]}, {"aliases": ["other", "OTHER"]},
                       {"doi_prefixes": ["10.99991", "10.99991"]}):
            self.reject_profile(**fields)
        # Marker-only elsevier.com is also protected from extension shadowing.
        for domain in ("pubs.acs.org", "www.elsevier.com", "elsevier.com", "acs.org"):
            value = {"schema_version": 1, "profiles": {"fixture": profile(domain=domain)}}
            with self.assertRaises(self.error):
                self.load(value)

    def test_cross_extension_conflicts_and_atomic_failure(self):
        baseline = dict(self.profiles.PUBLISHER_PROFILES)
        for fields in ({"aliases": ["Fixture Press"]}, {"name": "Fixture Press"},
                       {"doi_prefixes": ["10.99991"]}):
            other = profile("Other Press", "other.example", "10.99992")
            other["aliases"] = ["other-press"]
            other.update(fields)
            doc = {"schema_version": 1, "profiles": {"fixture": profile(), "other": other}}
            with self.subTest(fields=fields), self.assertRaises(self.error):
                self.load(doc)
            self.assertEqual(self.profiles.PUBLISHER_PROFILES, baseline)
        other = profile("Other Press", "archive.journals.fixture.example", "10.99992")
        other["aliases"] = ["other-press"]
        with self.assertRaises(self.error):
            self.load({"schema_version": 1, "profiles": {"fixture": profile(), "other": other}})

    def test_domains_and_identifier_lists_reject_malformed_values(self):
        for domain in ("https://journals.fixture.example", "fixture.example/path", "*.fixture.example",
                       "localhost", "127.0.0.1", "[::1]", "fixture.example:443", "evil@fixture.example",
                       "-bad.example", "fixture..example", "fixture.example.", "fixture_example.com"):
            self.reject_profile(base_domains=[domain])
        for fields in ({"base_domains": []}, {"doi_prefixes": []}, {"aliases": "fixture"},
                       {"doi_prefixes": ["10.99991/journal"]}, {"doi_prefixes": ["10.12"]},
                       {"sample_dois": ["10.1021/not-fixture"]}, {"name": "\nFixture"},
                       {"sso_text_markers": [None]}, {"base_domains": ["journals.fixture.example", "JOURNALS.FIXTURE.EXAMPLE"]}):
            self.reject_profile(**fields)

    def test_url_templates_reject_bad_authorities_schemes_and_placeholders(self):
        for template in ("http://journals.fixture.example/{doi}", "file:///tmp/{doi}",
                         "https://evil.example/{doi}", "https://journals.fixture.example.evil.example/{doi}",
                         "https://u:p@journals.fixture.example/{doi}", "https://journals.fixture.example:8443/{doi}",
                         "https://{doi}.journals.fixture.example/pdf", "https://journals.fixture.example/{doi.__class__}",
                         "https://journals.fixture.example/{doi[0]}", "https://journals.fixture.example/{doi!r}",
                         "https://journals.fixture.example/{doi:100}", "https://journals.fixture.example/{unknown}",
                         "https://journals.fixture.example/{doi}?access_token=synthetic-secret",
                         "https://journals.fixture.example/{doi}/{{literal}}",
                         "https://journals.fixture.example/{doi", "https://journals.fixture.example/static.pdf",
                         "https://journals.fixture.example/{doi}#secret", "//journals.fixture.example/{doi}"):
            with self.subTest(template=template):
                self.reject_profile(pdf_url_templates=[template])
        self.reject_profile(article_url_template="https://journals.fixture.example/{doi_quoted}")
        self.reject_profile(success_url_markers=["evil.example/article/"])
        self.reject_profile(success_url_markers=["journals.fixture.example/?redirect=evil"])

    def test_source_paths_reject_cross_host_or_executable_templates(self):
        base = {"domain": "journals.fixture.example", "path_prefix": "/article/", "path_template": "/pdf/{doi_quoted}"}
        for fields in ({"domain": "evil.example"}, {"path_prefix": "//evil"},
                       {"path_template": "https://evil.example/{doi}"}, {"path_template": "//evil.example/{doi}"},
                       {"path_template": "/pdf/{source_path.__class__}"}, {"path_template": "/pdf/{doi}?token=secret"},
                       {"extra": "x"}):
            self.reject_profile(pdf_source_path_templates=[{**base, **fields}])
        self.reject_profile(pdf_source_path_templates=[base, base])

    def test_examples_load_as_data_without_enabling_a_browser(self):
        path = ROOT / "tests" / "fixtures" / "publisher-profiles.example.json"
        catalog = self.extension.load_publisher_profiles({"publisher_profiles_file": path})
        self.assertIn("cambridge", catalog)
        self.assertIsNotNone(self.profiles.infer_publisher_profile("10.1017/fixture", profiles=catalog))
        self.assertNotIn(PACKAGE + ".engine.batch", sys.modules)
        self.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""builtin/*.json is the single source of truth for tier-1 profiles."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from paper_search_school.publishers import profiles
from paper_search_school.publishers.loader import (
    BUILTIN_DIR, SCHEMA_PATH, BuiltinProfileError, load_builtin_profiles,
)

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _check_type(value, spec: dict, where: str) -> list[str]:
    errors: list[str] = []
    if "const" in spec and value != spec["const"]:
        errors.append(f"{where}: expected const {spec['const']!r}")
    expected = spec.get("type")
    if expected == "string" and not isinstance(value, str):
        errors.append(f"{where}: expected string")
    elif expected == "array":
        if not isinstance(value, list):
            errors.append(f"{where}: expected array")
        else:
            items = spec.get("items")
            if items:
                for i, item in enumerate(value):
                    errors += _check_type(item, items, f"{where}[{i}]")
    elif expected == "object":
        if not isinstance(value, dict):
            return errors + [f"{where}: expected object"]
        props = spec.get("properties", {})
        for req in spec.get("required", []):
            if req not in value:
                errors.append(f"{where}: missing {req}")
        if spec.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{where}: unexpected field {key}")
        for key, sub in props.items():
            if key in value:
                errors += _check_type(value[key], sub, f"{where}.{key}")
    return errors


class BuiltinProfileTests(unittest.TestCase):
    def test_every_builtin_file_validates_against_schema(self):
        files = sorted(BUILTIN_DIR.glob("*.json"))
        self.assertGreaterEqual(len(files), 22)
        for path in files:
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(_check_type(document, SCHEMA, path.name), [])
            self.assertRegex(path.stem, r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

    def test_registry_is_loaded_from_json(self):
        loaded = load_builtin_profiles()
        self.assertEqual(set(loaded), {p.stem for p in BUILTIN_DIR.glob("*.json")})
        self.assertEqual(profiles.PUBLISHER_PROFILES, loaded)
        self.assertIs(profiles.ELSEVIER_PROFILE, profiles.PUBLISHER_PROFILES["elsevier"])
        self.assertEqual(profiles.get_publisher_profile("sciencedirect").name, "Elsevier")
        self.assertEqual(profiles.infer_publisher_profile("10.1002/anie.2024").name, "Wiley")
        self.assertEqual(
            profiles.WILEY_PROFILE.pdf_urls("10.1002/x")[0],
            "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/x",
        )

    def test_no_python_profile_literals_remain(self):
        source = Path(profiles.__file__).read_text(encoding="utf-8")
        self.assertNotIn("PublisherProfile(\n", source)
        self.assertNotIn("name=\"", source)

    def test_list_publishers_reports_the_profiles_and_their_platforms(self):
        from paper_search_school.server import school_list_publishers

        listed = json.loads(school_list_publishers())
        self.assertEqual(listed["profiles"], sorted(profiles.PUBLISHER_PROFILES))
        self.assertEqual(listed["platforms"], sorted({p.platform for p in profiles.PUBLISHER_PROFILES.values()}))
        self.assertIn("generic", listed["platforms"])

    def test_prefixes_and_aliases_are_unique(self):
        prefixes: dict[str, str] = {}
        names: dict[str, str] = {}
        for key, profile in profiles.PUBLISHER_PROFILES.items():
            for prefix in profile.doi_prefixes:
                self.assertRegex(prefix, r"^10\.\d{4,9}$")
                self.assertNotIn(prefix, prefixes, f"{key} shares {prefix} with {prefixes.get(prefix)}")
                prefixes[prefix] = key
            for alias in (key, profile.name, *profile.aliases):
                folded = alias.casefold()
                self.assertTrue(names.get(folded, key) == key, f"{key}: alias {alias} also used by {names.get(folded)}")
                names[folded] = key

    def test_loader_rejects_conflicts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            base = json.loads((BUILTIN_DIR / "wiley.json").read_text(encoding="utf-8"))
            (Path(tmp) / "wiley.json").write_text(json.dumps(base))
            clone = json.loads(json.dumps(base))
            clone["profile"]["name"] = "Wiley Clone"
            clone["profile"]["aliases"] = ["wiley-clone"]
            (Path(tmp) / "wiley-clone.json").write_text(json.dumps(clone))
            with self.assertRaises(BuiltinProfileError):
                load_builtin_profiles(Path(tmp))

            broken = json.loads(json.dumps(base))
            broken["profile"]["unexpected"] = 1
            (Path(tmp) / "wiley-clone.json").write_text(json.dumps(broken))
            with self.assertRaises(BuiltinProfileError):
                load_builtin_profiles(Path(tmp))


if __name__ == "__main__":
    unittest.main()

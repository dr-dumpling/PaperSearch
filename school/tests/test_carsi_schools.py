"""The CARSI member list: parsing, finding the user's school, and the cached copy. Offline."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_search_school import carsi_schools
from paper_search_school.carsi_schools import choose_school, find_schools, load_school_list, parse_school_list

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "carsi_school_list.js"
EXAMPLE = "https://idp.example.edu.cn/idp/shibboleth"


class ParseTests(unittest.TestCase):
    def test_every_group_is_read_with_names_and_entity_ids_decoded(self):
        schools = parse_school_list(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual([s.name for s in schools], ["示例大学", "示例师范大学", "样本学院"])
        first = schools[0]
        self.assertEqual((first.entity_id, first.name_en, first.domain, first.pinyin),
                         (EXAMPLE, "Example University", "example.edu.cn", "shi li da xue"))
        self.assertEqual(first.summary(), {"name": "示例大学", "name_en": "Example University",
                                           "domain": "example.edu.cn", "entity_id": EXAMPLE})

    def test_a_changed_format_is_an_error_not_an_empty_list(self):
        for text in ("", "var IdPList = new Array();", "<html>maintenance</html>"):
            with self.assertRaises(ValueError):
                parse_school_list(text)


class ChooseTests(unittest.TestCase):
    schools = parse_school_list(FIXTURE.read_text(encoding="utf-8"))

    def chosen(self, query):
        school, candidates = choose_school(self.schools, query)
        return (school.name if school else None), [s.name for s in candidates]

    def test_names_pinyin_domain_and_entity_id_find_one_school(self):
        for query in ("示例大学", "Example University", " example  UNIVERSITY ", "shilidaxue", "shi li da xue",
                      "example.edu.cn", "www.example.edu.cn", "example", EXAMPLE):
            self.assertEqual(self.chosen(query), ("示例大学", []), query)

    def test_an_exact_match_wins_over_schools_that_contain_it(self):
        exact, partial = find_schools(self.schools, "example")  # the domain example.edu.cn
        self.assertEqual([s.name for s in exact], ["示例大学"])
        self.assertEqual([s.name for s in partial], ["示例师范大学"])
        self.assertEqual(self.chosen("example"), ("示例大学", []))

    def test_a_part_of_one_name_is_enough_but_several_are_left_to_the_user(self):
        self.assertEqual(self.chosen("Normal"), ("示例师范大学", []))
        self.assertEqual(self.chosen("Sample"), ("样本学院", []))
        self.assertEqual(self.chosen("示例"), (None, ["示例大学", "示例师范大学"]))

    def test_nothing_matches(self):
        for query in ("", "   ", "-", "Nowhere Institute", "https://idp.other.edu.cn/idp/shibboleth"):
            self.assertEqual(self.chosen(query), (None, []), query)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="school-list-"))
        self.cache = self.dir / carsi_schools.CACHE_FILE

    def test_a_fresh_copy_is_used_without_the_network(self):
        self.cache.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        with patch("paper_search_school.network.fetch", side_effect=AssertionError("network used")):
            self.assertEqual(len(load_school_list({}, self.dir)), 3)

    def test_an_old_copy_is_fetched_again_and_replaced(self):
        self.cache.write_text("stale", encoding="utf-8")
        old = time.time() - carsi_schools.CACHE_MAX_AGE_SEC - 60
        os.utime(self.cache, (old, old))
        response = SimpleNamespace(text=FIXTURE.read_text(encoding="utf-8"), raise_for_status=Mock())
        with patch("paper_search_school.network.fetch", return_value=response) as fetch:
            self.assertEqual(len(load_school_list({}, self.dir)), 3)
        self.assertEqual(fetch.call_args.args[0], carsi_schools.SCHOOL_LIST_URL)
        self.assertEqual(self.cache.read_text(encoding="utf-8"), response.text)

    def test_an_unreadable_download_is_not_cached(self):
        response = SimpleNamespace(text="<html>maintenance</html>", raise_for_status=Mock())
        with patch("paper_search_school.network.fetch", return_value=response):
            with self.assertRaises(ValueError):
                load_school_list({}, self.dir)
        self.assertFalse(self.cache.exists())


if __name__ == "__main__":
    unittest.main()

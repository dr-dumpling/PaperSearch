"""DOI normalisation: what users paste becomes a plain DOI."""
import unittest

from paper_search_school.identifiers import normalize_doi


class NormalizeDoiTests(unittest.TestCase):
    def test_full_width_doi_with_chinese_punctuation(self):
        self.assertEqual(normalize_doi("１０．３９６９／ｊ．ｉｓｓｎ．１０００－１２３４。"), "10.3969/j.issn.1000-1234")

    def test_doi_url_and_label(self):
        self.assertEqual(normalize_doi("https://doi.org/10.1000%2Fabc"), "10.1000/abc")
        self.assertEqual(normalize_doi("doi：10.1000/abc"), "10.1000/abc")


if __name__ == "__main__":
    unittest.main()

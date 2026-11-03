"""Main-text acceptance: the front matter names this article (DOI or exact title)."""
import unittest
from unittest.mock import Mock

import pymupdf

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.engine.pdf_guard import classify
from paper_search_carsi.publishers.profiles import get_publisher_profile

DOI = "10.1002/art.70156"
TITLE = "Identifying Systemic Lupus Erythematosus From Serum Proteomic Profiles"
URL = "https://acrjournals.onlinelibrary.wiley.com/doi/pdfdirect/" + DOI


def pdf(*pages):
    with pymupdf.open() as doc:
        for lines in pages:
            page = doc.new_page()
            for i, line in enumerate(lines):
                page.insert_text((40, 40 + 14 * i), line, fontsize=9)
        return doc.tobytes() + b"\n" + b"%" * 6000


class ClassifyTests(unittest.TestCase):
    def test_doi_or_title_in_the_front_matter_is_a_match(self):
        self.assertEqual(classify(pdf(["Arthritis & Rheumatology", "DOI 10.1002/art.70156", "Body"]), DOI), "match")
        self.assertEqual(classify(pdf(["DOI10.1002/art.", "70156"]), DOI), "match")  # glued and wrapped
        self.assertEqual(classify(pdf(["Cover page", TITLE, "View the article online"]), DOI, TITLE), "match")
        self.assertEqual(classify(pdf(["Cover"], ["https://doi.org/10.1002/art.70156"]), DOI), "match")  # page 2

    def test_a_supplement_with_the_article_doi_is_not_the_main_text(self):
        self.assertEqual(classify(pdf(["Supporting Information", "DOI 10.1002/art.70156"]), DOI), "unknown")

    def test_another_articles_doi_or_a_citation_only_in_references(self):
        self.assertEqual(classify(pdf(["Optics Letters", "https://doi.org/10.1364/OL.527743", "Body"]), DOI), "other")
        refs = pdf(["Another article", "DOI: 10.9999/other.1", "References", "1. Hocaoglu M. doi:10.1002/art.70156"])
        self.assertEqual(classify(refs, DOI, TITLE), "other")

    def test_nothing_printed_is_unknown(self):
        self.assertEqual(classify(pdf(["Content Platform User Guide", "How to sign in"]), DOI, TITLE), "unknown")
        self.assertEqual(classify(b"%PDF-1.7 broken", DOI), "invalid")


class EngineAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=get_publisher_profile("wiley"))
        self.d._capture_doi, self.d._expected_title, self.d._fallback_pdf = DOI, TITLE, None

    def test_match_is_accepted_other_refused_unknown_kept_as_fallback(self):
        self.assertTrue(self.d._accept_pdf_body(pdf([TITLE, "Body"]), URL))
        self.assertFalse(self.d._accept_pdf_body(pdf(["DOI: 10.9999/other.1"]), URL))
        self.assertIsNone(self.d._fallback_pdf)
        unknown = pdf(["No identifying text"])
        self.assertFalse(self.d._accept_pdf_body(unknown, URL))
        self.assertEqual(self.d._fallback_pdf, (unknown, URL))
        self.d._fallback_pdf = None
        self.assertFalse(self.d._accept_pdf_body(b"%PDF-1.7" + b"x" * 8000, URL))  # unreadable: refused
        self.assertIsNone(self.d._fallback_pdf)

    def test_supplement_urls_are_never_the_main_text(self):
        supplement = "https://acrjournals.onlinelibrary.wiley.com/action/downloadSupplement?doi=10.1002%2Fart.70156&file=art70156-sup-0001.pdf"
        self.assertFalse(self.d._accept_pdf_body(pdf(["DOI 10.1002/art.70156"]), supplement))

    def test_capture_uses_the_fallback_only_when_nothing_better_arrived(self):
        page = Mock(); page.evaluate.return_value = TITLE
        unknown = pdf(["No identifying text"])
        def channels(page, doi, result):
            self.d._accept_pdf_body(unknown, URL)
            return None, "", None
        self.d._capture_pdf_channels = channels
        result = DownloadResult(doi=DOI, status="failed")
        self.assertEqual(self.d._capture_pdf(page, DOI, result), (unknown, URL, None))
        self.assertIn("pdf_saved_unconfirmed", [e["state"] for e in result.events])
        blocked = lambda page, doi, result: (self.d._accept_pdf_body(unknown, URL), (None, "", "ip_blocked"))[1]
        self.d._capture_pdf_channels = blocked
        self.assertEqual(self.d._capture_pdf(page, DOI, DownloadResult(doi=DOI, status="failed")), (None, "", "ip_blocked"))


if __name__ == "__main__":
    unittest.main()

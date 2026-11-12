"""An article whose footnote wraps "Supporting / Information" is accepted as the main text."""
import unittest

import pymupdf

from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile


def pdf(lines_per_page):
    with pymupdf.open() as doc:
        for lines in lines_per_page:
            page = doc.new_page()
            for i, line in enumerate(lines):
                page.insert_text((40, 40 + 14 * i), line, fontsize=9)
        return doc.tobytes()


ARTICLE = ["Arthritis & Rheumatology", "Vol. 78, No. 11, November 2026, pp 2280-2291", "DOI 10.1002/art.70156",
           "Identifying Systemic Lupus Erythematosus From Serum", "Proteomic Profiles", "Mehmet Example, MD",
           "Objective. Proteome-wide risk models for lupus remain underexplored."] + [f"Body line {i}" for i in range(30)] + [
           "Additional supplementary information cited in this article can be found", "online", "in", "the",
           "Supporting", "Information", "section", "Author disclosures and graphical abstract are available at https://"]
URL = "https://acrjournals.onlinelibrary.wiley.com/doi/pdfdirect/10.1002/art.70156"


class FootnoteHeadingTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=get_publisher_profile("wiley"))
        self.d._capture_doi = "10.1002/art.70156"

    def body(self, pages):
        return pdf(pages) + b"\n" + b"%" * 6000  # above the minimum size

    def test_wrapped_footnote_is_not_a_supplement_heading(self):
        self.assertTrue(self.d._accept_pdf_body(self.body([ARTICLE]), URL))


if __name__ == "__main__":
    unittest.main()

"""Is a captured PDF this article? The same rule and cases as PaperSearch's PdfIdentity."""
import json
import unittest
from pathlib import Path

import pymupdf

from paper_search_school.engine.pdf_guard import assess, classify, names_other_article, normalize_doi_text
from paper_search_school.engine.router import is_supplementary_url
from paper_search_school.publishers.profiles import infer_publisher_profile_from_url

CASES = json.loads((Path(__file__).parent / "fixtures" / "pdf_identity_cases.json").read_text(encoding="utf-8"))


def pdf(*pages):
    with pymupdf.open() as doc:
        for lines in pages:
            page = doc.new_page()
            for i, line in enumerate(lines):
                page.insert_text((40, 40 + 14 * i), line, fontsize=9)
        return doc.tobytes()


class SharedCasesTests(unittest.TestCase):
    def test_the_frontend_cases(self):
        for case in CASES:
            with self.subTest(case["group"] + ": " + case["name"]):
                self.assertEqual(assess(case["text"], case["doi"], case["title"], case.get("source", "")), case["expected"])


class PdfGuardTests(unittest.TestCase):
    def test_another_articles_pdf_is_refused(self):
        # Optica: a stale viewer handed over the previous paper's PDF.
        body = pdf(["Optics Letters 3926", "https://doi.org/10.1364/OL.527743", "Optimization of stimulated Raman"])
        self.assertEqual(names_other_article(body, "10.1364/josaa.543090"), ["10.1364/ol.527743"])
        self.assertEqual(names_other_article(body, "10.1364/OL.527743"), [])
        self.assertEqual(classify(body, "10.1364/josaa.543090"), "other")

    def test_invisible_characters_and_typographic_dashes_do_not_split_a_doi(self):
        printed = "10.1245/s10434‐026‐20785­‐z"
        self.assertEqual(normalize_doi_text(printed), "10.1245/s10434-026-20785-z")
        self.assertEqual(normalize_doi_text("10.1000/a​b﻿"), "10.1000/ab")
        self.assertEqual(normalize_doi_text("10.1245/x\x08y"), "10.1245/x y")

    def test_classify_reads_the_first_pages(self):
        doi, title = "10.1002/art.70156", "Identifying Systemic Lupus Erythematosus From Serum Proteomic Profiles"
        self.assertEqual(classify(pdf(["Arthritis & Rheumatology", "DOI 10.1002/art.70156", "Body"]), doi), "match")
        self.assertEqual(classify(pdf(["Cover"], ["https://doi.org/10.1002/art.70156"]), doi), "match")  # page 2
        self.assertEqual(classify(pdf(["Cover"], ["Page 2"], ["Page 3"], ["https://doi.org/10.1002/art.70156"]), doi), "unknown")
        self.assertEqual(classify(pdf(["Supporting Information", "DOI 10.1002/art.70156"]), doi), "unknown")
        self.assertEqual(classify(pdf(["Content Platform User Guide", "How to sign in"]), doi, title), "unknown")
        self.assertEqual(classify(b"%PDF-1.7 broken", doi), "invalid")
        self.assertEqual(names_other_article(b"not a pdf", doi), [])

    def test_cms_uploads_are_never_article_pdfs(self):
        profile = infer_publisher_profile_from_url("https://pubs.aip.org/aip/jcp/article/162/16/164505")
        self.assertTrue(is_supplementary_url(profile, "https://publishing.aip.org/wp-content/uploads/Content-Platform-User-Guide.pdf"))
        self.assertFalse(is_supplementary_url(profile, "https://pubs.aip.org/aip/jcp/article-pdf/162/16/164505/1.pdf"))


if __name__ == "__main__":
    unittest.main()

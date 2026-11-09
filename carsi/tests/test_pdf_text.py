"""Reading PDFs through pdf_text (pypdfium2): pages, text, broken files, whole transfers."""
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pymupdf  # builds the sample PDFs only (a dev dependency)

from paper_search_carsi import pdf_text


def sample(*pages: str) -> bytes:
    document = pymupdf.open()
    for words in pages:
        document.new_page().insert_text((72, 72), words)
    return document.tobytes()


class PdfTextTests(unittest.TestCase):
    def test_pages_and_text_from_bytes_or_a_file(self):
        body = sample("doi:10.1000/one first", "second page", "third page", "fourth page")
        self.assertEqual(pdf_text.page_count(body), 4)
        self.assertEqual(pdf_text.text(body, 2), "doi:10.1000/one first\nsecond page")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.pdf"
            path.write_bytes(body)
            self.assertEqual(len(pdf_text.page_texts(path)), 4)

    def test_line_ends_and_hyphens_read_as_other_readers_give_them(self):
        self.assertEqual(pdf_text._clean("annurev-publhealth\x02\r\n060722\r1"), "annurev-publhealth-\n060722\n1")

    def test_what_cannot_be_read(self):
        for broken in (b"", b"%PDF-1.7 nothing else", b"<html>not a pdf</html>"):
            with self.subTest(body=broken[:12]):
                with self.assertRaises(pdf_text.PdfError):
                    pdf_text.text(broken)

    def test_a_whole_transfer_and_a_cut_or_damaged_one(self):
        body = sample("page")
        self.assertTrue(pdf_text.complete(body))
        self.assertTrue(pdf_text.complete(body + b"\n\n"))
        self.assertFalse(pdf_text.complete(body[: len(body) // 2]))
        start = body.rindex(b"startxref")
        offset = int(body[start:].split()[1])
        wrong = body[:start] + b"startxref\n" + str(offset + 7).encode() + b"\n%%EOF\n"
        self.assertFalse(pdf_text.complete(wrong))

    def test_many_threads_at_once(self):
        # PDFium allows one call at a time; the lock keeps parallel downloads safe.
        body = sample("doi:10.1000/x", "two")
        errors = []

        def read():
            try:
                for _ in range(20):
                    assert pdf_text.text(body, 1) == "doi:10.1000/x"
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=read) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()

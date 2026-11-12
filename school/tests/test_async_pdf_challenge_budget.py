"""Human verification during the Elsevier PDF navigation must not use up the PDF step."""
import unittest
from unittest.mock import Mock, patch

from paper_search_school.engine import batch
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import ELSEVIER_PROFILE

PDF_URL = "https://www.sciencedirect.com/science/article/pii/S0016508524002919/pdfft"
BODY = b"%PDF-1.7\n" + b"x" * 20000


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class AsyncPdfChallengeBudgetTests(unittest.TestCase):
    def test_pdf_is_read_after_a_verification_longer_than_the_pdf_timeout(self):
        d = PublisherBatchDownloader({}, profile=ELSEVIER_PROFILE, pdf_timeout_sec=60)
        clock = Clock()
        page = Mock(); page.url = PDF_URL
        page.wait_for_timeout.side_effect = lambda ms: clock.sleep(ms / 1000)
        challenge = iter([True])
        seen = {}

        def verification(page_, result_, deadline):
            seen["budget"] = deadline - clock.now
            clock.sleep(150)  # the user needs two and a half minutes
            return True

        with patch.object(batch.time, "time", clock.time), patch.object(batch.time, "sleep", clock.sleep), \
             patch.object(d, "_raise_on_publisher_content_error"), \
             patch.object(d, "_is_challenge_page", side_effect=lambda p: next(challenge, False)), \
             patch.object(d, "_wait_for_challenge_with_deadline", side_effect=verification), \
             patch.object(d, "_capture_loaded_pdf_viewer", return_value=BODY), \
             patch.object(d, "_page_state_pdf_urls", return_value=[]):
            body, url = d._capture_pdf_via_async_navigation(page, PDF_URL, DownloadResult(doi="10.1053/x", status="failed"))
        self.assertGreaterEqual(seen["budget"], d.PAGE_WAIT_SEC)
        self.assertEqual((body, url), (BODY, PDF_URL))


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from paper_search_carsi.engine.batch import PublisherBatchDownloader, PublisherContentError, PublisherPlatformUnsupported, DownloadResult, PaperRecord
from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE, WILEY_PROFILE

TEXT = 'There was a problem providing the content you requested\nPlease contact our support team\nCPE00001'


class PublisherContentErrorTests(unittest.TestCase):
    def make(self, url='https://www.sciencedirect.com/science/article/pii/S0002916525005908/pdfft', text=TEXT):
        downloader = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
        downloader._body_text = Mock(return_value=text)
        page = Mock(url=url)
        return downloader, page

    def test_detects_error_page_on_expected_publisher_only(self):
        downloader, page = self.make()
        with self.assertRaises(PublisherContentError): downloader._raise_on_publisher_content_error(page)
        for url in ('https://sciencedirect.com.example.test/article', 'https://example.test/'):
            page.url = url; downloader._raise_on_publisher_content_error(page)
        page.url = 'https://www.sciencedirect.com/article'
        downloader.profile = WILEY_PROFILE
        downloader._raise_on_publisher_content_error(page)

    def test_sciencedirect_page_not_found_stops_at_once(self):
        # EMC titles (Annales d'Urologie): doi.org leads to a ScienceDirect PII without a page.
        downloader, page = self.make(url='https://www.sciencedirect.com/science/article/pii/S1283087926501276', text='')
        downloader._title = Mock(return_value='Page not found | ScienceDirect')
        with self.assertRaises(PublisherContentError) as raised:
            downloader._raise_on_publisher_content_error(page)
        self.assertEqual(str(raised.exception), 'Page not found | ScienceDirect')
        downloader._title.return_value = 'Page not found: a study of lost pages - ScienceDirect'
        downloader._raise_on_publisher_content_error(page)  # an article's own title
        downloader._title.return_value = 'Page not found | ScienceDirect'
        page.url = 'https://www.cell.com/cell/fulltext/S0092-8674(24)00001-1'
        downloader._raise_on_publisher_content_error(page)  # another host: no opinion

    def test_article_mentioning_error_code_is_not_rejected(self):
        downloader, page = self.make(text='Full text access. A study of CPE00001')
        downloader._raise_on_publisher_content_error(page)

    def test_async_capture_stops_before_viewer_or_http_retries(self):
        downloader, page = self.make()
        downloader._capture_loaded_pdf_viewer = Mock()
        downloader._fetch_pdf_url_with_browser_state = Mock()
        result = DownloadResult(doi='10.1000/test', status='failed')
        with self.assertRaises(PublisherContentError):
            downloader._capture_pdf_via_async_navigation(page, page.url, result)
        downloader._capture_loaded_pdf_viewer.assert_not_called()
        downloader._fetch_pdf_url_with_browser_state.assert_not_called()

    def test_fetch_returns_explicit_failure_without_relogin(self):
        downloader, page = self.make()
        # fetch_one receives a page rather than a context.
        del page.new_page
        downloader._ensure_login = Mock(return_value=True)
        downloader._looks_logged_out = Mock(return_value=False)
        downloader._hold_after_login = Mock()
        downloader._hold_after_run = Mock()
        downloader._title = Mock(return_value='ScienceDirect')
        downloader._capture_pdf = Mock(side_effect=PublisherContentError('publisher_content_error'))
        downloader._complete_login_from_current_page = Mock()
        downloader._write_diagnostic = Mock()
        with tempfile.TemporaryDirectory() as temp, patch('paper_search_carsi.engine.batch.time.sleep'):
            result = downloader.fetch_one(page, PaperRecord(doi='10.1000/test'), Path(temp))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'publisher_content_error')
        downloader._complete_login_from_current_page.assert_not_called()
        downloader._capture_pdf.assert_called_once()
        downloader._write_diagnostic.assert_called_once()

    def test_clinicalkey_is_an_unsupported_platform(self):
        # EMC titles: doi.org -> linkinghub -> clinicalkey.fr, never ScienceDirect.
        downloader, page = self.make(url='https://www.clinicalkey.fr/#!/content/playContent/51-s2.0-S1283087926501276', text='')
        with self.assertRaises(PublisherPlatformUnsupported) as raised:
            downloader._raise_on_publisher_content_error(page)
        self.assertEqual(str(raised.exception), 'ClinicalKey')
        for url in ('https://www.clinicalkey.com/#!/content/x', 'https://www.clinicalkey.com.au/#!/content/x'):
            page.url = url
            self.assertEqual(downloader.adapter.unsupported_platform(page), 'ClinicalKey')
        for url in ('https://clinicalkey.fr.example.test/', 'https://www.sciencedirect.com/science/article/pii/S1283087926501276'):
            page.url = url
            self.assertIsNone(downloader.adapter.unsupported_platform(page))
        downloader.profile = WILEY_PROFILE
        page.url = 'https://www.clinicalkey.fr/'
        self.assertIsNone(downloader.adapter.unsupported_platform(page))

    def test_unsupported_platform_ends_the_item_with_its_own_reason(self):
        downloader, page = self.make()
        del page.new_page
        downloader._ensure_login = Mock(return_value=True)
        downloader._looks_logged_out = Mock(return_value=False)
        downloader._hold_after_login = Mock()
        downloader._hold_after_run = Mock()
        downloader._capture_pdf = Mock(side_effect=PublisherPlatformUnsupported('ClinicalKey'))
        downloader._write_diagnostic = Mock()
        with tempfile.TemporaryDirectory() as temp, patch('paper_search_carsi.engine.batch.time.sleep'):
            result = downloader.fetch_one(page, PaperRecord(doi='10.1016/s1283-0879(26)50127-6'), Path(temp))
        self.assertFalse(result.ok)
        self.assertEqual((result.reason, result.state), ('unsupported_platform', 'unsupported_platform'))
        downloader._capture_pdf.assert_called_once()


if __name__ == '__main__': unittest.main()

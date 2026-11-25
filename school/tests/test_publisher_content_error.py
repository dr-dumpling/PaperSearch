from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from paper_search_school.engine.batch import PublisherBatchDownloader, PublisherContentError, PublisherPlatformUnsupported, DownloadResult, PaperRecord
from paper_search_school.publishers.profiles import ELSEVIER_PROFILE, WILEY_PROFILE

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
        with tempfile.TemporaryDirectory() as temp, patch('paper_search_school.engine.batch.time.sleep'):
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

    def test_a_sciencedirect_article_read_only_through_clinicalkey(self):
        """The Lancet 1975 after the school login: "You have access to this article
        through ClinicalKey", full text access, no PDF of its own (2026-11-08)."""
        banner = ('Brought to you by: Fixture University\nYou have access to this article through ClinicalKey\n'
                  'Full text access\nView full text\nRecommended articles\nView PDF')
        downloader, page = self.make(url='https://www.sciencedirect.com/science/article/pii/S014067367592262X', text=banner)
        page.evaluate = Mock(return_value=None)  # no PDF control of this article itself
        self.assertEqual(downloader.adapter.unsupported_platform(page), 'ClinicalKey')
        self.assertEqual(page.evaluate.call_args.args[1:], (True,))  # looked for, not clicked
        page.evaluate = Mock(return_value={'text': 'View PDF'})
        self.assertIsNone(downloader.adapter.unsupported_platform(page))
        downloader._body_text = Mock(return_value='Full text access\nView full text')
        page.evaluate = Mock(return_value=None)
        self.assertIsNone(downloader.adapter.unsupported_platform(page))

    def test_em_consulte_is_an_unsupported_platform(self):
        """La Revue de Santé Scolaire et Universitaire (10.1016/j.revssu.2025.09.004, Windows 2026-11-23):
        doi.org -> linkinghub -> em-consulte.com, an abstract there and no school login; the PII has no
        ScienceDirect page."""
        downloader, page = self.make(url='https://www.em-consulte.com/article/1771436/alertePM', text='')
        downloader._title = Mock(return_value='Agir pour réduire les inégalités de santé en milieu d’apprentissage - EM consulte')
        with self.assertRaises(PublisherPlatformUnsupported) as raised:
            downloader._raise_on_publisher_content_error(page)
        self.assertEqual(str(raised.exception), 'EM-Consulte')
        page.url = 'https://em-consulte.com.example.test/article/1771436'
        self.assertIsNone(downloader.adapter.unsupported_platform(page))
        from paper_search_school.publishers.site import site_profile
        self.assertIsNone(site_profile('10.1234/x', 'https://www.em-consulte.com/article/1771436/alertePM'))

    def test_linkinghubs_article_locator_offering_other_platforms(self):
        """La Revue de l'Infirmière (10.1016/j.revinf.2025.10.026) and Soins Cadres (Windows 2026-11-23):
        linkinghub stayed on its "Elsevier: Article Locator", which offers the article on EM-Consulte; the
        PII's ScienceDirect page was "Page not found", taken as the publisher's error after 100 s."""
        locator = 'https://linkinghub.elsevier.com/retrieve/pii/S1293850525004142'
        em_consulte = 'http://www.em-consulte.com/retrieve/pii/S1293850525004142'
        downloader, page = self.make(url=locator, text='')
        downloader._title = Mock(return_value='Elsevier: Article Locator')
        page.evaluate = Mock(return_value=[em_consulte])
        with self.assertRaises(PublisherPlatformUnsupported) as raised:
            downloader._raise_on_publisher_content_error(page)
        self.assertEqual(str(raised.exception), 'EM-Consulte')
        page.evaluate.return_value = [em_consulte, 'https://www.clinicalkey.fr/#!/content/playContent/1-s2.0-S1293850525004142',
                                      'https://www.elsevier.com', locator]
        self.assertEqual(downloader.adapter.unsupported_platform(page), 'EM-Consulte / ClinicalKey')
        # A site with rules among the offered ones, or none offered: no opinion (the flow goes on as before).
        for offered in ([em_consulte, 'https://www.sciencedirect.com/science/article/pii/S1293850525004142'], [], None):
            with self.subTest(offered=offered):
                page.evaluate.return_value = offered
                self.assertIsNone(downloader.adapter.unsupported_platform(page))
        # linkinghub's "Redirecting" page is not the locator: the engine waits for it to move on.
        downloader._title.return_value = 'Redirecting'
        page.evaluate.return_value = [em_consulte]
        downloader._raise_on_publisher_content_error(page)

    def test_linkinghubs_article_not_available_is_the_publishers_error_page(self):
        """EMC - Podologie (10.1016/s0292-062x(25)50176-9) and Anais Brasileiros de Dermatologia (Versão em
        Português) (10.1016/j.abdp.2025.501239, Windows 2026-11-23): no site of Elsevier's has the article; the
        second ended as pdf_not_captured after a ScienceDirect PDF address and a login with no entry."""
        downloader, page = self.make(url='https://linkinghub.elsevier.com/retrieve/pii/S2666275225002000', text='')
        downloader._title = Mock(return_value='Elsevier: Article Locator Error - Article Not Available')
        page.evaluate = Mock(return_value=[])
        with self.assertRaises(PublisherContentError) as raised:
            downloader._raise_on_publisher_content_error(page)
        self.assertEqual(str(raised.exception), 'Elsevier: Article Locator Error - Article Not Available')
        self.assertIsNone(downloader.adapter.unsupported_platform(page))
        downloader._title.return_value = 'Elsevier: Article Locator Error - Article Not Available'
        page.url = 'https://www.cell.com/cell/fulltext/S0092-8674(24)00001-1'
        downloader._raise_on_publisher_content_error(page)  # another host: the journal site's own rules

    def test_an_accepted_article_without_its_full_text_yet_stops_at_once(self):
        """Optica's early posting page (2026-11-08): no full text to fetch yet."""
        from paper_search_school.engine.batch_common import ArticleNotYetPublished
        text = ('This paper has been accepted for publication. The DOI 10.1364/OL.621126 has been\nregistered for this '
                'article. Authors and readers can cite the DOI and will redirect to the\npublished article when available.')
        from types import SimpleNamespace
        downloader, page = self.make(url='https://opg.optica.org/ol/abstract.cfm?doi=10.1364/ol.621126', text=text)
        snapshot = SimpleNamespace(text=text, lines=text.splitlines(), probe={})
        with self.assertRaises(ArticleNotYetPublished):
            downloader._access_decision(page, snapshot)
        snapshot.text = 'Received 2 March 2026; accepted for publication 4 May 2026'
        snapshot.lines = [snapshot.text]
        downloader._institution_session = Mock(return_value="")
        self.assertNotEqual(downloader._access_decision(page, snapshot)[1], "not_yet_published")
        # APS's accepted paper (2026-11-15): no PDF until the version of record.
        from paper_search_school.engine import access_rules
        self.assertTrue(access_rules.not_yet_published(
            "Accepted Paper\nPhys. Rev. Research - Accepted 13 November, 2026\nIf the author has provided any supplemental "
            "materials with this article they will be available upon publication of the version of record."))
        self.assertFalse(access_rules.not_yet_published("Accepted Paper collections; the version of record"))

    def test_unsupported_platform_ends_the_item_with_its_own_reason(self):
        downloader, page = self.make()
        del page.new_page
        downloader._ensure_login = Mock(return_value=True)
        downloader._looks_logged_out = Mock(return_value=False)
        downloader._hold_after_login = Mock()
        downloader._hold_after_run = Mock()
        downloader._capture_pdf = Mock(side_effect=PublisherPlatformUnsupported('ClinicalKey'))
        downloader._write_diagnostic = Mock()
        with tempfile.TemporaryDirectory() as temp, patch('paper_search_school.engine.batch.time.sleep'):
            result = downloader.fetch_one(page, PaperRecord(doi='10.1016/s1283-0879(26)50127-6'), Path(temp))
        self.assertFalse(result.ok)
        self.assertEqual((result.reason, result.state), ('unsupported_platform', 'unsupported_platform'))
        downloader._capture_pdf.assert_called_once()


if __name__ == '__main__': unittest.main()

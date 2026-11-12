"""Thieme account links must never become article PDF candidates."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.engine.router import is_pdf_candidate_url, is_thieme_article_pdf_url
from paper_search_school.publishers.profiles import PublisherProfile

DOI = '10.1055/s-fixture-12345'
PDF = 'https://www.thieme-connect.de/products/ejournals/pdf/' + DOI + '.pdf'


def profile():
    return PublisherProfile(name='Thieme',
        article_url_template='https://www.thieme-connect.de/products/ejournals/abstract/{doi}',
        pdf_url_templates=(), success_url_markers=('thieme-connect.de/products/ejournals/',),
        auth_url_markers=('/login', '/sso/'), auth_title_markers=('Login',),
        sso_text_markers=('Shibboleth/OpenAthens',),
        base_domains=('thieme-connect.de', 'thieme-connect.com'))


class ThiemeCaptureTests(unittest.TestCase):
    def setUp(self):
        self.profile = profile()
        self.downloader = PublisherBatchDownloader({},profile=self.profile)

    def test_official_article_pdf_and_exact_doi_on_both_domains(self):
        for domain in ('thieme-connect.de','www.thieme-connect.de',
                       'thieme-connect.com','www.thieme-connect.com'):
            url = 'https://' + domain + '/products/ejournals/pdf/' + DOI + '.pdf'
            self.assertTrue(is_pdf_candidate_url(self.profile,url))
            self.assertTrue(self.downloader._article_pdf_url_matches(url,DOI))
            self.assertFalse(self.downloader._article_pdf_url_matches(url,DOI+'-other'))
        self.assertTrue(is_thieme_article_pdf_url(PDF+'   ',DOI))

    def test_login_reset_and_forged_hosts_with_pdf_return_urls_are_rejected(self):
        for url in (
            'https://profile.thieme.de/HTML/sso/THIEME/thieme_forgotten_access_data.htm?hook_url='+PDF,
            'https://www.thieme-connect.de/products/ejournals/login?return='+PDF,
            'https://www.thieme-connect.de/products/ejournals/login?return='+PDF.replace('/','%2F'),
            PDF.replace('www.thieme-connect.de','www.thieme-connect.de.evil.example'),
            PDF.replace('www.thieme-connect.de','www.thieme-connect.de@evil.example'),
            PDF.replace('https:','http:'),
            PDF.replace('/pdf/','/abstract/'),
        ):
            with self.subTest(url=url):
                self.assertFalse(is_pdf_candidate_url(self.profile,url))
                self.assertFalse(self.downloader._article_pdf_url_matches(url,DOI))

    def test_login_page_pdf_return_query_is_never_requested_as_a_file(self):
        login='https://profile.thieme.de/login?hook_url='+PDF
        page=SimpleNamespace(url=login)
        self.downloader._is_challenge_page=Mock(return_value=False)
        self.downloader._institution_pdf_entitlement_missing=Mock(return_value=False)
        self.downloader._title=Mock(return_value='Login')
        self.downloader._fetch_pdf_url_with_browser_state=Mock(side_effect=AssertionError('account URL requested'))
        self.assertEqual(self.downloader._fetch_page_state_pdf(page,doi=DOI),(None,'',None))
        self.downloader._fetch_pdf_url_with_browser_state.assert_not_called()

    def test_pdf_redirect_to_account_or_other_article_cannot_be_accepted(self):
        history=[SimpleNamespace(url=PDF,headers={})]
        for final in ('https://profile.thieme.de/login?hook_url='+PDF, PDF.replace(DOI,DOI+'-other')):
            response=SimpleNamespace(url=final,status=200,headers={},history=history,request=None)
            self.assertFalse(self.downloader._response_matches_article(response,DOI))
        response=SimpleNamespace(url=PDF,status=200,headers={},history=[],request=None)
        self.assertTrue(self.downloader._response_matches_article(response,DOI))


if __name__ == '__main__':
    unittest.main()

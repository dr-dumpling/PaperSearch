"""Whole-file capture versus viewer ranges; synthetic PDFs and local traffic."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pymupdf

from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import PublisherProfile

DOI='10.1080/fixture'
ARTICLE='https://www.tandfonline.com/doi/full/'+DOI
PDF='https://www.tandfonline.com/doi/pdf/'+DOI
PROFILE=PublisherProfile(name='Taylor & Francis',article_url_template='https://doi.org/{doi}',
    pdf_url_templates=(),success_url_markers=('tandfonline.com/doi/',),auth_url_markers=(),
    auth_title_markers=(),sso_text_markers=(),base_domains=('tandfonline.com',))


def article_pdf():
    with pymupdf.open() as doc:
        for _ in range(32):
            doc.new_page().insert_text((40,40),'Fixture article\nDOI: '+DOI+'\n'+'Methods and results\n'*50)
        return doc.tobytes()


def http_pdf(body,status=200,headers=None):
    return SimpleNamespace(status_code=status,url=PDF,content=body,text='',headers=headers or {},history=[])


class TaylorWholeFileTests(unittest.TestCase):
    def setUp(self):
        self.downloader=PublisherBatchDownloader({},profile=PROFILE)
        self.downloader._capture_doi=DOI  # set by _capture_pdf; direct helper calls need it
        self.data=article_pdf()

    def test_complete_pdf_is_accepted_but_prefix_and_fake_tail_are_rejected(self):
        self.assertTrue(self.downloader._accept_pdf_body(self.data,PDF))
        self.assertGreater(len(self.data),12000)
        prefix=self.data[:6000]
        self.assertFalse(self.downloader._accept_pdf_body(prefix,PDF))
        self.assertFalse(self.downloader._accept_pdf_body(prefix+b'\n%%EOF\n',PDF))

    def test_http_range_is_not_saved_even_if_it_contains_a_parseable_pdf(self):
        for response in (http_pdf(self.data,206),http_pdf(self.data,200,{'Content-Range':'bytes 0-5999/24000'})):
            with patch('paper_search_school.engine.batch.requests.get',return_value=response):
                self.assertEqual(self.downloader._fetch_pdf_url(PDF),(None,PDF,None))

    def test_full_http_pdf_remains_available_without_range_headers(self):
        with patch('paper_search_school.engine.batch.requests.get',return_value=http_pdf(self.data)):
            self.assertEqual(self.downloader._fetch_pdf_url(PDF),(self.data,PDF,None))


@unittest.skipUnless(os.environ.get('SCHOOL_LOCAL_BROWSER_TEST')=='1','local Chrome fixture opt-in')
class TaylorRangeBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver=sync_playwright().start()
        cls.browser=cls.driver.chromium.launch(channel='chrome',headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def capture(self,http_status):
        data=article_pdf()
        context=self.browser.new_context(service_workers='block')
        self.addCleanup(context.close)
        def respond(route):
            if route.request.url==ARTICLE:
                route.fulfill(status=200,content_type='text/html',body='<title>Fixture article</title>Full access')
            elif route.request.url==PDF:
                route.fulfill(status=206,content_type='application/pdf',body=data[:6000],
                    headers={'Content-Range':f'bytes 0-5999/{len(data)}'})
            else:
                route.abort()
        context.route('**/*',respond)
        page=context.new_page()
        page.goto(ARTICLE)
        downloader=PublisherBatchDownloader({},profile=PROFILE)
        def click(*args,**kwargs):
            page.evaluate('url=>fetch(url).then(r=>r.arrayBuffer()).then(()=>true)',PDF)
            return True
        downloader._click_pdf_entry=Mock(side_effect=click)
        downloader._pdf_candidates=Mock(return_value=[])
        result=DownloadResult(doi=DOI,status='failed')
        with patch('paper_search_school.engine.batch.requests.get',return_value=http_pdf(data,http_status)) as request:
            captured=downloader._capture_pdf(page,DOI,result)
        self.assertEqual(request.call_count,1)
        self.assertIn('partial_pdf_response',[e['state'] for e in result.events])
        return captured,data

    def test_real_browser_partial_response_recovers_only_with_a_complete_transfer(self):
        captured,data=self.capture(200)
        self.assertEqual(captured,(data,PDF,None))

    def test_real_browser_and_http_partial_responses_never_become_saved_success(self):
        captured,_=self.capture(206)
        self.assertIsNone(captured[0])

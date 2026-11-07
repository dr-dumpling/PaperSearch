"""Publisher-specific supplement discovery: article identity and real DOM shapes."""
import os
import unittest
from paper_search_carsi.adapters import adapter_class
from paper_search_carsi.adapters.mdpi import MDPIAdapter, supplement_links_from_page as mdpi_links
from paper_search_carsi.adapters.frontiers import FrontiersAdapter, supplement_links_from_page as frontiers_links

MDPI_DOI = '10.3390/nu18213600'
MDPI_FILE = 'https://www.mdpi.com/article/' + MDPI_DOI + '/s1'
FRONTIERS_DOI = '10.3389/fbioe.2025.1651144'
FRONTIERS_FILE = 'https://public-pages-files-2025.frontiersin.org/articles/1651144/file/Presentation_1.pdf/1651144_presentation_1/1'


class PublisherSupplementTests(unittest.TestCase):
    def test_adapter_registration_preserves_pdf_routes(self):
        self.assertIs(adapter_class('mdpi'), MDPIAdapter)
        self.assertIs(adapter_class('frontiers'), FrontiersAdapter)
        self.assertIn('https://www.mdpi.com/2072-6643/18/21/3600/pdf',
                      MDPIAdapter.profile_pdf_candidates(MDPI_DOI, 'https://www.mdpi.com/2072-6643/18/21/3600'))

    def test_mdpi_requires_exact_article_and_file_endpoint(self):
        urls = [MDPI_FILE, MDPI_FILE + '#duplicate', MDPI_FILE.replace('nu18213600', 'nu18213601'),
                MDPI_FILE.replace('www.mdpi.com', 'www.mdpi.com.evil.example'),
                MDPI_FILE.replace('/s1', '/pdf'), MDPI_FILE + '/other', MDPI_FILE.replace('https:', 'http:')]
        self.assertEqual([s.url for s in mdpi_links({'doi': MDPI_DOI, 'rows': [{'href': u} for u in urls]}, MDPI_DOI)], [MDPI_FILE])

    def test_frontiers_requires_file_host_and_exact_article_id(self):
        urls = [FRONTIERS_FILE, FRONTIERS_FILE + '#duplicate',
                FRONTIERS_FILE.replace('/1651144/', '/16511440/'),
                FRONTIERS_FILE.replace('.frontiersin.org', '.frontiersin.org.evil.example'),
                FRONTIERS_FILE.replace('/file/', '/image/'),
                'https://www.frontiersin.org/files/Articles/1651144/xml-images/fbioe-13-1651144-g001.webp',
                'https://www.frontiersin.org/articles/' + FRONTIERS_DOI + '/pdf']
        self.assertEqual([s.url for s in frontiers_links({'doi': FRONTIERS_DOI, 'rows': [{'href': u} for u in urls]}, FRONTIERS_DOI)], [FRONTIERS_FILE])

    def test_wrong_article_or_absent_files_is_not_unsupported(self):
        for parser, doi, url in [(mdpi_links, MDPI_DOI, MDPI_FILE), (frontiers_links, FRONTIERS_DOI, FRONTIERS_FILE)]:
            for citation in ('', '10.1234/unrelated'):
                self.assertEqual(parser({'doi': citation, 'rows': [{'href': url}]}, doi), [])
            self.assertEqual(parser({'doi': doi, 'rows': []}, doi), [])


@unittest.skipUnless(os.environ.get('CARSI_LOCAL_BROWSER_TEST') == '1', 'local browser fixture opt-in')
class PublisherSupplementDOMTests(unittest.TestCase):
    def test_real_page_markup_keeps_labels_and_excludes_references(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                page.set_content(f'''<meta name="citation_doi" content="{MDPI_DOI}">
                    <div class="html-p">Supporting information: <a href="{MDPI_FILE}">download</a>; Tables S1–S2, Figures S1–S5.</div>
                    <a href="https://www.mdpi.com/article/{MDPI_DOI}/pdf">Main PDF</a>''')
                links = MDPIAdapter(None).supplement_links(page, MDPI_DOI)
                self.assertEqual([s.url for s in links], [MDPI_FILE])
                self.assertIn('Figures S1', links[0].label)
                page.set_content(f'''<meta name="citation_doi" content="{FRONTIERS_DOI}">
                    <a href="{FRONTIERS_FILE.replace('Presentation_1', 'Reference')}">Reference outside supplement panel</a>
                    <div id="supplementaryMaterial"><ul class="SupplementalDataV4__list">
                    <li class="SupplementalDataV4__file"><p class="SupplementalDataV4__file__name">Presentation 1.pdf</p>
                    <a aria-label="Download file" data-event="dt_articles-download-supplemental_data" href="{FRONTIERS_FILE}"></a></li></ul></div>''')
                links = FrontiersAdapter(None).supplement_links(page, FRONTIERS_DOI)
                self.assertEqual([(s.url, s.label) for s in links], [(FRONTIERS_FILE, 'Presentation 1.pdf')])
                page.set_content(f'<meta name="citation_doi" content="{FRONTIERS_DOI}"><p>Data are included in the article/supplementary material.</p>')
                self.assertEqual(FrontiersAdapter(None).supplement_links(page, FRONTIERS_DOI), [])
            finally:
                browser.close()

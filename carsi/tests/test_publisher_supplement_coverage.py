"""Observed PLOS, Copernicus and Thieme supplement links (2026-11-05)."""
import os
import unittest
from html import escape

from paper_search_carsi.adapters import plos, copernicus, thieme, aps, annual_reviews, iop, ams, ieee
from paper_search_carsi.engine.batch import PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import get_publisher_profile


PLOS_DOI = "10.1371/journal.pone.0317907"
PLOS_URL = "https://journals.plos.org/plosone/article/file?type=supplementary&id=10.1371%2Fjournal.pone.0317907.s001"
COP_DOI = "10.5194/acp-24-5181-2024"
COP_URL = "https://acp.copernicus.org/articles/24/5181/2024/acp-24-5181-2024-supplement.pdf"
THIEME_DOI = "10.1055/a-2445-4970"
THIEME_URL = "https://www.thieme-connect.de/media/endoscopy/202505/supmat/10-1055-a-2445-4970_24867124.pdf"
APS_DOI = "10.1103/PhysRevLett.133.185101"
APS_URL = "https://journals.aps.org/prl/supplemental/10.1103/PhysRevLett.133.185101/supp_pwOstellarators.pdf"
ANNUAL_DOI = "10.1146/annurev-med-052422-020909"
ANNUAL_URL = "https://www.annualreviews.org/deliver/fulltext/med/75/1/me75_burke_supmat.pdf?itemId=/content/suppdata/10.1146/annurev-med-052422-020909/1"
IOP_DOI = "10.1088/1748-9326/ad5032"
IOP_URL = "https://cfn-live-content-bucket-iop-org.s3.eu-west-1.amazonaws.com/journals/1748-9326/19/6/064065/revision2/erlad5032supp1.pdf?X-Amz-Signature=fixture"
AMS_DOI = "10.1175/WAF-D-24-0063.1"
AMS_URL = "https://journals.ametsoc.org/supplemental//journals/wefo/39/11/WAF-D-24-0063.1.xml/10.1175_WAF-D-24-0063.s1.pdf"
IEEE_DOI = "10.1109/TEC.2025.3597814"
IEEE_URL = "https://ieeexplore.ieee.org/ielx8/60/11409878/11122628/supp1-3597814.mp4"


class PublisherSupplementTests(unittest.TestCase):
    def check_links(self, module, doi, own, excluded):
        rows = [{"href": u, "label": "Supplement"} for u in [own, *excluded, own + "#download"]]
        for request_doi in (doi, doi.upper()):
            with self.subTest(doi=request_doi):
                self.assertEqual([s.url for s in module.supplement_links_from_rows(rows, request_doi)], [own])
        self.assertEqual(module.supplement_links_from_rows([], doi), [])

    def test_plos_excludes_main_text_figures_other_articles_and_foreign_hosts(self):
        self.check_links(plos, PLOS_DOI, PLOS_URL, [
            PLOS_URL.replace("supplementary", "printable"),
            PLOS_URL.replace("supplementary", "manuscript"),
            PLOS_URL.replace(".s001", ".g001"),
            PLOS_URL.replace("0317907", "0317908"),
            PLOS_URL.replace("journals.plos.org", "journals.plos.org.evil.example"),
            PLOS_URL.replace("https://", "https://user@"),
            PLOS_URL + "&id=" + PLOS_DOI + ".s002",
        ])

    def test_copernicus_excludes_article_figure_reference_and_other_directory(self):
        self.check_links(copernicus, COP_DOI, COP_URL, [
            COP_URL.replace("-supplement", ""),
            COP_URL.replace("-supplement", "-f01"),
            COP_URL.replace("5181", "5182"),
            COP_URL.replace("/24/", "/25/"),
            COP_URL.replace("acp.copernicus.org", "evil.example"),
            "https://doi.org/" + COP_DOI + "-supplement",
        ])

    def test_thieme_excludes_figures_and_other_article_files(self):
        self.check_links(thieme, THIEME_DOI, THIEME_URL, [
            THIEME_URL.replace("/supmat/", "/"),
            THIEME_URL.replace("a-2445-4970_", "a-2445-49700_"),
            THIEME_URL.replace("a-2445-4970", "a-2445-4971"),
            THIEME_URL.replace("www.thieme-connect.de", "evil.example"),
            "https://www.thieme-connect.de/products/ejournals/pdf/" + THIEME_DOI,
        ])

    def test_aps_only_takes_this_dois_files_not_the_supplement_landing_page(self):
        self.check_links(aps, APS_DOI, APS_URL, [
            APS_URL.rsplit("/", 1)[0], APS_URL.replace("185101", "185102"),
            APS_URL.replace("journals.aps.org", "evil.example"),
            "https://journals.aps.org/prl/pdf/" + APS_DOI,
        ])

    def test_annual_reviews_binds_delivery_to_the_suppdata_item(self):
        self.check_links(annual_reviews, ANNUAL_DOI, ANNUAL_URL, [
            ANNUAL_URL.replace("020909/1", "020910/1"),
            ANNUAL_URL.replace("/suppdata/", "/journals/"),
            ANNUAL_URL.replace("www.annualreviews.org", "evil.example"),
            ANNUAL_URL.split("?")[0],
        ])

    def test_a_silverchair_page_that_hides_its_supplementary_material_has_none(self):
        """pubs.aip.org marks the kinds an article has in its toolbar ("has-content")
        and hides the others: "Supplementary Material" hidden means none (2026-11-08)."""
        from unittest.mock import Mock
        from paper_search_carsi.adapters.platforms.silverchair import declares_no_supplements
        doi = "10.1063/5.0250823"
        filters = [{"label": "Figures & tables", "hide": False, "has": True},
                   {"label": "Video", "hide": True, "has": False},
                   {"label": "Supplementary Material", "hide": True, "has": False}]

        def page(data):
            return Mock(evaluate=Mock(return_value=data))
        self.assertTrue(declares_no_supplements(page({"doi": doi.upper(), "filters": filters}), doi))
        shown = [dict(f, hide=False, has=True) if f["label"].startswith("Supplementary") else f for f in filters]
        self.assertFalse(declares_no_supplements(page({"doi": doi, "filters": shown}), doi))
        self.assertFalse(declares_no_supplements(page({"doi": "10.1063/5.0000000", "filters": filters}), doi))
        not_rendered = [dict(f, hide=True, has=False) for f in filters]  # nothing marked: says nothing
        self.assertFalse(declares_no_supplements(page({"doi": doi, "filters": not_rendered}), doi))
        self.assertFalse(declares_no_supplements(page({"doi": doi, "filters": filters[:2]}), doi))

        d = PublisherBatchDownloader({}, profile=get_publisher_profile("aip"))
        scripts = Mock(side_effect=lambda script, *a: ({"doi": doi, "filters": filters} if "article-content-filter" in script
                                                       else {"doi": doi, "links": [], "labelled": []}))
        self.assertEqual(d._settled_supplement_links(Mock(evaluate=scripts), doi), [])
        scripts = Mock(side_effect=lambda script, *a: ({"doi": doi, "filters": shown} if "article-content-filter" in script
                                                       else {"doi": doi, "links": [], "labelled": []}))
        self.assertIsNone(d._settled_supplement_links(Mock(evaluate=scripts), doi))

    def test_iop_uses_the_bound_data_page_and_preserves_transfer_signature(self):
        page = "https://iopscience.iop.org/article/" + IOP_DOI + "/data"
        data = {"doi": IOP_DOI, "rows": [
            {"href": IOP_URL, "label": "Supplementary data"},
            {"href": IOP_URL + "#duplicate", "label": "Supplementary data"},
            {"href": IOP_URL.replace("erlad5032supp1", "figure1"), "label": "Figure 1"},
            {"href": "https://evil.example/file.pdf", "label": "Supplementary data"},
        ]}
        self.assertEqual([s.url for s in iop.supplement_links_from_page(data, page, IOP_DOI)], [IOP_URL])
        self.assertIsNone(iop.supplement_links_from_page(data, page, IOP_DOI + "x"))
        # No supplementary data: the page does not exist; a broken page stays unknown.
        self.assertEqual(iop.supplement_links_from_page({"status": 404, "doi": "", "rows": []}, page, IOP_DOI), [])
        self.assertIsNone(iop.supplement_links_from_page({"status": 500, "doi": "", "rows": []}, page, IOP_DOI))
        self.assertIsNone(iop.supplement_links_from_page({"status": 404, "doi": "", "rows": []},
                                                         page.replace("/data", ""), IOP_DOI))
        self.assertIsNone(iop.supplement_links_from_page({**data, "doi": ""}, page, IOP_DOI))
        self.assertIsNone(iop.supplement_links_from_page(data, page.replace("iopscience.iop.org", "evil.example"), IOP_DOI))
        self.assertEqual(iop.supplement_links_from_page({**data, "rows": []}, page, IOP_DOI), [])

    def test_ams_excludes_main_text_and_other_articles(self):
        self.check_links(ams, AMS_DOI, AMS_URL, [
            AMS_URL.replace("/supplemental//", "/view/"),
            AMS_URL.replace("0063.1.xml", "0064.1.xml"),
            AMS_URL.replace("journals.ametsoc.org", "evil.example"),
            AMS_URL.rsplit("/", 1)[0],
        ])
        self.assertEqual(len(ams.supplement_links_from_rows([
            {"href": AMS_URL}, {"href": AMS_URL.replace("/supplemental//", "/supplemental/")}
        ], AMS_DOI)), 1)

    def test_ieee_requires_article_number_and_a_matching_multimedia_doi(self):
        page = "https://ieeexplore.ieee.org/document/11122628/media"
        data = {"dois": ["https://doi.org/" + IEEE_DOI + "/mm1"], "rows": [
            {"href": IEEE_URL}, {"href": IEEE_URL + "#download"},
            {"href": IEEE_URL.replace("11122628", "11122629")},
            {"href": IEEE_URL.replace("ieeexplore.ieee.org", "evil.example")},
        ]}
        self.assertEqual([s.url for s in ieee.supplement_links_from_page(data, page, IEEE_DOI)], [IEEE_URL])
        self.assertIsNone(ieee.supplement_links_from_page(data, page, IEEE_DOI + "1"))
        self.assertIsNone(ieee.supplement_links_from_page({**data, "dois": []}, page, IEEE_DOI))
        self.assertIsNone(ieee.supplement_links_from_page(data, page.replace("ieeexplore.ieee.org", "evil.example"), IEEE_DOI))

    def test_ieee_explicit_empty_sections_must_belong_to_the_requested_article(self):
        page = 'https://ieeexplore.ieee.org/document/11219178'
        doi = '10.1109/access.2025.3626630'
        data = {'article':'11219178', 'doi':doi.upper(), 'multimedia':'false',
                'tabs':[page, page+'/authors'], 'dois':[], 'rows':[]}
        self.assertEqual(ieee.supplement_links_from_page(data, page, doi), [])
        self.assertEqual(ieee.supplement_links_from_page({**data, 'multimedia':False}, page, doi), [])
        for update in ({'doi':'10.1109/other'}, {'article':'11122628'}, {'doi':None},
                       {'multimedia':None}, {'multimedia':'true'}, {'multimedia':0},
                       {'tabs':[page+'/media']}, {'rows':[{'href':IEEE_URL}]}):
            with self.subTest(update=update):
                self.assertIsNone(ieee.supplement_links_from_page({**data, **update}, page, doi))
        self.assertIsNone(ieee.supplement_links_from_page(data, page.replace('ieeexplore.ieee.org','other.example'), doi))


class AtyponListedSupplementTests(unittest.TestCase):
    def test_this_articles_files_are_listed_without_leaving_the_page(self):
        from unittest.mock import Mock, patch
        from paper_search_carsi.adapters.platforms import atypon
        doi = "10.1161/circ.123.1"
        base = "https://www.ahajournals.org/doi/suppl/" + doi
        rows = [{"href": base + "/suppl_file/s1.pdf", "label": "Data Supplement"},
                {"href": base + "x/suppl_file/other.pdf", "label": "Another article"},
                {"href": base, "label": "Supplemental Material"}]
        adapter = atypon.AtyponAdapter(None)
        adapter.site_hosts = frozenset({"www.ahajournals.org"})
        page = Mock(url="https://www.ahajournals.org/doi/" + doi)
        page.evaluate.return_value = rows
        with patch.object(atypon, "open_page") as navigate:
            listed = adapter.listed_supplement_links(page, doi)
        self.assertEqual([(s.url, s.label) for s in listed], [(base + "/suppl_file/s1.pdf", "Data Supplement")])
        navigate.assert_not_called()


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class PublisherSupplementBrowserTests(unittest.TestCase):
    def test_atypon_follows_only_the_observed_supplement_page_for_this_article(self):
        from patchright.sync_api import sync_playwright
        from paper_search_carsi.adapters.platforms.atypon import AtyponAdapter
        doi = '10.1142/S1793545824410037'
        base = 'https://publisher.example'
        landing = base + '/doi/suppl/' + doi
        file = landing + '/suppl_file/attachment.pdf'
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                visited = []
                def serve(route):
                    visited.append(route.request.url)
                    if route.request.url == landing:
                        html = f'<a href="{file}">Supplement 1</a><a href="{file}">Duplicate</a>'
                    else:
                        html = (f'<a href="{landing}x">Other article</a>'
                                f'<a href="{landing.replace(base, "https://other.example")}">External</a>'
                                f'<a href="{landing}">Supplemental Materials</a>')
                    route.fulfill(content_type='text/html', body=html)
                page.route('**/*', serve)
                page.goto(base + '/doi/' + doi.lower())
                adapter = AtyponAdapter(None)
                adapter.site_hosts = frozenset({'publisher.example'})
                for _ in range(2):
                    self.assertEqual([s.url for s in adapter.supplement_links(page, doi.lower())], [file])
                self.assertEqual(visited, [base + '/doi/' + doi.lower(), landing])
            finally:
                browser.close()

    def test_remembered_school_widget_without_button_role_is_clicked_once(self):
        from patchright.sync_api import sync_playwright
        from unittest.mock import Mock
        from paper_search_carsi.engine.batch import DownloadResult
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                d = PublisherBatchDownloader({}, institution_query="Fixture University")
                d._click_unique_institution_entry = Mock(return_value=False)
                d._assist_carsi_discovery = Mock(return_value=False)
                d._institution_search_selectors = Mock(return_value=())
                result = DownloadResult(doi="10.1/fixture", status="failed")
                for school, clickable, expected in [
                    ("Other University", True, False), ("Fixture University", False, False),
                    ("Fixture University", True, True),
                ]:
                    style = 'style="cursor:pointer" onclick="this.dataset.clicked=1"' if clickable else ''
                    page.set_content(f'<div id="entry" {style}><span>Access Through</span><b>{school}</b></div>')
                    self.assertEqual(d._assist_configured_institution(page, result), expected)
                    self.assertEqual(page.locator('#entry').get_attribute('data-clicked'), '1' if expected else None)
                self.assertFalse(d._assist_configured_institution(page, result))
                for attributes, expected in [
                    ('aria-label="Institutional access"', True),
                    ('aria-label="Institutional access" disabled', False),
                ]:
                    result.events.clear()
                    page.set_content(f'<button id="entry" {attributes} onclick="this.dataset.clicked=1">'
                                     '<div>Access Through</div><div>Fixture University</div></button>')
                    self.assertEqual(d._assist_configured_institution(page, result), expected)
                    self.assertEqual(page.locator('#entry').get_attribute('data-clicked'), '1' if expected else None)
            finally:
                browser.close()

    def test_optica_reader_redirect_finishes_before_figshare_discovery(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                article = 'https://opg.optica.org/oe/fulltext.cfm?uri=oe-32-26-45613'
                html = ('<meta name="citation_doi" content="10.1364/OE.540130">'
                        '<a href="https://doi.org/10.6084/m9.figshare.28344677">Supplement</a>')
                reader = '<title>OPG</title>Please wait...<script>setTimeout(()=>location.href=' + repr(article) + ',200)</script>'
                page.route("**/*", lambda route: route.fulfill(content_type="text/html",
                           body=html if 'fulltext' in route.request.url else reader))
                page.goto('https://opg.optica.org/oe/viewmedia.cfm?uri=oe-32-26-45613&html=true')
                adapter = PublisherBatchDownloader({}, profile=get_publisher_profile("optica")).adapter
                self.assertIsNone(adapter.supplement_links(page, "10.1364/OE.540130"))
                self.assertEqual(page.url, article)
                self.assertIn('figshare', page.locator('a').get_attribute('href'))
            finally:
                browser.close()

    def test_ieee_already_open_remembered_modal_is_not_reopened(self):
        from patchright.sync_api import sync_playwright
        from paper_search_carsi.engine.batch import DownloadResult
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                html = ('<a class="inst-sign-in" href="#" onclick="this.dataset.clicked=1">Institutional Sign In</a>'
                        '<div role="dialog" style="position:fixed;inset:0;background:white">'
                        '<h2>Institutional Sign In</h2><button id="school" aria-label="Institutional access" '
                        'onclick="this.dataset.clicked=1"><div>Access Through</div>'
                        '<div>Fixture University</div></button></div>')
                page.route('**/*', lambda route: route.fulfill(content_type='text/html', body=html))
                page.goto('https://ieeexplore.ieee.org/document/11122628')
                d = PublisherBatchDownloader({}, profile=get_publisher_profile('ieee'),
                                             institution_query='Fixture University')
                result = DownloadResult(doi=IEEE_DOI, status='failed')
                self.assertFalse(d.adapter.open_institution_entry(page, result))
                self.assertIsNone(page.locator('a.inst-sign-in').get_attribute('data-clicked'))
                self.assertTrue(d._assist_configured_institution(page, result))
                self.assertEqual(page.locator('#school').get_attribute('data-clicked'), '1')
            finally:
                browser.close()

    def test_ieee_waits_for_the_observed_client_side_media_tab(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                html = ('<style>@keyframes moving {from {transform:translateX(0)} to {transform:translateX(500px)}}'
                        '#live{display:block;animation:moving .2s linear infinite}</style>'
                        '<a class="document-tab-link" style="display:none" href="/document/11122628/media" '
                        'onclick="document.documentElement.dataset.wrong=1">Hidden copy</a>'
                        '<a class="document-tab-link" aria-disabled="true" href="/document/11122628/media" '
                        'onclick="document.documentElement.dataset.wrong=1">Disabled copy</a>'
                        '<a id="live" class="document-tab-link" href="/document/11122628/media">Supplemental Items</a>'
                        '<script>document.querySelector("#live").onclick=e=>{e.preventDefault();'
                        'history.pushState({}, "", e.target.href);setTimeout(()=>{'
                        'document.body.innerHTML=`<div class="media-item">'
                        f'<a href="{IEEE_URL}">Video</a></div>'
                        f'<a class="multimedia-doi" href="https://doi.org/{IEEE_DOI}/mm1">DOI</a>`'
                        '}, 700);}</script>')
                page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
                page.goto("https://ieeexplore.ieee.org/document/11122628")
                adapter = PublisherBatchDownloader({}, profile=get_publisher_profile("ieee")).adapter
                self.assertEqual([s.url for s in adapter.supplement_links(page, IEEE_DOI)], [IEEE_URL])
                self.assertIsNone(page.locator('html').get_attribute('data-wrong'))
            finally:
                browser.close()

    def test_ieee_empty_article_metadata_and_unfinished_shell_are_distinct(self):
        from patchright.sync_api import sync_playwright
        doi = '10.1109/access.2025.3626630'
        article = 'https://ieeexplore.ieee.org/document/11219178'
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                page.route('**/*', lambda route: route.fulfill(content_type='text/html', body='<h1>Article shell</h1>'))
                page.goto(article)
                adapter = PublisherBatchDownloader({}, profile=get_publisher_profile('ieee')).adapter
                self.assertIsNone(adapter.supplement_links(page, doi))
                metadata = {'articleNumber':'11219178','doi':doi.upper(),'sections':{'multimedia':'false'}}
                page.evaluate('(metadata) => window.xplGlobal={document:{metadata}}', metadata)
                self.assertEqual(adapter.supplement_links(page, doi), [])
                page.evaluate('window.xplGlobal.document.metadata.doi="10.1109/wrong"')
                self.assertIsNone(adapter.supplement_links(page, doi))
                page.evaluate('''metadata => {
                    delete window.xplGlobal;
                    const script = document.createElement('script');
                    script.type = 'application/json';
                    script.textContent = 'xplGlobal.document.metadata=' + JSON.stringify(metadata) + ';';
                    document.body.append(script);
                }''', metadata)
                self.assertEqual(adapter.supplement_links(page, doi), [])
                page.evaluate("document.scripts[0].textContent='xplGlobal.document.metadata={invalid};'")
                self.assertIsNone(adapter.supplement_links(page, doi))
            finally:
                browser.close()

    def test_silverchair_datasupplink_section_accepts_only_its_doi(self):
        from patchright.sync_api import sync_playwright
        from paper_search_carsi.adapters.platforms.silverchair import supplement_links
        doi = "10.1182/bloodadvances.2024014900"
        own = ("https://ash.silverchair-cdn.com/ash/content_public/journal/bloodadvances/9/8/"
               "10.1182_bloodadvances.2024014900/2/blooda_adv-2024-014900-mmc1.pdf")
        other = own.replace("2024014900", "2024014901")
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                page.set_content(f'<div class="dataSuppLink"><a href="{own}">Supplemental data</a>'
                                 f'<a href="{other}">Other article</a></div>'
                                 f'<a href="{own.replace("mmc1", "figure1")}">Figure</a>')
                self.assertEqual([s.url for s in supplement_links(page, doi, frozenset({"ashpublications.org"}))],
                                 [own])
            finally:
                browser.close()

    def test_real_dom_extraction_and_registry_select_the_observed_files(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                for publisher, doi, own in [("plos", PLOS_DOI, PLOS_URL),
                                             ("copernicus", COP_DOI, COP_URL),
                                             ("thieme", THIEME_DOI, THIEME_URL),
                                             ("aps", APS_DOI, APS_URL),
                                             ("annual reviews", ANNUAL_DOI, ANNUAL_URL),
                                             ("iop", IOP_DOI, IOP_URL),
                                             ("ams", AMS_DOI, AMS_URL)]:
                    with self.subTest(publisher=publisher):
                        page = browser.new_page()
                        html = (f'<meta name="citation_doi" content="{doi}">'
                                f'<a href="{escape(own)}"><span>Supplement</span></a>'
                                f'<a href="{escape(own)}">duplicate</a>')
                        if publisher == "iop":
                            page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
                            page.goto("https://iopscience.iop.org/article/" + doi + "/data")
                        else:
                            page.set_content(html)
                        adapter = PublisherBatchDownloader({}, profile=get_publisher_profile(publisher)).adapter
                        self.assertEqual([(s.url, s.label) for s in adapter.supplement_links(page, doi)],
                                         [(own, "Supplement")])
                        page.close()
            finally:
                browser.close()

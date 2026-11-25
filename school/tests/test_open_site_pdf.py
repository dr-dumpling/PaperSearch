"""Open sites' PDFs and the reasons kept (Windows sweep, 2026-11-24).

An Open Journal Systems galley's Download on the page its "PDF" opens (AJPR, JSIHS); a bepress
Digital Commons file named in bepress_citation_pdf_url (Osgoode Hall Law Journal); a citation PDF
on a page whose DOI is only in DC.Identifier (Tellus B); F1000's platforms' page address plus
/pdf (Bioethics Open Research), whose licence badge has no rel="license" and whose "PDF downloads"
counter was clicked as the PDF; the login's own ending kept as the reason (DBpia: the school not in
its institution list); an article open to all whose page names no PDF (CAA Reviews); the box agreeing to
the download terms that holds back the PDF link (ufn.ru, 2026-11-25). Mocked pages;
the page scripts on synthetic pages in a local Chrome (opt-in)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from paper_search_school.engine import access_rules, batch, bridge
from paper_search_school.engine.batch import DownloadResult, PaperRecord, PublisherBatchDownloader
from paper_search_school.engine.router import build_pdf_candidates, is_pdf_candidate_url
from paper_search_school.publishers.model import PublisherProfile
from paper_search_school.publishers.site import site_profile

OJS = "https://journal.example/index.php/ajpr/article/view/442"
GALLEY = "https://journal.example/index.php/ajpr/article/view/442/292"
DOWNLOAD = "https://journal.example/index.php/ajpr/article/download/442/292/1576"
PROFILE = PublisherProfile(name="Fixture", article_url_template="https://doi.org/{doi}", pdf_url_templates=(),
                           success_url_markers=(), auth_url_markers=(), auth_title_markers=(), sso_text_markers=(),
                           base_domains=("journal.example",))


def downloader(profile=PROFILE):
    d = PublisherBatchDownloader({}, profile=profile, login_timeout_sec=300)
    d._write_diagnostic = Mock()
    d._hold_after_login = Mock()
    d._hold_after_run = Mock()
    d._return_from_other_article = Mock()
    d._title = Mock(return_value="Article")
    return d


class OpenJournalSystemsTests(unittest.TestCase):
    def test_a_galley_pages_download_is_the_articles_pdf(self):
        d = downloader()
        for page_url in (OJS, GALLEY):
            with self.subTest(page=page_url):
                keys = d._article_keys(page_url, "10.69980/ajpr.v28i1.442")
                self.assertIn("/article/download/442/", keys)
                self.assertTrue(d._article_pdf_link(DOWNLOAD, keys, page_url))
                self.assertTrue(d._article_pdf_link(DOWNLOAD.rsplit("/", 1)[0], keys, page_url))  # without the file
                # Another article's galley, the citation's export, another site: not this article's.
                self.assertFalse(d._article_pdf_link(DOWNLOAD.replace("/442/", "/4421/"), keys, page_url))
                self.assertFalse(d._article_pdf_link(
                    "https://journal.example/index.php/ajpr/citationstylelanguage/download/ris", keys, page_url))
                self.assertFalse(d._article_pdf_link(DOWNLOAD.replace("journal.example", "other.example"), keys, page_url))

    def test_an_article_named_by_its_name_instead_of_a_number(self):
        d = downloader()
        page_url = "https://journal.example/ojs/index.php/jsihs/article/view/ai-and-edge-analytics/239"
        link = "https://journal.example/ojs/index.php/jsihs/article/download/ai-and-edge-analytics/239/1341"
        keys = d._article_keys(page_url, "10.69996/jsihs.2025016")
        self.assertTrue(d._article_pdf_link(link, keys, page_url))
        self.assertTrue(is_pdf_candidate_url(PROFILE, link))
        self.assertFalse(d._article_pdf_link(link.replace("/ai-and-edge-analytics/", "/another-article/"), keys, page_url))

    def test_no_galley_key_off_an_ojs_page(self):
        d = downloader()
        self.assertFalse([key for key in d._article_keys("https://journal.example/article/442", "10.1/x")
                          if key.startswith("/article/download/")])


class PlatformFileTests(unittest.TestCase):
    def test_a_bepress_file_is_a_pdf_address(self):
        url = "https://digitalcommons.example.edu/cgi/viewcontent.cgi?article=4103&context=ohlj"
        self.assertTrue(is_pdf_candidate_url(PROFILE, url))
        self.assertTrue(downloader()._is_pdf_candidate_url(url))
        self.assertFalse(is_pdf_candidate_url(PROFILE, "https://digitalcommons.example.edu/cgi/preview.cgi?article=4103"))

    def test_the_citation_pdf_of_a_page_whose_doi_matches(self):
        d = downloader(PublisherProfile(name="Fixture", article_url_template="https://doi.org/{doi}", pdf_url_templates=(),
                                        success_url_markers=(), auth_url_markers=(), auth_title_markers=(),
                                        sso_text_markers=(), base_domains=("digitalcommons.example.edu",)))
        page = MagicMock()
        page.url = "https://digitalcommons.example.edu/ohlj/vol62/iss1/9/"
        pdf = "https://digitalcommons.example.edu/cgi/viewcontent.cgi?article=4103&context=ohlj"
        found = {"dois": ["10.60082/2817-5069.4103"], "pdfs": [pdf], "links": []}
        self.assertEqual(d._citation_pdf_urls(page, "10.60082/2817-5069.4103", found), [pdf])
        self.assertEqual(d._citation_pdf_urls(page, "10.60082/2817-5069.4104", found), [])


class F1000PlatformTests(unittest.TestCase):
    def test_the_pages_address_plus_pdf(self):
        doi = "10.12688/bioethopenres.17725.1"
        page_url = "https://bioethicsopenresearch.org/articles/3-2/v1"
        profile = site_profile(doi, page_url)
        self.assertEqual(build_pdf_candidates(profile, doi, source_url=page_url)[:1],
                         ["https://bioethicsopenresearch.org/articles/3-2/v1/pdf"])
        # Only on its article pages, only for F1000's DOIs.
        self.assertNotIn("https://bioethicsopenresearch.org/about/pdf",
                         build_pdf_candidates(profile, doi, source_url="https://bioethicsopenresearch.org/about"))
        other = site_profile("10.9999/x.1", "https://www.journal.example/articles/3-2/v1")
        self.assertEqual(other.pdf_source_path_templates, ())


def item_downloader(decision, signal=""):
    d = downloader(PublisherProfile(name="Fixture Press", article_url_template="https://doi.org/{doi}",
                                    pdf_url_templates=(), success_url_markers=("journal.example/",), auth_url_markers=(),
                                    auth_title_markers=(), sso_text_markers=(), base_domains=("journal.example",)))
    d._access_decision = Mock(return_value=decision)
    d._open_access_signal = Mock(return_value=signal)
    d._article_access_available = Mock(return_value=False)
    d._login_block_reason = Mock(return_value="")
    d._looks_logged_out = Mock(return_value=False)
    d._ensure_login = Mock(return_value=True)
    d._capture_pdf = Mock(return_value=(None, "", None))
    d._reopen_article_page = Mock()
    return d


def fetch(d, url="https://journal.example/reviews/4358"):
    page = MagicMock()
    page.url = url
    page.locator.return_value.inner_text.return_value = ""
    page.is_closed.return_value = False
    del page.new_page  # a page, not a context
    with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
        return d.fetch_one(page, PaperRecord(doi="10.3202/caa.reviews.2025.67"), Path(directory))


class LoginEndingTests(unittest.TestCase):
    def test_the_logins_own_ending_is_the_articles_reason(self):
        for reason in ("institution_federation_unavailable", "publisher_institution_entry_missing",
                       "idp_no_return_to_publisher", "generic_institution_entry_missing", "no_institution_entry"):
            with self.subTest(reason=reason):
                d = item_downloader(("unknown", "", ""))

                def ended(page, result, reason=reason):
                    result.reason = reason
                    return False

                d._complete_login_from_current_page = Mock(side_effect=ended)
                result = fetch(d)
                d._complete_login_from_current_page.assert_called_once()
                self.assertEqual((result.reason, result.state), (reason, reason))

    def test_a_wait_that_ran_out_says_where_it_ended(self):
        # DBpia (VPS, 2026-11-24): its institution search found nothing for the school, the wait stood a minute on
        # the publisher's page, then 原因不明 · 没取到 PDF.
        for where, code in (("publisher", "login_not_reached"), ("school_login", "login_timeout")):
            with self.subTest(where=where):
                d = item_downloader(("unknown", "", ""))
                d._login_wait_page = Mock(return_value=where)

                def ran_out(page, result):
                    d._wait_ran_out(result)
                    return False

                d._complete_login_from_current_page = Mock(side_effect=ran_out)
                result = fetch(d)
                self.assertEqual((result.reason, result.login_wait_page), ("sso_required", where))
                self.assertEqual(bridge._failure_reason_code(result), code)

    def test_a_login_that_ended_without_a_reason_of_its_own_is_still_pdf_not_captured(self):
        d = item_downloader(("unknown", "", ""))
        d._complete_login_from_current_page = Mock(return_value=False)
        self.assertEqual(fetch(d).reason, "pdf_not_captured")


class PdfNotOfferedTests(unittest.TestCase):
    OPEN = ("in", "reader", "licence: is licensed under a Creative Commons")

    def test_an_open_page_naming_no_pdf_is_a_web_page_only(self):
        d = item_downloader(self.OPEN, "open licence: licence link: https://creativecommons.org/licenses/by-nd/4.0/")
        d._page_offers_no_pdf = Mock(return_value=True)
        d._complete_login_from_current_page = Mock(side_effect=AssertionError("no school login"))
        result = fetch(d)
        self.assertEqual((result.reason, result.state), ("pdf_not_offered", "pdf_not_offered"))
        said = next(e["detail"] for e in result.events if e["state"] == "pdf_not_offered")
        self.assertIn("nothing on the page names a PDF", said)
        self.assertEqual(bridge._FAILURE_KINDS["pdf_not_offered"], ("pdf_not_offered", ""))

    def test_a_page_that_names_a_pdf_or_where_one_was_tried_is_not(self):
        d = item_downloader(self.OPEN, "open licence: licence link: https://creativecommons.org/licenses/by/4.0/")
        d._page_offers_no_pdf = Mock(return_value=False)
        self.assertEqual(fetch(d).reason, "pdf_not_captured")
        d = item_downloader(self.OPEN, "open licence: licence link: https://creativecommons.org/licenses/by/4.0/")
        d._page_offers_no_pdf = Mock(return_value=True)

        def tried(page, doi, result):
            result.pdf_attempts.append({"how": "url", "url": "https://journal.example/x.pdf", "outcome": "html page"})
            return None, "", None

        d._capture_pdf = Mock(side_effect=tried)
        self.assertEqual(fetch(d).reason, "pdf_not_captured")

    def test_a_page_not_known_open_signs_in_first(self):
        d = item_downloader(("unknown", "", ""))
        d._page_offers_no_pdf = Mock(return_value=True)
        d._complete_login_from_current_page = Mock(return_value=False)
        self.assertEqual(fetch(d).reason, "pdf_not_captured")
        d._complete_login_from_current_page.assert_called_once()


class DownloadTermsTests(unittest.TestCase):
    ARTICLE = "https://journal.example/en/articles/2026/1/f/"

    def test_the_box_is_ticked_before_the_links_are_read(self):
        d = downloader()
        page = MagicMock(url=self.ARTICLE)
        page.evaluate.return_value = "By downloading this file I agree with the terms of use."
        d._click_control = Mock(return_value=True)
        result = DownloadResult(doi="10.3367/ufne.2025.12.040079", status="failed")
        with patch("paper_search_school.engine.batch_capture.settle"):
            self.assertTrue(d._agree_to_download_terms(page, result))
        page.locator.assert_called_with('[data-papersearch-download-terms="1"]')
        self.assertEqual([e["state"] for e in result.events], ["download_terms_agreed"])
        self.assertIn("I agree with the terms of use", result.events[0]["detail"])

    def test_nothing_to_tick_or_a_schools_page_is_left_alone(self):
        d = downloader()
        d._click_control = Mock()
        for url, said in ((self.ARTICLE, ""), ("https://idp.example.edu.cn/idp/profile/SAML2/Redirect/SSO", "I agree")):
            with self.subTest(url=url):
                page = MagicMock(url=url)
                page.evaluate.return_value = said
                result = DownloadResult(doi="10.1/x", status="failed")
                self.assertFalse(d._agree_to_download_terms(page, result))
                self.assertEqual(result.events, [])
        d._click_control.assert_not_called()


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class PageScriptTests(unittest.TestCase):
    """The page scripts on synthetic pages."""

    def run_page(self, html, check, url="https://journal.example/articles/3-2/v1"):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context(service_workers="block")
                context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
                page = context.new_page()
                page.goto(url)
                return check(page)
            finally:
                browser.close()

    def test_a_pages_doi_and_pdf_from_bepress_or_dublin_core_when_citation_names_are_missing(self):
        d = downloader()
        bepress = ('<meta name="bepress_citation_doi" content="10.60082/2817-5069.4103">'
                   '<meta name="bepress_citation_pdf_url" content="/cgi/viewcontent.cgi?article=4103&amp;context=ohlj">')
        found = self.run_page(bepress, d._page_pdf_links)
        self.assertEqual(found["dois"], ["10.60082/2817-5069.4103"])
        self.assertEqual(found["pdfs"], ["https://journal.example/cgi/viewcontent.cgi?article=4103&context=ohlj"])
        dublin = ('<meta name="DC.Identifier" content="1881"><meta name="DC.Identifier" content="10.16993/tellusb.1881">'
                  '<meta name="citation_pdf_url" content="/articles/1881/files/693031ea99972.pdf">')
        self.assertEqual(self.run_page(dublin, d._page_pdf_links)["dois"], ["10.16993/tellusb.1881"])
        doi_link = '<meta name="DC.Identifier.DOI" content="https://doi.org/10.16993/tellusb.1881">'
        self.assertEqual(self.run_page(doi_link, d._page_pdf_links)["dois"], ["10.16993/tellusb.1881"])
        # citation_doi, when there, is the page's DOI: the others are not read.
        both = '<meta name="citation_doi" content="10.1/a"><meta name="DC.Identifier" content="10.1/b">'
        self.assertEqual(self.run_page(both, d._page_pdf_links)["dois"], ["10.1/a"])

    def test_a_licence_badge_named_creative_commons_licence(self):
        badge = ('<header><a aria-label="Creative Commons License CC-BY" href="https://creativecommons.org/licenses/">'
                 '<span></span></a></header>')
        said = self.run_page(badge, lambda page: page.evaluate(access_rules.OPEN_SIGNS_JS))
        self.assertEqual(said, "licence link: https://creativecommons.org/licenses/")
        footer = '<footer>' + badge + '</footer>'
        self.assertEqual(self.run_page(footer, lambda page: page.evaluate(access_rules.OPEN_SIGNS_JS)), "")
        data = '<a aria-label="Creative Commons License CC0" href="https://creativecommons.org/about/cc0">x</a>'
        self.assertEqual(self.run_page(data, lambda page: page.evaluate(access_rules.OPEN_SIGNS_JS)), "")

    def test_what_names_a_pdf(self):
        names = PublisherBatchDownloader._NAMES_A_PDF_JS
        for html, named in (("<article><p>A review of an exhibition.</p></article>", False),
                            ('<a href="/files/review.pdf">Download</a>', True),
                            ('<button title="Download PDF">Download</button>', True),
                            ("<p>Available as PDF.</p>", True),
                            ('<meta name="citation_pdf_url" content="/x">', True)):
            with self.subTest(html=html):
                self.assertEqual(self.run_page(html, lambda page: page.evaluate(names)), named)

    UFN = ("""<p><span>Fulltext</span> <a class="file-link pdf" href="/files/f.pdf" data-ehref="L2ZpbGVzL2YucGRm">pdf</a>
        <table><tr><td><input type="checkbox" id="agree"></td>
        <td><div>By&nbsp;downloading this file&nbsp;I agree with the <a id="terms">terms of&nbsp;use</a>.</div></td></tr></table>
        <script>
        const links = () => document.querySelectorAll('.file-link');
        function onAgree() {
            links().forEach(a => { if (this.checked) { a.setAttribute('href', atob(a.dataset.ehref)); a.classList.remove('disabled-link'); }
                                   else { a.removeAttribute('href'); a.classList.add('disabled-link'); } });
        }
        onAgree.call(document.getElementById('agree'));
        document.getElementById('agree').addEventListener('change', onAgree);
        </script>""")

    def test_the_box_agreeing_to_the_download_terms_gives_the_pdf_link_its_address(self):
        # ufn.ru's article page (2026-11-25): the PDF link has no address until the box is ticked.
        d = downloader()
        d._click_control = lambda page, control, result, what, timeout_ms=5_000: control.click(timeout=timeout_ms) or True
        result = DownloadResult(doi="10.3367/ufne.2025.12.040079", status="failed")

        def check(page):
            before = page.evaluate("() => document.querySelector('.file-link').getAttribute('href')")
            ticked = d._agree_to_download_terms(page, result)
            return before, ticked, page.evaluate("() => [document.getElementById('agree').checked, "
                                                 "document.querySelector('.file-link').getAttribute('href')]")
        before, ticked, after = self.run_page(self.UFN, check)
        self.assertIsNone(before)
        self.assertTrue(ticked)
        self.assertEqual(after, [True, "/files/f.pdf"])
        self.assertIn("I agree with the terms of use", result.events[-1]["detail"])

    def test_which_boxes_are_the_download_terms(self):
        terms = PublisherBatchDownloader._DOWNLOAD_TERMS_JS
        held = '<a class="btn download disabled">Download PDF</a>'
        cases = (
            ('<label><input type="checkbox"> I agree to the terms of use for downloading this PDF</label>', True),
            ('<meta charset="utf-8"><label><input type="checkbox"> 我已阅读并同意下载使用条款</label>', True),
            # Terms without a word of the download: only when a download control is held back.
            ('<label><input type="checkbox"> I accept the Terms and Conditions</label>' + held, True),
            ('<label><input type="checkbox"> I accept the Terms and Conditions</label>', False),
            ('<label><input type="checkbox"> I agree to receive the newsletter and accept the terms</label>' + held, False),
            ('<label><input type="checkbox"> I accept cookies under the terms of the cookie policy</label>' + held, False),
            ('<label><input type="checkbox"> Remember me</label>' + held, False),
            ('<form><input type="password"><label><input type="checkbox"> I agree to the terms of use to download</label></form>',
             False),
            ('<label><input type="checkbox" checked> I agree to the terms of use for downloading</label>', False),
            ('<label style="display:none"><input type="checkbox"> I agree to the terms of use for downloading</label>', False),
        )
        for html, ticks in cases:
            with self.subTest(html=html):
                said = self.run_page(html, lambda page: page.evaluate(terms))
                self.assertEqual(bool(said), ticks, said)

    def test_check_access_in_a_panel_about_an_institutional_subscription(self):
        check = PublisherBatchDownloader._MENU_CHECK_ACCESS_JS
        panel = ('<div class="access-options"><h3>Access Options</h3><p>You may have access to this content with your '
                 'personal login credentials or through your institutional subscription.</p>'
                 '<button>Check Access</button> OR <button>Purchase PDF</button></div>')
        found = self.run_page(panel, lambda page: page.evaluate(check))
        self.assertEqual((found["label"], found["href"]), ("Check Access", ""))
        offer = '<div class="purchase"><p>Buy this article for 30 days.</p><a href="/buy">Check Access</a></div>'
        self.assertIsNone(self.run_page(offer, lambda page: page.evaluate(check)))
        # The word far away on a long page is not the panel's.
        far = '<p>' + 'An article about institutions. ' * 80 + '</p><div><div><button>Check Access</button></div></div>'
        self.assertIsNone(self.run_page(far, lambda page: page.evaluate(check)))

    def test_a_title_naming_pdf_counts_only_on_a_control(self):
        html = ('<ul><li title="XML &amp; PDF downloads (all versions)">14<span>Downloads</span></li></ul>'
                '<a id="pdf" title="PDF (1.4 MB) opens in new window" href="/cgi/viewcontent.cgi?article=1">Download</a>')
        selector = "a[title*='PDF'], button[title*='PDF'], [role='button'][title*='PDF']"
        ids = self.run_page(html, lambda page: [el.get_attribute("id") for el in page.locator(selector).all()])
        self.assertEqual(ids, ["pdf"])



@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class NewTabPdfButtonTests(unittest.TestCase):
    def test_a_pdf_button_opening_a_new_tab_gives_its_pdf_in_the_watched_tab(self):
        # IJOR's Squarespace page (Windows, 2026-11-25): "PDF" with target=_blank, its
        # /s/ address redirecting to the file on static1.squarespace.com; the PDF in the
        # new tab was lost and the paper recorded as no institution entry.
        import fitz
        from patchright.sync_api import sync_playwright
        from fixture_network import network_is_the_fixture

        doc = fitz.open()
        for index in range(12):
            doc.new_page().insert_text((50, 60), "DOI: 10.1000/new-tab\n" + ("New tab fixture %s\n" % index) * 25)
        data = doc.tobytes(deflate=False)
        doc.close()
        article = "https://journal.example/articles/new-tab"
        button = "https://journal.example/s/Int-J-Fixture-k54x"
        pdf_url = "https://files.example/static/t/Int+J+Fixture.pdf"
        html = ('<html><head><meta name="citation_doi" content="10.1000/new-tab"></head><body>'
                '<a href="/s/Int-J-Fixture-k54x" target="_blank" class="sqs-block-button-element">PDF</a></body></html>')
        requests = []

        def local_response(route):
            url = route.request.url
            requests.append(url)
            if url == article:
                route.fulfill(status=200, content_type="text/html", body=html)
            elif url == button:
                route.fulfill(status=302, headers={"Location": pdf_url}, body="")
            elif url == pdf_url:
                route.fulfill(status=200, content_type="application/pdf", body=data)
            else:
                route.abort()

        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                network_is_the_fixture(self)
                context = browser.new_context()
                context.route("**/*", local_response)
                page = context.new_page()
                page.goto(article)
                d = downloader()
                d._pdf_candidates = Mock(return_value=[])
                d._fetch_page_state_pdf = Mock(return_value=(None, "", None))
                result = DownloadResult(doi="10.1000/new-tab", status="failed")
                body, url, block = d._capture_pdf(page, result.doi, result)
                self.assertEqual(body, data)
                self.assertEqual(url, pdf_url)
                self.assertIsNone(block)
                self.assertEqual(len(context.pages), 1)
                self.assertEqual(requests.count(pdf_url), 1)
            finally:
                browser.close()


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class ScriptedInstitutionEntryTests(unittest.TestCase):
    def run_entry(self, script):
        # ASCO (Windows, 2026-11-25): "INSTITUTIONAL LOGIN" is <a data-href="/action/ssostart">, followed
        # by the site's script; three of four clicks left the article page where it was for the minute.
        from patchright.sync_api import sync_playwright
        from fixture_network import network_is_the_fixture

        article = "https://journal.example/doi/10.1000/x"
        html = ('<html><body><a data-href="/action/ssostart" class="btn" href="#" onclick="return false">'
                'Institutional Login</a>%s</body></html>' % script)
        html = html.replace(' href="#"', "")
        opened = []

        def local_response(route):
            url = route.request.url.split("?", 1)[0]
            if url == article:
                route.fulfill(status=200, content_type="text/html", body=html)
            elif url == "https://journal.example/action/ssostart":
                opened.append(route.request.url)
                route.fulfill(status=200, content_type="text/html", body="<title>Shibboleth</title><p>Find your institution</p>")
            else:
                route.abort()

        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                network_is_the_fixture(self)
                context = browser.new_context()
                context.route("**/*", local_response)
                page = context.new_page()
                page.goto(article)
                d = downloader(PublisherProfile(name="Fixture", article_url_template="https://doi.org/{doi}",
                                                pdf_url_templates=(), success_url_markers=(), auth_url_markers=(),
                                                auth_title_markers=(), sso_text_markers=(),
                                                base_domains=("journal.example",)))
                result = DownloadResult(doi="10.1000/x", status="failed")
                self.assertTrue(d._click_manual_institution_entry(page, result))
                return page.url, opened, [e["state"] for e in result.events]
            finally:
                browser.close()

    def test_the_entrys_own_address_when_its_click_leaves_the_page_where_it_was(self):
        url, opened, states = self.run_entry("")
        self.assertEqual(url, "https://journal.example/action/ssostart")
        self.assertEqual(len(opened), 1)
        self.assertIn("sso_entry_opened", states)

    def test_nothing_more_when_the_sites_script_follows_it(self):
        url, opened, states = self.run_entry(
            "<script>document.querySelector('a').addEventListener('click', e => "
            "location.href = e.currentTarget.dataset.href + '?redirectUri=%2Fdoi%2F10.1000%2Fx')</script>")
        self.assertEqual(url, "https://journal.example/action/ssostart?redirectUri=%2Fdoi%2F10.1000%2Fx")
        self.assertEqual(len(opened), 1)
        self.assertNotIn("sso_entry_opened", states)

if __name__ == "__main__":
    unittest.main()

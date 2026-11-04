"""One rule for "this article's PDF" (batch_pdf_urls.py): the citation PDF bound by
its DOI, the page's own PDF links that name the article, the profile's formulas;
never a sharing, login, password or advertising link (2026-11-02)."""
import unittest
from unittest.mock import MagicMock, Mock, patch

from paper_search_carsi.browser.watchdog import BrowserUnresponsive
from paper_search_carsi.entitlements import UserSkippedArticle, UserStoppedBatch

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import get_publisher_profile

DOI = "10.1080/00222937500770001"
ARTICLE = "https://www.tandfonline.com/doi/abs/10.1080/00222937500770001"
PDF = "https://www.tandfonline.com/doi/pdf/10.1080/00222937500770001"


def page(url=ARTICLE, **found):
    p = MagicMock()
    p.url = url
    p.evaluate.return_value = found
    return p


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=get_publisher_profile("taylor & francis"))

    def test_share_login_password_and_ad_links_are_never_pdf_candidates(self):
        # J Nat Hist 1975 without access: these were tried as PDFs for 80 s (2026-11-02).
        found = {"dois": [DOI], "pdfs": [], "links": [
            "https://www.addtoany.com/share#url=https%3A%2F%2Fwww.tandfonline.com%2Fdoi%2Fpdf%2F10.1080%2F00222937500770001",
            "https://www.tandfonline.com/action/showLogin?uri=%2Fdoi%2Fpdf%2F10.1080%2F00222937500770001",
            "https://www.tandfonline.com/action/clickThrough?id=1&url=%2Fdoi%2Fpdf%2F10.1080%2F00222937500770001",
            "https://www.tandfonline.com/action/requestResetPassword?redirectUri=%2Fdoi%2Fpdf%2F10.1080%2F00222937500770001",
            "https://www.tandfonline.com/doi/pdf/10.1080/00222937500770001?needAccess=true",
            "https://www.tandfonline.com/doi/pdf/10.1080/00222937500770999",
            "https://www.tandfonline.com/doi/suppl/10.1080/00222937500770001/suppl_file/x.pdf",
        ]}
        urls = self.d._pdf_candidates(page(**found), DOI)
        self.assertIn(PDF + "?needAccess=true", urls)
        for url in urls:
            self.assertTrue(url.startswith("https://www.tandfonline.com/doi/"), url)
            self.assertIn(DOI, url)
            self.assertNotIn("suppl", url)

    def test_the_citation_pdf_counts_only_with_this_doi_alone(self):
        for found, expected in (({"dois": [DOI], "pdfs": [PDF]}, [PDF]),
                                ({"dois": ["doi:" + DOI.upper()], "pdfs": [PDF]}, [PDF]),
                                ({"dois": [DOI, "10.1080/other"], "pdfs": [PDF]}, []),
                                ({"dois": ["10.1080/other"], "pdfs": [PDF]}, []),
                                ({"dois": [DOI], "pdfs": [PDF.replace("www.tandfonline.com", "cdn.example.invalid")]}, []),
                                ({"dois": [DOI], "pdfs": [ARTICLE]}, [])):
            self.assertEqual(self.d._citation_pdf_urls(page(**found), DOI), expected, found)

    def test_the_article_is_named_by_its_doi_its_pii_or_the_pages_own_id(self):
        keys = self.d._article_keys("https://www.sciencedirect.com/science/article/pii/S0140673675900011", "10.1016/S0140-6736(75)90001-1")
        self.assertIn("s0140673675900011", keys)
        self.assertIn("10.1016/s0140-6736(75)90001-1", keys)
        keys = self.d._article_keys("https://ieeexplore.ieee.org/document/9123456/", "10.1109/x.2020.1")
        self.assertIn("9123456", keys)
        self.assertTrue(self.d._article_pdf_link("https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=9123456", keys,
                                                 "https://ieeexplore.ieee.org/document/9123456/"))
        self.assertFalse(self.d._article_pdf_link("https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=9000001", keys,
                                                  "https://ieeexplore.ieee.org/document/9123456/"))


class ClickTests(unittest.TestCase):
    """The PDF control clicked is the one naming this article, in this tab."""

    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=get_publisher_profile("taylor & francis"))
        self.result = DownloadResult(doi=DOI, status="failed")
        self.links = []
        self.controls = []
        self.page = MagicMock()
        self.page.url = ARTICLE
        self.page.evaluate.side_effect = self.evaluate
        self.page.locator.side_effect = lambda selector: SimpleLocator(self.controls)

    def evaluate(self, script, *args):
        if script == self.d._LINKS_JS:
            return self.links
        return {} if "citation_doi" in script else False  # no metadata, no gate

    def link(self, href, label="PDF"):
        control = Mock()
        control.is_visible.return_value = True
        self.controls.append(control)
        self.links.append({"href": href, "label": label, "visible": True, "in_references": False})
        return control

    def test_the_link_naming_this_article_comes_before_a_generic_pdf_control(self):
        share = self.link("https://www.tandfonline.com/action/showLogin?uri=%2Fdoi%2Fpdf%2F" + DOI.replace("/", "%2F"), "PDF")
        cited = self.link("/doi/pdf/10.1080/00000000000000000", "PDF")  # a reference's PDF outside the list's markup
        own = self.link("/doi/pdf/" + DOI + "?needAccess=true", "Download PDF")
        self.assertTrue(self.d._click_pdf_entry(self.page, self.result, doi=DOI))
        own.click.assert_called_once()
        share.click.assert_not_called()
        cited.click.assert_not_called()
        self.assertEqual(self.result.events[-1]["detail"], "current-doi-pdf-link")

    def test_terminal_error_from_article_link_stops_before_other_controls(self):
        for error in (BrowserUnresponsive("first stalled call"), UserSkippedArticle("skip"),
                      UserStoppedBatch("stop")):
            with self.subTest(error=type(error).__name__):
                self.links.clear()
                self.controls.clear()
                control = self.link("/doi/pdf/" + DOI)
                control.evaluate.side_effect = error
                with self.assertRaises(type(error)) as caught:
                    self.d._click_pdf_entry(self.page, self.result, doi=DOI)
                self.assertIs(caught.exception, error)
                control.click.assert_not_called()

    def test_terminal_error_in_last_script_is_not_a_missing_pdf_button(self):
        error = BrowserUnresponsive("original PDF script stalled")
        self.page.evaluate.side_effect = error
        with patch.object(self.d, "_bound_pdf_urls", return_value=[]), \
                patch.object(self.d, "_metadata_pdf_urls", return_value=[]), \
                patch.object(self.d, "_access_gate_visible", return_value=False), \
                patch.object(self.d, "_click_article_link", return_value=False):
            with self.assertRaises(BrowserUnresponsive) as caught:
                self.d._click_pdf_entry(self.page, self.result, doi=DOI)
        self.assertIs(caught.exception, error)
        self.page.evaluate.assert_called_once()


class SimpleLocator:
    def __init__(self, controls):
        self.controls = controls

    def nth(self, index):
        return self.controls[index]

    def all(self):
        return []


if __name__ == "__main__":
    unittest.main()

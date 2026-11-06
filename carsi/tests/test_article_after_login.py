"""After this item's school login the PDF is tried on its article: JAMA's login came
back to store.jamanetwork.com/index.aspx and the PDF step read that page's metadata
("citation_doi: none"), ending as "PDF not captured" (10.1001/jama.2026.20039,
2026-11-02); Wiley's once to /search/advanced. Mocked pages."""
import unittest
from unittest.mock import MagicMock, Mock

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.model import PublisherProfile

DOI = "10.1001/jama.2026.20039"
ARTICLE = "https://doi.org/" + DOI
FULLTEXT = "https://jamanetwork.com/journals/jama/fullarticle/2856275"
STORE = "https://store.jamanetwork.com/index.aspx"
# A profile as broad as JAMA's: every jamanetwork.com page counts as an article page.
PROFILE = PublisherProfile(name="Fixture Press", article_url_template="https://doi.org/{doi}", pdf_url_templates=(),
                           success_url_markers=("jamanetwork.com/",), auth_url_markers=("/login",),
                           auth_title_markers=(), sso_text_markers=(), base_domains=("jamanetwork.com",))


class ArticleAfterLoginTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=PROFILE)
        self.result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE, final_url=FULLTEXT)
        self.result.events.append({"state": "institution_selected", "detail": "Hong Mu-Lan University (entityID)"})
        self.result._visited_idp = True
        self.d._item_result = self.result
        for name in ("_challenge_shell", "_wait_past_redirect_page", "_dismiss_cookie_banners"):
            setattr(self.d, name, Mock(return_value=False))
        self.d._wait_for_challenge = Mock(return_value=True)
        self.d._title = Mock(return_value="Store Home | JAMA Network")

    def page(self, url, dois=()):
        page = MagicMock()
        page.url = url
        page.evaluate.side_effect = lambda script, *a: {"dois": list(dois), "pdfs": [], "links": []} \
            if "citation_doi" in script else ["complete", 4000]
        return page

    def test_a_store_page_after_the_login_goes_back_to_the_article_once(self):
        page = self.page(STORE)
        self.d._return_to_article_after_login(page, self.result)
        page.goto.assert_called_once_with(ARTICLE, wait_until="commit", timeout=60_000)
        event = next(e for e in self.result.events if e["state"] == "record_article_return")
        self.assertIn(STORE, event["detail"])
        self.d._wait_for_challenge.assert_called_once()
        self.d._return_to_article_after_login(page, self.result)
        page.goto.assert_called_once()  # once per item

    def test_this_article_s_own_pages_stay(self):
        for url, dois in ((FULLTEXT + "?resultClick=1", ()), ("https://jamanetwork.com/journals/jama/article-abstract/2856275", ()),
                          ("https://jamanetwork.com/journals/jama/fullarticle/9999999", (DOI.upper(),)),
                          ("https://jamanetwork.com/doi/" + DOI, ())):
            with self.subTest(url=url):
                page = self.page(url, dois)
                self.d._return_to_article_after_login(page, self.result)
                page.goto.assert_not_called()

    def test_the_page_the_login_started_from_names_the_article(self):
        # The Lancet 1975: the login started on ScienceDirect's abstract and came back to its article page.
        self.result.final_url = "https://www.thelancet.com/journals/lancet/article/PIIS0140-6736(75)92262-X/fulltext"
        self.result.events.append({"state": "sso_start",
                                   "detail": "https://jamanetwork.com/science/article/abs/pii/S014067367592262X"})
        page = self.page("https://jamanetwork.com/science/article/pii/S014067367592262X")
        self.d._return_to_article_after_login(page, self.result)
        page.goto.assert_not_called()

    def test_without_the_school_s_login_or_on_a_login_page_nothing_moves(self):
        self.result._visited_idp = False  # the school was selected but the IdP was not reached
        page = self.page(STORE)
        self.d._return_to_article_after_login(page, self.result)
        page.goto.assert_not_called()
        self.result._visited_idp = True
        page = self.page("https://jamanetwork.com/login?return=1")
        self.d._return_to_article_after_login(page, self.result)
        page.goto.assert_not_called()

    def test_a_completed_login_returns_to_the_article_before_the_pdf(self):
        self.d._complete_login_steps = Mock(return_value=True)
        self.d._return_to_article_after_login = Mock()
        page = self.page(STORE)
        self.assertTrue(self.d._complete_login_from_current_page(page, self.result))
        self.d._return_to_article_after_login.assert_called_once_with(page, self.result)
        self.d._complete_login_steps.return_value = False
        self.assertFalse(self.d._complete_login_from_current_page(page, self.result))
        self.d._return_to_article_after_login.assert_called_once()


if __name__ == "__main__":
    unittest.main()

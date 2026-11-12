"""The diagnostic's access state is the engine's own judgement (``_access_decision``
and the denial to the school) of the open tabs, not a second set of words (review
2026-11-02); a page whose text could not be read says so."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from patchright.sync_api import Error as PlaywrightError

from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile

# Not "Example ...": a line next to that word reads as help copy (access_rules._DENIAL_CONTEXT).
SCHOOL = {"publisher_institution_federation": "carsi", "school_name": "Fixture University",
          "school_name_en": "Fixture University"}
SPRINGER = "https://link.springer.com/article/10.1007/x"
WILEY = "https://onlinelibrary.wiley.com/doi/10.1111/x"


def tab(text, url=SPRINGER, **probe):
    page = MagicMock()
    page.url = url
    page.is_closed.return_value = False
    page.locator.return_value.inner_text.return_value = text
    page.evaluate.return_value = probe
    return page


class AccessStateTests(unittest.TestCase):
    def state(self, *tabs, publisher="springer", school_chosen=False):
        d = PublisherBatchDownloader(dict(SCHOOL), profile=get_publisher_profile(publisher))
        d._item_result = SimpleNamespace(_visited_idp=school_chosen, events=[{"state": "institution_selected", "detail": "Fixture University"}]
                                         if school_chosen else [])
        tabs[0].context.pages = list(tabs)
        return d._access_state(tabs[0])

    def test_not_logged_in(self):
        state, evidence = self.state(tab("Log in via an institution\nBuy article PDF 39,95 €"))
        self.assertEqual(state, "not_logged_in")
        self.assertEqual(evidence, [f"{SPRINGER} | out (closed): Buy article PDF 39,95 €"])

    def test_logged_in_but_no_entitlement(self):
        sciencedirect = "https://www.sciencedirect.com/science/chapter/edited-volume/abs/pii/B9780443222535000285"
        state, evidence = self.state(tab("Brought to you by:\nFixture University\n"
                                         "Fixture University does not subscribe to this content on ScienceDirect.\n"
                                         "Purchase chapter", sciencedirect), publisher="elsevier")
        self.assertEqual(state, "logged_in_no_entitlement")
        self.assertIn('denial line: "Fixture University does not subscribe to this content on ScienceDirect."',
                      evidence[0])

    def test_logged_in_by_the_session_and_readable_without_it(self):
        state, evidence = self.state(tab("Access provided by Fixture University\nDownload PDF"))
        self.assertEqual(state, "logged_in")
        self.assertEqual(evidence, [f"{SPRINGER} | in (session): session line: Fixture University"])
        self.assertEqual(self.state(tab("Download PDF", badges=["Open Access"]))[0], "readable")

    def test_wiley_denial_panel_in_another_tab_after_the_school_s_login(self):
        article = tab("Access by Fixture University", url=WILEY)
        reader = tab("", url="https://onlinelibrary.wiley.com/doi/epdf/10.1111/x#accessDenialLayout")
        state, evidence = self.state(article, reader, publisher="wiley", school_chosen=True)
        self.assertEqual(state, "logged_in_no_entitlement")
        self.assertEqual(len(evidence), 2)
        self.assertIn("denial address: accessdeniallayout", evidence[1])

    def test_subscriber_only_label_is_not_access(self):
        state, evidence = self.state(tab("Check Access\nFull Text Access for Subscribers"))
        self.assertEqual(state, "not_logged_in")
        self.assertTrue(any("Check Access" in e for e in evidence))

    def test_a_login_page_means_not_logged_in_and_nothing_means_unknown(self):
        self.assertEqual(self.state(tab("Welcome", url="https://idp.example.edu.cn/login", password=True))[0],
                         "not_logged_in")
        state, evidence = self.state(tab("An ordinary page"))
        self.assertEqual(state, "unknown")
        self.assertEqual(evidence, [f"{SPRINGER} | unknown (no rule): "])

    def test_a_page_whose_text_could_not_be_read_says_so(self):
        page = tab("")
        page.locator.return_value.inner_text.side_effect = PlaywrightError(
            "Locator.inner_text: Execution context was destroyed, most likely because of a navigation")
        state, evidence = self.state(page)
        self.assertEqual(state, "unknown")
        self.assertIn("page text unreadable (Error: Locator.inner_text: Execution context was destroyed", evidence[0])
        d = PublisherBatchDownloader(dict(SCHOOL), profile=get_publisher_profile("springer"))
        verdict, basis, unread = d._access_decision(page)
        self.assertEqual((verdict, basis), ("unknown", ""))
        found = d._checks_found_nothing(page, unread)
        self.assertTrue(found.startswith("page text unreadable"))
        self.assertNotIn("login page no", found)  # it does not claim the page was read
        page.locator.return_value.inner_text.side_effect = KeyError("program error")
        with self.assertRaises(KeyError):
            d._access_decision(page)


if __name__ == "__main__":
    unittest.main()

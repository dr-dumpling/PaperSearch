"""The shared access rule (engine/access_rules.py): in, out or unknown for any publisher."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from paper_search_carsi.engine import access_rules as rules
from paper_search_carsi.engine.batch import PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import get_publisher_profile

SCHOOL = {"publisher_institution_federation": "carsi", "carsi_idp_name": "红木兰大学",
          "carsi_idp_name_en": "Hong Mu-lan University"}
WILEY = "https://physoc.onlinelibrary.wiley.com/doi/10.1113/jphysiol.1965.sp007773"


def page(url, body="", **probe):
    p = MagicMock()
    p.url = url
    p.locator.return_value.inner_text.return_value = body
    p.evaluate.return_value = probe
    return p


class AuthPageTests(unittest.TestCase):
    def test_login_idp_and_chooser_addresses_in_host_and_path(self):
        for url in ("https://www.tandfonline.com/action/showLogin?uri=%2Fdoi%2Fpdf%2F10.1080%2Fx",
                    "https://dl.acm.org/action/showLogin", "https://login.openathens.net/auth/logon",
                    "https://wayf.springernature.com/?redirect_uri=x", "https://journals.aps.org/login",
                    "https://www.thieme-connect.de/HTML/sso/THIEME/login.htm",
                    "https://onlinelibrary.wiley.com/action/ssostart?redirectUri=%2Fdoi%2F10.1002%2Fx",
                    "https://pubs.rsc.org/institutional-login", "https://auth.elsevier.com/ShibAuth/institutionLogin"):
            self.assertTrue(rules.is_auth_url(url), url)

    def test_a_return_address_in_the_query_is_not_the_page(self):
        for url in ("https://academic.oup.com/aje/article-abstract/122/2/253/76983?redirectedFrom=fulltext&login=true",
                    "https://www.tandfonline.com/doi/full/10.1080/x?return=/login",
                    "https://onlinelibrary.wiley.com/doi/10.1002/x"):
            self.assertFalse(rules.is_auth_url(url), url)

    def test_profile_markers_count_in_any_case(self):
        # "/action/showLogin" in seven profiles never matched the lower-case URL (before 2026-11-02).
        self.assertTrue(rules.is_auth_url("https://pubs.aip.org/action/showLogin", ("/action/showLogin",)))


class RegistrableDomainTests(unittest.TestCase):
    def test_second_level_country_suffixes_keep_the_site_s_own_name(self):
        # www.jstage.jst.go.jp was "go.jp" and koreascience.or.kr "or.kr" (review 2026-11-02).
        for host, domain in (("www.jstage.jst.go.jp", "jst.go.jp"), ("koreascience.or.kr", "koreascience.or.kr"),
                             ("www.koreascience.or.kr", "koreascience.or.kr"), ("www.niph.go.jp", "niph.go.jp"),
                             ("www.example.ne.jp", "example.ne.jp"), ("idp.example.ac.jp", "example.ac.jp"),
                             ("www.example.co.jp", "example.co.jp"), ("www.example.ed.jp", "example.ed.jp"),
                             ("www.example.or.jp", "example.or.jp"), ("www.example.co.kr", "example.co.kr"),
                             ("idp.example.ac.kr", "example.ac.kr"), ("www.example.go.kr", "example.go.kr"),
                             ("www.kisti.re.kr", "kisti.re.kr"), ("www.isciii.gob.es", "isciii.gob.es"),
                             ("www.england.nhs.uk", "england.nhs.uk")):
            self.assertEqual(rules.registrable_domain(host), domain, host)

    def test_ordinary_domains_are_unchanged(self):
        for host, domain in (("www.cambridge.org", "cambridge.org"), ("idp.example.edu.cn", "example.edu.cn"),
                             ("journals.example.co", "example.co"), ("onlinelibrary.wiley.com", "wiley.com"),
                             ("www.go.com", "go.com"), ("jst.go.jp", "jst.go.jp"), ("go.jp", "go.jp")):
            self.assertEqual(rules.registrable_domain(host), domain, host)


class SessionTests(unittest.TestCase):
    def d(self, config=SCHOOL, publisher="wiley"):
        return PublisherBatchDownloader(dict(config), profile=get_publisher_profile(publisher))

    def test_session_lines_anywhere_on_the_page(self):
        long_page = "Abstract text. " * 2000
        for body in (long_page + "\nBrought to you by:\nHong Mu-lan University",
                     long_page + "\nYou have full access to this article via Hong Mu-lan University.",
                     "Access provided by 红木兰大学", "Access ByHong Mu lan University",
                     "Logged in through your institution: Hong Mu-lan University"):
            self.assertTrue(self.d()._has_publisher_institution_session(page(WILEY, body)), body[-60:])

    def test_another_school_generic_words_help_and_quotes_are_not_our_session(self):
        d = self.d()
        d._item_result = SimpleNamespace(events=[])
        d._event = lambda r, state, detail="": r.events.append({"state": state, "detail": detail})
        self.assertEqual(d._institution_session(page(WILEY, "Brought to you by: Peking University")), "other")
        for body in ("You have full access to this article via your institution.",
                     "FAQ\nYou have full access to this article via Hong Mu-lan University.",
                     '"Access provided by Hong Mu-lan University"',
                     "Provided by the Springer Nature SharedIt content-sharing initiative",
                     "Department of Medicine, Hong Mu-lan University"):
            self.assertIsNone(self.d()._institution_session(page(WILEY, body)), body)

    def test_header_labels_name_the_school(self):
        # Wiley's society and main sites show the school next to the logo (2026-11-02).
        self.assertTrue(self.d()._has_publisher_institution_session(page(WILEY, labels=["Hong Mu lan University"])))
        for labels in (["Institutional Login"], ["Log in via your institution"], ["Find your institution"]):
            self.assertFalse(self.d()._has_publisher_institution_session(page(WILEY, labels=labels)), labels)
        self.assertEqual(self.d()._institution_session(page(WILEY, labels=["Peking University"])), "other")

    def test_session_only_on_the_publishers_own_site(self):
        self.assertFalse(self.d()._has_publisher_institution_session(
            page("https://onlinelibrary.wiley.com.example.invalid/doi/10.1002/x", "Brought to you by: Hong Mu-lan University")))


class VerdictTests(unittest.TestCase):
    def d(self, publisher="wiley"):
        return PublisherBatchDownloader(dict(SCHOOL), profile=get_publisher_profile(publisher))

    def test_old_signed_in_pages_without_full_text_sections_are_in(self):
        # J Physiol 1965, BJH 1980, SID Symposium Digest: only "Full Access" by the title (2026-11-02).
        self.assertEqual(self.d()._access_verdict(page(WILEY, "PDF", badges=["Full Access"])), "in")
        self.assertEqual(self.d()._access_verdict(page(WILEY, "PDF", sections=True)), "in")

    def test_nothing_either_way_is_unknown(self):
        self.assertEqual(self.d()._access_verdict(page(WILEY, "Abstract\nPDF\nRead the full text\nInstitutional Login")),
                         "unknown")

    def test_offers_denials_gates_and_password_fields_are_out(self):
        for kwargs in ({"body": "Buy article PDF 39,95 €"}, {"body": "Purchase PDF"}, {"body": "Check Access"},
                       {"body": "This is a preview of subscription content, log in via an institution."},
                       {"body": "You do not currently have access to this content."},
                       {"offers": ["Buy this article ($64)"]}, {"gate": "Access through Hong Mu-lan University"},
                       {"password": True}, {"paywall": True}, {"denial_panel": True}):
            body = kwargs.pop("body", "")
            self.assertEqual(self.d()._access_verdict(page(WILEY, body, **kwargs)), "out", (body, kwargs))

    def test_abstract_only_views_are_out_and_the_session_wins(self):
        d = self.d("oxford academic")
        abstract = "https://academic.oup.com/brain/article-abstract/91/1/1/123"
        self.assertEqual(d._access_verdict(page(abstract, "Abstract", badges=["Free access"])), "out")
        self.assertEqual(d._access_verdict(page(abstract, "Brought to you by: Hong Mu-lan University")), "in")

    def test_reader_access_beats_offers_and_the_session_beats_everything(self):
        self.assertEqual(self.d()._access_verdict(page(WILEY, "Buy article PDF", badges=["Open Access"])), "in")
        self.assertEqual(self.d()._access_verdict(
            page(WILEY, "Brought to you by: Hong Mu-lan University\nBuy article PDF")), "in")


class DenialTests(unittest.TestCase):
    def d(self, config=SCHOOL):
        d = PublisherBatchDownloader(dict(config), profile=get_publisher_profile("oxford academic"))
        d._item_result = SimpleNamespace(events=[])
        return d

    ARTICLE = "https://academic.oup.com/aje/article-abstract/122/2/253/76983"

    def test_after_the_schools_login_a_denial_is_no_entitlement_not_another_login(self):
        # Brain 1968 and AJE 1985 chose the school three times (2026-11-02).
        url = self.ARTICLE + "?redirectedFrom=fulltext&login=true#no-access-message"
        d = self.d()
        self.assertFalse(d._institution_pdf_entitlement_missing(page(url, "Abstract")))  # not signed in yet: sign in
        d._item_result.events.append({"state": "institution_selected", "detail": "Hong Mu-lan University"})
        self.assertFalse(d._institution_pdf_entitlement_missing(page(url, "Abstract")))
        d._item_result._visited_idp = True
        self.assertTrue(d._institution_pdf_entitlement_missing(page(url, "Abstract")))
        self.assertTrue(d._institution_pdf_entitlement_missing(
            page(self.ARTICLE, "Abstract\nYou do not currently have access to this article.")))

    def test_a_denial_naming_the_school_needs_no_session(self):
        body = "Hong Mu-lan University does not subscribe to this content on ScienceDirect."
        self.assertTrue(self.d()._institution_pdf_entitlement_missing(page(self.ARTICLE, body)))
        self.assertFalse(self.d()._institution_pdf_entitlement_missing(page(self.ARTICLE, body.replace("Hong Mu-lan", "Peking"))))

    def test_conditional_quoted_and_help_copy_is_no_denial(self):
        for text in ("If you do not have access to this article, contact your librarian.",
                     "FAQ: You do not have access to this article.", "Help\nYou do not have access to this PDF.",
                     '"You do not have access to this article."', "You do not have access to this article?"):
            self.assertFalse(rules.has_denial_line(text), text)
        self.assertTrue(rules.has_denial_line("Abstract\nYou do not currently have access to this content."))

    def test_snapshot_without_denial_needs_no_more_browser_reads(self):
        d = self.d()
        p = page(self.ARTICLE.replace("article-abstract", "article"), "Open Access\nFull text", badges=["Open Access"])
        snapshot = d._access_snapshot(p)
        p.title.side_effect = AssertionError("unnecessary live title read")
        p.evaluate.side_effect = AssertionError("unnecessary live DOM read")
        p.locator.side_effect = AssertionError("unnecessary live text read")
        self.assertFalse(d._institution_pdf_entitlement_missing(p, snapshot=snapshot))

    def test_denial_snapshot_still_checks_for_a_verification_page(self):
        d = self.d()
        p = page(self.ARTICLE, "You do not currently have access to this article.")
        snapshot = d._access_snapshot(p)
        d._school_login_done = MagicMock(return_value=True)
        for challenge in (True, False):
            with self.subTest(challenge=challenge):
                d._is_challenge_page = MagicMock(return_value=challenge)
                self.assertEqual(d._institution_pdf_entitlement_missing(p, snapshot=snapshot), not challenge)
                d._is_challenge_page.assert_called_once_with(p)

    def test_without_snapshot_verification_precedes_reading_the_document(self):
        d = self.d()
        p = page(self.ARTICLE)
        d._is_challenge_page = MagicMock(return_value=True)
        d._access_snapshot = MagicMock(side_effect=AssertionError("do not inspect a verification page"))
        self.assertFalse(d._institution_pdf_entitlement_missing(p))


if __name__ == "__main__":
    unittest.main()

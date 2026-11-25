"""PDF first when the page says nothing either way; one login after a failed PDF;
the login wait tries the PDF after each login round trip and every 15 seconds
(ASCE, 2026-11-02: signed in at 11:54:50, back on the article at 11:55:02, idle
until the five minutes ran out)."""
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pymupdf

from paper_search_school.engine import batch
from paper_search_school.engine.batch import DownloadResult, PaperRecord, PublisherBatchDownloader
from paper_search_school.engine.batch_user import PdfFoundWhileWaiting
from paper_search_school.publishers.model import PublisherProfile
from paper_search_school.publishers.profiles import infer_publisher_profile
from tests.thread_clock import this_thread_only

DOI = "10.1061/jsendh.steng-16404"
TITLE = "Synthetic structural engineering article for the PDF probe"
ARTICLE = "https://ascelibrary.org/doi/10.1061/JSENDH.STENG-16404"
PDF = "https://ascelibrary.org/doi/pdf/10.1061/JSENDH.STENG-16404"
IDP = "https://idp.school.edu.cn/idp/profile/SAML2/Redirect/SSO"
PROFILE = PublisherProfile(name="Fixture Press", article_url_template="https://ascelibrary.org/doi/{doi}",
                           pdf_url_templates=("https://ascelibrary.org/doi/pdf/{doi}",),
                           success_url_markers=("ascelibrary.org/doi/",), auth_url_markers=(),
                           auth_title_markers=(), sso_text_markers=(), base_domains=("ascelibrary.org",))


def pdf(doi=DOI, title=TITLE):
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 60), f"{title}\nDOI: {doi}\nAbstract\nResults and methods.")
        return document.tobytes() + b"\n%" + b"x" * 6000


class PdfFirstTests(unittest.TestCase):
    def downloader(self, **config):
        d = PublisherBatchDownloader(config, profile=PROFILE, login_timeout_sec=300)
        d._write_diagnostic = Mock()
        d._hold_after_login = Mock()
        d._hold_after_run = Mock()
        d._return_from_other_article = Mock()
        d._title = Mock(return_value="Article")
        return d

    def page(self, url=ARTICLE):
        page = MagicMock()
        page.url = url
        page.locator.return_value.inner_text.return_value = ""
        page.is_closed.return_value = False
        del page.new_page  # a page, not a context
        return page

    def test_unknown_or_reader_only_access_tries_the_pdf_and_says_so(self):
        d = self.downloader()
        # An open-access article gains nothing from the school's login: no login after its PDF.
        for decision, first in ((("unknown", "", ""), True), (("in", "reader", "badge: Full Access"), True),
                                (("in", "reader", "badge: Full text access"), True),
                                (("in", "reader", "badge: Open Access"), False),
                                (("in", "reader", "licence: is licensed under a Creative Commons"), False),
                                (("in", "session", ""), False)):
            result = DownloadResult(doi=DOI, status="failed")
            d._item_result = result
            d._access_decision = Mock(return_value=decision)
            self.assertTrue(d._pdf_first_unless_signed_out(self.page(), result))
            self.assertEqual(getattr(result, "_pdf_first", False), first, decision)
            self.assertEqual("access_unknown_pdf_first" in [e["state"] for e in result.events], first)
        d._access_decision = Mock(return_value=("out", "closed", "Get Access"))
        self.assertFalse(d._pdf_first_unless_signed_out(self.page(), DownloadResult(doi=DOI, status="failed")))

    def fetch(self, d, captures, logged_in=True):
        d._ensure_login = Mock(return_value=True)
        d._capture_pdf = Mock(side_effect=captures)
        d._complete_login_from_current_page = Mock(return_value=logged_in)
        d._reopen_article_page = Mock()
        d._save_captured_pdf = Mock(side_effect=lambda page, record, result, run_dir, body, url: result)
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
            return d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))

    def test_a_failed_pdf_without_the_session_signs_in_once_and_tries_again(self):
        d = self.downloader()
        d._access_decision = Mock(return_value=("unknown", "", ""))
        result = self.fetch(d, [(None, "", None), (pdf(), PDF, None)])
        self.assertEqual(d._capture_pdf.call_count, 2)
        d._complete_login_from_current_page.assert_called_once()
        d._reopen_article_page.assert_called_once()  # back to the article's own login entry
        d._save_captured_pdf.assert_called_once()
        states = [e["state"] for e in result.events]
        self.assertLess(states.index("access_unknown_pdf_first"), states.index("access_unknown_pdf_failed"))

    def test_a_login_after_the_pdf_that_ran_out_says_where_it_ended(self):
        # Thieme, Windows 2026-11-22: the wait ended on its school list page and did not say where, so it
        # counted as the user's (等学校登录超时); JAMA's ended on the school's own login page.
        for where in ("institution_chooser", "school_login"):
            with self.subTest(where=where):
                d = self.downloader()
                d._access_decision = Mock(return_value=("unknown", "", ""))
                d._article_access_available = Mock(return_value=False)
                d._login_wait_page = Mock(return_value=where)

                def ran_out(page, result):
                    result._user_wait_expired = True
                    return False

                d._ensure_login = Mock(return_value=True)
                d._capture_pdf = Mock(side_effect=[(None, "", None)])
                d._complete_login_from_current_page = Mock(side_effect=ran_out)
                d._reopen_article_page = Mock()
                with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
                    result = d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))
                self.assertEqual(result.login_wait_page, where)
                self.assertEqual([e["detail"] for e in result.events if e["state"] == "login_wait_ended"][:1], [where])

    def test_an_open_page_whose_pdf_entry_asks_for_access_signs_in_once(self):
        """PNAS 2026-11-17: a Creative Commons line in the copyright notes, "GET ACCESS" by the
        title, the PDF addresses 403 without the school's login."""
        for gate in (True, False):
            with self.subTest(gate=gate):
                d = self.downloader()
                d._access_decision = Mock(return_value=("in", "reader", "licence: is distributed under Creative Commons"))
                replies = iter([(None, "", None), (pdf(), PDF, None)])

                def capture(page, doi, result):
                    if gate:
                        d._event(result, "pdf_entry_gated", "get access / access through institution shown")
                    return next(replies)

                d._article_access_available = Mock(return_value=False)
                d._login_block_reason = Mock(return_value="")
                d._looks_logged_out = Mock(return_value=False)
                result = self.fetch(d, capture)
                states = [e["state"] for e in result.events]
                self.assertEqual(d._capture_pdf.call_count, 2 if gate else 1)
                self.assertEqual(d._complete_login_from_current_page.call_count, 1 if gate else 0)
                self.assertEqual("open_access_pdf_gated" in states, gate)
                self.assertNotIn("access_unknown_pdf_first", states)

    def test_an_open_page_whose_pdf_is_sent_to_the_article_page_signs_in_once(self):
        """Open for its web page only, or not at all (Windows 2026-11-23, both ended as
        pdf_not_captured with no school tried). JAMA: citation_fulltext_world_readable, its
        /articlepdf/ address answered with /fullarticle/. jacc.org: "This is an Open Access
        Article" read on a page with "GET ACCESS", its PDF addresses answering 403 with the
        article's page."""
        jama = "https://jamanetwork.com/journals/jama/fullarticle/2841034"
        jama_pdf = "https://jamanetwork.com/journals/jama/articlepdf/2841034/jama_isaka_2025_oi_250083_1764782053.74853.pdf"
        jacc = "https://www.jacc.org/doi/10.1016/j.jcmg.2025.09.021"
        jacc_pdfs = ("https://www.jacc.org/doi/pdf/10.1016/j.jcmg.2025.09.021",
                     "https://www.jacc.org/doi/epdf/10.1016/j.jcmg.2025.09.021")
        title = "Prognostic Value of AI-Based Quantitative Coronary CTA vs Human Reader-Based Visual Assessment"

        def attempt(how, url, final, outcome="html page", status=200):
            return {"how": how, "url": url, "final_url": final, "status": status, "type": "text/html",
                    "size": "", "outcome": outcome, "seconds": 5.0}

        cases = {
            "jama": ("10.1001/jama.2025.19316", jama, ("unknown", "", ""),
                     "open licence: meta citation_fulltext_world_readable", [],
                     [attempt("click", "jama-data-article-url", jama, "no pdf", None), attempt("url", jama_pdf, jama)], True),
            "jacc": ("10.1016/j.jcmg.2025.09.021", jacc, ("in", "reader", "licence: This is an Open Access Article"), "",
                     [f"403 {url} | {title}" for url in jacc_pdfs],
                     [attempt("url", url, url, status=403) for url in jacc_pdfs], True),
            # An HTML answer at the PDF's own address, without the article's title: not the article's page.
            "jacc, not the article's page": ("10.1016/j.jcmg.2025.09.021", jacc,
                                             ("in", "reader", "licence: This is an Open Access Article"), "", [],
                                             [attempt("url", url, url, status=403) for url in jacc_pdfs], False),
            # Nothing came back as the article's page.
            "jama, no answer": ("10.1001/jama.2025.19316", jama, ("unknown", "", ""),
                                "open licence: meta citation_fulltext_world_readable", [],
                                [attempt("click", "jama-data-article-url", jama, "no pdf", None)], False),
        }
        for name, (doi, article, decision, signal, answers, attempts, signs_in) in cases.items():
            with self.subTest(name):
                profile = infer_publisher_profile(doi)
                d = PublisherBatchDownloader({}, profile=profile, login_timeout_sec=300)
                for helper in ("_write_diagnostic", "_hold_after_login", "_hold_after_run", "_return_from_other_article"):
                    setattr(d, helper, Mock())
                d._title = Mock(return_value="Article")
                d._access_decision = Mock(return_value=decision)
                d._open_access_signal = Mock(return_value=signal)
                d._article_access_available = Mock(return_value=False)
                d._login_block_reason = Mock(return_value="")
                d._looks_logged_out = Mock(return_value=False)
                replies = iter([(None, "", None), (pdf(doi), article + ".pdf", None)])

                def capture(page, doi, result, answers=answers, attempts=attempts):
                    if not result.pdf_attempts:
                        for answer in answers:
                            d._event(result, "pdf_step_article_page", answer)
                        result.pdf_attempts.extend(attempts)
                    return next(replies)

                d._capture_pdf = Mock(side_effect=capture)
                d._complete_login_from_current_page = Mock(return_value=True)
                d._reopen_article_page = Mock()
                d._save_captured_pdf = Mock(side_effect=lambda page, record, result, run_dir, body, url: result)
                with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
                    result = d.fetch_one(self.page(article), PaperRecord(doi=doi), Path(directory))
                gated = [e["detail"] for e in result.events if e["state"] == "open_access_pdf_gated"]
                self.assertEqual(d._complete_login_from_current_page.call_count, 1 if signs_in else 0)
                self.assertEqual(d._capture_pdf.call_count, 2 if signs_in else 1)
                self.assertEqual(bool(gated), signs_in)
                if signs_in:
                    self.assertIn("PDF sent to the article's web page: " + attempts[-1]["url"][:120], gated[0])
                    d._save_captured_pdf.assert_called_once()
                else:
                    self.assertEqual(result.reason, "pdf_not_captured")

    def test_public_access_is_reused_only_until_the_main_document_changes(self):
        for navigation in (None, "iframe", "reload"):
            with self.subTest(navigation=navigation):
                d, page = self.downloader(), self.page()
                d._access_decision = Mock(return_value=("in", "reader", "badge: Free Access"))
                d._ensure_login = Mock(side_effect=d._pdf_first_unless_signed_out)
                d._capture_pdf = Mock(return_value=(pdf(), PDF, None))
                d._save_captured_pdf = Mock(side_effect=lambda p, rec, result, *args: result)

                def settle(*args):
                    if navigation:
                        for call in page.on.call_args_list:
                            if call.args[0] == "framenavigated":
                                call.args[1](page.main_frame if navigation == "reload" else object())

                with tempfile.TemporaryDirectory() as directory, patch.object(batch, "settle", side_effect=settle):
                    d.fetch_one(page, PaperRecord(doi=DOI), Path(directory))
                self.assertEqual(d._access_decision.call_count, 2 if navigation == "reload" else 1)
                d._capture_pdf.assert_called_once()
                for call in page.on.call_args_list:
                    page.remove_listener.assert_any_call(*call.args)

    def test_browser_timeout_is_preserved_without_running_final_page_work(self):
        from paper_search_school.browser.watchdog import BrowserUnresponsive
        d = self.downloader()
        d._ensure_login = Mock(side_effect=BrowserUnresponsive("Page.title timed out"))
        d._capture_reported_issues = Mock()
        with tempfile.TemporaryDirectory() as directory:
            result = d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))
        self.assertEqual((result.state, result.reason), ("browser_unresponsive", "browser_unresponsive"))
        d._capture_reported_issues.assert_not_called()
        d._hold_after_run.assert_not_called()

    def test_a_new_item_does_not_reuse_a_previous_articles_citation_title(self):
        d = self.downloader()
        d._expected_title = "The previous article's citation title"
        d._access_decision = Mock(return_value=("in", "session", ""))
        self.fetch(d, [(pdf(), PDF, None)])
        self.assertEqual(d._identity_title(), "")

    def test_without_a_login_to_do_the_failed_pdf_stays_the_reason(self):
        d = self.downloader()
        d._access_decision = Mock(return_value=("unknown", "", ""))
        d._article_access_available = Mock(return_value=False)
        d._login_block_reason = Mock(return_value="")
        result = self.fetch(d, [(None, "", None)], logged_in=False)
        self.assertEqual(result.reason, "pdf_not_captured")
        self.assertEqual(d._capture_pdf.call_count, 1)

    def test_with_the_institutions_session_a_failed_pdf_is_not_a_login(self):
        d = self.downloader()
        d._access_decision = Mock(return_value=("in", "session", ""))
        d._login_block_reason = Mock(return_value="")
        result = self.fetch(d, [(None, "", None)])
        self.assertEqual(result.reason, "pdf_not_captured")
        d._complete_login_from_current_page.assert_not_called()

    def test_a_pdf_found_while_the_login_waits_is_saved(self):
        d = self.downloader()
        body = pdf()
        d._ensure_login = Mock(side_effect=PdfFoundWhileWaiting(body, PDF))
        d._save_captured_pdf = Mock(side_effect=lambda page, record, result, run_dir, body, url: result)
        with tempfile.TemporaryDirectory() as directory:
            result = d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))
        self.assertEqual(d._save_captured_pdf.call_args.args[4:], (body, PDF))
        self.assertIn("pdf_found_while_waiting", [e["state"] for e in result.events])

    def test_the_pdf_step_stops_on_a_login_page_instead_of_waiting_for_a_403(self):
        # Taylor & Francis J Nat Hist 1975: "Read this article" led to /action/showLogin (2026-11-02).
        d = self.downloader()
        result = DownloadResult(doi=DOI, status="failed")
        d._pdf_viewer_present = Mock(return_value=False)
        login = self.page("https://ascelibrary.org/action/showLogin?uri=%2Fdoi%2Fpdf%2F10.1061%2Fx")
        captured = {}
        self.assertTrue(d._pdf_step_hit_wall(login, result, captured))
        self.assertTrue(captured["login_wall"])
        self.assertEqual(result.events[-1]["state"], "pdf_step_login_required")
        self.assertTrue(d._pdf_step_login_required(result))
        article = self.page()
        article.locator.return_value.inner_text.return_value = "Abstract"
        article.evaluate.return_value = {}
        self.assertFalse(d._pdf_step_hit_wall(article, DownloadResult(doi=DOI, status="failed")))
        article.evaluate.return_value = {"gate": "Access through Hong Mu-lan University"}  # ScienceDirect's pdfft, The Lancet
        self.assertTrue(d._pdf_step_hit_wall(article, DownloadResult(doi=DOI, status="failed")))

    def test_the_login_after_a_failed_pdf_needs_an_institution_entry(self):
        d = self.downloader()
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        result._pdf_retry_login = True
        d._item_result = result
        for name in ("_dismiss_cookie_banners", "_click_sso_entry", "_institution_pdf_entitlement_missing",
                     "_is_human_login_page", "_challenge_shell"):
            setattr(d, name, Mock(return_value=False))
        with patch.object(batch.time, "sleep"):
            self.assertFalse(d._complete_login_from_current_page(self.page(), result))
        self.assertIn("login_entry_missing", [e["state"] for e in result.events])


class SaveIdentityTests(unittest.TestCase):
    """The save-time check reads the article's title too (review, 2026-11-02): a PDF the
    capture accepted by its exact title is not refused for citing another DOI."""

    downloader, page = PdfFirstTests.downloader, PdfFirstTests.page

    def body(self):
        with pymupdf.open() as document:
            document.new_page().insert_text(
                (40, 60), f"{TITLE}\nSee the related editorial https://doi.org/10.1000/other.2026.1\nAbstract\nResults.")
            return document.tobytes() + b"\n%" + b"x" * 6000

    def saved(self, title, body=None):
        d = self.downloader()
        d._expected_title = title
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        d._item_result = result
        with tempfile.TemporaryDirectory() as directory, patch.object(d, "_save_publisher_session", Mock()), \
                patch.object(d, "_write_diagnostic", Mock()):
            result = d._save_captured_pdf(self.page(), PaperRecord(doi=DOI), result, Path(directory),
                                          self.body() if body is None else body, ARTICLE.replace("/doi/", "/doi/pdf/"))
        return result

    def test_the_title_keeps_a_pdf_that_cites_another_doi(self):
        self.assertNotEqual(self.saved(TITLE).state, "pdf_wrong_article")
        self.assertEqual(self.saved("").state, "pdf_wrong_article")

    def test_citation_identity_is_kept_when_the_page_title_was_unavailable(self):
        self.assertTrue(self.saved(TITLE, pdf(doi="")).verified_match)
        self.assertEqual(self.saved("A completely different article about unrelated experiments").state,
                         "pdf_wrong_article")


class LoginWaitProbeTests(unittest.TestCase):
    """The login loop with a fake clock: where the page is, and what the probe finds."""

    def loop(self, urls, probes, no_access=""):
        d = PublisherBatchDownloader({}, profile=PROFILE, login_timeout_sec=300)
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        d._item_result = result
        for name in ("_dismiss_cookie_banners", "_click_openathens_entry", "_select_institution",
                     "_institution_pdf_entitlement_missing", "_challenge_shell", "_follow_federated_login_option",
                     "_return_to_record_article_if_needed", "_article_access_available",
                     "_has_publisher_institution_session", "_is_challenge_page", "_click_optional_continue",
                     "_return_from_login_site", "_is_human_login_page", "_check_user_decision"):
            setattr(d, name, Mock(return_value=False))
        d._click_sso_entry = Mock(return_value=True)
        d._login_block_reason = Mock(return_value="")
        d._title = Mock(return_value="Article")
        d._looks_logged_out = Mock(return_value=True)  # "GET ACCESS" stays on the page
        d._probe_pdf = Mock(side_effect=probes)
        d._no_access_after_login = Mock(return_value=no_access)
        page = MagicMock()
        page.url = urls[0]
        page.evaluate.return_value = ""
        page.locator.return_value.inner_text.return_value = ""
        clock = [1000.0]
        steps = iter(urls[1:])

        def sleep(seconds):
            clock[0] += seconds
            page.url = next(steps, page.url)
        fake_time, fake_sleep = this_thread_only(lambda: clock[0], sleep)
        with patch.object(batch.time, "sleep", fake_sleep), patch.object(batch.time, "time", fake_time):
            try:
                return d, result, d._complete_login_from_current_page(page, result), clock[0] - 1000
            except PdfFoundWhileWaiting as found:
                return d, result, found, clock[0] - 1000

    def test_back_from_the_school_login_the_pdf_is_tried_at_once(self):
        d, result, outcome, waited = self.loop([ARTICLE, IDP, IDP, ARTICLE], [(pdf(), PDF)])
        self.assertIsInstance(outcome, PdfFoundWhileWaiting)
        self.assertEqual(outcome.url, PDF)
        self.assertLess(waited, 10)
        self.assertIn("login_round_trip_returned", [e["state"] for e in result.events])
        self.assertEqual(d._probe_pdf.call_count, 1)

    def test_back_from_the_school_login_and_still_offered_ends_as_not_subscribed(self):
        d, result, outcome, waited = self.loop([ARTICLE, IDP, ARTICLE], [None], no_access="Get Access")
        self.assertIs(outcome, False)
        self.assertEqual(result.reason, "institution_pdf_entitlement_missing")
        self.assertIn("no_access_after_login", [e["state"] for e in result.events])
        self.assertLess(waited, 10)

    def test_back_from_the_school_login_with_nothing_conclusive_the_wait_goes_on_for_a_page_wait(self):
        d, result, outcome, waited = self.loop([ARTICLE, IDP, ARTICLE], [None] * 40)
        self.assertIs(outcome, False)
        # Off the school's login page a wait lasts a page wait (60 s), not the article's whole wait.
        self.assertGreaterEqual(waited, 60)
        self.assertLess(waited, 300)
        self.assertNotEqual(result.reason, "institution_pdf_entitlement_missing")

    def test_waiting_on_the_article_page_tries_the_pdf_every_15_seconds(self):
        d, result, outcome, waited = self.loop([ARTICLE], [None, None, (pdf(), PDF)])
        self.assertIsInstance(outcome, PdfFoundWhileWaiting)
        self.assertEqual(d._probe_pdf.call_count, 3)
        self.assertGreaterEqual(waited, 45)
        self.assertLess(waited, 60)


class NoAccessAfterLoginTests(unittest.TestCase):
    """What ends the login wait as not subscribed once the school's login is done."""

    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=PROFILE)
        self.result = DownloadResult(doi=DOI, status="failed")
        self.d._item_result = self.result

    def page(self, body="", url=ARTICLE, **probe):
        page = MagicMock()
        page.url = url
        page.title.return_value = "Article"
        page.locator.return_value.inner_text.return_value = body
        page.evaluate.return_value = probe
        return page

    def test_offers_denials_and_the_sites_own_rule_count_only_after_the_login(self):
        offered = self.page("GET ACCESS\nBuy this article")
        self.assertEqual(self.d._no_access_after_login(offered, self.result), "")  # no login yet
        self.result._login_round_trip = True
        self.assertEqual(self.d._no_access_after_login(offered, self.result), "GET ACCESS")
        self.assertTrue(self.d._no_access_after_login(self.page("You do not currently have access to this content."),
                                                      self.result))
        self.d.adapter.looks_logged_out = Mock(return_value=True)  # e.g. Atypon's access box
        self.assertIn("still shown without access", self.d._no_access_after_login(self.page("Abstract"), self.result))

    def test_the_login_sites_own_article_is_tried_first(self):
        # jacc.org's abstract after ScienceDirect's login (2026-11-03): the login
        # site's article is still to be opened (_return_from_login_site).
        offered = self.page("GET ACCESS\nBuy this article")
        self.result._login_round_trip = True
        self.result._login_site_fallback = "https://www.sciencedirect.com/science/article/pii/S0735109726068920"
        self.assertEqual(self.d._no_access_after_login(offered, self.result), "")
        self.result._login_site_fallback = ""  # tried: the page's own evidence counts again
        self.assertEqual(self.d._no_access_after_login(offered, self.result), "GET ACCESS")

    def test_a_remembered_school_gate_and_reader_access_are_not_no_access(self):
        self.result._login_round_trip = True
        self.assertEqual(self.d._no_access_after_login(
            self.page("Abstract", gate="Access through Hong Mu-lan University"), self.result), "")
        self.assertEqual(self.d._no_access_after_login(
            self.page("Buy this article", badges=["Full Access"]), self.result), "")


class PdfSentToArticleAfterLoginTests(unittest.TestCase):
    """A PDF returning HTML after login requires access-denial evidence before
    being classified as missing entitlement; unexplained redirects stay unknown."""

    downloader, page = PdfFirstTests.downloader, PdfFirstTests.page
    PDF_URL = "https://ascelibrary.org/doi/pdf/10.1061/JSENDH.STENG-16404"

    def attempt(self, outcome, final=ARTICLE, url=None):
        return {"how": "url", "url": url or self.PDF_URL, "final_url": final, "status": 200,
                "type": "text/html", "size": "", "outcome": outcome, "seconds": 6.1}

    def judged(self, attempts, signed_in=True, since=0, body="Buy this article"):
        d = self.downloader()
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        result.pdf_attempts.extend(attempts)
        if signed_in:
            result._visited_idp = True
            result.events.append({"state": "institution_selected", "detail": "Synthetic University A (entityID)"})
        d._item_result = result
        page = self.page()
        page.locator.return_value.inner_text.return_value = body
        return d._pdf_sent_to_article_after_login(page, result, since), result

    def test_redirect_without_access_denial_is_not_missing_entitlement(self):
        # A Free JAMA article returned HTML from its PDF endpoint on Windows.
        # The redirect alone says nothing about an institution's subscription.
        for body in ("", "Free\nIntroduction\nMethods\nResults\nDiscussion"):
            with self.subTest(body=body):
                found, result = self.judged([self.attempt("html page")], body=body)
                self.assertFalse(found)
                self.assertNotEqual(result.reason, "institution_pdf_entitlement_missing")

    def test_sent_to_the_article_after_the_login_is_no_access(self):
        found, result = self.judged([self.attempt("no pdf", url="current-doi-metadata-pdf"), self.attempt("html page")])
        self.assertTrue(found)
        self.assertEqual(result.reason, "institution_pdf_entitlement_missing")
        event = next(e for e in result.events if e["state"] == "no_access_after_login")
        self.assertIn(self.PDF_URL, event["detail"])
        self.assertEqual(result.snapshots[-1]["why"], "not subscribed")

    def test_other_endings_and_no_login_stay_pdf_not_captured(self):
        for attempts, signed_in in (([self.attempt("html page")], False),  # no school login yet
                                    ([self.attempt("html page", final=self.PDF_URL)], True),  # a reader page at its address
                                    ([self.attempt("no pdf")], True),
                                    ([self.attempt("html page"), self.attempt("verification page")], True),
                                    ([self.attempt("html page"), self.attempt("identity rejected")], True),
                                    ([self.attempt("login page", final="https://ascelibrary.org/action/showLogin")], True)):
            with self.subTest(outcomes=[a["outcome"] for a in attempts], signed_in=signed_in):
                found, result = self.judged(attempts, signed_in)
                self.assertFalse(found)
                self.assertNotEqual(result.reason, "institution_pdf_entitlement_missing")

    def test_a_pdf_address_that_shows_the_article_without_access_is_sent_back(self):
        # Taylor & Francis (Scand J Rheumatol 2013, Windows 2026-11-22): signed in, its PDF address answered with the
        # article's page, "Purchase options" on it. Only where the publisher's rules say its PDF address does so.
        at_its_address = [self.attempt("html page", final=self.PDF_URL)]
        with patch.object(type(self.downloader().adapter), "pdf_address_shows_article_page", True):
            found, result = self.judged(at_its_address, body="Purchase options *")
            self.assertTrue(found)
            self.assertEqual(result.reason, "institution_pdf_entitlement_missing")
            found, _ = self.judged(at_its_address, body="Abstract\nReferences")  # nothing denied or offered
            self.assertFalse(found)
        from paper_search_school.adapters.taylor_francis import TaylorFrancisAdapter
        self.assertTrue(TaylorFrancisAdapter.pdf_address_shows_article_page)

    def test_before_the_login_a_paywall_answer_leaves_the_other_addresses_for_after_it(self):
        # Wiley's Angewandte (10.1002/anie.202516998, Windows 2026-11-24): epdf, pdfdirect and pdf each answered 403 with
        # the article's page in about 20 s; the page budget ran out before the login. One such answer is enough.
        d = self.downloader()
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        d._item_result = result
        result._pdf_first = True
        d._event(result, "pdf_capture_started")
        self.assertFalse(d._paywall_answered_before_login(result))
        d._event(result, "pdf_step_article_page", f"403 {self.PDF_URL} | {TITLE}")
        self.assertTrue(d._paywall_answered_before_login(result))
        # After the school's login every address is tried again; so too in the next capture until it answers so.
        result._visited_idp = True
        self.assertFalse(d._paywall_answered_before_login(result))
        result._visited_idp = False
        d._event(result, "pdf_capture_started")
        self.assertFalse(d._paywall_answered_before_login(result))
        # Not the PDF tried first (the access read on the page): the capture goes on as before.
        result._pdf_first = False
        d._event(result, "pdf_step_article_page", f"403 {self.PDF_URL} | {TITLE}")
        self.assertFalse(d._paywall_answered_before_login(result))

    def test_a_pdf_address_answering_403_with_the_article_page_is_sent_back(self):
        # jacc.org (10.1016/j.jcmg.2025.09.021, Windows 2026-11-23): /doi/pdf/ answered 403 with a page printing
        # the article's title (pdf_step_article_page). Still only with the page's denial or offer.
        at_its_address = {**self.attempt("html page", final=self.PDF_URL), "status": 403}
        for body, found in (("Buy this article", True), ("Abstract\nReferences", False)):
            with self.subTest(body=body):
                d = self.downloader()
                result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
                result.pdf_attempts.append(at_its_address)
                result._visited_idp = True
                d._item_result = result
                d._event(result, "pdf_step_article_page", f"403 {self.PDF_URL} | {TITLE}")
                page = self.page()
                page.locator.return_value.inner_text.return_value = body
                self.assertEqual(d._pdf_sent_to_article_after_login(page, result, 0), found)
                self.assertEqual(d._pdf_sent_to_article(page, result, 0), [at_its_address])

    def test_only_the_attempts_after_the_login_count(self):
        found, _ = self.judged([self.attempt("html page"), self.attempt("no pdf")], since=1)
        self.assertFalse(found)

    def capture(self, outcome):
        def run(page, doi, result):
            result.pdf_attempts.append(self.attempt(outcome))
            if outcome == "paywall":
                page.locator.return_value.inner_text.return_value = "Buy this article"
            return None, "", None
        return run

    def test_the_login_after_a_failed_pdf_ends_as_no_access(self):
        d = self.downloader()
        d._access_decision = Mock(return_value=("unknown", "", ""))

        def login(page, result):
            result._visited_idp = True
            result.events.append({"state": "institution_selected", "detail": "Synthetic University A (entityID)"})
            page.locator.return_value.inner_text.return_value = "Buy this article"
            return True
        captures = [self.capture("html page"), self.capture("html page")]
        d._ensure_login = Mock(return_value=True)
        d._capture_pdf = Mock(side_effect=lambda *a: captures.pop(0)(*a))
        d._complete_login_from_current_page = Mock(side_effect=login)
        d._reopen_article_page = Mock()
        d._login_block_reason = Mock(return_value="")
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
            result = d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))
        self.assertEqual((result.state, result.reason), ("institution_pdf_entitlement_missing",) * 2)
        self.assertEqual([e["state"] for e in result.events].count("no_access_after_login"), 1)

    def test_still_denied_after_the_login_there_is_no_second_login(self):
        # JAMA Oncology (10.1001/jamaoncol.2026.4196, 2026-11-02): back from the school's
        # login through the store page, the article showed only its abstract; a second
        # login found its entry used and waited out the user's three minutes.
        d = self.downloader()
        d._access_decision = Mock(return_value=("out", "abstract", ARTICLE))
        # The page's own evidence is _no_access_after_login's (NoAccessAfterLoginTests): here
        # only whether this item has been through the school's login.
        d._no_access_after_login = Mock(side_effect=lambda page, result: (
            f"abstract-only view: {ARTICLE}" if d._school_login_done() else ""))

        def login(page, result):
            result._visited_idp = True
            result.events.append({"state": "institution_selected", "detail": "Synthetic University A (entityID)"})
            return True
        d._ensure_login = Mock(side_effect=login)
        d._complete_login_from_current_page = Mock(return_value=False)
        d._capture_pdf = Mock()
        d._login_block_reason = Mock(return_value="")
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
            result = d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))
        self.assertEqual((result.state, result.reason), ("institution_pdf_entitlement_missing",) * 2)
        self.assertIn("no_access_after_login", [e["state"] for e in result.events])
        d._complete_login_from_current_page.assert_not_called()
        d._capture_pdf.assert_not_called()
        # Without this item's school login the same page still opens the login.
        d._ensure_login = Mock(return_value=True)
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
            d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))
        d._complete_login_from_current_page.assert_called_once()

    def test_nothing_tried_after_the_login_with_an_offer_on_the_page_is_no_access(self):
        # Thieme's Thrombosis and Haemostasis (2026-11-02): back from the school's login
        # the PDF step tried nothing and the page offered "Buy Article".
        for evidence, expected in (("Buy Article", "institution_pdf_entitlement_missing"), ("", "pdf_not_captured")):
            with self.subTest(evidence=evidence):
                d = self.downloader()
                d._access_decision = Mock(return_value=("unknown", "", ""))

                def login(page, result):
                    result._visited_idp = True
                    result.events.append({"state": "institution_selected", "detail": "Synthetic University A (entityID)"})
                    return True
                d._ensure_login = Mock(return_value=True)
                d._capture_pdf = Mock(return_value=(None, "", None))
                d._complete_login_from_current_page = Mock(side_effect=login)
                d._reopen_article_page = Mock()
                d._login_block_reason = Mock(return_value="")
                d._looks_logged_out = Mock(return_value=False)
                d._no_access_after_login = Mock(side_effect=lambda page, result: evidence if d._school_login_done() else "")
                with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
                    result = d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))
                self.assertEqual(result.state, expected)

    def test_a_pdf_step_that_tried_nothing_says_what_the_page_offered(self):
        d = self.downloader()
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        d._capture_pdf_channels = Mock(return_value=(None, "", None))
        d._citation_title = Mock(return_value="")
        d._decision_text = Mock(return_value=f"{ARTICLE} | unknown (no rule): ")
        d._pdf_candidates = Mock(return_value=[ARTICLE.replace("/doi/", "/doi/pdf/")])
        d._capture_pdf(self.page(), DOI, result)
        event = next(e for e in result.events if e["state"] == "pdf_step_nothing_tried")
        self.assertIn("candidates: https://ascelibrary.org/doi/pdf/", event["detail"])

    def test_a_login_before_the_capture_ends_as_no_access_too(self):
        d = self.downloader()
        d._access_decision = Mock(return_value=("in", "session", ""))
        d._school_login_done = Mock(return_value=True)
        d._login_block_reason = Mock(return_value="")
        d._ensure_login = Mock(return_value=True)
        d._capture_pdf = Mock(side_effect=self.capture("paywall"))
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
            result = d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))
        self.assertEqual(result.state, "institution_pdf_entitlement_missing")
        # No login in this item, and the page shows no school's session: nothing says who reads.
        d._school_login_done.return_value = False
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
            result = d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))
        self.assertEqual(result.state, "pdf_not_captured")
        # The school's session from an earlier item shows on the page, the article still offered.
        page = self.page()
        page.evaluate.return_value = {"labels": ["Welcome: Hong Mu-lan University"]}
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
            result = d.fetch_one(page, PaperRecord(doi=DOI), Path(directory))
        self.assertEqual(result.state, "institution_pdf_entitlement_missing")
        event = next(e for e in result.events if e["state"] == "no_access_after_login")
        self.assertIn("with the school signed in", event["detail"])

    def test_the_schools_session_from_an_earlier_item_with_get_access_is_no_access(self):
        # NEJM Catalyst (10.1056/cat.24.0478, Windows 2026-11-23): "Welcome: <school>" in the header,
        # "Get Access" over the abstract, the PDF address answering with that page at its own address.
        from paper_search_school.publishers.profiles import infer_publisher_profile
        doi = "10.1056/cat.24.0478"
        pdf_url = "https://catalyst.nejm.org/doi/pdf/10.1056/CAT.24.0478"
        d = PublisherBatchDownloader({"school_name_en": "Hong Mu-lan University"},
                                     profile=infer_publisher_profile(doi))
        self.assertTrue(d.adapter.pdf_address_shows_article_page)  # Atypon's, not one publisher's
        result = DownloadResult(doi=doi, status="failed", article_url=f"https://doi.org/{doi}")
        result.pdf_attempts.append({"how": "url", "url": pdf_url, "final_url": pdf_url, "status": 200,
                                    "type": "text/html", "size": "", "outcome": "html page", "seconds": 13.6})
        d._item_result = result
        page = self.page(pdf_url)
        page.locator.return_value.inner_text.return_value = "Get Access\nAbstract\nReferences"
        for labels, expected in ((["Welcome: Hong Mu-lan University"], True), ([], False),
                                 (["Welcome: Another Medical University"], False)):
            with self.subTest(labels=labels):
                page.evaluate.return_value = {"labels": labels}
                self.assertIs(d._pdf_sent_to_article_after_login(page, result, 0), expected)
        self.assertEqual(result.reason, "institution_pdf_entitlement_missing")
        # The evidence the failures list shows (entitlement_denied): the page's offer, not "nothing saved".
        page.evaluate.return_value = {"labels": ["Welcome: Hong Mu-lan University"]}
        self.assertEqual(d._denial_line(page), 'offer: "Get Access" (the institution\'s session)')


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=PROFILE)
        self.d._record_title = TITLE
        self.d._pdf_candidates = Mock(return_value=[PDF, PDF + "?other=1"])
        self.result = DownloadResult(doi=DOI, status="failed")
        self.d._item_result = self.result
        self.fetched = {}
        self.page = MagicMock()
        self.page.url = ARTICLE
        self.page.context.pages = [self.page]
        self.page.evaluate.side_effect = self.evaluate

    def evaluate(self, script, *args):
        if script == self.d._FETCH_PDF_JS:
            url = args[0]["url"]
            status, body = self.fetched.get(url, (404, b""))
            return {"status": status, "url": url, "body": base64.b64encode(body).decode()}
        return ""  # citation_title, the PDF viewer

    def test_the_article_page_fetches_its_pdf_and_only_this_articles_counts(self):
        own = pdf()
        self.fetched = {PDF: (200, pdf(doi="10.1061/other", title="Another article")), PDF + "?other=1": (200, own)}
        self.assertEqual(self.d._probe_pdf(self.page, self.result), (own, PDF + "?other=1"))

    def test_a_refusal_stops_probing_for_the_item(self):
        self.fetched = {PDF: (403, b"")}
        self.assertIsNone(self.d._probe_pdf(self.page, self.result))
        self.assertTrue(self.result._probe_refused)
        self.assertIsNone(self.d._probe_pdf(self.page, self.result))
        fetches = [c for c in self.page.evaluate.call_args_list if c.args[0] == self.d._FETCH_PDF_JS]
        self.assertEqual(len(fetches), 1)

    def test_one_address_is_asked_at_most_three_times_per_item(self):
        for _ in range(5):
            self.assertIsNone(self.d._probe_pdf(self.page, self.result))
        fetches = [c.args[1]["url"] for c in self.page.evaluate.call_args_list if c.args[0] == self.d._FETCH_PDF_JS]
        self.assertEqual(fetches.count(PDF), 3)


class AccessMenuEntryTests(unittest.TestCase):
    """The institution entry inside a site's "GET ACCESS" menu (ascelibrary.org, 2026-11-02)."""

    def setUp(self):
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"}, profile=PROFILE)
        self.d._is_human_login_page = Mock(return_value=False)
        self.d._has_visible_editable_input = Mock(return_value=False)
        self.result = DownloadResult(doi=DOI, status="failed")
        self.page = MagicMock()
        self.page.url = ARTICLE
        self.entry = None
        self.page.evaluate.side_effect = self.evaluate

    check_access = None

    def evaluate(self, script, *args):
        if script == self.d._ACCESS_MENU_JS:
            return "GET ACCESS"
        if script == self.d._INSTITUTION_ENTRY_JS:
            return self.entry
        if script == self.d._MENU_CHECK_ACCESS_JS:
            return self.check_access
        return None

    def test_the_menus_institution_entry_is_opened(self):
        chooser = "https://ascelibrary.org/action/ssostart?redirectUri=%2Fdoi%2F10.1061%2FJSENDH.STENG-16404"
        self.entry = {"label": "Institutional Login", "href": chooser, "index": 7}
        self.assertTrue(self.d._open_entry_from_access_menu(self.page, self.result))
        self.page.goto.assert_called_once_with(chooser, wait_until="commit", timeout=30_000)
        self.assertEqual([e["state"] for e in self.result.events], ["access_menu_opened", "sso_entry_clicked"])
        # Once per page: a second pass does not toggle the menu shut.
        self.assertFalse(self.d._open_entry_from_access_menu(self.page, self.result))

    def test_a_link_that_selects_one_idp_or_leaves_the_site_is_not_opened(self):
        for href in ("https://ascelibrary.org/action/ssostart?idp=https%3A%2F%2Fidp.other.edu&redirectUri=x",
                     "https://sso.example.invalid/login"):
            with self.subTest(href=href):
                self.result.events.clear()
                self.result._access_menus = set()
                self.entry = {"label": "Institutional Login", "href": href, "index": 7}
                self.assertFalse(self.d._open_entry_from_access_menu(self.page, self.result))
                self.page.goto.assert_not_called()

    def test_no_menu_entry_and_the_users_own_pages_are_left_alone(self):
        self.entry = None
        self.assertFalse(self.d._open_entry_from_access_menu(self.page, self.result))
        self.page.url = IDP
        self.result._access_menus = set()
        self.assertFalse(self.d._open_entry_from_access_menu(self.page, self.result))
        # Looked for on the article (the entry, then the panel's "Check Access"), nothing on the school's page.
        self.assertEqual([c.args[0] for c in self.page.evaluate.call_args_list[-2:]],
                         [self.d._INSTITUTION_ENTRY_JS, self.d._MENU_CHECK_ACCESS_JS])

    def test_the_panels_check_access_for_an_institutional_subscription_is_opened(self):
        # APA PsycNET (2026-11-24): "Get Access" shows "... through your institutional subscription. CHECK ACCESS",
        # a button that opens its sign-in page with the institutions' list.
        self.check_access = {"label": "CHECK ACCESS", "href": "", "index": 4}
        self.d._click_control = Mock(return_value=True)
        self.assertTrue(self.d._open_entry_from_access_menu(self.page, self.result))
        self.assertEqual(self.d._click_control.call_args.args[3], "access-menu entry: CHECK ACCESS")
        self.assertEqual(self.result.events[-1], {**self.result.events[-1], "state": "sso_entry_clicked",
                                                  "detail": "access-menu: CHECK ACCESS"})


if __name__ == "__main__":
    unittest.main()

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

from paper_search_carsi.engine import batch
from paper_search_carsi.engine.batch import DownloadResult, PaperRecord, PublisherBatchDownloader
from paper_search_carsi.engine.batch_user import PdfFoundWhileWaiting
from paper_search_carsi.publishers.model import PublisherProfile

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

    def saved(self, title):
        d = self.downloader()
        d._expected_title = title
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        d._item_result = result
        with tempfile.TemporaryDirectory() as directory, patch.object(d, "_save_publisher_session", Mock()), \
                patch.object(d, "_write_diagnostic", Mock()):
            result = d._save_captured_pdf(self.page(), PaperRecord(doi=DOI), result, Path(directory),
                                          self.body(), ARTICLE.replace("/doi/", "/doi/pdf/"))
        return result

    def test_the_title_keeps_a_pdf_that_cites_another_doi(self):
        self.assertNotEqual(self.saved(TITLE).state, "pdf_wrong_article")
        self.assertEqual(self.saved("").state, "pdf_wrong_article")


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
        with patch.object(batch.time, "sleep", sleep), patch.object(batch.time, "time", lambda: clock[0]):
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

    def test_back_from_the_school_login_with_nothing_conclusive_the_wait_goes_on(self):
        d, result, outcome, waited = self.loop([ARTICLE, IDP, ARTICLE], [None] * 40)
        self.assertIs(outcome, False)
        self.assertGreaterEqual(waited, 300)  # the article's whole wait
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
    """After this item's school login a PDF that comes back as the article's web
    page is no access after login (JAMA 10.1001/jama.2026.20039: articlepdf ->
    article-abstract -> fullarticle; The Lancet 1975: ScienceDirect's pdfft ->
    its article page; both ended as "PDF not captured", 2026-11-02)."""

    downloader, page = PdfFirstTests.downloader, PdfFirstTests.page
    PDF_URL = "https://ascelibrary.org/doi/pdf/10.1061/JSENDH.STENG-16404"

    def attempt(self, outcome, final=ARTICLE, url=None):
        return {"how": "url", "url": url or self.PDF_URL, "final_url": final, "status": 200,
                "type": "text/html", "size": "", "outcome": outcome, "seconds": 6.1}

    def judged(self, attempts, signed_in=True, since=0):
        d = self.downloader()
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        result.pdf_attempts.extend(attempts)
        if signed_in:
            result.events.append({"state": "institution_selected", "detail": "Synthetic University A (entityID)"})
        d._item_result = result
        return d._pdf_sent_to_article_after_login(self.page(), result, since), result

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

    def test_only_the_attempts_after_the_login_count(self):
        found, _ = self.judged([self.attempt("html page"), self.attempt("no pdf")], since=1)
        self.assertFalse(found)

    def capture(self, outcome):
        def run(page, doi, result):
            result.pdf_attempts.append(self.attempt(outcome))
            return None, "", None
        return run

    def test_the_login_after_a_failed_pdf_ends_as_no_access(self):
        d = self.downloader()
        d._access_decision = Mock(return_value=("unknown", "", ""))

        def login(page, result):
            result.events.append({"state": "institution_selected", "detail": "Synthetic University A (entityID)"})
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
        d._school_login_done.return_value = False  # the institution's session alone: the old outcome
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"):
            result = d.fetch_one(self.page(), PaperRecord(doi=DOI), Path(directory))
        self.assertEqual(result.state, "pdf_not_captured")


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

    def evaluate(self, script, *args):
        if script == self.d._ACCESS_MENU_JS:
            return "GET ACCESS"
        if script == self.d._INSTITUTION_ENTRY_JS:
            return self.entry
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
        self.assertEqual(self.page.evaluate.call_args_list[-1].args[0], self.d._INSTITUTION_ENTRY_JS)


if __name__ == "__main__":
    unittest.main()

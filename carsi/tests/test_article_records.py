"""What an article's record says (2026-11-02): the rule and words behind each
access decision, waits over 10 s with how they ended, silence before a step,
the time per phase. Mocked pages."""
import itertools
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

from paper_search_carsi.browser import watchdog
from paper_search_carsi.download_diagnostics import serialize_download_result
from paper_search_carsi.engine import access_rules, batch_diagnostics
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.model import PublisherProfile

DOI = "10.1136/bmj-2026-101299"
ARTICLE = "https://www.fixture-press.example/content/395/bmj-2026-101299"
PROFILE = PublisherProfile(name="Fixture Press", article_url_template="https://doi.org/{doi}", pdf_url_templates=(),
                           success_url_markers=("fixture-press.example/content/",), auth_url_markers=("/login",),
                           auth_title_markers=(), sso_text_markers=(), base_domains=("fixture-press.example",))


def result():
    return DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)


def page(body="", url=ARTICLE, **probe):
    page = MagicMock()
    page.url = url
    page.title.return_value = "Article"
    page.is_closed.return_value = False
    page.locator.return_value.inner_text.return_value = body
    page.evaluate.return_value = probe
    return page


class EventTimingTests(unittest.TestCase):
    def test_silence_over_ten_seconds_before_a_step_is_recorded(self):
        r = result()
        clock = iter([100.0, 103.0, 140.0])
        with patch.object(batch_diagnostics.time, "monotonic", lambda: next(clock)):
            for state in ("article_access_ready", "pdf_capture_started", "pdf_candidate"):
                PublisherBatchDownloader._event(r, state)
        self.assertEqual([e.get("gap") for e in r.events], [None, None, 37])
        packet = serialize_download_result(r, diagnostic=True)
        self.assertEqual(packet["events"][2]["gap"], 37)

    def test_phases_add_up_and_reach_the_record(self):
        d, r = PublisherBatchDownloader({}), result()
        clock = iter([0.0, 5.0, 25.0, 31.0, 33.0])
        with patch.object(batch_diagnostics.time, "monotonic", lambda: next(clock)):
            d._phase(r, "open")
            d._phase(r, "login")
            previous = d._phase(r, "verification")
            d._phase(r, previous)
            d._close_phase(r)
        self.assertEqual(r.phases, {"open": 5.0, "login": 22.0, "verification": 6.0})
        self.assertEqual(serialize_download_result(r, diagnostic=True)["phases"], r.phases)

    def test_only_a_wait_over_ten_seconds_is_recorded_with_how_it_ended(self):
        d, r = PublisherBatchDownloader({}), result()
        d._note_wait(r, "verification", time.time() - 3, "passed")
        self.assertEqual(r.events, [])
        d._note_wait(r, "verification", time.time() - 22, "passed")
        self.assertEqual(r.events[-1]["state"], "wait")
        self.assertEqual(r.events[-1]["detail"], "verification: 22 s, ended: passed")


class SilenceTests(unittest.TestCase):
    def test_a_silence_says_how_much_of_it_the_browser_took(self):
        r = result()
        clock = iter([100.0, 160.0])
        with patch.object(batch_diagnostics.time, "monotonic", lambda: next(clock)), \
                patch.object(watchdog, "_period", {"calls": 0, "seconds": 0.0, "slowest": "", "slowest_sec": 0.0}):
            PublisherBatchDownloader._event(r, "challenge_resolved")
            watchdog._period.update(calls=14, seconds=57.6, slowest="Page.title", slowest_sec=12.4)
            PublisherBatchDownloader._event(r, "article_access_ready")
        self.assertEqual(r.events[1]["gap"], 60)
        self.assertEqual(r.events[1]["browser_time"], "14 browser calls, 58 s; slowest Page.title 12 s")
        self.assertEqual(serialize_download_result(r, diagnostic=True)["events"][1]["browser_time"],
                         r.events[1]["browser_time"])


class SlowBrowserCallTests(unittest.TestCase):
    def test_a_long_browser_call_is_reported_with_the_line_that_made_it(self):
        from playwright._impl import _sync_base
        reports = []

        class Fake:
            def _sync(self, coro):
                coro.close()
                raise TimeoutError("Locator.click: Timeout 10000ms exceeded.")

        async def click():
            return None

        ticks = itertools.count()
        with patch.object(_sync_base, "SyncBase", Fake), patch.object(watchdog, "_installed", False), \
                patch.object(watchdog.threading, "Thread"), \
                patch.object(watchdog.time, "monotonic", lambda: next(ticks) * 11.0), \
                patch.object(watchdog, "on_slow_call", lambda *args: reports.append(args)):
            watchdog.install()
            with self.assertRaises(TimeoutError):
                Fake()._sync(click())
        self.assertEqual(len(reports), 1)
        name, seconds, ended, where = reports[0]
        self.assertTrue(name.endswith("click"))
        self.assertGreater(seconds, 10)
        self.assertEqual(ended, "TimeoutError")


class DecisionEvidenceTests(unittest.TestCase):
    def test_a_closed_page_records_its_rule_and_words(self):
        d, r = PublisherBatchDownloader({}, profile=PROFILE), result()
        self.assertFalse(d._pdf_first_unless_signed_out(page("Abstract\nBuy this article ($64)"), r))
        self.assertEqual(r.events[-1]["state"], "access_decision")
        self.assertEqual(r.events[-1]["detail"], "out (closed): Buy this article ($64)")
        d._pdf_first_unless_signed_out(page("Abstract\nBuy this article ($64)"), r)
        self.assertEqual(len(r.events), 1)  # the same decision again adds nothing

    def test_unknown_access_lists_the_checks_that_found_nothing(self):
        d, r = PublisherBatchDownloader({}, profile=PROFILE), result()
        self.assertTrue(d._pdf_first_unless_signed_out(page("Abstract\nMethods"), r))
        detail = r.events[-1]["detail"]
        self.assertEqual(r.events[-1]["state"], "access_unknown_pdf_first")
        for check in ("login page no", "institution session no", "abstract-only view no", "reader access no",
                      "page rule none", "password field, denial line, offer or gate none"):
            self.assertIn(check, detail)

    def test_the_institution_s_session_names_who_gives_it(self):
        d, r = PublisherBatchDownloader({}, profile=PROFILE), result()
        d._pdf_first_unless_signed_out(page("Brought to you by:\nExample University\nAbstract"), r)
        self.assertEqual(r.events[-1]["detail"], "in (session): session line: Example University")

    def test_denials_carry_their_rule_and_the_page_s_words(self):
        line = "Example University does not subscribe to this content."
        self.assertEqual(access_rules.denial_evidence(ARTICLE, [line], {}),
                         ('denial line: "Example University does not subscribe to this content."', "Example University"))
        panel = "Example University does not provide access to this content."  # Wiley's panel
        self.assertEqual(access_rules.denial_evidence(ARTICLE, [], {"denial_panel": panel})[0], f'denial panel: "{panel}"')
        self.assertEqual(access_rules.denial_evidence(ARTICLE + "#no-access-message", [], {})[0],
                         "denial address: #no-access-message")

    def test_a_login_block_keeps_the_words_that_decided(self):
        d = PublisherBatchDownloader({"publisher_institution_federation": "carsi",
                                      "idp_entity_id": "https://idp.example.edu.cn/idp/shibboleth"}, profile=PROFILE)
        idp = page("Login\nYour account is locked. Contact the help desk.", url="https://idp.example.edu.cn/idp/profile/SAML2")
        self.assertEqual(d._login_block_reason(idp), "idp_account_locked")
        self.assertTrue(d._block_evidence.startswith('idp.example.edu.cn: "'))
        self.assertIn("Your account is locked. Contact the help desk.", d._block_evidence)
        self.assertEqual(d._login_block_reason(page("Abstract")), "")
        self.assertEqual(d._block_evidence, "")

"""--fulltext: the article's full-text page read on the article and saved after the PDF (engine/fulltext_page.py)."""
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

from paper_search_school.adapters.elsevier import ElsevierAdapter
from paper_search_school.adapters.science import ScienceAdapter
from paper_search_school.engine import fulltext_page
from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.engine.batch_common import DownloadResult
from paper_search_school.engine.fulltext_page import read_page, save_page, wait_stable


class FakePage:
    """Answers the module's scripts: the fingerprint, the page's DOI, the adapter's two rules."""

    def __init__(self, *, doi="10.1126/science.abc1234", shown=True, images=(), fingerprints=("1:2:0",),
                 url="https://www.science.org/doi/10.1126/science.abc1234", pdf_only="", mathjax=("",)):
        self.url = url
        self.doi, self.shown, self.images, self.pdf_only = doi, shown, list(images), pdf_only
        self.mathjax = list(mathjax)
        self.scripts = []
        self.fingerprints = list(fingerprints)
        self.prepared = []
        self.waited = []

    def wait_for_timeout(self, ms):
        self.waited.append(ms)

    def evaluate(self, script, **options):
        self.scripts.append(script)
        if script == "prepare":
            self.prepared.append(options)
            return 3
        if "innerText.length}" in script:
            return self.fingerprints.pop(0) if len(self.fingerprints) > 1 else self.fingerprints[0]
        if "MathJax_Message" in script:
            return self.mathjax.pop(0) if len(self.mathjax) > 1 else self.mathjax[0]
        if "citation_doi" in script:
            return self.doi
        if "open or download the pdf" in script:
            return self.pdf_only
        if "usual body containers" in script or "sizes.join" in script:
            return "www.science.org #body=-"
        if "outerHTML" in script:
            return "<html><body>red magnolia</body></html>"
        if script == "shown":
            return self.shown
        if script == "images":
            return self.images
        raise AssertionError(script)


ADAPTER = SimpleNamespace(fulltext_shown_js="shown", fulltext_images_js="images")


class ReadPageTests(unittest.TestCase):
    def test_reads_html_and_image_addresses_once_the_page_names_this_doi_and_shows_the_text(self):
        page = FakePage(images=["https://www.science.org/cms/x/large/f1.jpg", "javascript:void(0)",
                                "https://www.science.org/cms/x/large/f1.jpg", 7])
        read, why = read_page(page, "10.1126/SCIENCE.ABC1234", ADAPTER)
        self.assertEqual(why, "")
        self.assertEqual(read["url"], "https://www.science.org/doi/10.1126/science.abc1234")
        self.assertTrue(read["html"].startswith("<!DOCTYPE html>\n<html>"))
        self.assertEqual(read["image_urls"], ["https://www.science.org/cms/x/large/f1.jpg"])

    def test_runs_the_adapters_preparation_in_the_pages_own_world_before_reading(self):
        page = FakePage()
        read, _ = read_page(page, "10.1126/science.abc1234", SimpleNamespace(**vars(ADAPTER), fulltext_prepare_js="prepare"))
        self.assertIsNotNone(read)
        self.assertEqual(page.prepared, [{"isolated_context": False}])
        self.assertEqual(read["prepared"], "3")  # what it did goes into the record
        self.assertEqual(FakePage().prepared, [])
        self.assertNotIn("prepared", read_page(FakePage(), "10.1126/science.abc1234", ADAPTER)[0])

    def test_gives_the_preparation_the_document_the_adapter_names_fetched_in_the_browser_session(self):
        # PLOS's formulas: the page has only their images, the article's XML their MathML, on
        # another host the page cannot fetch from (no CORS, 2026-11-18).
        class Response:
            def __init__(self, status=200, body=b"<article>MathML</article>"):
                self.status, self.ok, self._body, self.disposed = status, 200 <= status < 300, body, False

            def body(self):
                return self._body

            def dispose(self):
                self.disposed = True

        class Request:
            def __init__(self, answer):
                self.answer, self.asked = answer, []

            def get(self, url, *, timeout):
                self.asked.append((url, timeout))
                if isinstance(self.answer, BaseException):
                    raise self.answer
                return self.answer

        class SourcePage(FakePage):
            def __init__(self, answer):
                super().__init__()
                self.context = SimpleNamespace(request=Request(answer))
                self.given = []

            def evaluate(self, script, *args, **options):
                if script == "prepare":
                    self.given.append((args, options))
                    return "2 of 2 formulas"
                return super().evaluate(script, **options)

        named = []

        def source(doi, page_url):
            named.append((doi, page_url))
            return "https://journals.example.org/article/file?id=10.1/x&type=manuscript"

        adapter = SimpleNamespace(**vars(ADAPTER), fulltext_prepare_js="prepare", fulltext_prepare_source=source)
        answer = Response()
        page = SourcePage(answer)
        read, _ = read_page(page, "10.1126/science.abc1234", adapter)
        self.assertEqual(named, [("10.1126/science.abc1234", "https://www.science.org/doi/10.1126/science.abc1234")])
        self.assertEqual(page.context.request.asked, [("https://journals.example.org/article/file?id=10.1/x&type=manuscript",
                                                       fulltext_page.PREPARE_SOURCE_TIMEOUT_MS)])
        self.assertEqual(page.given, [(("<article>MathML</article>",), {"isolated_context": False})])
        self.assertTrue(answer.disposed)
        self.assertEqual(read["prepared"], "2 of 2 formulas")

        # Not fetched: the script still runs, given "", and the record says why.
        page = SourcePage(Response(status=403))
        read, _ = read_page(page, "10.1126/science.abc1234", adapter)
        self.assertEqual(page.given, [(("",), {"isolated_context": False})])
        self.assertEqual(read["prepared"], "2 of 2 formulas; source not fetched: http_403")
        with mock.patch.object(fulltext_page, "PREPARE_SOURCE_MAX_BYTES", 4):
            self.assertEqual(read_page(SourcePage(Response()), "10.1126/science.abc1234", adapter)[0]["prepared"],
                             "2 of 2 formulas; source not fetched: too_large")
        TimeoutError = type("TimeoutError", (Exception,), {"__module__": "patchright._impl._errors"})
        read, _ = read_page(SourcePage(TimeoutError("Timeout 15000ms exceeded")), "10.1126/science.abc1234", adapter)
        self.assertEqual(read["prepared"], "2 of 2 formulas; source not fetched: TimeoutError")
        # A program error is not taken for a missing document.
        with self.assertRaises(KeyError):
            read_page(SourcePage(KeyError("bug")), "10.1126/science.abc1234", adapter)
        # An adapter naming no document: the script runs as before, without an argument.
        page = SourcePage(Response())
        read_page(page, "10.1126/science.abc1234", SimpleNamespace(**{**vars(adapter), "fulltext_prepare_source": lambda doi, url: ""}))
        self.assertEqual((page.given, page.context.request.asked), ([((), {"isolated_context": False})], []))

    def test_a_site_without_page_scripts_is_read_with_the_general_rules(self):
        # Its page is kept for PaperSearch to try its templates on (user, 2026-11-16).
        with mock.patch.object(fulltext_page, "_SAMPLE_SHOWN_JS", "shown"), \
             mock.patch.object(fulltext_page, "_SAMPLE_IMAGES_JS", "images"), \
             mock.patch.object(fulltext_page, "MATHJAX_SOURCES_JS", "prepare"):
            page = FakePage(images=["https://journals.example.org/f1.jpg"], url="https://journals.example.org/doi/10.1126/science.abc1234")
            read, why = read_page(page, "10.1126/science.abc1234", SimpleNamespace())
            self.assertEqual(why, "")
            self.assertEqual((read["image_urls"], read["general"], read["prepared"]), (["https://journals.example.org/f1.jpg"], True, "3"))
            self.assertEqual(page.prepared, [{"isolated_context": False}])  # the formulas MathJax holds
            # Still only a page that names this DOI and shows a full text.
            self.assertEqual(read_page(FakePage(doi="10.1126/other"), "10.1126/science.abc1234", SimpleNamespace())[1], "other_article")
            with mock.patch.object(fulltext_page, "SHOWN_WAIT_MS", 0):
                self.assertTrue(read_page(FakePage(shown=False), "10.1126/science.abc1234", SimpleNamespace())[1].startswith("fulltext_not_shown"))
        # A site with its own scripts keeps them.
        self.assertNotIn("general", read_page(FakePage(), "10.1126/science.abc1234", ADAPTER)[0])

    def test_says_why_a_page_is_not_read(self):
        self.assertEqual(read_page(FakePage(doi="10.1126/other"), "10.1126/science.abc1234", ADAPTER)[1], "other_article")
        self.assertEqual(read_page(FakePage(shown=False), "10.1126/science.abc1234", ADAPTER)[1],
                         "fulltext_not_shown: www.science.org #body=-")

    def test_a_page_whose_text_is_in_its_pdf_alone_is_not_waited_for(self):
        # A one-page figure article ("To view this SnapShot, open or download the PDF") and a
        # retracted article opened as its PDF waited out the read's time (Cell, 2026-11-18).
        page = FakePage(shown=False, pdf_only="To view this SnapShot, open or download the PDF")
        self.assertEqual(read_page(page, "10.1126/science.abc1234", ADAPTER)[1],
                         "fulltext_not_shown: pdf_only: To view this SnapShot, open or download the PDF")
        self.assertNotIn("shown", page.scripts)  # nothing waited for
        # A maintainer's sample is read whatever the page says.
        with mock.patch.object(fulltext_page, "SHOWN_WAIT_MS", 0), \
             mock.patch.object(fulltext_page, "_SAMPLE_SHOWN_JS", "shown"), \
             mock.patch.object(fulltext_page, "_SAMPLE_IMAGES_JS", "images"):
            read, why = read_page(FakePage(shown=False, pdf_only="the page is the PDF"), "10.1126/science.abc1234",
                                  ADAPTER, sample=True)
        self.assertEqual(why, "")

    def test_a_maintainers_sample_is_kept_even_when_the_general_rule_sees_no_full_text(self):
        with mock.patch.object(fulltext_page, "_SAMPLE_SHOWN_JS", "shown"), \
             mock.patch.object(fulltext_page, "_SAMPLE_IMAGES_JS", "images"), \
             mock.patch.object(fulltext_page, "SHOWN_WAIT_MS", 0):
            read, why = read_page(FakePage(shown=False), "10.1126/science.abc1234", SimpleNamespace(), sample=True)
        self.assertEqual(why, "")
        self.assertIn("red magnolia", read["html"])

    def test_waits_until_the_page_stops_changing(self):
        page = FakePage(fingerprints=["1:0:0", "5:1:0", "9:2:0", "9:2:0"])
        self.assertTrue(wait_stable(page))
        self.assertEqual(page.waited, [750, 750, 750])
        clock = iter(range(100)).__next__
        self.assertFalse(wait_stable(FakePage(fingerprints=[str(n) for n in range(50)]), clock=clock, timeout=5))

    def test_waits_for_mathjax_2_while_its_progress_moves(self):
        # Frontiers, 2026-11-18: 157 formulas typeset over 36 s; the page changed all along.
        from paper_search_school.engine import fulltext_page as module

        def clock_of(page):
            return lambda: len(page.waited) * 0.75  # the time passes in the page's waits

        steps = 40
        page = FakePage(fingerprints=[f"{n}:20:157" for n in range(steps)] + [f"{steps}:20:158"] * 3,
                        mathjax=[f"Typesetting math: {n * 2}%" for n in range(steps)] + [""])
        with mock.patch("paper_search_school.browser.watchdog.extend_operation") as extend:
            self.assertTrue(wait_stable(page, clock=clock_of(page), timeout=5))
            self.assertTrue(extend.called)
            # The same text twice is not settled while MathJax still says it is typesetting.
            page = FakePage(fingerprints=["9:2:0"] * 3 + ["9:2:1"] * 3,
                            mathjax=["Typesetting math: 50%", "Typesetting math: 80%", ""])
            self.assertTrue(wait_stable(page, clock=clock_of(page), timeout=5))
            self.assertEqual(len(page.waited), 4)
            # Progress that stops moving, or MathJax past MATHJAX_WAIT_SEC, ends the wait as before.
            stuck = FakePage(fingerprints=[str(n) for n in range(200)], mathjax=["Typesetting math: 10%"])
            self.assertFalse(wait_stable(stuck, clock=clock_of(stuck), timeout=5))
            self.assertLess(len(stuck.waited) * 0.75, 12)
            endless = FakePage(fingerprints=[str(n) for n in range(500)], mathjax=[f"Typesetting math: {n}" for n in range(500)])
            self.assertFalse(wait_stable(endless, clock=clock_of(endless), timeout=5))
            self.assertLessEqual(len(endless.waited) * 0.75, module.MATHJAX_WAIT_SEC + 1)

    def test_waits_for_a_body_that_comes_after_the_abstract(self):
        page = FakePage()
        answers = iter([False, False, True])
        page.shown = None
        original = page.evaluate
        page.evaluate = lambda script, **options: next(answers) if script == "shown" else original(script, **options)
        read, why = read_page(page, "10.1126/science.abc1234", ADAPTER)
        self.assertEqual(why, "")
        self.assertIsNotNone(read)


class Response:
    def __init__(self, status=200, content_type="image/jpeg", body=b"\xff\xd8 jpeg"):
        self.status, self.ok = status, status < 400
        self.headers = {"content-type": content_type}
        self.body = body
        self.disposed = False

    def chunks(self):
        yield self.body

    def dispose(self):
        self.disposed = True


class SavePageTests(unittest.TestCase):
    def test_writes_the_html_and_the_images_and_says_which_failed(self):
        answers = {
            "https://x.org/cms/a/large/f1.jpg": Response(),
            "https://x.org/cms/b/large/f1.jpg": Response(),
            "https://x.org/cms/f2": Response(content_type="image/png"),
            "https://x.org/cms/f3.jpg": Response(status=403),
            "https://x.org/cms/f4.jpg": Response(content_type="text/html"),
        }

        class Request:
            def get(self, url, *, timeout):
                if url == "https://x.org/cms/f5.jpg":
                    raise ConnectionError("reset")
                return answers[url]

        read = {"html": "<!DOCTYPE html>\n<html></html>", "url": "https://x.org/doi/10.1/x", "image_urls": [*answers, "https://x.org/cms/f5.jpg"]}
        with tempfile.TemporaryDirectory() as out:
            saved = save_page(read, Path(out), "10.1/x", Request())
            folder = Path(out) / "10.1_x_fulltext_page"
            self.assertEqual(saved["file"], str(folder / "article.html"))
            self.assertEqual((folder / "article.html").read_text(encoding="utf-8"), read["html"])
            self.assertEqual([Path(image["file"]).name for image in saved["images"]], ["f1.jpg", "f1-2.jpg", "f2.png"])
            self.assertEqual((folder / "images" / "f1-2.jpg").read_bytes(), b"\xff\xd8 jpeg")
            self.assertEqual([(f["url"].rsplit("/", 1)[-1], f["reason"]) for f in saved["failed_images"]],
                             [("f3.jpg", "http_403"), ("f4.jpg", "not_an_image"), ("f5.jpg", "ConnectionError")])
            self.assertTrue(all(response.disposed for response in answers.values()))


class RememberPageTests(unittest.TestCase):
    def test_a_page_read_that_runs_out_of_time_leaves_the_download_going(self):
        from paper_search_school.browser import watchdog
        from paper_search_school.engine.batch import PublisherBatchDownloader
        from paper_search_school.engine.batch_common import DownloadResult
        from paper_search_school.publishers.profiles import get_publisher_profile

        downloader = PublisherBatchDownloader({"fulltext": True}, profile=get_publisher_profile("science"))
        result = DownloadResult(doi="10.1126/science.abc1234", status="started")
        exhausted = watchdog.BrowserBudgetExhausted("fulltext_page exhausted its page budget")
        with mock.patch.object(fulltext_page, "read_page", side_effect=exhausted):
            downloader._remember_fulltext_page(SimpleNamespace(url="https://www.science.org/doi/10.1126/science.abc1234"),
                                               "10.1126/science.abc1234", result)
        self.assertEqual([event.get("detail") for event in result.events if event.get("state") == "fulltext_page_not_saved"],
                         ["time_limit"])
        self.assertIsNone(getattr(result, "_fulltext_read", None))

    def page(self, url="https://ieeexplore.ieee.org/document/11397562"):
        cookies = [{"name": "session", "value": "fixture", "domain": "ieeexplore.ieee.org", "path": "/"}]
        return SimpleNamespace(url=url, evaluate=lambda script: "Fixture Browser" if script == "navigator.userAgent" else None,
                               context=SimpleNamespace(cookies=lambda: cookies), wait_for_load_state=mock.Mock())

    def test_the_session_for_the_pages_images_is_kept_as_the_page_is_read(self):
        # IEEE's 32 and 37 MB PDFs ran their step past its time; the watchdog then ended every
        # browser call, and the page read before the PDF was not saved (2026-11-18).
        from paper_search_school.publishers.profiles import get_publisher_profile

        downloader = PublisherBatchDownloader({"fulltext": True}, profile=get_publisher_profile("ieee"))
        result = DownloadResult(doi="10.1109/tpami.2026.1", status="started")
        page = self.page()
        with mock.patch.object(fulltext_page, "read_page", return_value=({"html": "x", "url": page.url, "image_urls": []}, "")):
            downloader._remember_fulltext_page(page, "10.1109/tpami.2026.1", result)
        self.assertEqual(result._fulltext_session, {"user_agent": "Fixture Browser", "cookies": page.context.cookies()})

    def test_a_read_cut_by_the_page_moving_on_is_read_once_more(self):
        # Right after the school's login a call of the read ended in an error after 11 s; the PDF
        # step found the page fine a second later, and the page was not saved (IEEE, 2026-11-18).
        from paper_search_school.publishers.profiles import get_publisher_profile

        driver_error = type("Error", (Exception,), {"__module__": "patchright._impl._errors"})
        closed_error = type("TargetClosedError", (Exception,), {"__module__": "patchright._impl._errors"})
        doi, page = "10.1109/tpami.2026.1", self.page()
        read = ({"html": "x", "url": page.url, "image_urls": []}, "")
        cut = driver_error("Execution context was destroyed, most likely because of a navigation\nCall log: ...")

        def remember(*answers):
            downloader = PublisherBatchDownloader({"fulltext": True}, profile=get_publisher_profile("ieee"))
            result = DownloadResult(doi=doi, status="started")
            with mock.patch.object(fulltext_page, "read_page", side_effect=list(answers)) as reading:
                downloader._remember_fulltext_page(page, doi, result)
            return result, reading.call_count

        result, reads = remember(cut, read)
        self.assertEqual(reads, 2)
        self.assertEqual(result._fulltext_read["url"], page.url)
        page.wait_for_load_state.assert_called_once()
        self.assertEqual([e["detail"] for e in result.events if e["state"] == "fulltext_page_read_again"],
                         ["Error: Execution context was destroyed, most likely because of a navigation"])
        # Cut twice: not saved, and the record says what cut it.
        result, reads = remember(cut, cut)
        self.assertEqual(reads, 2)
        self.assertEqual([e["detail"] for e in result.events if e["state"] == "fulltext_page_not_saved"],
                         ["browser: Error: Execution context was destroyed, most likely because of a navigation"])
        # A page closed under the read is not read again.
        result, reads = remember(closed_error("Target page, context or browser has been closed"), read)
        self.assertEqual(reads, 1)
        self.assertIsNone(getattr(result, "_fulltext_read", None))


    def test_a_page_without_its_text_behind_a_paywall_is_said_closed(self):
        # pnas.org's "Get full access to this article" was said 文章页没有正文 (2026-11-17).
        from paper_search_school.engine.batch import PublisherBatchDownloader
        from paper_search_school.engine.batch_common import DownloadResult
        from paper_search_school.publishers.profiles import get_publisher_profile

        page = SimpleNamespace(url="https://www.pnas.org/doi/10.1073/pnas.2608608123")
        for closed, said in (("GET ACCESS", "fulltext_denied: GET ACCESS"), ("", "fulltext_not_shown: www.pnas.org main=4000")):
            downloader = PublisherBatchDownloader({"fulltext": True}, profile=get_publisher_profile("pnas"))
            downloader._page_closed = mock.Mock(return_value=closed)
            result = DownloadResult(doi="10.1073/pnas.2608608123", status="started")
            with mock.patch.object(fulltext_page, "read_page", return_value=(None, "fulltext_not_shown: www.pnas.org main=4000")):
                downloader._remember_fulltext_page(page, "10.1073/pnas.2608608123", result)
            self.assertEqual([e.get("detail") for e in result.events if e.get("state") == "fulltext_page_not_saved"], [said])
            # Either way the school's login may be what is missing: the page is read again after it.
            self.assertTrue(downloader._fulltext_hidden(result))


class SaveAfterTheBrowserStoppedTests(unittest.TestCase):
    """IEEE, 2026-11-18: the page was read before the PDF; the PDF step ran past its time on a
    32 MB PDF and the watchdog ended every browser call. The PDF was saved, the page was not,
    and the Markdown's visit for the page alone went to the same backend and failed in 3 s."""

    DOI = "10.1109/tpami.2026.1"
    URL = "https://ieeexplore.ieee.org/document/11613177"
    IMAGE = "https://ieeexplore.ieee.org/mediastore/IEEE/content/media/34/11613177/fig1.gif"

    def run_item(self, out: Path, *, kept: dict | None):
        from contextlib import contextmanager
        from paper_search_school.browser import watchdog
        from paper_search_school.engine import bridge, supplement_transfer

        pdf = out / "work.pdf"
        pdf.write_bytes(b"%PDF-1.7 fixture")
        result = DownloadResult(doi=self.DOI, status="success", state="pdf_response_captured", pdf_path=str(pdf),
                                verified_match=True)
        result._fulltext_read = {"html": "<!DOCTYPE html>\n<html>red magnolia</html>", "url": self.URL,
                                 "image_urls": [self.IMAGE]}
        if kept:
            result._fulltext_session = kept
        downloader = mock.MagicMock(config={"fulltext": True}, _context_proxy={})
        downloader.fetch_one.return_value = result
        downloader._event.side_effect = lambda item, state, detail="": item.events.append({"state": state, "detail": detail})
        context = downloader._launch_context.return_value
        context.new_page.side_effect = watchdog.BrowserOperationTimeout("_capture_pdf exceeded its page budget")
        asked = []

        @contextmanager
        def session_request(state, config, *, referer, proxy=None):
            asked.append((state, referer))
            yield SimpleNamespace(get=lambda url, *, timeout: Response(content_type="image/gif"))

        with mock.patch.object(watchdog, "fired", {"call": "Page.goto", "seconds": 46, "operation": "_capture_pdf"}), \
             mock.patch("paper_search_school.browser.backend.is_available", return_value=True), \
             mock.patch("paper_search_school.engine.batch.PublisherBatchDownloader", return_value=downloader), \
             mock.patch.object(supplement_transfer, "session_request", session_request):
            answer = bridge._try_browser_batch_download(self.DOI, out / "paper.pdf", {"fulltext": True},
                                                       SimpleNamespace(name="IEEE"))
        context.new_page.assert_not_called()  # no browser call once the watchdog has ended them
        return answer, result, asked

    def test_the_page_read_before_the_pdf_is_saved_with_the_session_kept_then(self):
        kept = {"user_agent": "Fixture Browser", "cookies": [{"name": "s", "value": "v", "domain": "ieeexplore.ieee.org"}]}
        with tempfile.TemporaryDirectory() as out:
            answer, result, asked = self.run_item(Path(out), kept=kept)
            self.assertTrue(answer["success"])
            page = answer["fulltext_page"]
            self.assertEqual(Path(page["file"]).read_text(encoding="utf-8"), result._fulltext_read["html"])
            self.assertEqual([image["url"] for image in page["images"]], [self.IMAGE])
        self.assertEqual(asked, [(kept, self.URL)])
        self.assertEqual([e["detail"] for e in result.events if e["state"] == "fulltext_page_saved"],
                         ["1/1 images; with the session as read (browser_operation_timeout ended the browser's calls)"])
        # The caller starts another backend for what comes next.
        self.assertIs(answer["artifacts"]["browser_stopped"], True)

    def test_without_a_session_kept_the_page_is_not_saved_and_the_record_says_why(self):
        with tempfile.TemporaryDirectory() as out:
            answer, result, asked = self.run_item(Path(out), kept=None)
        self.assertNotIn("fulltext_page", answer)
        self.assertEqual(asked, [])
        self.assertEqual([e["detail"] for e in result.events if e["state"] == "fulltext_page_not_saved"],
                         ["browser_stopped: browser_operation_timeout"])


class LoginForThePageTests(unittest.TestCase):
    """Wiley's page says nothing about the reader's access: read before the school's login,
    it shows no full text (2026-11-14)."""

    def downloader(self, login_done: bool):
        downloader = PublisherBatchDownloader({"fulltext": True}, profile=SimpleNamespace(name="Wiley", article_url=lambda doi: f"https://onlinelibrary.wiley.com/doi/{doi}"))
        downloader._school_login_done = mock.Mock(return_value=login_done)
        downloader._complete_login_from_current_page = mock.Mock(return_value=True)
        downloader._remember_fulltext_page = mock.Mock()
        return downloader

    def hidden(self) -> DownloadResult:
        result = DownloadResult(doi="10.1111/apt.1", status="started")
        result.events.append({"state": "fulltext_page_not_saved", "detail": "fulltext_not_shown: onlinelibrary.wiley.com main=5499"})
        return result

    def test_a_visit_for_the_page_alone_signs_in_then_reads_it_again(self):
        page = SimpleNamespace(url="https://onlinelibrary.wiley.com/doi/10.1111/apt.1")
        downloader = self.downloader(False)
        with mock.patch("paper_search_school.engine.batch_capture.settle"):
            downloader._fulltext_after_login_only(page, "10.1111/apt.1", self.hidden())
        downloader._complete_login_from_current_page.assert_called_once()
        downloader._remember_fulltext_page.assert_called_once_with(page, "10.1111/apt.1", mock.ANY)
        # Signed in already, read already, or out of time: nothing more.
        for downloader, result in ((self.downloader(True), self.hidden()),
                                   (self.downloader(False), DownloadResult(doi="10.1111/apt.1", status="started"))):
            downloader._fulltext_after_login_only(page, "10.1111/apt.1", result)
            downloader._complete_login_from_current_page.assert_not_called()

    def test_a_page_whose_text_is_in_its_pdf_is_not_read_again_after_a_login(self):
        # A one-page figure article: read, signed in for, read again, a minute for nothing,
        # then said 文章页没存下来 (Cell, 2026-11-18). It says 文章页没有正文 at once.
        from paper_search_school.engine.bridge import _page_not_saved, _page_showed_no_fulltext

        def pdf_only() -> DownloadResult:
            result = DownloadResult(doi="10.1111/apt.1", status="started")
            result.events.append({"state": "fulltext_page_not_saved",
                                  "detail": "fulltext_not_shown: pdf_only: To view this SnapShot, open or download the PDF"})
            return result
        page = SimpleNamespace(url="https://onlinelibrary.wiley.com/doi/10.1111/apt.1")
        downloader = self.downloader(False)
        downloader._fulltext_after_login_only(page, "10.1111/apt.1", pdf_only())
        downloader._complete_login_from_current_page.assert_not_called()
        downloader = self.downloader(True)
        downloader._fulltext_after_pdf_login(page, "10.1111/apt.1", pdf_only())
        downloader._remember_fulltext_page.assert_not_called()
        self.assertEqual(_page_not_saved(pdf_only()), "fulltext_not_shown")
        self.assertTrue(_page_showed_no_fulltext(pdf_only()))
        # Nor is it looked at for a paywall: the reason stays.
        reader = PublisherBatchDownloader({"fulltext": True}, profile=SimpleNamespace(name="Cell"))
        reader._page_closed = mock.Mock(return_value="GET ACCESS")
        result = DownloadResult(doi="10.1111/apt.1", status="started")
        with mock.patch.object(fulltext_page, "read_page", return_value=(None, pdf_only().events[0]["detail"])):
            reader._remember_fulltext_page(page, "10.1111/apt.1", result)
        reader._page_closed.assert_not_called()
        self.assertEqual(result.events[-1]["detail"], pdf_only().events[0]["detail"])

    def test_a_pdf_visit_says_its_page_showed_no_full_text_only_when_read_so(self):
        # ACM, IOP (2026-11-15): a second visit for the page alone read it the same way.
        from paper_search_school.engine.bridge import _page_showed_no_fulltext

        self.assertTrue(_page_showed_no_fulltext(self.hidden()))
        saved = self.hidden()
        saved.fulltext_page = {"file": "/tmp/x.html"}
        out_of_time = self.hidden()
        out_of_time.events.append({"state": "fulltext_page_not_saved", "detail": "time_limit"})
        for result in (saved, out_of_time, DownloadResult(doi="10.1111/apt.1", status="started")):
            self.assertFalse(_page_showed_no_fulltext(result))

    def test_a_visit_for_the_page_alone_says_why_its_page_was_not_saved(self):
        # It came back as success with nothing in it, 后端结果无法使用 (Oxford, Karger, PNAS, 2026-11-17).
        from paper_search_school.engine.bridge import _page_not_saved

        self.assertEqual(_page_not_saved(self.hidden()), "fulltext_not_shown")
        cut = DownloadResult(doi="10.1111/apt.1", status="started")
        cut.events.append({"state": "fulltext_page_not_saved", "detail": "browser: TargetClosedError"})
        self.assertEqual(_page_not_saved(cut), "browser")
        odd = DownloadResult(doi="10.1111/apt.1", status="started")
        odd.events.append({"state": "fulltext_page_not_saved", "detail": "Seite <b>nicht</b> gespeichert"})
        self.assertEqual(_page_not_saved(odd), "page_not_saved")
        self.assertEqual(_page_not_saved(DownloadResult(doi="10.1111/apt.1", status="started")), "")

    def test_after_the_login_for_the_pdf_the_article_page_is_read_again_in_a_tab(self):
        result = self.hidden()
        result.final_url = "https://onlinelibrary.wiley.com/doi/10.1111/apt.1?saml_referrer"
        downloader = self.downloader(True)
        downloader._fulltext_after_pdf_login(SimpleNamespace(url="https://onlinelibrary.wiley.com/doi/epdf/10.1111/apt.1"),
                                             "10.1111/apt.1", result)
        self.assertEqual(downloader._remember_fulltext_page.call_args.kwargs["target"], result.final_url)
        # No login in this visit: the page read before stays the answer.
        downloader = self.downloader(False)
        downloader._fulltext_after_pdf_login(SimpleNamespace(url="x"), "10.1111/apt.1", self.hidden())
        downloader._remember_fulltext_page.assert_not_called()

    def test_the_read_opens_a_given_address_in_a_tab_of_its_own(self):
        downloader = PublisherBatchDownloader({"fulltext": True}, profile=SimpleNamespace(name="Wiley"))
        result = DownloadResult(doi="10.1111/apt.1", status="started")
        article, tab = mock.Mock(url="https://onlinelibrary.wiley.com/doi/epdf/10.1111/apt.1"), mock.Mock(url="https://onlinelibrary.wiley.com/doi/10.1111/apt.1")
        article.context.new_page.return_value = tab
        with mock.patch("paper_search_school.engine.batch_common.open_page") as opened, \
             mock.patch.object(fulltext_page, "read_page", return_value=({"html": "x", "url": tab.url, "image_urls": []}, "")) as read:
            downloader._remember_fulltext_page(article, "10.1111/apt.1", result, target=tab.url)
        self.assertEqual(opened.call_args.args[1], tab.url)
        self.assertIs(read.call_args.args[0], tab)


class PageOnlyVisitTests(unittest.TestCase):
    def test_a_visit_for_the_page_alone_stops_at_the_access_and_returns_the_page(self):
        from paper_search_school import orchestrator

        seen = {}
        page = {"file": "/out/10.1126_x_fulltext_page/article.html", "url": "https://www.science.org/doi/10.1126/x", "images": []}

        def institutional(doi, output_path, config):
            seen.update(config)
            return {"success": True, "identifier": doi, "doi": doi, "login": {"signed_in": True}, "artifacts": {},
                    "fulltext_page": page}
        with mock.patch.object(orchestrator, "try_institutional", institutional), \
             mock.patch.object(orchestrator, "cache_get", side_effect=AssertionError("no cached PDF for a page")), \
             tempfile.TemporaryDirectory() as directory:
            result = orchestrator.download_institutional("10.1126/x", directory, strategy="institutional_only", fulltext="only")
        self.assertEqual((seen.get("login_only"), seen.get("fulltext")), (True, True))
        self.assertEqual(result["fulltext_page"], page)  # no PDF is asked of it


class FullTextElsewhereTests(unittest.TestCase):
    def test_thieme_names_its_full_text_page_and_the_read_opens_it_in_a_tab_of_its_own(self):
        from paper_search_school.adapters.base import PublisherAdapter
        from paper_search_school.adapters.thieme import ThiemeAdapter
        from paper_search_school.engine.batch import PublisherBatchDownloader
        from paper_search_school.engine.batch_common import DownloadResult
        from paper_search_school.publishers.profiles import get_publisher_profile

        self.assertEqual(ThiemeAdapter.fulltext_page_url(None, "10.1055/a-1", "https://www.thieme-connect.com/products/ejournals/abstract/10.1055/a-1"),
                         "https://www.thieme-connect.com/products/ejournals/html/10.1055/a-1")
        self.assertEqual(ThiemeAdapter.fulltext_page_url(None, "10.1055/a-1", "https://idp.example.edu/login"),
                         "https://www.thieme-connect.de/products/ejournals/html/10.1055/a-1")
        self.assertEqual(PublisherAdapter.fulltext_page_url(None, "10.1/x", "https://example.org/a"), "")

        downloader = PublisherBatchDownloader({"fulltext": True}, profile=get_publisher_profile("thieme"))
        result = DownloadResult(doi="10.1055/a-1", status="started")
        tab = mock.Mock(url="https://www.thieme-connect.de/products/ejournals/html/10.1055/a-1")
        article = mock.Mock(url="https://www.thieme-connect.de/products/ejournals/abstract/10.1055/a-1")
        article.context.new_page.return_value = tab
        with mock.patch("paper_search_school.engine.batch_common.open_page") as opened, \
             mock.patch.object(fulltext_page, "read_page", return_value=({"html": "x", "url": tab.url, "image_urls": []}, "")) as read:
            downloader._remember_fulltext_page(article, "10.1055/a-1", result)
        opened.assert_called_once()
        self.assertIs(read.call_args.args[0], tab)
        tab.close.assert_called_once()
        self.assertEqual(result._fulltext_read["url"], tab.url)


class AdapterRuleTests(unittest.TestCase):
    def test_science_and_sciencedirect_name_their_pages(self):
        for adapter in (ScienceAdapter, ElsevierAdapter):
            self.assertIn("=>", adapter.fulltext_shown_js)
            self.assertIn("=>", adapter.fulltext_images_js)
        self.assertIn("section#bodymatter", ScienceAdapter.fulltext_shown_js)
        # Atypon's current template, shared by the publishers verified on it.
        from paper_search_school.adapters.nejm import NEJMAdapter
        from paper_search_school.adapters.platforms.atypon import CLASSIC_TEMPLATE_FULLTEXT_SHOWN_JS, AtyponAdapter
        from paper_search_school.adapters.pnas import PNASAdapter
        from paper_search_school.adapters.taylor_francis import TaylorFrancisAdapter

        from paper_search_school.adapters.aha_journals import AHAJournalsAdapter
        from paper_search_school.adapters.neurology import NeurologyAdapter
        from paper_search_school.adapters.sage import SageAdapter

        self.assertTrue(ScienceAdapter.fulltext_shown_js is NEJMAdapter.fulltext_shown_js is PNASAdapter.fulltext_shown_js
                        is SageAdapter.fulltext_shown_js is NeurologyAdapter.fulltext_shown_js is AHAJournalsAdapter.fulltext_shown_js)
        self.assertIsNone(AtyponAdapter.fulltext_shown_js)
        # Atypon's older template, on its own rules.
        self.assertIs(TaylorFrancisAdapter.fulltext_shown_js, CLASSIC_TEMPLATE_FULLTEXT_SHOWN_JS)
        # Silverchair's article page, shared by the publishers verified on it (JAMA, OUP).
        from paper_search_school.adapters.jama import JAMAAdapter
        from paper_search_school.adapters.karger import KargerAdapter
        from paper_search_school.adapters.oup import OUPAdapter
        from paper_search_school.adapters.platforms.silverchair import (
            SILVERCHAIR_FULLTEXT_IMAGES_JS, SILVERCHAIR_FULLTEXT_SHOWN_JS, SilverchairAdapter)

        self.assertTrue(JAMAAdapter.fulltext_shown_js is OUPAdapter.fulltext_shown_js is SILVERCHAIR_FULLTEXT_SHOWN_JS)
        self.assertTrue(JAMAAdapter.fulltext_images_js is OUPAdapter.fulltext_images_js is SILVERCHAIR_FULLTEXT_IMAGES_JS)
        self.assertIn(".widget-ArticleFulltext", SILVERCHAIR_FULLTEXT_SHOWN_JS)
        self.assertIn("downloadimage", SILVERCHAIR_FULLTEXT_IMAGES_JS)
        self.assertIsNone(SilverchairAdapter.fulltext_shown_js)
        self.assertIs(KargerAdapter.fulltext_shown_js, SILVERCHAIR_FULLTEXT_SHOWN_JS)
        self.assertIs(KargerAdapter.fulltext_images_js, SILVERCHAIR_FULLTEXT_IMAGES_JS)
        self.assertIn("view-large", SILVERCHAIR_FULLTEXT_IMAGES_JS)  # a viewer page, not the image
        self.assertIn("_lrg.", ElsevierAdapter.fulltext_images_js)
        self.assertIn("data-original-mathml", ElsevierAdapter.fulltext_prepare_js)
        # One script keeps each formula's MathML on ScienceDirect and Wiley alike.
        from paper_search_school.adapters.wiley import WileyAdapter
        from paper_search_school.engine.fulltext_page import MATHJAX_SOURCES_JS

        self.assertIs(ElsevierAdapter.fulltext_prepare_js, MATHJAX_SOURCES_JS)
        self.assertIs(WileyAdapter.fulltext_prepare_js, MATHJAX_SOURCES_JS)
        from paper_search_school.adapters.taylor_francis import TaylorFrancisAdapter as TF

        self.assertIs(TF.fulltext_prepare_js, MATHJAX_SOURCES_JS)
        self.assertIsNone(ScienceAdapter.fulltext_prepare_js)

    def test_springer_nature_names_its_pages_and_puts_in_its_linked_tables(self):
        from paper_search_school.adapters.springer import SpringerNatureAdapter as SN

        self.assertIn(".main-content", SN.fulltext_shown_js)
        self.assertIn("full access to this article", SN.fulltext_shown_js)
        # Full-size figures, Extended Data figures, and the tables' images it put in.
        for part in ("'$1full/'", "data-supp-info-image", ".c-article-table .c-article-table-image img"):
            self.assertIn(part, SN.fulltext_images_js)
        # Each table's own page fetched from the article page, in time for the page read.
        self.assertTrue(SN.fulltext_prepare_js.startswith("async () =>"))
        for part in ("/tables/", "credentials: 'include'", "AbortController", "DOMParser", ".c-article-table-container",
                     "data-table-inlined", ".slice(0, 30)", "Date.now() + 12000", "Math.min(5000"):
            self.assertIn(part, SN.fulltext_prepare_js)
        self.assertNotEqual(SN.fulltext_prepare_js, fulltext_page.MATHJAX_SOURCES_JS)

    def test_bmj_reads_highwire_pages_and_puts_in_their_tables(self):
        from paper_search_school.adapters import bmj
        from paper_search_school.adapters.bmj import BMJAdapter

        # The full text is div.article.fulltext-view; each figure's large image, without the viewer's size.
        self.assertIs(BMJAdapter.fulltext_shown_js, bmj.FULLTEXT_SHOWN_JS)
        self.assertIn(".article.fulltext-view", BMJAdapter.fulltext_shown_js)
        self.assertIs(BMJAdapter.fulltext_images_js, bmj.FULLTEXT_IMAGES_JS)
        self.assertIn("div.fig", BMJAdapter.fulltext_images_js)
        self.assertIn(r"\.large\.", BMJAdapter.fulltext_images_js)
        self.assertIn("url.search = ''", BMJAdapter.fulltext_images_js)
        # A table is only its caption and "View inline": each fetched from the page and put in.
        prepare = BMJAdapter.fulltext_prepare_js
        self.assertTrue(prepare.startswith("async () =>"))
        for part in ("a.table-expand-inline[data-table-url]", "credentials: 'include'", "AbortController", "DOMParser",
                     "Date.now() + 20000", "Math.min(8000", "papersearch-table", ".table-foot"):
            self.assertIn(part, prepare)
        self.assertNotEqual(prepare, fulltext_page.MATHJAX_SOURCES_JS)

    def test_lww_reads_ovid_pages_and_thieme_its_full_text_page(self):
        from paper_search_school.adapters.lww import LWWAdapter, ovid
        from paper_search_school.adapters.thieme import ThiemeAdapter

        # LWW's article pages are Ovid's: the body .lww-article__body, each figure's widest image.
        self.assertIs(LWWAdapter.fulltext_shown_js, ovid.FULLTEXT_SHOWN_JS)
        self.assertIs(LWWAdapter.fulltext_images_js, ovid.FULLTEXT_IMAGES_JS)
        self.assertIn(".lww-article__body", LWWAdapter.fulltext_shown_js)
        self.assertIn("omni-article-tool__check-access", LWWAdapter.fulltext_shown_js)
        self.assertIn(r"\/width\/", LWWAdapter.fulltext_images_js)
        self.assertIn("#image-gallery", LWWAdapter.fulltext_images_js)
        self.assertIsNone(LWWAdapter.fulltext_prepare_js)  # Ovid has no MathJax
        # Thieme's rules are for its full-text page (fulltext_page_url, /products/ejournals/html/):
        # section#htmlfulltext, each figure's image behind its zoom link, MathJax 3's MathML kept.
        from paper_search_school.adapters import thieme
        from paper_search_school.engine.fulltext_page import MATHJAX_SOURCES_JS

        self.assertIs(ThiemeAdapter.fulltext_shown_js, thieme.FULLTEXT_SHOWN_JS)
        self.assertIs(ThiemeAdapter.fulltext_images_js, thieme.FULLTEXT_IMAGES_JS)
        self.assertIn("section#htmlfulltext", ThiemeAdapter.fulltext_shown_js)
        self.assertIn(".zoomFunction", ThiemeAdapter.fulltext_images_js)
        self.assertIs(ThiemeAdapter.fulltext_prepare_js, MATHJAX_SOURCES_JS)

    def test_elsevier_journal_sites_and_annual_reviews_name_their_pages(self):
        # Elsevier's own journal sites (cell.com, thelancet.com) beside ScienceDirect.
        self.assertIn("sciencedirect.com", ElsevierAdapter.fulltext_shown_js)
        self.assertIn("section#bodymatter", ElsevierAdapter.fulltext_shown_js)
        self.assertIn(".dropBlock__holder", ElsevierAdapter.fulltext_shown_js)
        self.assertIn("a.download-link", ElsevierAdapter.fulltext_images_js)
        self.assertIn("data-viewer-src", ElsevierAdapter.fulltext_images_js)
        from paper_search_school.adapters.annual_reviews import AnnualReviewsAdapter
        from paper_search_school.engine.fulltext_page import MATHJAX_SOURCES_JS

        self.assertIn("#html-body", AnnualReviewsAdapter.fulltext_shown_js)
        self.assertIn("a.media-link", AnnualReviewsAdapter.fulltext_images_js)
        self.assertIn(".table-container", AnnualReviewsAdapter.fulltext_images_js)
        self.assertIs(AnnualReviewsAdapter.fulltext_prepare_js, MATHJAX_SOURCES_JS)

    def test_acs_aip_and_the_royal_society_on_silverchair_and_asce_on_atypon(self):
        # Their body paragraphs are plain <p> in .article-section-wrapper (2026-11-15).
        from paper_search_school.adapters import adapter_class
        from paper_search_school.adapters.platforms.atypon import CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS
        from paper_search_school.adapters.platforms.silverchair import SILVERCHAIR_FULLTEXT_IMAGES_JS, SILVERCHAIR_FULLTEXT_SHOWN_JS
        from paper_search_school.engine.fulltext_page import MATHJAX_SOURCES_JS

        self.assertIn(".article-section-wrapper > p", SILVERCHAIR_FULLTEXT_SHOWN_JS)
        for name in ("ACS", "AIP Publishing", "Royal Society Publishing", "RSC"):
            adapter = adapter_class(name)
            self.assertIs(adapter.fulltext_shown_js, SILVERCHAIR_FULLTEXT_SHOWN_JS, name)
            self.assertIs(adapter.fulltext_images_js, SILVERCHAIR_FULLTEXT_IMAGES_JS, name)
        for name in ("ASCE", "ACM"):
            adapter = adapter_class(name)
            self.assertIs(adapter.fulltext_shown_js, CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS, name)
            self.assertIs(adapter.fulltext_prepare_js, MATHJAX_SOURCES_JS, name)

    def test_ieee_reads_its_article_and_writes_in_its_references(self):
        from paper_search_school.adapters import ieee
        from paper_search_school.adapters.ieee import IEEEAdapter

        # The full text is #article; a paywalled page shows the first paragraph as div.document-text.snippet-text.
        self.assertIs(IEEEAdapter.fulltext_shown_js, ieee.FULLTEXT_SHOWN_JS)
        self.assertIn("div.document-text:not(.snippet-text) #article", IEEEAdapter.fulltext_shown_js)
        # Each figure's full-size image: the link around its -small.gif, else the zoom button's data-src.
        self.assertIs(IEEEAdapter.fulltext_images_js, ieee.FULLTEXT_IMAGES_JS)
        for part in ("div.figure", "node.tagName === 'A'", "javascript:", "button[data-src]", "new URL(src, location.href)"):
            self.assertIn(part, IEEEAdapter.fulltext_images_js)
        # The references are not in the page: fetched from IEEE's REST in the page and written in for the converter.
        prepare = IEEEAdapter.fulltext_prepare_js
        self.assertTrue(prepare.startswith("async () =>"))
        for part in ("/rest/document/${number}/references", "rowsPerPage=30", "credentials: 'include'", "AbortController",
                     "referenceCount", "Date.now() + 10000", "Math.min(5000", "papersearch-ieee-references", "application/json",
                     r"'\\u003c'"):
            self.assertIn(part, prepare)
        # The formulas' TeX stays in MathJax 2's scripts: no MathML to keep.
        self.assertNotEqual(prepare, fulltext_page.MATHJAX_SOURCES_JS)
    def test_copernicus_reads_its_open_article_page(self):
        from paper_search_school.adapters import copernicus
        from paper_search_school.adapters.copernicus import CopernicusAdapter

        # The sections of div.article; each figure's print version when it is an image file (it
        # can be a PDF), else its web version; a table's image (the page has no HTML table).
        self.assertIs(CopernicusAdapter.fulltext_shown_js, copernicus.FULLTEXT_SHOWN_JS)
        self.assertIs(CopernicusAdapter.fulltext_images_js, copernicus.FULLTEXT_IMAGES_JS)
        self.assertIn('div.article > div.sec[id^="section"]:not(.ref-list)', CopernicusAdapter.fulltext_shown_js)
        for part in ("'figure-download', ['href', 'data-printversion']", "'figure-link'", "'table-link'", "png|jpe?g|gif|webp"):
            self.assertIn(part, CopernicusAdapter.fulltext_images_js)
        self.assertIsNone(CopernicusAdapter.fulltext_prepare_js)  # MathJax 2 keeps each formula's MathML

    def test_world_scientific_on_atypons_older_template(self):
        # Taylor & Francis's rules; its figures are <figure>, the full-size image in data-lg-src (2026-11-15).
        from paper_search_school.adapters.platforms.atypon import (
            CLASSIC_TEMPLATE_FULLTEXT_IMAGES_JS, CLASSIC_TEMPLATE_FULLTEXT_PREPARE_JS, CLASSIC_TEMPLATE_FULLTEXT_SHOWN_JS)
        from paper_search_school.adapters.world_scientific import WorldScientificAdapter
        from paper_search_school.engine.fulltext_page import MATHJAX_SOURCES_JS

        self.assertIs(WorldScientificAdapter.fulltext_shown_js, CLASSIC_TEMPLATE_FULLTEXT_SHOWN_JS)
        self.assertIs(WorldScientificAdapter.fulltext_images_js, CLASSIC_TEMPLATE_FULLTEXT_IMAGES_JS)
        self.assertIs(WorldScientificAdapter.fulltext_prepare_js, MATHJAX_SOURCES_JS)
        self.assertIs(CLASSIC_TEMPLATE_FULLTEXT_PREPARE_JS, MATHJAX_SOURCES_JS)
        for part in (".hlFld-Abstract figure img, .hlFld-Fulltext figure img", "data-lg-src", "closest('figcaption')", "tfviewerdata="):
            self.assertIn(part, CLASSIC_TEMPLATE_FULLTEXT_IMAGES_JS)

    def test_optica_reads_its_article_page(self):
        # div#articleBody > article; each figure's "Download Full Size" link, not its lazy
        # <img> (a loader until in view); MathJax 4's TeX on its output, MathML kept (2026-11-15).
        from paper_search_school.adapters import adapter_class
        from paper_search_school.adapters import optica
        from paper_search_school.engine.fulltext_page import MATHJAX_SOURCES_JS

        adapter = adapter_class("Optica")
        self.assertIs(adapter.fulltext_shown_js, optica.FULLTEXT_SHOWN_JS)
        self.assertIs(adapter.fulltext_images_js, optica.FULLTEXT_IMAGES_JS)
        self.assertIn("div#articleBody > article", adapter.fulltext_shown_js)
        for part in ("div.figure-image", "imagetype=full", "data-src", "ajax-loader"):
            self.assertIn(part, adapter.fulltext_images_js)
        self.assertIs(adapter.fulltext_prepare_js, MATHJAX_SOURCES_JS)

    def test_iop_reads_its_full_text_and_loads_its_references(self):
        from paper_search_school.adapters import iop
        from paper_search_school.adapters.iop import IOPAdapter

        # The full text is div.wd-jnl-art-full-text; an accepted manuscript or a paywalled page has none.
        self.assertIs(IOPAdapter.fulltext_shown_js, iop.FULLTEXT_SHOWN_JS)
        self.assertIn("div.wd-jnl-art-full-text", IOPAdapter.fulltext_shown_js)
        # Each figure's high-resolution image, else the standard one, else the <img>; not the formulas' GIFs.
        self.assertIs(IOPAdapter.fulltext_images_js, iop.FULLTEXT_IMAGES_JS)
        for part in ("fig-dwnld-hi-img", "fig-dwnld-std-img", "closest('figure')", ".texImage", "new URL(src, location.href)"):
            self.assertIn(part, IOPAdapter.fulltext_images_js)
        # The references are loaded only when their panel opens: fetched as the page does and put into it.
        prepare = IOPAdapter.fulltext_prepare_js
        self.assertTrue(prepare.startswith("async () =>"))
        for part in ("references-wrapper", "/references${path}", "location.pathname.replace('/meta', '')",
                     "credentials: 'include'", "AbortController", "8000", "DOMParser",
                     '[data-toolbar-content="references"], li[data-reference]', "data-papersearch-references"):
            self.assertIn(part, prepare)
        # The formulas' TeX stays in MathJax's scripts (MathJax is off by default): no MathML to keep.
        self.assertNotEqual(prepare, fulltext_page.MATHJAX_SOURCES_JS)

    def test_aps_reads_its_loaded_full_text_and_keeps_every_formulas_mathml(self):
        from paper_search_school.adapters import aps
        from paper_search_school.adapters.aps import APSAdapter

        # The full text #fulltext-content, once loaded; not an accepted paper, not behind the authorization box.
        self.assertIs(APSAdapter.fulltext_shown_js, aps.FULLTEXT_SHOWN_JS)
        for part in ("#article-body #fulltext-content", "'pending'", r"\/accepted\/", "#inline-unauthorized-page",
                     ".article-fulltext-table-wrap"):
            self.assertIn(part, APSAdapter.fulltext_shown_js)
        # Each figure's largest image from the page's data (window.APS), the medium one shown in its place.
        self.assertIs(APSAdapter.fulltext_images_js, aps.FULLTEXT_IMAGES_JS)
        for part in ("window.APS = ", "article?.figures", "entry?.xmlid === figure.id", "actual_dimensions", "/deliverable",
                     "img.closest('figcaption')", "new URL(src, location.href)"):
            self.assertIn(part, APSAdapter.fulltext_images_js)
        # The shared script keeps the MathML MathJax still lists; the rest comes from the full text's JSON.
        prepare = APSAdapter.fulltext_prepare_js
        self.assertTrue(prepare.startswith("async () =>"))
        self.assertIn(fulltext_page.MATHJAX_SOURCES_JS, prepare)
        self.assertNotIn("await (MATHJAX_SOURCES_JS)", prepare)
        for part in ("fulltext/${id}", "credentials: 'include'", "AbortController", "10000", "['front', 'back']",
                     "nodes.length !== sources.length", ".article-fulltext-disp-eq", "data-original-mathml"):
            self.assertIn(part, prepare)
        # The PDF's rules are as they were: an accepted paper is no article PDF.
        self.assertFalse(APSAdapter.belongs_to_article("https://journals.aps.org/prl/accepted/10.1103/x", "10.1103/x", ""))

    def test_ams_reads_its_article_body_and_each_figures_largest_image(self):
        from paper_search_school.adapters import ams
        from paper_search_school.adapters.ams import AMSAdapter

        # The body is #articleBody's paragraphs; the tabs are on an early-online page without one too.
        self.assertIs(AMSAdapter.fulltext_shown_js, ams.FULLTEXT_SHOWN_JS)
        for part in ("#articleBody", "'p, div.p'", ".figure, .tableWrap, .refSection, .keywords", "text > 500"):
            self.assertIn(part, AMSAdapter.fulltext_shown_js)
        self.assertNotIn("data-tab-id", AMSAdapter.fulltext_shown_js)
        # Each figure's and table's largest image, in its hidden pop-up, not the lazy Blank.svg it shows.
        self.assertIs(AMSAdapter.fulltext_images_js, ams.FULLTEXT_IMAGES_JS)
        for part in ("div.figure, div.tableWrap", "data-image-src", "img.closest('pf-box')", r"\/Blank\.svg",
                     "new URL(src, location.href)"):
            self.assertIn(part, AMSAdapter.fulltext_images_js)
        self.assertIsNone(AMSAdapter.fulltext_prepare_js)  # MathJax 2 keeps each formula's MathML
        # The PDF's rules are as they were.
        self.assertEqual(
            AMSAdapter.profile_pdf_candidates("10.1175/AIES-D-26-0041.1",
                                              "https://journals.ametsoc.org/view/journals/aies/5/4/AIES-D-26-0041.1.xml"),
            ["https://journals.ametsoc.org/downloadpdf/view/journals/aies/5/4/AIES-D-26-0041.1.pdf"])

    def test_dove_reads_its_open_article_page(self):
        from paper_search_school.adapters import dovepress
        from paper_search_school.adapters.dovepress import DovePressAdapter

        # The body in div#article-fulltext (an older page's p.h1 headings aside, the references and
        # the floats' captions aside); each figure's and table's full image, the link around its
        # thumbnail, not the lens icon an older page puts beside it (2026-11-18).
        self.assertIs(DovePressAdapter.fulltext_shown_js, dovepress.FULLTEXT_SHOWN_JS)
        self.assertIs(DovePressAdapter.fulltext_images_js, dovepress.FULLTEXT_IMAGES_JS)
        for part in ("div.article-inner_html > div#article-fulltext", "p.closest('table')", "'$reftext'", "text >= 200"):
            self.assertIn(part, DovePressAdapter.fulltext_shown_js)
        for part in ("table.thumbnail-table", "thumbnail-lens", "img.closest('a[href]')", "new URL(src, location.href)"):
            self.assertIn(part, DovePressAdapter.fulltext_images_js)
        self.assertIsNone(DovePressAdapter.fulltext_prepare_js)  # no MathJax: formulas are text


    def test_frontiers_reads_its_article_content_and_each_figures_original_image(self):
        from paper_search_school.adapters import adapter_class
        from paper_search_school.adapters import frontiers
        from paper_search_school.adapters.frontiers import FrontiersAdapter

        # The body sections of div.ArticleContent, not its abstract, statements, references or summary.
        self.assertIs(adapter_class("frontiers"), FrontiersAdapter)
        self.assertIs(FrontiersAdapter.fulltext_shown_js, frontiers.FULLTEXT_SHOWN_JS)
        for part in ("div.ArticleContent", ".Summary, [class*=\"Statement__\"]", "ul.References", "^abstract$",
                     ".ArticleFigure, .ArticleTable", "text > 500"):
            self.assertIn(part, FrontiersAdapter.fulltext_shown_js)
        # Each figure's original image, the resizer's addresses (/api/ipx/…/<original>) taken back to it.
        self.assertIs(FrontiersAdapter.fulltext_images_js, frontiers.FULLTEXT_IMAGES_JS)
        for part in ("div.ArticleFigure", "div.ArticleTable", "source[srcset]", r"\/api\/ipx\/", "new URL(original(value), location.href)"):
            self.assertIn(part, FrontiersAdapter.fulltext_images_js)
        self.assertIsNone(FrontiersAdapter.fulltext_prepare_js)  # MathJax 2 keeps each formula's MathML
        self.assertEqual(FrontiersAdapter.fulltext_page_url(None, "10.3389/fexr.2026.1234567", "https://www.frontiersin.org/x"), "")

    def test_mdpi_reads_its_article_and_each_figures_full_size_image(self):
        from paper_search_school.adapters import adapter_class
        from paper_search_school.adapters import mdpi

        # The body's div.html-p in #article-contents (the current design) or div.html-body (the
        # earlier one); the abstract, back matter, references and hidden copies apart (2026-11-18).
        adapter = adapter_class("mdpi")
        self.assertIs(adapter.fulltext_shown_js, mdpi.FULLTEXT_SHOWN_JS)
        for part in ("#article-contents", "div.html-body", "div.html-p", ".html-abstract", "#html-references_list",
                     '[type="display-objects"]', "text > 500"):
            self.assertIn(part, adapter.fulltext_shown_js)
        # Each figure's full size (data-large, not the 550 px thumbnail in src); a table's image only
        # when its pop-up has no HTML table; not the hidden copies, pop-ups or graphical abstract.
        self.assertIs(adapter.fulltext_images_js, mdpi.FULLTEXT_IMAGES_JS)
        for part in ("div.html-fig-wrap, div.html-table-wrap", "'data-large', 'data-original', 'data-lsrc', 'src'",
                     "'html-figpopup'", "'html-tablepopup'", "!table.querySelector('table')", 'section[type="display-objects"]',
                     "#html-graphical", "table\\.png", "new URL(src, location.href)"):
            self.assertIn(part, adapter.fulltext_images_js)
        # The shared script keeps the formulas' MathML when MathJax answers; PaperSearch reads the payload otherwise.
        self.assertIs(adapter.fulltext_prepare_js, fulltext_page.MATHJAX_SOURCES_JS)
        # Read at the address with a query: the bare one can serve the abstract alone on a repeat visit.
        page_url = adapter.fulltext_page_url
        self.assertEqual(page_url(None, "10.3390/en19215291", "https://www.mdpi.com/1996-1073/19/21/5291"),
                         "https://www.mdpi.com/1996-1073/19/21/5291?type=check_update&version=1")
        self.assertEqual(page_url(None, "10.3390/jcm14217740", "https://www.mdpi.com/2077-0383/14/21/7740/#sec1"),
                         "https://www.mdpi.com/2077-0383/14/21/7740/?type=check_update&version=1")
        for other in ("https://www.mdpi.com/1996-1073/19/21/5291?type=check_update&version=1",
                      "https://www.mdpi.com/1996-1073/19/21/5291/pdf", "https://www.mdpi.com/journal/energies",
                      "http://www.mdpi.com/1996-1073/19/21/5291", "https://evil.example/1996-1073/19/21/5291", ""):
            self.assertEqual(page_url(None, "10.3390/en19215291", other), "", other)

    def test_plos_reads_its_article_text_each_floats_larger_image_and_the_formulas_mathml(self):
        from paper_search_school.adapters import adapter_class
        from paper_search_school.adapters import plos

        # The body sections of div#artText, not the abstracts, the supporting information, the
        # acknowledgments or the references; each figure's and table's larger PNG (size=large),
        # not the thumbnail the general rules took (2026-11-18).
        adapter = adapter_class("plos")
        self.assertIs(adapter.fulltext_shown_js, plos.FULLTEXT_SHOWN_JS)
        for part in ("div#artText", "div.section", ".abstract, .contributions", "div.supplementary-material, ol.references",
                     "acknowledge?ments?", "p.closest('div.figure')", "chars >= 200"):
            self.assertIn(part, adapter.fulltext_shown_js)
        self.assertIs(adapter.fulltext_images_js, plos.FULLTEXT_IMAGES_JS)
        for part in ("div#artText div.figure", "size=large", "size=medium", "new URL(href, location.href)"):
            self.assertIn(part, adapter.fulltext_images_js)
        # The formulas are images on the page; their MathML comes from the article's XML, which
        # the backend fetches (the page cannot: another host, no CORS) and the script writes on them.
        self.assertIs(adapter.fulltext_prepare_js, plos.FULLTEXT_PREPARE_JS)
        for part in ("span.inline-formula", "span.equation", "DOMParser", "'inline-formula'", "'disp-formula'",
                     "http://www.w3.org/1998/Math/MathML", "info:doi", "data-original-mathml", "node.localName"):
            self.assertIn(part, adapter.fulltext_prepare_js)
        source = adapter(None).fulltext_prepare_source
        self.assertEqual(source("10.1371/journal.pcbi.1004142", "https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1004142"),
                         "https://journals.plos.org/ploscompbiol/article/file?id=10.1371/journal.pcbi.1004142&type=manuscript")
        for doi, page in (("10.1371/journal.pone.0300001", "https://example.org/plosone/article?id=10.1371/journal.pone.0300001"),
                          ("10.1371/journal.pone.0300001", "https://journals.plos.org/article?id=10.1371/journal.pone.0300001"),
                          ("10.1371/journal.pone.0300001&type=printable", "https://journals.plos.org/plosone/article?id=x"),
                          ("10.1000/other", "https://journals.plos.org/plosone/article?id=10.1000/other"), ("", "")):
            self.assertEqual(source(doi, page), "", (doi, page))





# A Dove article page as the server renders it, with invented text: the byline and abstract in
# the first <p>, then div#article-fulltext with a figure, a table and the references.
DOVE_PAGE = """<!DOCTYPE html><html><head><meta name="citation_doi" content="10.2147/JEI.S600001"></head><body>
<aside class="sidebar"><div class="padding"><p>Submit your manuscript.</p><img src="/assets/img/promo.jpg"></div></aside>
<div class="copy"><div class="article-inner_html">
<p>Alice Author<sup>1</sup><br><br><sup>1</sup>Red Magnolia University<br><br><strong>Abstract:</strong> Knees swell.<br><br></p>
<div id="article-fulltext" class="html-oct"><div class="$body">
<h2>Introduction</h2>
<p>Swollen knees trouble many rats in the cold season, and the bark of the red magnolia tree is an old remedy for them,
 though few studies have asked how it might work and fewer have measured it at all; we did, in forty rats.<sup><a href="#cit0001">1</a></sup></p>
<div id="f0001"></div><a name="f0001"></a><table class="thumbnail-table"><tbody><tr><td><a href="article/fulltext_file/600001/aW1n/JEI_A_600001_O_F0001g.jpg" class="float_border"><img src="article/fulltext_file/600001/aW1n/JEI_A_600001_O_F0001g_Thumb.jpg" class="imgsmall"></a></td><td><p class="tabtext"><strong>Figure 1</strong> The bark.</p></td></tr></tbody></table>
<div id="t0001"></div><a name="t0001"></a><table class="thumbnail-table"><tbody><tr><td><a href="article/fulltext_file/600001/aW1n/JEI_A_600001_t0001.jpg" class="float_border"><img src="article/fulltext_file/600001/aW1n/JEI_A_600001_t0001_Thumb.jpg" class="imgsmall"></a></td><td><p class="tabtext"><strong>Table 1</strong> Doses.</p></td></tr></tbody></table>
<div id="F2" class="dotted1"></div><table class="thumbnail-table"><tr><td><a href="article/fulltext_file/600001/aW1n/fig2.jpg" class="float_border"><img src="article/fulltext_file/600001/aW1n/fig2small.jpg" class="imgsmall"><img src="article/fulltext_file/600001/aW1n/lens.jpg" class="thumbnail-lens"></a></td><td><p class="tabtext"><span class="b">Figure 2</span> The knee.</p></td></tr></table>
</div><div class="$back"><h2>References</h2>
<p id="cit0001" class="$reftext"><a name="cit0001" href="#ref-cit0001">1.</a> Smith J. Magnolia remedies for swollen knees and other troubles of the joints in rats, a long review. <em>J Example Herbs</em>. 2020;12:100–110.</p>
</div></div></div></div></body></html>"""


@unittest.skipUnless(__import__("os").environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class DoveFulltextPageBrowserTests(unittest.TestCase):
    URL = "https://www.dovepress.com/red-magnolia-bark-eases-knee-swelling-in-rats-peer-reviewed-fulltext-article-JEI"

    def evaluate(self, html):
        from patchright.sync_api import sync_playwright
        from paper_search_school.adapters.dovepress import FULLTEXT_IMAGES_JS, FULLTEXT_SHOWN_JS

        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context()
                context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
                page = context.new_page()
                page.goto(self.URL)
                return page.evaluate(FULLTEXT_SHOWN_JS), page.evaluate(FULLTEXT_IMAGES_JS)
            finally:
                browser.close()

    def test_the_body_shows_and_each_float_is_its_full_image(self):
        shown, images = self.evaluate(DOVE_PAGE)
        base = "https://www.dovepress.com/article/fulltext_file/600001/aW1n/"
        self.assertTrue(shown)
        # The links around the thumbnails, in page order; not the lens icon nor the sidebar's image.
        self.assertEqual(images, [base + "JEI_A_600001_O_F0001g.jpg", base + "JEI_A_600001_t0001.jpg", base + "fig2.jpg"])

    def test_an_article_with_only_its_abstract_is_not_shown(self):
        start = DOVE_PAGE.index('<div id="article-fulltext"')
        empty = DOVE_PAGE[:start] + '<div id="article-fulltext"></div></div></div></body></html>'
        self.assertEqual(self.evaluate(empty), (False, []))


if __name__ == "__main__":
    unittest.main()

# A Frontiers article page as the browser has it (2026-11-18): a journal card, an <article>, in the left
# column before <main>; the authors' photos in <figure>; div.ArticleContent with the abstract, the body,
# the statements, the references and the summary; a card with its image after the article.
FRONTIERS_ORIGINAL = "https://www.frontiersin.org/files/Articles/1234567/xml-images/fexr-14-1234567-{}.webp"
FRONTIERS_RESIZED = "https://www.frontiersin.org/api/ipx/w=340&amp;f=webp&amp;v=7/" + FRONTIERS_ORIGINAL
FRONTIERS_BODY = "<p>" + "Red magnolia pollen burns in a flame-assisted fuel cell and gives power for hours. " * 8 + "</p>"
FRONTIERS_TEXT = {"abstract": "Pollen gives power. " * 40, "funding": "The groves paid for it. " * 30,
                  "reference": "Smith J. Pollen. " * 40, "summary": "Keywords and the copyright of this article. " * 20}
FRONTIERS_PAGE = """<html><head><meta name="citation_doi" content="10.3389/fexr.2026.1234567"></head><body>
<aside><article class="CardJournal"><p>Frontiers in Example Research</p></article>
  <figure class="FrontiersImage"><img src="{g001_resized}"></figure></aside>
<main class="ArticleDetailsV4__main"><h1 class="ArticleDetailsV4__main__title">Red magnolia pollen</h1>
<div class="PeopleList"><figure class="Avatar"><img src="https://loop.frontiersin.org/images/profile/1001/74"></figure>
  <p class="PeopleListItem__name">Alice Author</p></div>
<div class="ArticleContent">
  <div id="h1"><h2>Abstract</h2><p>{abstract}</p></div>
  <div id="s1"><h2>1 Introduction</h2>{{body}}
    <div class="ArticleFigure" id="F1"><p class="ArticleFigure__title">FIGURE 1</p><button><figure class="FrontiersImage"><picture>
      <source srcset="{g001_resized} 1x"><img src="{g001}" loading="lazy"></picture>
      <figcaption><p>The cell.</p></figcaption></figure></button></div>
    <div class="ArticleFigure" id="F2"><p class="ArticleFigure__title">FIGURE 2</p><button><figure class="FrontiersImage"><picture>
      <img src="{g002_resized}" loading="lazy"></picture><figcaption><p>The run.</p></figcaption></figure></button></div>
    <div class="ArticleFigure" id="F3"><p class="ArticleFigure__title">FIGURE 3</p><button><figure class="FrontiersImage"><picture>
      <img src="/files/Articles/1234567/xml-images/fexr-14-1234567-g003.webp"></picture></figure></button></div>
    <div class="ArticleTable" id="T1"><p class="ArticleTable__title">TABLE 1</p><div class="ArticleTable__content"><table><tr><td>1</td></tr></table></div></div>
    <div class="ArticleTable" id="T2"><p class="ArticleTable__title">TABLE 2</p><div class="ArticleTable__content"><img src="{t002}"></div>
      <div class="ArticleTable__description"><p>Sites.</p></div></div></div>
  <h2 id="h7">Statements</h2><div class="Statement__Funding"><h3>Funding</h3><p>{funding}</p></div>
  <div id="h9"><h2>References</h2><ul class="References"><li class="References__item" id="B1"><div class="References__content"><p>{reference}</p></div></li></ul></div>
  <div class="Summary"><p>{summary}</p></div>
</div>
<div class="AnnouncementCard"><article class="CardA"><figure class="FrontiersImage CardA__img"><img src="https://www.frontiersin.org/api/ipx/s=366x408/https://brand.frontiersin.org/asset/x/thumbnail/grove"></figure></article></div>
</main></body></html>""".format(g001=FRONTIERS_ORIGINAL.format("g001"), g001_resized=FRONTIERS_RESIZED.format("g001"),
                               g002_resized=FRONTIERS_RESIZED.format("g002"), t002=FRONTIERS_ORIGINAL.format("t002"), **FRONTIERS_TEXT)


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class FrontiersPageScriptTests(unittest.TestCase):
    """The Frontiers adapter's page scripts on a page as the browser has it (Chrome, headless)."""

    def evaluate(self, html, *scripts):
        from patchright.sync_api import sync_playwright

        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context()
                context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
                page = context.new_page()
                page.goto("https://www.frontiersin.org/journals/example-research/articles/10.3389/fexr.2026.1234567/full")
                return [page.evaluate(script) for script in scripts]
            finally:
                browser.close()

    def test_the_article_page_shows_the_full_text_where_the_general_rule_saw_none(self):
        from paper_search_school.adapters import frontiers

        shown, general = self.evaluate(FRONTIERS_PAGE.replace("{body}", FRONTIERS_BODY),
                                       frontiers.FULLTEXT_SHOWN_JS, fulltext_page._SAMPLE_SHOWN_JS)
        self.assertTrue(shown)
        # The general rule read the journal card, the first <article>: "文章页没有正文" (2026-11-18).
        self.assertFalse(general)

    def test_a_page_with_only_its_abstract_statements_and_references_shows_no_full_text(self):
        from paper_search_school.adapters import frontiers

        self.assertEqual(self.evaluate(FRONTIERS_PAGE.replace("{body}", "<p>Short.</p>"), frontiers.FULLTEXT_SHOWN_JS), [False])

    def test_each_figures_original_image_and_a_tables_given_only_as_one(self):
        from paper_search_school.adapters import frontiers

        [images] = self.evaluate(FRONTIERS_PAGE.replace("{body}", FRONTIERS_BODY), frontiers.FULLTEXT_IMAGES_JS)
        # Not the authors' photos, the left column's thumbnails or the card's image; a table in HTML has none.
        self.assertEqual(images, [FRONTIERS_ORIGINAL.format(name) for name in ("g001", "g002", "g003", "t002")])

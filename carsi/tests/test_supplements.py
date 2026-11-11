"""Supplementary files: collection with the browser session, Wiley's link table, bridge results."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from paper_search_carsi.engine import bridge, supplements
from paper_search_carsi.adapters import SupplementLink
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import get_publisher_profile

DOI = "10.1002/art.70156"
SUPP = "https://acrjournals.onlinelibrary.wiley.com/action/downloadSupplement?doi=10.1002%2Fart.70156&file=art70156-sup-0001-Disclosureform.pdf"


def response(body=b"data", status=200, ctype="application/pdf", disposition="", length=None):
    headers = {"content-type": ctype, "content-disposition": disposition}
    if length is not None:
        headers["content-length"] = str(length)
    return SimpleNamespace(ok=200 <= status < 300, status=status, headers=headers, body=lambda: body)


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())

    def test_files_are_saved_named_and_listed_with_failures_explained(self):
        replies = {
            SUPP: response(b"%PDF-1.7 disclosure"),
            "https://x.example/a.xlsx": response(b"xlsx", ctype="application/vnd.ms-excel",
                                                 disposition='attachment; filename="Table S1.xlsx"'),
            "https://x.example/login": response(b"<html>", ctype="text/html; charset=utf-8"),
            "https://x.example/gone": response(status=404),
            "https://x.example/huge.zip": response(length=supplements.MAX_FILE_BYTES + 1),
        }
        request = MagicMock(); request.get.side_effect = lambda url, **kw: replies[url]
        links = [SupplementLink(SUPP, "Disclosure form"), SupplementLink(SUPP, "duplicate"),
                 *(SupplementLink(u, u[-6:]) for u in list(replies)[1:])]
        files = supplements.collect(request, links, self.out, DOI)
        by_url = {f["url"]: f for f in files}
        self.assertEqual(len(files), 5)
        folder = self.out / "10.1002_art.70156_supplements"
        self.assertEqual(Path(by_url[SUPP]["file"]), folder / "art70156-sup-0001-Disclosureform.pdf")
        self.assertEqual(Path(by_url["https://x.example/a.xlsx"]["file"]).name, "Table S1.xlsx")
        self.assertEqual(by_url["https://x.example/login"]["reason"], "html_page")
        self.assertEqual(by_url["https://x.example/gone"]["reason"], "http_404")
        self.assertEqual(by_url["https://x.example/huge.zip"]["reason"], "too_large")
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertEqual([f["status"] for f in manifest["files"]], ["saved", "saved", "failed", "failed", "skipped"])

    def test_a_page_instead_of_the_file_is_recorded_as_it_was(self):
        """Which page Figshare's download address answered, for the record (2026-11-08)."""
        page = SimpleNamespace(ok=True, status=202, url="https://ndownloader.figshare.com/files/51439886?token=secret",
                               headers={"content-type": "text/html; charset=UTF-8", "x-amzn-waf-action": "challenge",
                                        "server": "CloudFront"},
                               body=lambda: b"<html><head><title>\n Human &amp; Verification </title></head></html>")
        request = MagicMock(); request.get.return_value = page
        files = supplements.collect(request, [SupplementLink("https://api.figshare.com/v2/file/download/51439886")],
                                    self.out, DOI)
        self.assertEqual(files[0]["reason"], "verification_page")  # the firewall's challenge, told apart
        self.assertEqual({k: files[0][k] for k in ("http_status", "final_url", "page_title", "page_headers")}, {
            "http_status": 202, "final_url": "https://ndownloader.figshare.com/files/51439886",
            "page_title": "Human & Verification",
            "page_headers": {"server": "CloudFront", "x-amzn-waf-action": "challenge"}})

    def test_a_verification_page_goes_to_the_browser_as_a_403_does(self):
        """Figshare's AWS WAF answered every scripted request with a page (2026-11-08):
        the browser opens the link as a reader would; failing that, the page is recorded."""
        def challenge():
            return SimpleNamespace(ok=True, status=202, url="https://api.figshare.com/v2/file/download/51439886",
                                   headers={"content-type": "text/html; charset=UTF-8", "x-amzn-waf-action": "challenge"},
                                   body=lambda: b"<html></html>", dispose=MagicMock())
        link = SupplementLink("https://api.figshare.com/v2/file/download/51439886", "Supplementary_Material.pdf")
        request = MagicMock(); request.get.side_effect = lambda url, **kw: challenge()
        browser = MagicMock(return_value=(b"%PDF-1.7 supplementary", "Supplementary_Material.pdf"))
        files = supplements.collect(request, [link], self.out, DOI, download=browser)
        browser.assert_called_once_with(link.url)
        self.assertEqual((files[0]["status"], files[0]["via"]), ("saved", "browser_download"))
        self.assertTrue(files[0]["file"].endswith("Supplementary_Material.pdf"))

        browser = MagicMock(side_effect=TimeoutError("attachment download or native PDF was not ready"))
        files = supplements.collect(request, [link], self.out, DOI, download=browser)
        self.assertEqual({k: files[0].get(k) for k in ("status", "reason", "via", "http_status")},
                         {"status": "failed", "reason": "verification_page", "via": "browser_download", "http_status": 202})

    def test_a_dropped_connection_is_tried_once_more(self):
        dropped = Exception("APIRequestContext.get: Client network socket disconnected before secure TLS "
                            "connection was established\nCall log:")
        request = MagicMock(); request.get.side_effect = [dropped, response(b"PK zip", ctype="application/zip")]
        files = supplements.collect(request, [SupplementLink("https://cdn.example/s/data.zip")], self.out, DOI,
                                    sleep=lambda s: None)
        self.assertEqual(files[0]["status"], "saved")
        self.assertIn("socket disconnected", files[0]["retried"])
        self.assertEqual(request.get.call_count, 2)
        # Any other error (a timeout) is not repeated.
        request = MagicMock(); request.get.side_effect = Exception("Timeout 60000ms exceeded")
        files = supplements.collect(request, [SupplementLink("https://cdn.example/s/data.zip")], self.out, DOI,
                                    sleep=lambda s: None)
        self.assertEqual((files[0]["status"], request.get.call_count), ("failed", 1))

    def test_a_file_refused_to_scripted_requests_is_downloaded_by_a_click(self):
        # Emerging Microbes & Infections with ego: 403 to every scripted request, a click went through.
        request = MagicMock(); request.get.return_value = response(status=403, ctype="text/html")
        url = "https://www.tandfonline.com/action/downloadSupplement?doi=10.1080%2F22221751.2026.2751725&file=temi_a_2751725_sm4955.docx"
        clicked = []
        def download(link):
            clicked.append(link)
            return b"PK docx", "temi_a_2751725_sm4955.docx"
        files = supplements.collect(request, [SupplementLink(url, "Table S1")], self.out, DOI, download=download)
        self.assertEqual((files[0]["status"], files[0]["via"]), ("saved", "browser_download"))
        self.assertEqual(Path(files[0]["file"]).read_bytes(), b"PK docx")
        self.assertEqual(Path(files[0]["file"]).name, "temi_a_2751725_sm4955.docx")
        self.assertEqual(clicked, [url])
        # Without a browser download the refusal stands.
        files = supplements.collect(request, [SupplementLink(url, "Table S1")], self.out, DOI)
        self.assertEqual((files[0]["status"], files[0]["reason"]), ("failed", "http_403"))

    def test_time_budget_skips_the_rest(self):
        now = [0]
        request = MagicMock(); request.get.return_value = response()
        files = supplements.collect(request, [SupplementLink("https://x/1.pdf"), SupplementLink("https://x/2.pdf")],
                                    self.out, DOI, clock=lambda: now[0],
                                    progress=lambda saved: now.__setitem__(0, supplements.TIME_BUDGET_SEC + 1))
        self.assertEqual([f["status"] for f in files], ["saved", "skipped"])
        self.assertEqual(files[1]["reason"], "time_budget")

    def test_oversized_native_viewer_attachment_is_a_size_skip(self):
        request = MagicMock(); request.get.return_value = response(status=403)
        page = MagicMock(); page.evaluate.return_value = {"oversized": supplements.MAX_FILE_BYTES + 1}
        d = PublisherBatchDownloader({})
        files = supplements.collect(request, [SupplementLink(SUPP)], self.out, DOI,
            download=lambda url: d._capture_loaded_pdf_viewer(page, url, output=self.out / 'part',
                                                              max_bytes=supplements.MAX_FILE_BYTES))
        self.assertEqual((files[0]['status'], files[0]['reason']), ('skipped', 'too_large'))
        self.assertEqual(files[0]['size'], supplements.MAX_FILE_BYTES + 1)
        self.assertFalse((self.out / 'part').exists())

    def test_stopping_mid_collection_keeps_saved_files_and_skips_the_rest(self):
        from paper_search_carsi.entitlements import UserStoppedBatch
        request = MagicMock()
        request.get.side_effect = [response(b"first"), UserStoppedBatch("stop")]
        links = [SupplementLink(f"https://fixture.example/{i}.pdf", f"S{i}") for i in range(3)]
        files = supplements.collect(request, links, self.out, DOI)
        self.assertEqual(request.get.call_count, 2)
        self.assertEqual([f["status"] for f in files], ["saved", "skipped", "skipped"])
        self.assertEqual(Path(files[0]["file"]).read_bytes(), b"first")
        self.assertEqual([f["reason"] for f in files[1:]], ["batch_stopped", "batch_stopped"])
        manifest = json.loads((supplements.supplements_dir(self.out, DOI) / "manifest.json").read_text())
        self.assertEqual(manifest["files"], files)

    def test_separate_manifest_preserves_final_attachment_paths(self):
        request = MagicMock()
        request.get.return_value = response(b"supplement bytes")
        target = self.out / "papers" / "Nature_2026_Article" / "supplements"
        diagnostic = self.out / "diagnostics" / "article-run"
        files = supplements.collect(request, [SupplementLink("https://fixture.example/S1.pdf")],
                                    self.out, DOI, target_dir=target, manifest_dir=diagnostic)
        self.assertEqual(Path(files[0]["file"]), target / "S1.pdf")
        self.assertFalse((target / "manifest.json").exists())
        manifest = json.loads((diagnostic / "manifest.json").read_text())
        self.assertEqual(manifest["files"], files)
        self.assertTrue(Path(manifest["files"][0]["file"]).is_file())

    def test_no_links_writes_nothing(self):
        self.assertEqual(supplements.collect(MagicMock(), [], self.out, DOI), [])
        self.assertEqual(list(self.out.iterdir()), [])


class BridgeTests(unittest.TestCase):
    def run_bridge(self, mode, result, files=None):
        profile = get_publisher_profile("wiley")
        downloader = MagicMock(); downloader.fetch_one.return_value = result
        downloader.collect_supplements.return_value = (files if files is not None else
            [{"status": "saved", "file": "/tmp/out/s/x.pdf", "label": "S1"}])
        with patch("paper_search_carsi.engine.batch.PublisherBatchDownloader", return_value=downloader), \
             patch("paper_search_carsi.browser.backend.is_available", return_value=True):
            out = bridge._try_browser_batch_download(DOI, Path("/tmp/out/x.pdf"), {"supplements": mode}, profile)
        return out, downloader

    def test_only_mode_skips_the_main_text_and_reports_supplements(self):
        out, downloader = self.run_bridge("only", None)
        downloader.fetch_one.assert_not_called()
        self.assertFalse(out["success"])
        self.assertEqual(out["error_type"], "supplements_only")
        self.assertEqual(out["supplements"][0]["label"], "S1")

    def test_with_mode_adds_supplements_to_a_failure(self):
        out, downloader = self.run_bridge("with", DownloadResult(doi=DOI, status="failed", state="sso_required"))
        downloader.fetch_one.assert_called_once()
        self.assertEqual(out["supplements"][0]["status"], "saved")

    def test_no_supplements_keeps_empty_result_and_discovery_evidence(self):
        out, _ = self.run_bridge("only", None, files=[])
        self.assertEqual(out["supplements"], [])
        manifest = json.loads(Path(out["artifacts"]["record"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["doi"], DOI)
        self.assertEqual(manifest["files"], [])
        with patch.object(bridge, "_try_browser_batch_download", return_value=out):
            aggregated = bridge.try_institutional(DOI, Path("/tmp/out/x.pdf"), {
                "publisher_institution_federation": "carsi", "publisher_hourly_limit": 0})
        self.assertEqual(aggregated["supplements"], [])
        self.assertEqual(aggregated["artifacts"]["record"], out["artifacts"]["record"])

    def test_the_supplements_step_is_added_to_the_articles_record(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "x.json"
            record.write_text(json.dumps({"events": [{"state": "pdf_saved"}]}), encoding="utf-8")
            result = DownloadResult(doi=DOI, status="failed", state="sso_required")
            result.record_path = str(record)
            profile = get_publisher_profile("wiley")
            downloader = MagicMock(); downloader.fetch_one.return_value = result

            def collect(context, doi, out, res, **kwargs):
                res.events.append({"state": "supplements_found", "detail": "0"})
                return []
            downloader.collect_supplements.side_effect = collect
            with patch("paper_search_carsi.engine.batch.PublisherBatchDownloader", return_value=downloader), \
                 patch("paper_search_carsi.browser.backend.is_available", return_value=True):
                bridge._try_browser_batch_download(DOI, Path(tmp) / "x.pdf", {"supplements": "with"}, profile)
            data = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual([e["state"] for e in data["events"]], ["pdf_saved", "supplements_found"])
        self.assertEqual(data["supplements"], [])

    def test_unfinished_verification_skips_the_supplements_visit(self):
        out, downloader = self.run_bridge("with", DownloadResult(doi=DOI, status="failed",
                                                                 state="challenge_or_viewer_timeout"))
        downloader.collect_supplements.assert_not_called()
        self.assertEqual(out["supplements"], [{"status": "skipped", "reason": "challenge_timeout", "url": "", "label": ""}])

    def test_an_unsupported_platform_skips_the_supplements_visit(self):
        out, downloader = self.run_bridge("with", DownloadResult(doi=DOI, status="failed", state="unsupported_platform",
                                                                 reason="unsupported_platform"))
        downloader.collect_supplements.assert_not_called()
        self.assertEqual(out["error_type"], "unsupported_platform")
        self.assertEqual(out["supplements"], [{"status": "skipped", "reason": "unsupported_platform", "url": "", "label": ""}])

    def test_supplement_discovery_timeout_preserves_the_main_pdf_result(self):
        from paper_search_carsi.browser.watchdog import BrowserOperationTimeout
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("wiley"))
        context = MagicMock()
        result = DownloadResult(doi=DOI, status="success", state="pdf_response_captured", pdf_path="saved.pdf")
        with patch.object(d, "_challenge_shell", return_value=False), \
                patch.object(d, "_is_challenge_page", return_value=False), \
                patch.object(d, "_settled_supplement_links", side_effect=BrowserOperationTimeout("page budget")):
            files = d.collect_supplements(context, DOI, Path("/tmp/out"), result)
        self.assertTrue(result.ok)
        self.assertEqual(result.pdf_path, "saved.pdf")
        self.assertEqual(files[0]["reason"], "browser_operation_timeout")

    def test_a_site_that_does_not_answer_is_reported_as_unreachable(self):
        """Not as the driver error's class name, "Error" (pubs.acs.org, Windows 2026-11-07)."""
        from patchright.sync_api import Error
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("acs"))
        result = DownloadResult(doi=DOI, status="success", state="pdf_response_captured", pdf_path="saved.pdf")
        dropped = Error("Page.goto: net::ERR_CONNECTION_CLOSED at https://doi.org/" + DOI)
        with patch("paper_search_carsi.engine.batch.open_page", side_effect=dropped):
            files = d.collect_supplements(MagicMock(), DOI, Path("/tmp/out"), result)
        self.assertTrue(result.ok)
        self.assertEqual(files, [{"status": "failed", "reason": "publisher_unreachable", "url": "", "label": ""}])

    def test_default_collects_nothing(self):
        out, downloader = self.run_bridge("", DownloadResult(doi=DOI, status="failed", state="sso_required"))
        downloader.collect_supplements.assert_not_called()
        self.assertNotIn("supplements", out)

    def test_user_actions_stop_the_supplements_too(self):
        for state in ("user_skipped", "batch_stopped", "user_marked_no_entitlement"):
            with self.subTest(state=state):
                out, downloader = self.run_bridge("with", DownloadResult(
                    doi=DOI, status="failed", state=state, reason=state))
                downloader.collect_supplements.assert_not_called()
                self.assertEqual(out["supplements"], [
                    {"status": "skipped", "reason": state, "url": "", "label": ""}])



SD_PAGE = "https://www.sciencedirect.com/science/article/pii/S1063458422007701"
GASTRO_DOI = "10.1053/j.gastro.2024.02.046"
GASTRO_PAGE = "https://www.gastrojournal.org/article/S0016-5085(24)00291-9/fulltext"


class ElsevierLinksTests(unittest.TestCase):
    def adapter(self):
        return PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier")).adapter

    def test_sciencedirect_lists_only_this_articles_mmc_files(self):
        from paper_search_carsi.adapters.elsevier import supplement_links_from_rows
        own = "https://ars.els-cdn.com/content/image/1-s2.0-S1063458422007701-mmc1.pdf"
        rows = [{"href": own, "label": "Supplementary data 1"},
                {"href": own, "label": "duplicate"},
                {"href": SD_PAGE + "#mmc1", "label": "Multimedia component 1"},
                {"href": "https://ars.els-cdn.com/content/image/1-s2.0-S0000000000000000-mmc1.pdf"},
                {"href": "https://ars.els-cdn.com/content/image/1-s2.0-S1063458422007701-gr1.jpg"},
                {"href": "https://evil.example/content/image/1-s2.0-S1063458422007701-mmc2.pdf"}]
        links = supplement_links_from_rows(rows, SD_PAGE, "10.1016/j.joca.2022.06.006")
        self.assertEqual(links, [SupplementLink(own, "Supplementary data 1")])

    def test_journal_site_lists_attachments_under_this_doi_on_its_own_host(self):
        from paper_search_carsi.adapters.elsevier import supplement_links_from_rows
        own = f"https://www.gastrojournal.org/cms/{GASTRO_DOI}/attachment/8b89135e/mmc1.pdf"
        rows = [{"href": own, "label": "PDF (259.19 KB)"},
                {"href": GASTRO_PAGE + "#supplementary-material", "label": "Supplementary Table 13"},
                {"href": "https://www.gastrojournal.org/cms/10.1053/j.gastro.2024.01.001/attachment/x/mmc1.pdf"},
                {"href": f"https://evil.example/cms/{GASTRO_DOI}/attachment/y/mmc2.pdf"}]
        self.assertEqual([l.url for l in supplement_links_from_rows(rows, GASTRO_PAGE, GASTRO_DOI)], [own])

    def test_an_abstract_only_page_lists_nothing(self):
        from paper_search_carsi.adapters.elsevier import supplement_links_from_rows
        rows = [{"href": "https://www.sciencedirect.com/science/article/abs/pii/S0016508524002919#ref1"}]
        self.assertEqual(supplement_links_from_rows(rows, "https://www.sciencedirect.com/science/article/abs/pii/S0016508524002919", GASTRO_DOI), [])

    def test_sciencedirect_first_then_the_doi_landing_page(self):
        with patch("paper_search_carsi.adapters.elsevier.journal_site._get_elsevier_pii", return_value="S0016508524002919"):
            self.assertEqual(self.adapter().supplements_page_urls(GASTRO_DOI),
                             ["https://www.sciencedirect.com/science/article/pii/S0016508524002919", "https://doi.org/" + GASTRO_DOI])
        with patch("paper_search_carsi.adapters.elsevier.journal_site._get_elsevier_pii", return_value=None):
            self.assertEqual(self.adapter().supplements_page_urls(GASTRO_DOI), ["https://doi.org/" + GASTRO_DOI])


class SpringerLinksTests(unittest.TestCase):
    def test_bmj_files_come_from_the_full_texts_supplementary_material(self):
        # BJSM and BMJ Open pages (Windows, 2026-11-11): HighWire's DC1 files of this article only.
        from paper_search_carsi.adapters.bmj import supplement_links_from_page
        page = "https://bmjopen.bmj.com/content/16/4/e116911"
        own = "https://bmjopen.bmj.com/content/bmjopen/16/4/e116911/DC1/embed/inline-supplementary-material-1.pdf"
        rows = [
            {"href": own + "?download=true", "label": "Supplementary data", "supplement": True},
            {"href": own, "label": "", "supplement": False},
            {"href": "https://bmjopen.bmj.com/content/bmjopen/15/2/e090001/DC1/embed/inline-supplementary-material-1.pdf",
             "label": "another article", "supplement": False},
            {"href": "https://evil.example/content/bmjopen/16/4/e116911/DC1/embed/x.pdf", "label": "", "supplement": True},
            {"href": "http://dx.doi.org/10.2337/dc22-1710", "label": "reference", "supplement": False},
        ]
        self.assertEqual(supplement_links_from_page({"fullText": True, "rows": rows}, page),
                         [SupplementLink(own, "Supplementary data")])
        self.assertEqual(supplement_links_from_page({"fullText": True, "rows": rows}, page + ".full")[0].url, own)
        # A full text without files: checked, none; no full text shown: nothing can be said.
        self.assertEqual(supplement_links_from_page({"fullText": True, "rows": rows[4:]}, page), [])
        self.assertIsNone(supplement_links_from_page({"fullText": False, "rows": rows}, page))
        # Not on an article's own path: only links inside its supplementary-material block.
        self.assertEqual([l.url for l in supplement_links_from_page({"fullText": True, "rows": rows}, "https://bmjopen.bmj.com/lookup/doi/x")],
                         [own])

    def test_only_this_articles_electronic_supplementary_material(self):
        from paper_search_carsi.adapters.springer import supplement_links_from_rows
        doi = "10.1038/s41467-026-78958-z"
        own = "https://static-content.springer.com/esm/art%3A10.1038%2Fs41467-026-78958-z/MediaObjects/41467_2026_78958_MOESM2_ESM.xlsx"
        rows = [{"href": own, "label": "Supplementary Data 1 (download XLSX )"},
                {"href": own + "#x", "label": "duplicate"},
                {"href": "https://static-content.springer.com/esm/art%3A10.1038%2Fs41467-026-00000-0/MediaObjects/a_ESM.pdf"},
                {"href": "https://static-content.springer.com/image/art%3A10.1038%2Fs41467-026-78958-z/MediaObjects/41467_2026_78958_Fig1_HTML.png"},
                {"href": "https://evil.example/esm/art%3A10.1038%2Fs41467-026-78958-z/MediaObjects/b_ESM.pdf"},
                {"href": "http://static-content.springer.com/esm/art%3A10.1038%2Fs41467-026-78958-z/MediaObjects/c_ESM.pdf"}]
        self.assertEqual(supplement_links_from_rows(rows, doi), [SupplementLink(own, "Supplementary Data 1 (download XLSX )")])
        self.assertEqual(supplement_links_from_rows(rows, doi.upper()), [SupplementLink(own, "Supplementary Data 1 (download XLSX )")])
        self.assertEqual(supplement_links_from_rows([], doi), [])


class CandidatePagesTests(unittest.TestCase):
    def test_a_blank_supplement_page_does_not_overwrite_the_saved_main_text(self):
        from paper_search_carsi.engine.batch_common import PublisherContentError
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("acs"))
        page = MagicMock(); context = MagicMock(); context.new_page.return_value = page
        result = DownloadResult(doi="10.1021/offline", status="success", state="pdf_response_captured")
        with patch.object(d, "_challenge_shell", return_value=False), \
                patch.object(d, "_is_challenge_page", return_value=False), \
                patch.object(d, "_wait_for_page_text", side_effect=PublisherContentError("publisher_page_blank")), \
                patch.object(supplements, "collect") as collect:
            files = d.collect_supplements(context, result.doi, Path("/tmp/out"), result)
        self.assertTrue(result.ok)
        self.assertEqual(result.state, "pdf_response_captured")
        self.assertEqual(files[0]["reason"], "publisher_content_error")
        collect.assert_not_called()

    def test_login_redirect_is_not_reported_as_an_article_without_supplements(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        page = MagicMock()
        page.url = "https://id.elsevier.com/as/authorization.oauth2"
        context = MagicMock(); context.new_page.return_value = page
        result = DownloadResult(doi=GASTRO_DOI, status="success", state="pdf_response_captured")
        with patch.object(d, "_challenge_shell", return_value=False), \
                patch.object(d, "_is_challenge_page", return_value=False), \
                patch.object(d, "_wait_for_page_text"), \
                patch.object(d, "_settled_supplement_links", return_value=[]), \
                patch.object(supplements, "collect") as collect:
            files = d.collect_supplements(context, GASTRO_DOI, Path("/tmp/out"), result)
        self.assertEqual(files[0]["reason"], "login_required")
        self.assertTrue(result.ok)
        collect.assert_not_called()

    def test_the_next_page_is_tried_until_one_lists_files(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        page = MagicMock()
        context = MagicMock(); context.new_page.return_value = page
        link = SupplementLink("https://www.gastrojournal.org/cms/x/attachment/y/mmc1.pdf", "S1")
        adapter = MagicMock()
        adapter.supplements_page_urls.return_value = ["https://sd.example/abs", "https://doi.org/" + GASTRO_DOI]
        adapter.supplement_links.side_effect = [[], [link]]
        adapter.is_institution_chooser.return_value = False
        result = DownloadResult(doi=GASTRO_DOI, status="failed")
        with patch.object(PublisherBatchDownloader, "adapter", new=adapter), \
                patch.object(d, "_challenge_shell", return_value=False), \
                patch.object(d, "_is_challenge_page", return_value=False), \
                patch.object(supplements, "collect", return_value=[{"status": "saved"}]) as collect:
            files = d.collect_supplements(context, GASTRO_DOI, Path("/tmp/out"), result)
        self.assertEqual([c.args[0] for c in page.goto.call_args_list], adapter.supplements_page_urls.return_value)
        self.assertEqual(collect.call_args.args[1], [link])
        self.assertEqual(files, [{"status": "saved"}])

    def test_the_journal_page_the_main_text_came_from_is_tried_first(self):
        # Cell Metabolism: the PDF came from cell.com; its page lists the files too.
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        page = MagicMock(); context = MagicMock(); context.new_page.return_value = page
        own = "https://www.cell.com/cell-metabolism/fulltext/S1550-4131(25)00486-3"
        link = SupplementLink("https://www.cell.com/cms/10.1016/j.cmet.2025.11.002/attachment/x/mmc1.pdf", "S1")
        adapter = MagicMock()
        adapter.is_article_page_url.side_effect = lambda url: url == own
        adapter.is_institution_chooser.return_value = False
        adapter.supplements_page_urls.return_value = ["https://www.sciencedirect.com/science/article/pii/S1550413125004863",
                                                       "https://doi.org/10.1016/j.cmet.2025.11.002"]
        adapter.supplement_links.return_value = [link]
        result = DownloadResult(doi="10.1016/j.cmet.2025.11.002", status="success", final_url=own)
        with patch.object(PublisherBatchDownloader, "adapter", new=adapter), \
                patch.object(d, "_challenge_shell", return_value=False), \
                patch.object(d, "_is_challenge_page", return_value=False), \
                patch.object(supplements, "collect", return_value=[{"status": "saved"}]):
            d.collect_supplements(context, result.doi, Path("/tmp/out"), result)
        self.assertEqual([c.args[0] for c in page.goto.call_args_list], [own])
        adapter.supplement_links.return_value = []  # The Lancet Rheumatology: none listed, none elsewhere
        page.goto.reset_mock()
        with patch.object(PublisherBatchDownloader, "adapter", new=adapter), \
                patch.object(d, "_challenge_shell", return_value=False), \
                patch.object(d, "_is_challenge_page", return_value=False), \
                patch.object(supplements, "collect", return_value=[]):
            d.collect_supplements(context, result.doi, Path("/tmp/out"), result)
        self.assertEqual([c.args[0] for c in page.goto.call_args_list], [own])
        adapter.supplement_links.return_value = [link]
        result.final_url = "https://www.sciencedirect.com/science/article/pii/S1550413125004863"
        page.goto.reset_mock()
        with patch.object(PublisherBatchDownloader, "adapter", new=adapter), \
                patch.object(d, "_challenge_shell", return_value=False), \
                patch.object(d, "_is_challenge_page", return_value=False), \
                patch.object(supplements, "collect", return_value=[]):
            d.collect_supplements(context, result.doi, Path("/tmp/out"), result)
        self.assertEqual([c.args[0] for c in page.goto.call_args_list], adapter.supplements_page_urls.return_value[:1])

    def test_links_are_read_again_after_a_script_navigation(self):
        from patchright.sync_api import Error
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        page = MagicMock()
        link = SupplementLink("https://ars.els-cdn.com/content/image/1-s2.0-S1-mmc1.pdf", "S1")
        adapter = MagicMock()
        adapter.supplement_links.side_effect = [
            Error("Page.evaluate: Execution context was destroyed, most likely because of a navigation"), [link]]
        with patch.object(PublisherBatchDownloader, "adapter", new=adapter):
            self.assertEqual(d._settled_supplement_links(page, GASTRO_DOI), [link])
        page.wait_for_load_state.assert_any_call("domcontentloaded", timeout=30_000)

    def test_sciencedirect_files_are_read_once_the_article_body_is_there(self):
        # 2026-11-01: 2 s after loading, foodchem's page had no body yet and no files.
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        page = MagicMock(); page.url = "https://www.sciencedirect.com/science/article/pii/S0308814626035971"
        page.evaluate.return_value = [{"href": "https://ars.els-cdn.com/content/image/1-s2.0-S0308814626035971-mmc1.docx",
                                       "label": "Download Word document (25KB)"}]
        links = d.adapter.supplement_links(page, "10.1016/j.foodchem.2026.151437")
        page.wait_for_selector.assert_called_once_with("#body", state="attached", timeout=15_000)
        self.assertEqual([link.url[-9:] for link in links], ["mmc1.docx"])
        page = MagicMock(); page.url = "https://www.gastrojournal.org/article/S0016-5085(24)00291-9/fulltext"
        page.evaluate.return_value = []
        d.adapter.supplement_links(page, GASTRO_DOI)
        page.wait_for_selector.assert_not_called()  # a journal's own site lists them at once

    def test_a_publisher_without_link_support_stops_at_the_first_page(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        page = MagicMock(); context = MagicMock(); context.new_page.return_value = page
        adapter = MagicMock()
        adapter.supplements_page_urls.return_value = ["https://a.example/1", "https://a.example/2"]
        adapter.supplement_links.return_value = None
        with patch.object(PublisherBatchDownloader, "adapter", new=adapter), \
                patch.object(d, "_challenge_shell", return_value=False), \
                patch.object(d, "_is_challenge_page", return_value=False):
            self.assertEqual(d.collect_supplements(context, GASTRO_DOI, Path("/tmp/out"), DownloadResult(doi=GASTRO_DOI, status="failed")),
                             [{"status": "skipped", "reason": "supplements_not_supported",
                               "url": "https://a.example/1", "label": ""}])
        self.assertEqual(page.goto.call_count, 1)

class FourPublishersLinksTests(unittest.TestCase):
    """Supplement links as the four publishers' article pages showed them (2026-11-01, ADR 0011)."""

    def links(self, publisher, rows, doi):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile(publisher))
        page = MagicMock(); page.evaluate.return_value = rows
        return [(link.url, link.label) for link in d.adapter.supplement_links(page, doi)]

    def test_oup_takes_each_cdn_file_of_this_doi_once(self):
        cdn = "https://oup.silverchair-cdn.com/oup/backfile/Content_public/Journal/labmed/57/6/10.1093_labmed_lmag082/3/"
        rows = [{"href": cdn + "lmag082_supplementary_data.zip?Expires=1&Signature=a", "label": "supplement file"},
                {"href": cdn + "lmag082_supplementary_data.zip?Expires=1&Signature=a", "label": "Table S1"},
                {"href": "https://academic.oup.com/DownloadFile/DownloadImage.aspx?image=" + cdn + "f1.png", "label": "Download slide"},
                {"href": cdn.replace("lmag082", "lmag999") + "other.zip", "label": "other article"}]
        found = self.links("oxford academic", rows, "10.1093/labmed/lmag082")
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0][0].endswith("lmag082_supplementary_data.zip?Expires=1&Signature=a"))
        self.assertTrue(found[0][1].startswith("lmag082_supplementary_data.zip"))

    def test_sage_takes_suppl_files_of_this_doi(self):
        own = "https://journals.sagepub.com/doi/suppl/10.1177/13872877261497622/suppl_file/sj-docx-1-alz.docx"
        rows = [{"href": own, "label": "sj-docx-1-alz.docx"},
                {"href": "https://journals.sagepub.com/doi/suppl/10.1177/other/suppl_file/x.docx", "label": "x"}]
        self.assertEqual(self.links("sage", rows, "10.1177/13872877261497622"), [(own, "sj-docx-1-alz.docx")])

    def test_taylor_and_francis_takes_this_dois_download_supplement_links(self):
        own = "https://www.tandfonline.com/action/downloadSupplement?doi=10.1080%2F08964289.2026.2619691&file=vbmd_a_2619691_sm8478.docx"
        rows = [{"href": own, "label": "Download MS Word (32.9 KB)"},
                {"href": own.replace("2619691", "1111111"), "label": "other"}]
        found = self.links("taylor & francis", rows, "10.1080/08964289.2026.2619691")
        self.assertEqual([url for url, _ in found], [own])
        self.assertTrue(found[0][1].startswith("vbmd_a_2619691_sm8478.docx"))

    def test_a_short_link_is_saved_under_the_name_in_its_text(self):
        from paper_search_carsi.engine.supplements import _file_name
        docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        self.assertEqual(_file_name("https://links.lww.com/CORR/B539", "", set(),
                                    "CORR_2026_04_03_HUNDESHAGEN_1_SDC1.docx (46.34 KB)", docx),
                         "CORR_2026_04_03_HUNDESHAGEN_1_SDC1.docx")
        self.assertEqual(_file_name("https://links.lww.com/MCG/A15", "", set(), "Supplemental", "application/pdf"), "A15.pdf")
        self.assertEqual(_file_name("https://x.example/s/data.zip", "", set(), "other.docx", "application/zip"), "data.zip")

    def test_ovids_doi_address_is_waited_past(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("lww"))
        self.assertTrue(d.adapter.is_redirect_page("https://www.ovid.com/10.1097/EDE.0000000000002056"))
        self.assertFalse(d.adapter.is_redirect_page("https://www.ovid.com/jnls/epidem/fulltext/10.1097/ede.0000000000002056~x"))

    def test_lww_takes_only_the_supplemental_digital_content_list(self):
        rows = [{"href": "http://links.lww.com/CORR/B539", "label": "http://links.lww.com/CORR/B539", "sdc": False},
                {"href": "https://links.lww.com/CORR/B539", "label": "CORR_SDC1.docx (46.34 KB)", "sdc": True},
                {"href": "https://links.lww.com/CORR/B539", "label": "CORR_SDC1.docx (46.34 KB)", "sdc": True},
                {"href": "https://journals.lww.com/corr/pages/default.aspx", "label": "journal", "sdc": True}]
        self.assertEqual(self.links("lww", rows, "10.1097/CORR.0000000000003962"),
                         [("https://links.lww.com/CORR/B539", "CORR_SDC1.docx (46.34 KB)")])


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class WileyLinksTests(unittest.TestCase):
    def test_only_this_articles_supporting_information_rows(self):
        from patchright.sync_api import sync_playwright
        html = f"""<table><tr><td><a href="{SUPP}">art70156-sup-0001-Disclosureform.pdf</a></td><td>Disclosure Form</td></tr>
          <tr><td><a href="/action/downloadSupplement?doi=10.1002%2Fother.1&file=x.pdf">x.pdf</a></td><td>Other article</td></tr></table>
          <a href="https://evil.example/action/downloadSupplement?doi=10.1002%2Fart.70156&file=y.pdf">y</a>"""
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context()
                context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
                page = context.new_page()
                page.goto("https://acrjournals.onlinelibrary.wiley.com/doi/full/" + DOI)
                d = PublisherBatchDownloader({}, profile=get_publisher_profile("wiley"))
                links = d.adapter.supplement_links(page, DOI)
            finally:
                browser.close()
        self.assertEqual([link.url for link in links], [SUPP])
        self.assertIn("Disclosure Form", links[0].label)
        self.assertEqual(d.adapter.supplements_page_url(DOI), "https://onlinelibrary.wiley.com/doi/full/" + DOI)


if __name__ == "__main__":
    unittest.main()

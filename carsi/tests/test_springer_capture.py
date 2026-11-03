"""Offline Springer attachment and paid-preview regression fixtures.

Reuse the existing isolated module loader and fake browser primitives. PDFs are
synthetic and memory-only except for a temporary output-boundary test.
"""

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote

import pymupdf
import test_wiley_capture as wiley_fixture


DOI = "10.1007/s00000-026-00001-1"
ARTICLE = "https://link.springer.com/article/" + DOI
PDF = "https://link.springer.com/content/pdf/" + DOI + ".pdf"  # as citation_pdf_url prints it
SUPPLEMENT = ("https://static-content.springer-cdn.com/esm/art%3A" + quote(DOI, safe="")
              + "/MediaObjects/11010_2026_1_MOESM1_ESM.pdf")
PREVIEW = "This is a preview of subscription content, log in via an institution to check access."


def make_pdf(supplement=False):
    with pymupdf.open() as document:
        for index in range(4 if supplement else 2):
            page = document.new_page()
            if index == 0:
                text = "Offline Springer article title\nFixture authors\n" + DOI
                if not supplement:
                    text += "\nAbstract\nResearch methods and results."
            elif supplement:
                text = "Supplementary Table1" if index == 1 else "Supplementary Figure1"
            else:
                text = "Results\nSee Supplementary Table1 online for additional data."
            page.insert_text((40, 50), text)
        return document.tobytes() + b"\n%" + b"x" * 6000


class SpringerCaptureTests(unittest.TestCase):
    locator = wiley_fixture.WileyCaptureTests.locator
    control = wiley_fixture.WileyCaptureTests.control
    response = wiley_fixture.WileyCaptureTests.response
    enable_http_fixture = wiley_fixture.WileyCaptureTests.enable_http_fixture

    def setUp(self):
        wiley_fixture.WileyCaptureTests.setUp(self)
        self.d.profile = self.profiles.SPRINGER_PROFILE
        self.d._capture_doi = DOI
        self.page.url = ARTICLE
        self.result = self.batch.DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        self.article = make_pdf()
        self.supplement = make_pdf(supplement=True)

    def capture(self, responses):
        def navigate(url, **kwargs):
            response = responses(url)
            self.page.url = response.url
            self.handlers["response"](response)
            return response
        self.page.goto.side_effect = navigate
        return self.d._capture_pdf(self.page, DOI, self.result)

    def http_response(self, url=PDF, disposition="", history=()):
        return types.SimpleNamespace(
            url=url, status_code=200, content=self.article, text="",
            headers={"Content-Disposition": disposition}, history=list(history),
            request=types.SimpleNamespace(url=url),
        )

    def test_springer_attachment_markers_and_encoded_paths(self):
        for url in (SUPPLEMENT, SUPPLEMENT.replace("/MediaObjects/", "%2FMediaObjects%2F"),
                    "https://files.example.invalid/esm/file.pdf", "11010_2026_1_MOESM1_ESM.pdf",
                    "https://files.example.invalid/MediaObjects/opaque.pdf"):
            with self.subTest(url=url):
                self.assertTrue(self.d._is_supplementary_url(url))
                self.assertFalse(self.d._accept_pdf_body(self.article, url))
        self.assertFalse(self.d._is_supplementary_url(PDF))

    def test_current_doi_pdf_candidates_exclude_media_and_wrong_nature_template(self):
        urls = self.router.build_pdf_candidates(self.profiles.SPRINGER_PROFILE, DOI,
            source_url=ARTICLE, discovered_urls=[SUPPLEMENT, PDF, PDF.replace("00001", "00002")])
        self.assertEqual(urls, [PDF])
        self.assertTrue(self.router.is_springer_article_pdf_url(PDF, DOI))
        self.assertTrue(self.router.is_springer_article_pdf_url(PDF.replace("%2F", "/"), DOI))
        self.assertFalse(self.router.is_springer_article_pdf_url(PDF.replace("springer.com", "springer.com.example.invalid"), DOI))
        self.assertFalse(self.router.is_springer_article_pdf_url(SUPPLEMENT + "?next=" + PDF, DOI))

    def test_open_access_reference_pdf_is_the_article_pdf(self):
        self.assertTrue(self.router.is_springer_article_pdf_url(
            "https://link.springer.com/content/pdf/10.1186/s12889-026-30006-7_reference.pdf", "10.1186/s12889-026-30006-7"))
        self.assertTrue(self.router.is_springer_article_pdf_url(
            "https://www.nature.com/articles/s41467-026-78958-z_reference.pdf", "10.1038/s41467-026-78958-z"))
        self.assertFalse(self.router.is_springer_article_pdf_url(
            "https://link.springer.com/content/pdf/10.1186/s12889-026-30006-8_reference.pdf", "10.1186/s12889-026-30006-7"))

    def test_shared_nature_profile_keeps_its_current_article_route(self):
        doi = "10.1038/s00000-026-00001-1"
        url = "https://www.nature.com/articles/s00000-026-00001-1.pdf"
        self.assertTrue(self.router.is_springer_article_pdf_url(url, doi))
        self.assertFalse(self.router.is_springer_article_pdf_url(url, DOI))
        self.assertIn(url, self.router.build_pdf_candidates(self.profiles.SPRINGER_PROFILE, doi))

    def test_supplement_link_is_skipped_and_current_article_clicked(self):
        supplement = self.control(SUPPLEMENT, "Download supplementary information PDF")
        mislabelled = self.control(PDF, "Supplementary PDF")
        main = self.control(PDF, "Download PDF")
        self.controls = [supplement, mislabelled, main]
        self.assertTrue(self.d._click_pdf_entry(self.page, self.result, doi=DOI))
        supplement.click.assert_not_called()
        mislabelled.click.assert_not_called()
        main.click.assert_called_once()
        main.evaluate.assert_any_call("el => el.setAttribute('target', '_self')")

    def test_only_supplement_link_does_not_preempt_main_article_candidate(self):
        attachment = self.control(SUPPLEMENT, "Supplement PDF")
        self.controls = [attachment]
        body, url, _ = self.capture(lambda url: self.response(url, self.article))
        self.assertEqual(body, self.article)
        self.assertEqual(url, PDF)
        attachment.click.assert_not_called()
        self.assertEqual(self.page.goto.call_args.args[0], PDF)

    def test_incidental_supplement_response_does_not_win_capture(self):
        attachment = self.response(SUPPLEMENT, self.supplement)
        def responses(url):
            self.handlers["response"](attachment)
            return self.response(url, self.article)
        self.assertEqual(self.capture(responses)[0], self.article)
        attachment.body.assert_not_called()

    def test_redirect_to_mediaobjects_is_not_a_main_pdf_response(self):
        response = self.response(SUPPLEMENT, self.supplement, origin=PDF)
        self.assertFalse(self.d._response_matches_article(response, DOI))
        self.assertIsNone(self.capture(lambda url: response)[0])
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()

    def test_opaque_pdf_needs_current_doi_provenance(self):
        asset = "https://files.example.invalid/main.pdf"
        self.assertFalse(self.d._response_matches_article(self.response(asset, self.article), DOI))
        self.assertTrue(self.d._response_matches_article(self.response(asset, self.article, origin=PDF), DOI))
        self.assertFalse(self.d._response_matches_article(
            self.response(PDF.replace("00001", "00002"), self.article, origin=PDF), DOI))

    def test_supplements_are_told_apart_by_url_not_by_their_pages(self):
        # A PDF from the article endpoint naming this DOI is the main text,
        # whatever its second page says; the same file from the ESM path is not.
        self.assertTrue(self.d._accept_pdf_body(self.supplement, PDF))
        self.assertTrue(self.d._accept_pdf_body(self.article, PDF))
        self.assertFalse(self.d._accept_pdf_body(self.article, SUPPLEMENT))

    def test_disposition_rejected_in_browser_cannot_be_replayed_over_http(self):
        transport = self.enable_http_fixture(self.http_response())
        self.assertIsNone(self.capture(lambda url: self.response(
            url, self.article, disposition='attachment; filename="11010_MOESM1_ESM.pdf"'))[0])
        transport.assert_not_called()

    def test_http_checks_expected_doi_and_attachment_metadata(self):
        transport = self.enable_http_fixture(self.http_response(disposition='filename="11010_MOESM1_ESM.pdf"'))
        self.page.url = PDF
        self.assertIsNone(self.d._fetch_page_state_pdf(self.page, doi=DOI)[0])
        transport.assert_called_once()
        transport.reset_mock()
        self.page.url = PDF.replace("00001", "00002")
        self.assertIsNone(self.d._fetch_page_state_pdf(self.page, doi=DOI)[0])
        transport.assert_not_called()

    def test_success_boundary_rejects_supplement_without_writing(self):
        self.d._ensure_login = Mock(return_value=True)
        self.d._capture_pdf = Mock(return_value=(self.supplement, SUPPLEMENT, None))
        with tempfile.TemporaryDirectory() as directory:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "pdf_not_captured")
        self.d._save_publisher_session.assert_not_called()

    def test_preview_wall_starts_sso_and_clicks_observed_label(self):
        self.body = PREVIEW + "\nBuy article PDF USD39.95"
        sso = self.control("https://wayf.springernature.com/", "Log in via an institution")
        def login(**kwargs):
            self.body = "Access provided by Offline University\nFull text"
        sso.click.side_effect = login
        locator = self.page.locator
        self.page.locator = lambda selector: (types.SimpleNamespace(first=sso)
            if selector == "a:has-text('Log in via an institution')" else locator(selector))
        for name in ("_is_human_login_page", "_click_elsevier_institution_entry",
                     "_click_openathens_entry", "_select_institution", "_click_optional_continue"):
            setattr(self.d, name, Mock(return_value=False))
        self.assertTrue(self.d._looks_logged_out(self.page))
        self.assertNotEqual(self.d._login_block_reason(self.page), "institution_pdf_entitlement_missing")
        self.assertTrue(self.d._ensure_login(self.page, self.result))
        sso.click.assert_called_once()
        self.assertIn("sso_start", [event["state"] for event in self.result.events])
        self.assertFalse(self.d._looks_logged_out(self.page))

    def test_login_label_and_article_purchase_offer_require_login_not_entitlement(self):
        self.body = "Log in via an institution\nBuy article PDF USD39.95"
        self.assertTrue(self.d._looks_logged_out(self.page))
        self.assertFalse(self.d._institution_pdf_entitlement_missing(self.page))

    def test_generic_footer_login_does_not_start_an_sso_loop(self):
        self.body = "Article text and abstract\nFooter: Log in via an institution"
        self.d._complete_login_from_current_page = Mock()
        self.assertFalse(self.d._looks_logged_out(self.page))
        self.assertTrue(self.d._ensure_login(self.page, self.result))
        self.d._complete_login_from_current_page.assert_not_called()

    def test_authenticated_explicit_denial_stays_entitlement_not_login(self):
        self.body = "Access provided by Offline University\nYou do not have access to this article."
        self.d._complete_login_from_current_page = Mock()
        self.d._capture_pdf = Mock()
        with tempfile.TemporaryDirectory() as directory:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(directory))
        self.assertEqual(result.reason, "institution_pdf_entitlement_missing")
        self.d._complete_login_from_current_page.assert_not_called()
        self.d._capture_pdf.assert_not_called()

    def test_authenticated_preview_alone_does_not_prove_entitlement_denial(self):
        self.body = "Access provided by Offline University\n" + PREVIEW
        self.assertFalse(self.d._looks_logged_out(self.page))
        self.assertFalse(self.d._institution_pdf_entitlement_missing(self.page))

    def test_explicit_supplement_url_is_rejected_by_shared_body_guard(self):
        self.d.profile = self.profiles.ACS_PROFILE
        self.assertFalse(self.d._accept_pdf_body(self.article, "https://files.example.invalid/suppl_file/data.pdf"))


if __name__ == "__main__":
    unittest.main()

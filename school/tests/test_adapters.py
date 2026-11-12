"""Publisher adapters: selection order journal > publisher > generic, and the Wiley adapter in the engine."""
import unittest
from unittest.mock import MagicMock
from types import SimpleNamespace
from urllib.parse import urljoin
from unittest.mock import Mock, patch

from paper_search_school.adapters import PublisherAdapter, adapter_class
from paper_search_school.adapters import base
from paper_search_school.adapters.wiley import WileyAdapter
from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile


# The school as setup saves it from the CARSI member list.
CARSI_SCHOOL = {"publisher_institution_federation": "carsi", "school_name": "红木兰大学",
                "school_name_en": "Hong Mu-lan University"}

class SelectionTests(unittest.TestCase):
    def setUp(self):
        class SocietyJournal(WileyAdapter):
            issns = frozenset({"2326-5191"})
            hosts = ("acrjournals.onlinelibrary.wiley.com",)

        class PatternJournal(WileyAdapter):
            doi_pattern = r"10\.1111/apt\..+"

        self.society, self.pattern = SocietyJournal, PatternJournal
        base._REGISTRY["wiley"][:0] = [SocietyJournal, PatternJournal]
        self.addCleanup(lambda: [base._REGISTRY["wiley"].remove(c) for c in (SocietyJournal, PatternJournal)])

    def test_most_specific_adapter_wins(self):
        self.assertIs(adapter_class("Wiley", issns=["2326-5191"]), self.society)
        self.assertIs(adapter_class("Wiley", host="acrjournals.onlinelibrary.wiley.com"), self.society)
        self.assertIs(adapter_class("Wiley", doi="10.1111/apt.70286"), self.pattern)
        self.assertIs(adapter_class("Wiley", doi="10.1002/x", host="onlinelibrary.wiley.com"), WileyAdapter)
        self.assertIs(adapter_class("Unadapted Publisher"), PublisherAdapter)

    def test_engine_reselects_when_the_page_lands_on_the_journal_site(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("wiley"))
        page = SimpleNamespace(url="https://onlinelibrary.wiley.com/doi/10.1002/art.70156")
        d._track_article_for_adapter(page, "10.1002/art.70156")
        self.assertIs(type(d.adapter), WileyAdapter)
        page.url = "https://acrjournals.onlinelibrary.wiley.com/doi/10.1002/art.70156"
        self.assertIs(type(d.adapter), self.society)
        self.assertIs(d.adapter, d.adapter)  # cached while nothing changes


class GenericPublisherTests(unittest.TestCase):
    def test_optica_pdf_uses_article_uri_and_excludes_html_and_figures(self):
        from paper_search_school.engine.router import build_pdf_candidates, is_pdf_candidate_url
        profile = get_publisher_profile("optica")
        source = "https://opg.optica.org/oe/fulltext.cfm?uri=oe-32-4-5582"
        pdf = "https://opg.optica.org/oe/viewmedia.cfm?uri=oe-32-4-5582&seq=0"
        compressed = pdf + "&compressed=1"
        wrong = pdf.replace("5582", "5583")
        excluded = [pdf + "&html=true", pdf + "&figure=oe-32-4-5582-g001&imagetype=pdf"]
        for url in excluded:
            with self.subTest(url=url):
                self.assertFalse(is_pdf_candidate_url(profile, url))
        candidates = build_pdf_candidates(profile, "10.1364/oe.506519", source_url=source,
                                          discovered_urls=[*excluded, wrong, compressed])
        self.assertEqual(candidates[0], pdf)
        self.assertIn(compressed, candidates)
        for url in [*excluded, wrong]:
            self.assertNotIn(url, candidates)
        adapter = PublisherBatchDownloader({}, profile=profile).adapter
        self.assertEqual(adapter.profile_pdf_candidates("10.1364/ol.500000",
            "https://opg.optica.org/ol/abstract.cfm?uri=ol-49-1-100"),
            ["https://opg.optica.org/ol/viewmedia.cfm?uri=ol-49-1-100&seq=0"])
        self.assertEqual(adapter.profile_pdf_candidates("10.1364/oe.506519",
            source.replace("opg.optica.org", "example.org")), [])

    def test_publishers_without_adapter_keep_generic_behaviour(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("aip"))
        self.assertIs(type(d.adapter), PublisherAdapter)
        self.assertIsNone(d.adapter.open_institution_entry(Mock(), None))
        self.assertFalse(d._uses_article_pdf_validation())
        jama = PublisherBatchDownloader({}, profile=get_publisher_profile("jama"))
        self.assertTrue(jama._uses_article_pdf_validation())  # JAMA keeps its own rule, now in its adapter

    def test_springer_adapter_adds_supplements_only(self):
        from paper_search_school.adapters.springer import SpringerNatureAdapter
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("springer"))
        self.assertIs(type(d.adapter), SpringerNatureAdapter)
        self.assertIsNone(d.adapter.open_institution_entry(Mock(), None))
        self.assertTrue(d._uses_article_pdf_validation())  # Springer keeps its own rule

    def test_wiley_answers_through_its_adapter(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("wiley"))
        self.assertTrue(d._uses_article_pdf_validation())
        self.assertTrue(d._article_pdf_url_matches(
            "https://acrjournals.onlinelibrary.wiley.com/doi/pdfdirect/10.1002/art.70156", "10.1002/art.70156"))
        self.assertFalse(d._article_pdf_url_matches(
            "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/other", "10.1002/art.70156"))
        self.assertEqual(d._get_login_url(), "https://onlinelibrary.wiley.com/")

    def test_an_article_page_the_template_cannot_give_comes_from_the_adapter(self):
        # APS's journal codes (PhysRevLett -> prl): the adapter's answer, not a name check in the model.
        aps = PublisherBatchDownloader({}, profile=get_publisher_profile("aps"))
        self.assertEqual(aps._article_url("10.1103/PhysRevLett.130.010001"),
                         "https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.130.010001")
        self.assertEqual(aps._article_url("10.1103/Unknown.1"), get_publisher_profile("aps").article_url("10.1103/Unknown.1"))
        wiley = PublisherBatchDownloader({}, profile=get_publisher_profile("wiley"))
        self.assertEqual(wiley._article_url("10.1002/x"), get_publisher_profile("wiley").article_url("10.1002/x"))

    def test_aps_normalized_doi_uses_the_publishers_case_sensitive_article_path(self):
        aps = PublisherBatchDownloader({}, profile=get_publisher_profile("aps"))
        for suffix, journal in (("PhysRevLett.132.191602", "prl"),
                                ("PhysRevResearch.6.013001", "prresearch"),
                                ("PRXQuantum.5.010001", "prxquantum")):
            for value in (suffix.lower(), suffix.upper(), suffix):
                with self.subTest(doi=value):
                    url = aps._article_url("10.1103/" + value)
                    self.assertEqual(url, f"https://journals.aps.org/{journal}/abstract/10.1103/{suffix}")
                    self.assertIn(url.replace("/abstract/", "/pdf/"),
                                  aps.adapter.profile_pdf_candidates("10.1103/" + value, url))

    def test_the_shared_login_page_comes_from_the_adapter_not_the_name(self):
        # Parallel login over a proxy pool opens this page once (batch_runs.py).
        for key, url in (("springer", "https://link.springer.com/institutional-login"),
                         ("ieee", "https://ieeexplore.ieee.org/"), ("acs", "https://pubs.acs.org/")):
            self.assertEqual(PublisherBatchDownloader({}, profile=get_publisher_profile(key))._get_login_url(), url)
        from dataclasses import replace
        macs = replace(get_publisher_profile("nejm"), name="MACS Press")  # "acs" in the name is not ACS
        self.assertEqual(PublisherBatchDownloader({}, profile=macs)._get_login_url(), "https://nejm.org/")
        # Without one in the rules: the publisher's own site, from its article address or first domain.
        for key, url in (("sage", "https://sagepub.com/"), ("thieme", "https://www.thieme-connect.de/"),
                         ("bmj", "https://bmj.com/")):
            self.assertEqual(PublisherBatchDownloader({}, profile=get_publisher_profile(key))._get_login_url(), url)



class ElsevierJournalSiteTests(unittest.TestCase):
    """Elsevier journals on their own hosts (oarsijournal.com, gastrojournal.org, cell.com)."""

    FULLTEXT = "https://oarsijournal.com/article/S1063-4584(22)00770-1/fulltext"
    ABSTRACT = "https://www.journal-of-hepatology.eu/article/S0168-8278(24)00277-0/abstract"
    LANCET = "https://www.thelancet.com/journals/lanrhe/article/PIIS2665-9913(25)00091-8/fulltext"

    def test_lancet_article_paths_are_journal_site_articles(self):
        # The Lancet family: /journals/<code>/article/PII<PII>/<view>.
        from paper_search_school.engine.router import elsevier_journal_article, extract_elsevier_pii
        self.assertEqual(elsevier_journal_article(self.LANCET), ("S2665-9913(25)00091-8", "fulltext"))
        self.assertEqual(elsevier_journal_article(self.LANCET.replace("/fulltext", "/abstract"))[1], "abstract")
        self.assertEqual(extract_elsevier_pii("/action/showPdf?pii=S2665-9913%2825%2900091-8"), "S2665991325000918")
        self.assertIsNone(elsevier_journal_article("https://www.thelancet.com/journals/lanrhe/issue/current"))
        self.assertIsNone(elsevier_journal_article("https://www.thelancet.com/a/b/c/article/PIIS2665-9913(25)00091-8/fulltext"))

    def test_cell_press_series_paths_with_two_segments_are_articles(self):
        # Molecular Therapy and Trends journals: /<series>/<journal>/fulltext/<PII>.
        from paper_search_school.engine.router import elsevier_journal_article
        mt = "https://www.cell.com/molecular-therapy-family/molecular-therapy/fulltext/S1525-0016(26)00767-7?_returnURL=x"
        self.assertEqual(elsevier_journal_article(mt), ("S1525-0016(26)00767-7", "fulltext"))
        self.assertEqual(elsevier_journal_article(
            "https://www.cell.com/trends/biotechnology/abstract/S0167-7799(26)00301-2")[1], "abstract")

    def downloader(self, **config):
        from paper_search_school.engine.batch import PublisherBatchDownloader
        from paper_search_school.publishers.profiles import get_publisher_profile
        return PublisherBatchDownloader(config, profile=get_publisher_profile("elsevier"))

    def test_a_login_that_returns_to_another_article_is_recognised(self):
        # AJHG: the IdP kept Cell Metabolism's return URL from the item before.
        from unittest.mock import patch
        from paper_search_school.adapters import elsevier
        adapter = self.downloader().adapter
        elsevier._record_pii.cache_clear()
        with patch("paper_search_school.adapters.elsevier.journal_site._get_elsevier_pii", return_value="S0002929725000143"):
            other = SimpleNamespace(url="https://www.cell.com/cell-metabolism/fulltext/S1550-4131(25)00486-3?_returnURL=x")
            own = SimpleNamespace(url="https://www.cell.com/ajhg/fulltext/S0002-9297(25)00014-3")
            sd_own = SimpleNamespace(url="https://www.sciencedirect.com/science/article/pii/S0002929725000143")
            self.assertTrue(adapter.is_other_article(other, "10.1016/j.ajhg.2025.01.014"))
            self.assertFalse(adapter.is_other_article(own, "10.1016/j.ajhg.2025.01.014"))
            self.assertFalse(adapter.is_other_article(sd_own, "10.1016/j.ajhg.2025.01.014"))
            self.assertFalse(adapter.is_other_article(SimpleNamespace(url="https://id.elsevier.com/as/x"), "10.1016/j.ajhg.2025.01.014"))
        elsevier._record_pii.cache_clear()
        with patch("paper_search_school.adapters.elsevier.journal_site._get_elsevier_pii", return_value=None), \
                patch("paper_search_school.adapters.elsevier.journal_site._doi_handle_pii", return_value=""):
            self.assertFalse(adapter.is_other_article(other, "10.1016/j.ajhg.2025.01.014"))  # PII unknown: no opinion
        elsevier._record_pii.cache_clear()

    def test_the_article_is_opened_again_once(self):
        from paper_search_school.engine.batch import DownloadResult
        d = self.downloader()
        page = Mock(url="https://www.cell.com/cell-metabolism/fulltext/S1550-4131(25)00486-3")
        result = DownloadResult(doi="10.1016/j.ajhg.2025.01.014", status="failed",
                                article_url="https://doi.org/10.1016/j.ajhg.2025.01.014")
        adapter = Mock(); adapter.is_other_article.return_value = True
        from unittest.mock import patch
        with patch.object(type(d), "adapter", new=adapter), patch.object(d, "_dismiss_cookie_banners"), \
                patch("paper_search_school.engine.batch.time.sleep"):
            d._return_from_other_article(page, result)
            d._return_from_other_article(page, result)
        page.goto.assert_called_once_with(result.article_url, wait_until="commit", timeout=60_000)
        self.assertEqual([e["state"] for e in result.events].count("other_article_return"), 1)
        adapter.is_other_article.return_value = False
        page2 = Mock(url="https://www.cell.com/ajhg/fulltext/S0002-9297(25)00014-3")
        fresh = DownloadResult(doi=result.doi, status="failed", article_url=result.article_url)
        with patch.object(type(d), "adapter", new=adapter):
            d._return_from_other_article(page2, fresh)
        page2.goto.assert_not_called()

    def test_journal_site_article_pages_belong_to_the_publisher(self):
        d = self.downloader()
        for url in (self.FULLTEXT, self.ABSTRACT, "https://www.cell.com/article/S1550-4131%2825%2900486-3/fulltext",
                    self.LANCET):
            self.assertTrue(d._is_success_article_url(url), url)
            self.assertTrue(d._on_publisher_host(url), url)
        for url in ("https://oarsijournal.com/", "https://idp.example.edu/article/S1063-4584(22)00770-1/x",
                    "http://oarsijournal.com/article/S1063-4584(22)00770-1/fulltext"):
            self.assertFalse(d._on_publisher_host(url), url)
        self.assertTrue(d._is_success_article_url("https://www.sciencedirect.com/science/article/pii/S1063458422007701"))

    def test_full_text_on_a_journal_site_is_access_and_not_a_user_login_page(self):
        d = self.downloader(publisher_institution_federation="carsi")
        page = MagicMock(); page.url = self.FULLTEXT
        page.locator.return_value.count.return_value = 0
        self.assertFalse(d._is_human_login_page(page))
        # A full-text view says nothing either way (The Lancet with a personal
        # account, 2026-11-02): the shared rule and then the PDF decide.
        self.assertIsNone(d.adapter.looks_logged_out(page, self.FULLTEXT, ""))
        self.assertIs(d.adapter.looks_logged_out(page, self.ABSTRACT, ""), True)

    def test_formatted_pii_and_the_journals_own_pdf_first(self):
        from paper_search_school.engine.router import build_pdf_candidates, extract_elsevier_pii
        from paper_search_school.publishers.profiles import get_publisher_profile
        self.assertEqual(extract_elsevier_pii(self.FULLTEXT), "S1063458422007701")
        self.assertEqual(extract_elsevier_pii("https://www.cell.com/action/showPdf?pii=S1550-4131%2825%2900486-3"), "S1550413125004863")
        self.assertEqual(build_pdf_candidates(get_publisher_profile("elsevier"), "10.1016/j.joca.2022.06.006", source_url=self.FULLTEXT),
                         ["https://oarsijournal.com/action/showPdf?pii=S1063-4584(22)00770-1",
                          "https://www.sciencedirect.com/science/article/pii/S1063458422007701/pdfft"])


    def test_only_this_articles_pdf_link_is_clicked_on_a_journal_site(self):
        d = self.downloader()
        page = MagicMock(); page.url = self.FULLTEXT
        reference = "https://www.cell.com/servlet/linkout?suffix=e_1&dbid=4&doi=10.1016%2Fj.joca.2022.06.006&key=10.1016%2Fj.cmet.2022.05.009&cf=pdf"
        other = "https://www.amjmed.com/action/showPdf?pii=S0002-9343(04)00525-X"
        own = "https://www.oarsijournal.com/action/showPdf?pii=S1063-4584(22)00770-1"
        page.evaluate.side_effect = [[reference, other, "", own], True]
        result = SimpleNamespace(events=[])
        d._event = lambda r, state, detail="": r.events.append((state, detail))
        self.assertIs(d.adapter.open_pdf_entry(page, result), True)
        self.assertEqual(page.evaluate.call_args.args[1], 3)
        page.evaluate.side_effect = [[reference, other]]
        self.assertIs(d.adapter.open_pdf_entry(page, result), False)

    def test_reference_linkouts_are_never_pdf_candidates(self):
        from paper_search_school.engine.router import belongs_to_current_article
        from paper_search_school.publishers.profiles import get_publisher_profile
        url = "https://www.cell.com/servlet/linkout?suffix=e_1&dbid=4&doi=10.1016%2Fj.cmet.2025.11.002&key=10.1016%2Fj.cmet.2022.05.009&cf=pdf"
        self.assertFalse(belongs_to_current_article(get_publisher_profile("elsevier"), url, doi="10.1016/j.cmet.2025.11.002",
                                                    source_url="https://www.cell.com/cell-metabolism/fulltext/S1550-4131(25)00486-3"))

    def test_a_journal_abstract_logs_in_through_sciencedirect_once(self):
        d = self.downloader(publisher_institution_federation="carsi")
        page = MagicMock(); page.url = self.ABSTRACT
        result = SimpleNamespace(events=[])
        d._event = lambda r, state, detail="": r.events.append({"state": state, "detail": detail})
        target = "https://www.sciencedirect.com/science/article/pii/S0168827824002770"
        self.assertEqual(d.adapter.login_page_url(page), target)
        self.assertIs(d._open_adapter_login_page(page, result), True)
        page.goto.assert_called_once()
        self.assertEqual(page.goto.call_args.args[0], target)
        self.assertIs(d._open_adapter_login_page(page, result), False)  # once per item
        page.url = self.FULLTEXT
        self.assertIsNone(d.adapter.login_page_url(page))

    def test_after_the_sciencedirect_login_the_journal_site_decides(self):
        d = self.downloader(publisher_institution_federation="carsi")
        page = MagicMock(); page.url = self.ABSTRACT
        result = SimpleNamespace(events=[], article_url="https://doi.org/10.1016/j.jhep.2024.04.009")
        d._event = lambda r, state, detail="": r.events.append({"state": state, "detail": detail})
        d._wait_past_redirect_page = Mock()
        d._open_adapter_login_page(page, result)
        sciencedirect = page.goto.call_args.args[0]
        page.url = sciencedirect
        d._has_publisher_institution_session = Mock(return_value=False)
        d._article_access_available = Mock(return_value=False)
        self.assertFalse(d._return_from_login_site(page, result))  # not signed in there yet
        # Full-text access without the school's session (ClinicalKey, a personal account) also counts.
        d._article_access_available = Mock(return_value=True)
        with patch("paper_search_school.engine.batch.time.sleep"):
            self.assertTrue(d._return_from_login_site(page, result))
            self.assertEqual(page.goto.call_args.args[0], result.article_url)
            # The journal site shows the full text: it goes on there.
            page.url = self.FULLTEXT
            d._looks_logged_out = Mock(return_value=False)
            self.assertFalse(d._return_from_login_site(page, result))
            # It shows only the abstract: back to ScienceDirect's article, once.
            page.url = self.ABSTRACT
            d._looks_logged_out = Mock(return_value=True)
            self.assertTrue(d._return_from_login_site(page, result))
            self.assertEqual(page.goto.call_args.args[0], sciencedirect)
            page.url = self.ABSTRACT
            self.assertFalse(d._return_from_login_site(page, result))
        self.assertEqual([e["state"] for e in result.events if e["state"].startswith("login_site")],
                         ["login_site_left", "login_site_fallback"])

    def test_ard_moved_from_bmj_to_elsevier(self):
        from paper_search_school.publishers.profiles import infer_publisher_profile
        self.assertEqual(infer_publisher_profile("10.1136/ard-2024-225876").name, "Elsevier")
        self.assertEqual(infer_publisher_profile("10.1136/bmj-2024-081234").name, "BMJ")
        self.assertEqual(infer_publisher_profile("10.1016/j.ajhg.2025.01.014").name, "Elsevier")

    def test_ash_journals_use_their_elsevier_article_route_without_accepting_other_prefixes(self):
        from paper_search_school.publishers.profiles import infer_publisher_profile
        for doi in ("10.1182/blood.2023022921", "10.1182/bloodadvances.2024012345"):
            with self.subTest(doi=doi):
                profile = infer_publisher_profile(doi)
                self.assertIsNotNone(profile)
                self.assertEqual(profile.name, "Elsevier")
                d = PublisherBatchDownloader({}, profile=profile)
                self.assertEqual(d._article_url(doi), f"https://linkinghub.elsevier.com/retrieve/doi/{doi}")
        for doi in ("10.1182/bloodneoplasia.2024012345", "10.11820/blood.2023022921", "10.1016/j.example.2024.1"):
            with self.subTest(doi=doi):
                self.assertIsNone(self.downloader().adapter.article_url(doi))

    def test_ash_supplements_on_the_society_site_use_the_silverchair_rule(self):
        d = self.downloader()
        page = Mock(url="https://ashpublications.org/blood/article/143/1/1/507123/Title")
        supplement = "https://ashpublications.org/blood/article-supplement/507123/pdf/Supplement.pdf"
        page.evaluate.return_value = [
            {"href": supplement, "label": "Supplemental data"},
            {"href": supplement.replace("507123", "507124"), "label": "Another article"},
            {"href": supplement.replace("ashpublications.org", "ashpublications.org.evil.example"), "label": "Other host"},
        ]
        self.assertEqual([(s.url, s.label) for s in d.adapter.supplement_links(page, "10.1182/blood.2023022921")],
                         [(supplement, "Supplemental data")])

    def test_ash_supplements_visit_the_original_journal_without_a_sciencedirect_detour(self):
        for doi in ("10.1182/blood.2023022921", "10.1182/bloodadvances.2024012345"):
            with self.subTest(doi=doi), patch(
                    "paper_search_school.adapters.elsevier.journal_site._get_elsevier_pii") as metadata:
                self.assertEqual(self.downloader().adapter.supplements_page_urls(doi), [f"https://doi.org/{doi}"])
                metadata.assert_not_called()

    def test_get_access_or_an_institution_entry_means_no_full_text(self):
        d = self.downloader()

        def page(url, body="", **probe):
            p = MagicMock(); p.url = url
            p.locator.return_value.inner_text.return_value = body
            p.evaluate.return_value = probe
            return p
        gate = {"gate": "Access through Hong Mu-lan University"}
        self.assertEqual(d._access_verdict(page(self.FULLTEXT, "Download PDF", **gate)), "out")
        self.assertEqual(d._access_verdict(page(self.FULLTEXT)), "unknown")  # the PDF decides
        cell_abstract = "https://www.cell.com/cell-metabolism/abstract/S1550-4131(25)00486-3"
        self.assertEqual(d._access_verdict(page(cell_abstract)), "out")
        sd_abs = "https://www.sciencedirect.com/science/article/abs/pii/S1550413125004863"
        # "View PDF" of another article in the "Referred to by" box is not access.
        self.assertEqual(d._access_verdict(page(sd_abs, "Referred to by\nView PDF")), "out")
        sd_gated = "https://www.sciencedirect.com/science/article/pii/S1550413125004863"
        self.assertEqual(d._access_verdict(page(sd_gated, "View PDF", **gate)), "out")
        # Back from the IdP, still loading: nothing either way; the PDF decides.
        loading = page(sd_gated, "Referred to by\nView PDF")
        self.assertEqual(d._access_verdict(loading), "unknown")
        self.assertTrue(d._article_access_available(loading))
        # ScienceDirect's access label by the title: ready.
        for label in ("Full text access", "Open access", "Open archive"):
            self.assertEqual(d._access_verdict(page(sd_gated, "Research article", badges=[label])), "in", label)

    def test_no_pdf_control_is_clicked_while_get_access_is_shown(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("bmj"))
        page = MagicMock(); page.url = "https://journals.example/article/1"
        page.evaluate.return_value = True
        result = SimpleNamespace(events=[])
        d._event = lambda r, state, detail="": r.events.append((state, detail))
        self.assertIs(d._click_pdf_entry(page, result, doi="10.1136/x"), False)
        page.locator.assert_not_called()
        self.assertEqual(result.events[-1][0], "pdf_entry_gated")

class SpringerChooserTests(unittest.TestCase):
    def test_springer_natures_own_chooser_may_be_opened(self):
        # Cold start, 2026-11-01: nature.com's "Access through your institution"
        # leads to wayf.springernature.com, which was taken for another site.
        d = PublisherBatchDownloader(dict(CARSI_SCHOOL), profile=get_publisher_profile("springer"))
        self.assertTrue(d._manual_institution_target_allowed(
            "https://wayf.springernature.com?redirect_uri=https%3A%2F%2Fwww.nature.com%2Farticles%2Fs41591-026-04722-x"))
        self.assertFalse(d._manual_institution_target_allowed("https://wayf.example.org/?redirect_uri=x"))


class IEEEAdapterTests(unittest.TestCase):
    ARTICLE = "https://ieeexplore.ieee.org/document/11493918"

    def adapter(self):
        d = PublisherBatchDownloader(dict(CARSI_SCHOOL), profile=get_publisher_profile("ieee"))
        d._event = Mock()
        return d

    def page(self, search_visible, entry_visible=True):
        page = MagicMock(url=self.ARTICLE)
        search, entry = Mock(), Mock()
        search.is_visible.side_effect = list(search_visible) + [True] * 20
        entry.is_visible.return_value = entry_visible
        page.locator.side_effect = lambda sel: Mock(first=search if "typeahead" in sel else entry)
        page.get_by_role.return_value.first.is_visible.return_value = False
        return page, entry

    def test_institutional_sign_in_opens_the_search(self):
        d = self.adapter()
        page, entry = self.page([False, False, True])
        self.assertIs(d.adapter.open_institution_entry(page, SimpleNamespace(events=[])), True)
        entry.click.assert_called_once()
        d._event.assert_called_once()

    def test_an_open_search_or_another_site_is_not_an_entry(self):
        d = self.adapter()
        page, entry = self.page([True])
        self.assertIs(d.adapter.open_institution_entry(page, SimpleNamespace(events=[])), False)
        entry.click.assert_not_called()
        page.url = "https://www.ieee.org/"
        self.assertIsNone(d.adapter.open_institution_entry(page, SimpleNamespace(events=[])))


class ArticleTitleTests(unittest.TestCase):
    ARTICLE = "https://accpjournals.onlinelibrary.wiley.com/doi/10.1002/jac5.70308"

    def downloader(self, title):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("wiley"))
        d._title = lambda page: title
        d._body_text = lambda page, limit=2000: ""
        d._institution_pdf_entitlement_missing = lambda page: False
        d.adapter.looks_logged_out = Mock(return_value=False)  # open access
        return d

    def test_an_articles_own_title_is_no_login_page(self):
        # Wiley's title marker "Identity" in "Professional Identity Formation" (2026-11-02).
        d = self.downloader("How Preceptors Can Cultivate Professional Identity Formation")
        self.assertFalse(d._looks_logged_out(Mock(url=self.ARTICLE)))
        login = Mock(url="https://onlinelibrary.wiley.com/action/ssostart?redirectUri=%2Fdoi%2F10.1002%2Fjac5.70308")
        self.assertTrue(self.downloader("Identity Provider Login")._looks_logged_out(login))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(__import__("os").environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class ElsevierViewPdfTests(unittest.TestCase):
    def test_a_view_pdf_link_to_another_pii_is_never_clicked(self):
        # Journal of Hepatology: a related article's "View PDF" won on position.
        from patchright.sync_api import sync_playwright
        from paper_search_school.adapters.elsevier.sciencedirect import _VIEW_PDF_JS
        own = "/science/article/pii/S0168827824002770/pdfft?md5=a"
        html = f"""<body style="margin:0">
          <a id="other" href="/science/article/pii/S0168827823003240/pdfft?md5=b" style="position:absolute;top:10px;left:10px">View PDF</a>
          <a id="own" href="{own}" style="position:absolute;top:300px;left:10px">View PDF</a>
          <script>document.querySelectorAll('a').forEach(a => a.addEventListener('click', e => {{
            e.preventDefault(); document.body.dataset.clicked = a.id; }}));</script></body>"""
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context()
                context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
                page = context.new_page()
                page.goto("https://www.sciencedirect.com/science/article/pii/S0168827824002770")
                detail = page.evaluate(_VIEW_PDF_JS)
                clicked = page.evaluate("() => document.body.dataset.clicked")
                page.evaluate("() => document.getElementById('own').remove()")
                none_left = page.evaluate(_VIEW_PDF_JS)
            finally:
                browser.close()
        self.assertEqual(clicked, "own")
        self.assertTrue(detail["href"].endswith(own))
        self.assertIsNone(none_left)

    def test_a_supplementary_pdf_link_is_not_the_articles_pdf(self):
        from patchright.sync_api import sync_playwright
        from paper_search_school.adapters.elsevier.sciencedirect import _VIEW_PDF_JS
        html = """<body><a id="supp" class="anchor download-link"
            href="https://ars.els-cdn.com/content/image/1-s2.0-S0168827824002770-mmc1.pdf">Download: Download Acrobat PDF file (10MB)</a>
            <a id="own" href="/science/article/pii/S0168827824002770/pdfft?md5=a">View PDF</a>
            <script>document.querySelectorAll('a').forEach(a => a.addEventListener('click', e => {
              e.preventDefault(); document.body.dataset.clicked = a.id; }));</script></body>"""
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context()
                context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
                page = context.new_page()
                page.goto("https://www.sciencedirect.com/science/article/pii/S0168827824002770")
                clicked = page.evaluate(_VIEW_PDF_JS)
                which = page.evaluate("() => document.body.dataset.clicked || ''")
                page.evaluate("() => document.getElementById('own').remove()")
                only_supplement = page.evaluate(_VIEW_PDF_JS)
            finally:
                browser.close()
        self.assertEqual(clicked["text"], "View PDF")
        self.assertEqual(which, "own")
        self.assertIsNone(only_supplement)  # the supplementary file never counts


class GatewayErrorPageTests(unittest.TestCase):
    ENVOY = ("upstream connect error or disconnect/reset before headers. "
             "retried and the latest reset reason: connection timeout")

    def downloader(self):
        from paper_search_school.engine.batch import PublisherBatchDownloader
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("lww"))
        d._wait_past_redirect_page = Mock()
        return d

    def test_the_article_is_opened_again_after_the_proxys_error_page(self):
        # Journal of Clinical Gastroenterology: Ovid's DOI address answered with Envoy's error body.
        from paper_search_school.engine.batch import DownloadResult
        d = self.downloader()
        page = Mock(url="https://www.ovid.com/10.1097/MCG.0000000000002460")
        d._body_text = Mock(side_effect=[self.ENVOY, "Metabolic Syndrome Is Associated With Worsened ... " * 10])
        result = DownloadResult(doi="10.1097/mcg.0000000000002460", status="failed",
                                article_url="https://doi.org/10.1097/mcg.0000000000002460")
        with patch("paper_search_school.engine.batch_login.time.sleep"):
            d._reopen_after_gateway_error(page, result)
        page.goto.assert_called_once()
        self.assertEqual(page.goto.call_args.args[0], result.article_url)
        self.assertEqual([e["state"] for e in result.events], ["gateway_error_page"])

    def test_the_same_error_twice_is_the_publishers_error(self):
        from paper_search_school.engine.batch import DownloadResult, PublisherContentError
        d = self.downloader()
        page = Mock(url="https://www.ovid.com/10.1097/MCG.0000000000002460")
        d._body_text = Mock(return_value=self.ENVOY)
        result = DownloadResult(doi="10.1097/mcg.0000000000002460", status="failed",
                                article_url="https://doi.org/10.1097/mcg.0000000000002460")
        with patch("paper_search_school.engine.batch_login.time.sleep"):
            with self.assertRaises(PublisherContentError):
                d._reopen_after_gateway_error(page, result)
        page.goto.assert_called_once()

    def test_an_ordinary_page_is_left_alone(self):
        d = self.downloader()
        page = Mock()
        for text in ("Sign in to continue. 502 bad gateway " + "article text " * 40, "Journal of Hypertension"):
            d._body_text = Mock(return_value=text)
            self.assertEqual(d._gateway_error_text(page), "")
        d._body_text = Mock(return_value="502 Bad Gateway nginx")
        self.assertTrue(d._gateway_error_text(page))


class RedirectPageTests(unittest.TestCase):
    def test_linkinghub_is_left_before_the_access_check(self):
        # The Lancet Rheumatology: the access check ran on linkinghub's "Redirecting" page.
        from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        urls = iter(["https://linkinghub.elsevier.com/retrieve/pii/S2665991325000918"] * 2
                    + ["https://www.thelancet.com/journals/lanrhe/article/PIIS2665-9913(25)00091-8/fulltext"] * 5)

        class Page:
            url = next(urls)

            def locator(self, selector):
                assert selector == "head > title"
                return SimpleNamespace(first=SimpleNamespace(text_content=lambda timeout: ""))

            def wait_for_timeout(self, ms):
                Page.url = next(urls)

        page = Page()
        result = DownloadResult(doi="10.1016/s2665-9913(25)00091-8", status="failed")
        d._wait_past_redirect_page(page, result)
        self.assertIn("thelancet.com", page.url)
        self.assertEqual([e["state"] for e in result.events], ["redirect_page_passed"])
        self.assertFalse(d.adapter.is_redirect_page("https://www.sciencedirect.com/science/article/pii/S2665991325000918"))
        other = PublisherBatchDownloader({}, profile=get_publisher_profile("wiley"))
        self.assertFalse(other.adapter.is_redirect_page("https://linkinghub.elsevier.com/retrieve/pii/S2665991325000918"))


class ElsevierNotSubscribedTests(unittest.TestCase):
    """ScienceDirect with the school recognised but the content outside its subscription
    (an Academic Press chapter, 2026-10-31): the item ends at once instead of waiting
    on the login page."""

    URL = "https://www.sciencedirect.com/science/article/pii/B9780443222535000285"
    BODY = ("Brought to you by:\nHong Mu-Lan University\nScienceDirect\nJournals & Books\n"
            "Hong Mu-Lan University does not subscribe to this content on ScienceDirect.\n"
            "Chapter\nChapter 25 - Clinical translation and regulations of theranostics\n"
            "Access through another organization\nAbstract")

    def downloader(self):
        from paper_search_school.engine.batch import PublisherBatchDownloader
        return PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))

    def page(self, body, url=URL):
        page = MagicMock(); page.url = url
        page.locator.return_value.inner_text.return_value = body
        page.title.return_value = "Clinical translation and regulations of theranostics - ScienceDirect"
        return page

    def test_the_not_subscribed_banner_is_an_entitlement_denial(self):
        d = self.downloader()
        self.assertTrue(d._institution_pdf_entitlement_missing(self.page(self.BODY)))
        self.assertEqual(d._login_block_reason(self.page(self.BODY)), "institution_pdf_entitlement_missing")

    def test_the_banner_needs_its_own_line_and_a_recognised_school(self):
        d = self.downloader()
        quoted = self.BODY.replace("Hong Mu-Lan University does not subscribe to this content on ScienceDirect.",
                                   "If a page says your school does not subscribe to this content on ScienceDirect, ask the library.")
        self.assertFalse(d._institution_pdf_entitlement_missing(self.page(quoted)))
        anonymous = self.BODY.replace("Brought to you by:\nHong Mu-Lan University\n", "")
        self.assertFalse(d._institution_pdf_entitlement_missing(self.page(anonymous)))
        # Without the session, the banner counts once it names the configured school.
        named = PublisherBatchDownloader(dict(CARSI_SCHOOL), profile=get_publisher_profile("elsevier"))
        self.assertTrue(named._institution_pdf_entitlement_missing(self.page(anonymous)))
        other = anonymous.replace("Hong Mu-Lan University does", "Peking University does")
        self.assertFalse(named._institution_pdf_entitlement_missing(self.page(other)))
        self.assertTrue(named._looks_logged_out(self.page(other)))  # another school's denial: sign in

    def test_book_chapter_pages_are_scienceDirect_items(self):
        # The chapter URL was not an article page: the login loop reloaded it forever.
        d = self.downloader()
        chapter = "https://www.sciencedirect.com/science/chapter/monograph/abs/pii/B9780443445347000107?via%3Dihub"
        self.assertTrue(d._is_success_article_url(chapter))
        self.assertEqual(d._access_verdict(self.page("", chapter)), "out")  # the abstract-only view
        self.assertTrue(d._institution_pdf_entitlement_missing(self.page(self.BODY, chapter)))
        full = self.page("", chapter.replace("/abs/", "/"))
        full.evaluate.return_value = {"badges": ["Full text access"]}
        self.assertEqual(d._access_verdict(full), "in")

    def test_another_institutions_session_is_not_the_schools(self):
        # Login state E: the page names a session, but not the configured school's.
        d = PublisherBatchDownloader(dict(CARSI_SCHOOL), profile=get_publisher_profile("elsevier"))
        d._item_result = SimpleNamespace(events=[])
        d._event = lambda r, state, detail="": r.events.append({"state": state, "detail": detail})
        for body, ours in [("Brought to you by:\nHong Mu-Lan University\nScienceDirect", True),
                           ("Brought to you by: Hong Mu-lan University Library", True),
                           ("Brought to you by: 红木兰大学(Hong Mu-lan University) (Hong Mu-lan University)", True),
                           ("Brought to you by:\nPeking University\nScienceDirect", False),
                           ("Access provided by Tsinghua University and Hong Mu-lan University", True)]:
            with self.subTest(body=body):
                self.assertIs(d._has_publisher_institution_session(self.page(body)), ours)
        self.assertEqual([e["detail"] for e in d._item_result.events if e["state"] == "institution_session_other"],
                         ["peking university"])
        # Once this paper chose the school itself, the publisher's name for it is accepted.
        d._item_result.events.append({"state": "institution_selected", "detail": "Hong Mu-lan University"})
        self.assertTrue(d._has_publisher_institution_session(self.page("Brought to you by: HMLU")))
        # Without a configured school any session counts, as before.
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        self.assertTrue(d._has_publisher_institution_session(self.page("Brought to you by: Peking University")))

    def test_brought_to_you_by_with_a_colon_is_an_institution_session(self):
        d = self.downloader()
        self.assertTrue(d._has_publisher_institution_session(self.page("Brought to you by: Hong Mu-Lan University ScienceDirect")))
        self.assertFalse(d._has_publisher_institution_session(self.page("Brought to you by: ")))


class ElsevierDoiPathJournalSiteTests(unittest.TestCase):
    """Journal sites with DOI paths (jacc.org): the site's "Sign In" is a personal
    society account, so institutions sign in on ScienceDirect (2026-10-31)."""

    URL = "https://www.jacc.org/doi/10.1016/j.jacc.2026.06.019"
    DOI = "10.1016/j.jacc.2026.06.019"

    def downloader(self):
        from paper_search_school.engine.batch import PublisherBatchDownloader
        return PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))

    def test_doi_paths_are_journal_site_articles(self):
        from paper_search_school.adapters.elsevier import journal_site
        self.assertEqual(journal_site.doi_article(self.URL), (self.DOI, ""))
        self.assertEqual(journal_site.doi_article(self.URL.replace("/doi/", "/doi/abs/") + "?download=true")[1], "abstract")
        self.assertEqual(journal_site.doi_article(self.URL.replace("/doi/", "/doi/pdfdirect/"))[1], "pdf")
        self.assertIsNone(journal_site.doi_article("https://www.sciencedirect.com/doi/" + self.DOI))
        self.assertIsNone(journal_site.doi_article("https://www.jacc.org/toc/jacc/88/14"))
        self.assertTrue(self.downloader()._is_success_article_url(self.URL))

    def test_get_access_signs_in_on_sciencedirect(self):
        from unittest.mock import patch
        from paper_search_school.adapters import elsevier
        d = self.downloader()
        page = Mock(url=self.URL)
        page.evaluate.return_value = {"gate": "Get Access"}
        self.assertEqual(d._access_verdict(page), "out")
        elsevier._record_pii.cache_clear()
        with patch("paper_search_school.adapters.elsevier.journal_site._get_elsevier_pii", return_value="S0735109726068920"):
            self.assertEqual(d.adapter.login_page_url(page),
                             "https://www.sciencedirect.com/science/article/pii/S0735109726068920")
        elsevier._record_pii.cache_clear()
        with patch("paper_search_school.adapters.elsevier.journal_site._get_elsevier_pii", return_value=None), \
                patch("paper_search_school.adapters.elsevier.journal_site._doi_handle_pii", return_value=""):
            self.assertIsNone(d.adapter.login_page_url(page))
        elsevier._record_pii.cache_clear()

    def test_another_articles_doi_page_is_recognised(self):
        d = self.downloader()
        self.assertFalse(d.adapter.is_other_article(Mock(url=self.URL), self.DOI.upper()))
        self.assertTrue(d.adapter.is_other_article(Mock(url=self.URL), "10.1016/j.jacc.2026.07.001"))


@unittest.skipUnless(__import__("os").environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class ElsevierDoiPathPdfTests(unittest.TestCase):
    def test_only_this_articles_doi_pdf_link_is_clicked(self):
        from patchright.sync_api import sync_playwright
        from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
        doi = "10.1016/j.jaccas.2026.110553"
        html = f"""<body>
          <div class="references"><a id="ref" href="/doi/pdf/{doi}">Full Text (PDF)</a></div>
          <a id="other" href="/doi/pdf/10.1016/j.jaccas.2026.110000">PDF</a>
          <a id="own" href="/doi/pdf/{doi}?download=true">Download PDF</a>
          <script>document.querySelectorAll('a').forEach(a => a.addEventListener('click', e => {{
            e.preventDefault(); document.body.dataset.clicked = a.id; }}));</script></body>"""
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        result = DownloadResult(doi=doi, status="failed")
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context()
                context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
                page = context.new_page()
                page.goto("https://www.jacc.org/doi/" + doi)
                clicked = d.adapter.journal_site.open_pdf_entry(page, result)
                which = page.evaluate("() => document.body.dataset.clicked")
            finally:
                browser.close()
        self.assertTrue(clicked)
        self.assertEqual(which, "own")



class ScienceDirectWithoutTheSchoolTests(unittest.TestCase):
    """ScienceDirect giving the full text through ClinicalKey or a personal account,
    without the school's session (J Hepatol, 2026-10-31): "View full text", no PDF."""
    URL = "https://www.sciencedirect.com/science/article/pii/S0168827824002770"
    TEXT = "research article full text access you have access to this article through clinicalkey"

    def site(self, session, control):
        from paper_search_school.adapters.elsevier.sciencedirect import ScienceDirectSite
        d = Mock()
        d._access_gate_visible.return_value = False
        d._has_publisher_institution_session.return_value = session
        page = Mock(url=self.URL)
        page.evaluate.return_value = control
        return ScienceDirectSite(d), page

    def test_full_text_without_the_school_is_read_and_the_pdf_step_signs_in(self):
        # "Full text access" is the reader's access: the PDF is tried. Without the
        # school's session there is no PDF control; the PDF step lands on the
        # "Access through <school>" gate and signs in (test_pdf_first.py).
        from paper_search_school.engine.batch import PublisherBatchDownloader
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        page = MagicMock(); page.url = self.URL
        page.locator.return_value.inner_text.return_value = "Research article\nYou have access to this article through ClinicalKey"
        page.evaluate.return_value = {"badges": ["Full text access"]}
        self.assertEqual(d._access_verdict(page), "in")

    def test_without_the_articles_pdf_control_nothing_else_is_clicked(self):
        site, page = self.site(session=True, control=None)
        result = Mock()
        self.assertIs(site.open_pdf_entry(page, result), False)
        site.d._event.assert_called_with(result, "pdf_button_missing", "sciencedirect")



class ScienceDirectSignedOutTests(unittest.TestCase):
    """State C (2026-10-31): no school session and no remembered school. "Access through
    your organization" leads to Elsevier ID's "Find your organization", where the
    configured school's entry goes on to the school's sign-in page."""
    CHOOSER = "https://id.elsevier.com/as/authorization.oauth2?platSite=SD%2Fscience"
    HMLU = "红木兰大学(Hong Mu-lan University) (Hong Mu-lan University)"

    def downloader(self):
        return PublisherBatchDownloader(dict(CARSI_SCHOOL),
                                        profile=get_publisher_profile("elsevier"), institution_query="红木兰大学")

    def test_elsevier_ids_organisation_search_is_a_chooser_not_the_users_page(self):
        d = self.downloader()
        page = Mock(url=self.CHOOSER)
        page.locator.return_value.count.return_value = 0
        self.assertFalse(d._is_human_login_page(page))
        page.locator.return_value.count.return_value = 1  # a password field there is the user's
        self.assertTrue(d._is_human_login_page(page))
        self.assertFalse(d.adapter.is_institution_chooser(
            "https://auth.elsevier.com/ShibAuth/institutionLogin?entityID=https://idp.example.edu/idp/shibboleth"))

    def test_the_school_is_told_from_its_namesakes_in_elseviers_list(self):
        score = self.downloader()._institution_match_score
        self.assertEqual(score(self.HMLU), 3)
        for other in ("National Hong Mu-lan University", "The Fifth Affiliated Hospital of Hong Mu-lan University",
                      "红木兰大学(Hong Mu-lan University) (Guangzhou Library)"):
            self.assertEqual(score(other), 1, other)
        self.assertEqual(score("Hong Mu-Lan Library of Guangdong Province"), 0)  # lacks the CARSI name "Hong Mu-lan University"
        self.assertEqual(score("Hong Mu-lan University (Guangzhou)"), 2)
        self.assertEqual(score("Hong Mu-Lan University, Library"), 2)  # LibLynx (De Gruyter), 2026-11-02
        d = self.downloader()
        d._institution_names = lambda: ("华中科技大学", "Huazhong University of Science and Technology")
        long_name = "华中科技大学(Huazhong University of Science and Technology) (Huazhong University of Science and Technology)"
        self.assertEqual(d._institution_match_score(long_name), 3)
        self.assertEqual(d._institution_match_score(
            "Huazhong University of Science and Technology Tongji Medical College Union Hospital"), 1)

    def test_an_entry_that_goes_on_by_itself_gets_no_continue_click(self):
        from patchright.sync_api import TimeoutError as PlaywrightTimeout
        d = self.downloader()
        d._event, d._click_optional_continue = Mock(), Mock()
        listed = [{"i": 0, "t": self.HMLU}, {"i": 1, "t": "National Hong Mu-lan University"}]
        page = Mock(url=self.CHOOSER)
        page.evaluate.side_effect = [listed, True]
        self.assertTrue(d._click_unique_institution_entry(page, SimpleNamespace(events=[]), self.CHOOSER))
        self.assertEqual(page.evaluate.call_args.args[1][1], 0)
        d._click_optional_continue.assert_not_called()  # the page went on to the school
        page.evaluate.side_effect = [listed, True]
        page.wait_for_url.side_effect = PlaywrightTimeout("still on the list")
        self.assertTrue(d._click_unique_institution_entry(page, SimpleNamespace(events=[]), self.CHOOSER))
        d._click_optional_continue.assert_called_once()


class JournalSiteOwnLoginTests(unittest.TestCase):
    """2026-10-31, after a cold start: ScienceDirect showed the school's session but ARD
    and Cell Metabolism stayed at the abstract; their own institution login opens them."""
    ABSTRACT = "https://ard.eular.org/article/S0003-4967(25)00053-6/abstract"
    OWN = ("https://ard.eular.org/action/idLogin?type=institution&redirectUri="
           "https%3A%2F%2Fard.eular.org%2Farticle%2FS0003-4967%2825%2900053-6%2Fabstract")

    def downloader(self):
        return PublisherBatchDownloader(dict(CARSI_SCHOOL),
                                        profile=get_publisher_profile("elsevier"), institution_query="红木兰大学")

    def test_the_journal_site_signs_in_on_itself_before_sciencedirect(self):
        from urllib.parse import parse_qs, urlparse
        d = self.downloader()
        page = Mock(url=self.ABSTRACT)
        page.evaluate.return_value = self.OWN
        own, sciencedirect = d.adapter.login_page_urls(page)
        self.assertEqual(urlparse(own).path, "/action/idLogin")
        self.assertEqual(parse_qs(urlparse(own).query)["redirectUri"],
                         ["https://ard.eular.org/article/S0003-4967(25)00053-6/fulltext"])
        self.assertEqual(sciencedirect, "https://www.sciencedirect.com/science/article/pii/S0003496725000536")
        result = SimpleNamespace(events=[])
        d._event = lambda r, state, detail="": r.events.append({"state": state, "detail": detail})
        opened = []
        page.goto.side_effect = lambda url, **kw: opened.append(url)
        while d._open_adapter_login_page(page, result):
            page.url = self.ABSTRACT  # each login came back to the abstract
        self.assertEqual(opened, [own, sciencedirect])
        page.wait_for_selector.assert_called_once()  # looked for once per page
        other = self.downloader()
        page.evaluate.return_value = "https://elsewhere.example/action/idLogin?type=institution"
        self.assertEqual(other.adapter.login_page_urls(page), [sciencedirect])  # only the site's own

    def test_a_remembered_school_is_found_under_any_of_its_names(self):
        d = self.downloader()
        d._event = Mock()
        labels = ["红木兰大学(Hong Mu-lan University) (Hong Mu-Lan University)", "your organization ↗"]
        entries = [Mock(**{"is_visible.return_value": True, "inner_text.return_value": "Access through " + label})
                   for label in labels]
        page = Mock(url="https://id.elsevier.com/as/authorization.oauth2?platSite=LT%2Fgeneric")
        page.get_by_role.side_effect = lambda role, name: Mock(**{"all.return_value": entries if role == "button" else []})
        self.assertTrue(d._assist_configured_institution(page, SimpleNamespace(events=[])))
        entries[0].click.assert_called_once()
        entries[1].click.assert_not_called()


class SchoolChooserRulesTests(unittest.TestCase):
    """2026-11-01: OUP's SAMS Sigma page lists the recently chosen school above the full
    list; Sage's OpenAthens route opens login.openathens.net's "Find your institution"."""

    def downloader(self):
        return PublisherBatchDownloader(dict(CARSI_SCHOOL),
                                        profile=get_publisher_profile("oxford academic"), institution_query="红木兰大学")

    def test_the_same_school_listed_twice_with_the_same_link_is_one_school(self):
        d = self.downloader()
        d._event, d._click_optional_continue, d._left_page = Mock(), Mock(), Mock(return_value=True)
        link = "/shibboleth-login-redirect?returnUrl=https://oup-sp.sams-sigma.com/x"
        page = Mock(url="https://oup2-ds.sams-sigma.com/?entityID=x")
        page.evaluate.side_effect = [[{"i": 0, "t": "Hong Mu-lan University", "h": link},
                                      {"i": 7, "t": "Hong Mu-lan University", "h": link}], True]
        self.assertTrue(d._click_unique_institution_entry(page, SimpleNamespace(events=[]), page.url))
        page.evaluate.side_effect = [[{"i": 0, "t": "Hong Mu-lan University", "h": link},
                                      {"i": 7, "t": "Hong Mu-lan University", "h": link + "&other"}]]
        self.assertFalse(d._click_unique_institution_entry(page, SimpleNamespace(events=[]), page.url))

    def test_a_remembered_school_page_that_moves_on_by_itself_is_no_error(self):
        # 2026-11-01: OpenAthens forwarded to the remembered school while it was clicked.
        from patchright.sync_api import TimeoutError as PlaywrightTimeout
        d = self.downloader()
        d._event = Mock()
        entry = Mock(**{"is_visible.return_value": True, "inner_text.return_value": "Hong Mu-lan University",
                        "click.side_effect": PlaywrightTimeout("Locator.click: Timeout 5000ms exceeded.")})
        page = Mock(url="https://wayfinder.openathens.net/?return=x")
        page.get_by_role.side_effect = lambda role, name: Mock(**{"all.return_value": [entry] if role == "button" else []})
        d._click_unique_institution_entry = Mock(return_value=False)
        self.assertFalse(d._assist_configured_institution(page, SimpleNamespace(events=[])))

    def test_openathens_without_the_school_ends_the_login_at_once(self):
        d = PublisherBatchDownloader(dict(CARSI_SCHOOL),
                                     profile=get_publisher_profile("sage"), institution_query="红木兰大学")

        def page(typed, found=False):
            p = Mock(url="https://login.openathens.net/auth?t=%2Fsaml%2F2%2Fsso")
            p.get_by_text.return_value.first.is_visible.return_value = not found
            p.locator.return_value.first.input_value.return_value = typed
            return p
        self.assertTrue(d._openathens_lacks_school(page("Hong Mu-lan University")))
        self.assertFalse(d._openathens_lacks_school(page("Hong Mu-lan University", found=True)))
        self.assertFalse(d._openathens_lacks_school(page("Someone typing")))  # the user's own search

    def test_openathens_find_your_institution_is_a_chooser(self):
        d = self.downloader()
        self.assertTrue(d._is_federation_chooser("https://login.openathens.net/auth?t=%2Fsaml%2F2%2Fsso"))
        self.assertTrue(d._is_federation_chooser("https://wayfinder.openathens.net/?return=x"))
        self.assertFalse(d._is_federation_chooser("https://login.openathens.net/saml/2/sso"))

class ElsevierLookupAndRedirectTests(unittest.TestCase):
    """2026-10-31: a lost PII lookup sent a jacc.org article to type the school into the
    site's search box; a PDF click on ScienceDirect passed Elsevier ID's sign-in first."""

    def test_the_pii_comes_from_doi_org_when_crossref_fails_and_only_answers_are_kept(self):
        from unittest.mock import patch
        from paper_search_school.adapters.elsevier import journal_site
        journal_site._record_pii.cache_clear()
        handle = Mock(status_code=200)
        handle.json.return_value = {"values": [{"type": "URL", "data": {
            "value": "https://linkinghub.elsevier.com/retrieve/pii/S0735109726068920"}}]}
        doi = "10.1016/j.jacc.2026.06.019"
        with patch("paper_search_school.adapters.elsevier.journal_site._get_elsevier_pii", return_value=None), \
                patch("requests.get", return_value=Mock(status_code=503)) as get:
            self.assertEqual(journal_site._record_pii(doi), "")
            self.assertEqual(journal_site._record_pii(doi), "")  # not asked again at once
        self.assertEqual(get.call_count, 1)
        with patch.object(journal_site.time, "monotonic", return_value=journal_site.time.monotonic() + 61), \
                patch("paper_search_school.adapters.elsevier.journal_site._get_elsevier_pii", return_value=None), \
                patch("requests.get", return_value=handle):
            self.assertEqual(journal_site._record_pii(doi), "S0735109726068920")  # a minute later
        with patch("paper_search_school.adapters.elsevier.journal_site._get_elsevier_pii", return_value=""), \
                patch("requests.get") as get:
            journal_site._record_pii.cache_clear()
            self.assertEqual(journal_site._record_pii("10.1000/no-pii"), "")  # Crossref answered: no doi.org
        get.assert_not_called()
        journal_site._record_pii.cache_clear()

    def test_crossref_is_asked_again_when_busy(self):
        from unittest.mock import patch
        from paper_search_school.adapters.elsevier import journal_site
        busy = Mock(status_code=429, headers={"Retry-After": "1"})
        ok = Mock(status_code=200)
        ok.json.return_value = {"message": {"alternative-id": ["S0735109726068920"]}}
        with patch("requests.get", side_effect=[busy, ok]) as get, patch.object(journal_site.time, "sleep") as sleep:
            self.assertEqual(journal_site._get_elsevier_pii("10.1016/j.jacc.2026.06.019"), "S0735109726068920")
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_broad_input_selectors_only_on_a_page_that_asks_for_an_institution(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        self.assertIn("input", d.profile.institution_input_selectors)
        d._page_has_institution_chooser = Mock(return_value=False)  # an article page with a search box
        self.assertNotIn("input", d._institution_search_selectors(Mock()))
        d._page_has_institution_chooser = Mock(return_value=True)
        self.assertIn("input", d._institution_search_selectors(Mock()))

    def test_elsevier_ids_sign_in_round_trip_is_waited_past(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        ping = "https://id.elsevier.com/as/9qZUAZ3osW/resume/as/authorization.ping?acwCookieCreated=true"
        self.assertTrue(d.adapter.is_redirect_page(ping))
        self.assertTrue(d.adapter.is_redirect_page("https://id.elsevier.com/as/authorization.oauth2?platSite=SD"))
        self.assertFalse(d.adapter.is_redirect_page("https://id.elsevier.com/as/sign_in"))
        # The PDF viewer itself can sit on the challenge-resolve address.
        self.assertFalse(d.adapter.is_redirect_page(
            "https://www.sciencedirect.com/science/article/pii/S0168827824002770/pdfft?crasolve=1&r=a53"))
        page = Mock(url=ping)
        page.wait_for_timeout.side_effect = lambda ms: setattr(page, "url", "https://www.sciencedirect.com/x/pdfft")
        d._challenge_shell = Mock(return_value=False)
        d._event = Mock()
        d._wait_past_redirect_page(page, SimpleNamespace(events=[]))
        self.assertEqual(page.wait_for_timeout.call_count, 1)
        page.url, page.wait_for_timeout.call_count = ping, 0
        d._challenge_shell = Mock(return_value=True)  # a verification there: the challenge wait handles it
        d._wait_past_redirect_page(page, SimpleNamespace(events=[]))
        self.assertEqual(page.wait_for_timeout.call_count, 0)


class RSCAdapterTests(unittest.TestCase):
    WAYF = "https://sso.rsc.org/WAYF?returnUrl=%2Fconnect%2Fauthorize%2Fcallback%3Fclient_id%3Dx"


    def test_article_pages_are_rsc_articles_only(self):
        from paper_search_school.adapters.rsc import RSCAdapter
        adapter = RSCAdapter(Mock())
        for url in ("https://pubs.rsc.org/bm/article-abstract/9/4/1291/123/Offline-article",
                    "https://pubs.rsc.org/en/content/articlelanding/2025/fo/d5fo01234a"):
            self.assertIs(adapter.is_article_page_url(url), True, url)
        for url in ("https://pubs.rsc.org/institutional-login", "http://pubs.rsc.org/en/content/articlelanding/2025/x",
                    "https://pubs.rsc.org.evil.example/bm/article/9/4/1/1/x"):
            self.assertIs(adapter.is_article_page_url(url), False, url)
    def test_rscs_own_institution_search_is_a_chooser_not_the_users_login(self):
        d = PublisherBatchDownloader(dict(CARSI_SCHOOL), profile=get_publisher_profile("rsc"))
        self.assertTrue(d.adapter.is_institution_chooser(self.WAYF))
        for url in ("https://sso.rsc.org/connect/authorize?client_id=x&response_mode=form_post",
                    "https://sso.rsc.org/connect/authorize/callback?client_id=x",
                    "https://pubs.rsc.org/ExternalAuthentication/OIDCLogin"):
            self.assertTrue(d.adapter.is_redirect_page(url), url)
        for url in (self.WAYF, "https://pubs.rsc.org/fo/article-abstract/15/10/5496/850757/x",
                    "https://sso.rsc.org.evil.example/connect/authorize"):
            self.assertFalse(d.adapter.is_redirect_page(url), url)
        for url in ("https://sso.rsc.org/connect/authorize?client_id=x", "http://sso.rsc.org/WAYF",
                    "https://sso.rsc.org.evil.example/WAYF", "https://pubs.rsc.org/institutional-login"):
            self.assertFalse(d.adapter.is_institution_chooser(url), url)
        page = Mock(url=self.WAYF)
        page.locator.return_value.count.return_value = 0  # no password field
        self.assertFalse(d._is_human_login_page(page))
        page.locator.return_value.count.return_value = 1  # a password field there is the user's
        self.assertTrue(d._is_human_login_page(page))

    def test_a_signed_in_school_and_rscs_denial_are_recognised(self):
        d = PublisherBatchDownloader(dict(CARSI_SCHOOL), profile=get_publisher_profile("rsc"))
        article = "https://pubs.rsc.org/fo/article-abstract/15/10/5496/850757/Example"
        page = Mock(url=article)
        page.locator.return_value.inner_text.return_value = ""
        page.evaluate.return_value = {"labels": ["Hong Mu-lan University"]}  # the header's institution panel
        self.assertTrue(d._has_publisher_institution_session(page))
        page.evaluate.return_value = {"labels": ["Sign in via your Institution"]}
        self.assertFalse(d._has_publisher_institution_session(page))
        self.assertFalse(d._has_publisher_institution_session(Mock(url="https://sso.rsc.org/WAYF")))
        box = "  You do not currently have access to this content. "
        page.evaluate.return_value = {"labels": ["Hong Mu-lan University"], "denial_boxes": [box]}
        self.assertTrue(d._institution_pdf_entitlement_missing(page))
        page.evaluate.return_value = {"labels": ["Hong Mu-lan University"],
                                      "denial_boxes": ["You do not currently have access to this content. Sign in below."]}
        self.assertFalse(d._institution_pdf_entitlement_missing(page))
        page.evaluate.return_value = {"denial_boxes": [box]}  # not signed in: sign in
        self.assertFalse(d._institution_pdf_entitlement_missing(page))
        self.assertTrue(d._looks_logged_out(page))


class AtyponSiteTests(unittest.TestCase):
    """AHA journals, Neurology and ASCE share Taylor & Francis's Atypon login rules."""

    ARTICLE = "https://www.ahajournals.org/doi/10.1161/CIRCULATIONAHA.126.082827"

    def downloader(self, doi="10.1161/circulationaha.126.082827"):
        from paper_search_school.publishers.profiles import infer_publisher_profile
        return PublisherBatchDownloader(dict(CARSI_SCHOOL), profile=infer_publisher_profile(doi))

    def page(self, url, hrefs, probe=None):
        from paper_search_school.adapters.platforms import atypon
        links = [{"href": urljoin(url, href), "visible": True} for href in hrefs]
        page = Mock(url=url)
        page.locator.return_value.inner_text.return_value = ""
        page.evaluate.side_effect = lambda script, *a: links if script == atypon._SSOSTART_LINKS_JS else (probe or {})
        return page

    def test_publishers_route_to_their_atypon_adapters(self):
        self.assertEqual(type(self.downloader().adapter).__name__, "AHAJournalsAdapter")
        self.assertEqual(type(self.downloader("10.1212/wnl.0000000000218791").adapter).__name__, "NeurologyAdapter")
        self.assertEqual(type(self.downloader("10.1080/14737140.2026.2758536").adapter).__name__, "TaylorFrancisAdapter")
        # ASCE moved from the old CARSI route to the Atypon rules (2026-11-02).
        self.assertEqual(type(self.downloader("10.1061/jsendh.steng-16404").adapter).__name__, "ASCEAdapter")
        # On the platform by its public announcements or its pages' Literatum markers (2026-11-03).
        from paper_search_school.adapters.platforms.atypon import AtyponAdapter
        for doi, name in (("10.1126/science.aee5920", "ScienceAdapter"), ("10.1073/pnas.2611970123", "PNASAdapter"),
                          ("10.1145/3842385", "ACMAdapter"), ("10.1142/s1793545826500331", "WorldScientificAdapter")):
            with self.subTest(doi):
                adapter = self.downloader(doi).adapter
                self.assertEqual(type(adapter).__name__, name)
                self.assertIsInstance(adapter, AtyponAdapter)

    def test_an_article_page_without_the_link_opens_the_platforms_chooser(self):
        # NEJM's article page links only to its own /sign-in, whose "INSTITUTIONAL
        # SIGN IN" leads to /action/ssostart (2026-11-03).
        d = self.downloader("10.1056/nejmoa2605812")
        self.assertEqual(type(d.adapter).__name__, "NEJMAdapter")
        d._event = Mock()
        url = "https://www.nejm.org/doi/10.1056/NEJMoa2605812"
        page = self.page(url, ["/sign-in?uri=/doi/10.1056/NEJMoa2605812"])
        with patch("paper_search_school.adapters.platforms.atypon.open_page") as opened:
            self.assertIs(d.adapter.open_institution_entry(page, SimpleNamespace(doi="10.1056/nejmoa2605812", events=[])),
                          True)
        opened.assert_called_once_with(
            page, "https://www.nejm.org/action/ssostart?redirectUri=%2Fdoi%2F10.1056%2FNEJMoa2605812", timeout_ms=30_000)
        self.assertIsNone(d.adapter.looks_logged_out(page, url, ""))  # no link: not by itself a sign of no access
        self.assertEqual(d.adapter.chooser_url("https://www.nejm.org/sign-in?uri=/doi/10.1056/NEJMoa2605812"), "")
        self.assertEqual(type(self.downloader("10.1056/evidx2600264").adapter).__name__, "NEJMAdapter")

    def test_the_institution_login_is_used_never_a_link_to_one_idp(self):
        d = self.downloader()
        member = "/action/ssostart?idp=https://ahasso.heart.org&redirectUri=%2Fdoi%2F10.1161%2FCIRCULATIONAHA.126.082827"
        institution = "/action/ssostart?redirectUri=%2Fdoi%2F10.1161%2FCIRCULATIONAHA.126.082827"
        page = self.page(self.ARTICLE, [member, institution])
        self.assertEqual(d.adapter.institution_link(page, "10.1161/circulationaha.126.082827"),
                         "https://www.ahajournals.org" + institution)
        self.assertEqual(d.adapter.institution_link(self.page(self.ARTICLE, [member]), "10.1161/circulationaha.126.082827"), "")
        other = "/action/ssostart?redirectUri=%2Fdoi%2F10.1161%2FCIRCULATIONAHA.126.000001"
        self.assertEqual(d.adapter.institution_link(self.page(self.ARTICLE, [other]), "10.1161/circulationaha.126.082827"), "")
        self.assertTrue(d.adapter.looks_logged_out(page, self.ARTICLE, ""))

    def test_an_open_article_is_not_sent_to_the_institution_login(self):
        d = self.downloader("10.1212/nxi.0000000000200676")
        url = "https://www.neurology.org/doi/10.1212/NXI.0000000000200676"
        link = ["/action/ssostart?redirectUri=%2Fdoi%2F10.1212%2FNXI.0000000000200676"]
        page = self.page(url, link, probe={"badges": ["open access"]})  # the access icon by the title
        self.assertEqual(d._access_verdict(page), "in")
        self.assertEqual(d._access_verdict(self.page(url, link)), "out")  # the access box's institution login

    def test_only_this_articles_supplement_files_are_taken(self):
        d = self.downloader()
        own = "https://www.ahajournals.org/doi/suppl/10.1161/CIRCULATIONAHA.126.082827/suppl_file/cir-supplemental.pdf"
        page = Mock(url=self.ARTICLE)
        page.evaluate.return_value = [
            {"href": own, "label": "Supplemental Material"}, {"href": own, "label": "again"},
            {"href": "https://www.ahajournals.org/doi/suppl/10.1161/CIRCULATIONAHA.124.071855", "label": "other"},
            {"href": "https://www.ahajournals.org/doi/suppl/10.1161/CIRCULATIONAHA.124.071855/suppl_file/x.pdf", "label": "other"}]
        links = d.adapter.supplement_links(page, "10.1161/circulationaha.126.082827")
        self.assertEqual([link.url for link in links], [own])

    def test_dove_pdf_address_is_its_citation_pdf(self):
        # /article/download/<n> names no PDF (JIR, 20 MB, 2026-11-03).
        from fnmatch import fnmatch
        from paper_search_school.publishers.profiles import infer_publisher_profile
        d = PublisherBatchDownloader({}, profile=infer_publisher_profile("10.2147/jir.s620421"))
        self.assertTrue(any(fnmatch("https://www.dovepress.com/article/download/121006", p)
                            for p in d.adapter.metadata_pdf_patterns))

    def test_dove_supplements_follow_the_doi_number(self):
        from paper_search_school.publishers.profiles import infer_publisher_profile
        d = PublisherBatchDownloader({}, profile=infer_publisher_profile("10.2147/jir.s620421"))
        self.assertEqual(type(d.adapter).__name__, "DovePressAdapter")
        base = "https://www.dovepress.com/article/supplementary_file/"
        page = Mock()
        page.evaluate.return_value = [{"href": base + "620421/620421%20Table%20S1.docx", "label": "Supplementary Table S1"},
                                      {"href": base + "620421/620421%20Table%20S1.docx", "label": "Supplementary Table S1"},
                                      {"href": base + "999999/other.docx", "label": "other"}]
        links = d.adapter.supplement_links(page, "10.2147/JIR.S620421")
        self.assertEqual([link.url for link in links], [base + "620421/620421%20Table%20S1.docx"])
        self.assertEqual(d.adapter.supplement_links(page, "10.2147/odd-doi"), [])

    def test_a_search_box_chooser_is_left_to_the_engine(self):
        d = self.downloader()
        chooser = Mock(url="https://www.ahajournals.org/action/ssostart?redirectUri=%2Fdoi%2Fx")
        chooser.locator.return_value.is_visible.return_value = False  # no federation dropdown
        self.assertTrue(d.adapter.is_institution_chooser(chooser.url))
        self.assertIsNone(d.adapter.choose_institution(chooser, SimpleNamespace(events=[])))
        self.assertFalse(d.adapter.choose_institution(Mock(url=self.ARTICLE), SimpleNamespace(events=[])))
        self.assertTrue(d.adapter.is_article_page_url(self.ARTICLE))
        self.assertFalse(d.adapter.is_article_page_url("https://www.ahajournals.org.evil.example/doi/10.1161/x"))



class WorldScientificChooserTests(unittest.TestCase):
    CHOOSER = "https://www.worldscientific.com/action/ssostart?redirecturi=%2fdoi%2f10.1142%2fs0218194026500348"

    def test_its_chooser_without_the_institution_search_is_a_stalled_redirect(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("worldscientific"))
        self.assertEqual(d.adapter.chooser_block_reason(Mock(), self.CHOOSER, "find your institution"), "")
        self.assertEqual(d.adapter.chooser_block_reason(Mock(), self.CHOOSER, "loading"), "sso_redirect_stalled")
        self.assertIsNone(d.adapter.chooser_block_reason(
            Mock(), "https://www.worldscientific.com/doi/10.1142/s0218194026500348", "loading"))
        # Asked before the later block rules, as when the engine named the publisher.
        page = Mock(url=self.CHOOSER)
        page.is_closed.return_value = False
        d._title, d._body_text = Mock(return_value=""), Mock(return_value="Loading")
        d._publisher_access_blocked = Mock(return_value=False)
        d._is_challenge_page = Mock(return_value=False)
        d._institution_pdf_entitlement_missing = Mock(side_effect=AssertionError("asked after the chooser"))
        self.assertEqual(d._login_block_reason(page), "sso_redirect_stalled")


class AMSEntryTests(unittest.TestCase):
    def test_no_institutional_sign_in_ends_the_login_at_once(self):
        """journals.ametsoc.org: "Sign in" is the AMS member login only (2026-11-08)."""
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("ams"))
        d._event = Mock()
        result = SimpleNamespace(events=[])
        self.assertIs(d.adapter.prepare_institution_choice(Mock(), result), False)
        self.assertTrue(result._institution_not_listed)
        self.assertEqual(d._event.call_args.args[1], "institution_login_unavailable")
        self.assertIs(d.adapter.prepare_institution_choice(Mock(), result), False)
        self.assertEqual(d._event.call_count, 1)


class IOPEntryTests(unittest.TestCase):
    ARTICLE = "https://iopscience.iop.org/article/10.1088/1361-648X/ae62e5"

    def downloader(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("iop"))
        d._event = Mock()
        return d

    def test_the_access_wall_opens_myiopscience_sign_in_for_this_article(self):
        from urllib.parse import urlencode
        d = self.downloader()
        d._body_text = Mock(return_value="Access this article")
        page = Mock(url=self.ARTICLE)
        self.assertIs(d.adapter.open_institution_entry(page, SimpleNamespace(events=[])), True)
        signin = "https://myiopscience.iop.org/signin?" + urlencode({"origin": "deeplink", "target": self.ARTICLE})
        page.goto.assert_called_once_with(signin, wait_until="commit", timeout=30_000)
        page.goto.side_effect = RuntimeError("offline")
        self.assertIsNone(d.adapter.open_institution_entry(page, SimpleNamespace(events=[])))
        self.assertEqual(d._event.call_args[0][1], "sso_entry_error")

    def test_an_accepted_manuscript_without_access_box_signs_in_once(self):
        d = self.downloader()
        d._body_text = Mock(return_value="ACCEPTED MANUSCRIPT\nThree-dimensional computational evaluation\nPDF")
        page = Mock(url=self.ARTICLE)
        self.assertIs(d.adapter.open_institution_entry(page, SimpleNamespace(events=[])), True)
        self.assertIn("myiopscience.iop.org/signin?origin=deeplink", page.goto.call_args.args[0])
        tried = SimpleNamespace(events=[{"state": "sso_entry_clicked", "detail": page.goto.call_args.args[0]}])
        self.assertIsNone(d.adapter.open_institution_entry(page, tried))
        self.assertIsNone(d.adapter.open_institution_entry(page, None))

    def test_other_pages_are_left_to_the_engine(self):
        d = self.downloader()
        d._body_text = Mock(return_value="Full text")
        self.assertIsNone(d.adapter.open_institution_entry(Mock(url=self.ARTICLE), None))
        d._body_text = Mock(return_value="Access this article")
        athens = Mock(url="https://login.openathens.net/auth?target=https://iopscience.iop.org/article/10.1088/x")
        self.assertIsNone(d.adapter.open_institution_entry(athens, None))
        self.assertFalse(d._click_sso_entry(athens, None))  # the engine clicks nothing on a federation page
        athens.goto.assert_not_called()


class IEEEOwnControlsTests(unittest.TestCase):
    """Outside CARSI: IEEE's own institution control and its institution search."""

    ARTICLE = "https://ieeexplore.ieee.org/document/11493918"

    def downloader(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("ieee"), institution_query="Example University")
        d._event = Mock()
        return d

    def test_the_institution_control_is_clicked_only_on_an_article_offering_it(self):
        d = self.downloader()
        d._body_text = Mock(return_value="Sign in to continue reading")
        page = Mock(url=self.ARTICLE)
        page.evaluate.return_value = {"text": "Institutional Sign In", "href": ""}
        self.assertIs(d.adapter.click_institution_control(page, SimpleNamespace(events=[])), True)
        self.assertEqual(d._event.call_args[0][1], "sso_entry_clicked")
        page.evaluate.return_value = None
        self.assertIs(d.adapter.click_institution_control(page, None), False)
        for url in ("https://ieeexplore.ieee.org/servlet/wayf.jsp", "https://www.example.org/document/1"):
            page = Mock(url=url)
            self.assertIs(d.adapter.click_institution_control(page, None), False)
            page.evaluate.assert_not_called()
        d._body_text = Mock(return_value="Abstract")
        page = Mock(url=self.ARTICLE)
        self.assertIs(d.adapter.click_institution_control(page, None), False)
        page.evaluate.assert_not_called()
        self.assertIs(PublisherBatchDownloader({}, profile=get_publisher_profile("iop")).adapter
                      .click_institution_control(Mock(url=self.ARTICLE), None), False)

    def test_the_school_is_typed_into_the_search_and_its_entry_chosen(self):
        d = self.downloader()
        page = MagicMock(url=self.ARTICLE)
        box = page.locator.return_value.first
        box.is_visible.return_value = True
        self.assertIs(d.adapter.fill_institution_search(page, SimpleNamespace(events=[])), True)
        box.type.assert_called_once_with("Example University", timeout=5_000)
        self.assertEqual([c[0][1] for c in d._event.call_args_list], ["institution_search", "institution_selected"])
        box.is_visible.return_value = False
        self.assertIs(d.adapter.fill_institution_search(page, SimpleNamespace(events=[])), False)


class ThiemeEntryRequiredTests(unittest.TestCase):
    def test_a_school_login_without_thiemes_entry_ends_at_once(self):
        from paper_search_school.engine.batch import DownloadResult
        d = PublisherBatchDownloader(dict(CARSI_SCHOOL), profile=get_publisher_profile("thieme"))
        for name in ("_institution_pdf_entitlement_missing", "_dismiss_cookie_banners",
                     "_click_sso_entry", "_is_human_login_page"):
            setattr(d, name, Mock(return_value=False))
        page = Mock(url="https://www.thieme-connect.de/products/ejournals/abstract/10.1055/a-1234-5678")
        result = DownloadResult(doi="10.1055/a-1234-5678", status="failed")
        self.assertFalse(d._complete_login_from_current_page(page, result))
        self.assertEqual(result.reason, "publisher_institution_entry_missing")
        self.assertFalse(PublisherBatchDownloader({}, profile=get_publisher_profile("karger"))
                         .adapter.requires_institution_entry)


class APSEntryTests(unittest.TestCase):
    ARTICLE = "https://journals.aps.org/pre/abstract/10.1103/PhysRevE.1"

    def test_without_the_federated_sign_in_the_entry_is_reported_missing(self):
        d = PublisherBatchDownloader(dict(CARSI_SCHOOL), profile=get_publisher_profile("aps"))
        d._event = Mock()
        page = Mock(url=self.ARTICLE)
        page.evaluate.return_value = None  # no /auth/openathens/login link
        self.assertIs(d.adapter.open_institution_entry(page, SimpleNamespace(events=[])), False)
        self.assertEqual(d._event.call_args[0][1], "aps_institution_entry_missing")
        athens = Mock(url="https://wayfinder.openathens.net/?return=x")
        self.assertIsNone(d.adapter.open_institution_entry(athens, None))  # the engine clicks nothing there
        athens.evaluate.assert_not_called()
        self.assertTrue(d.adapter.returns_to_record_article)


class ProfilePdfCandidateTests(unittest.TestCase):
    """The router's publisher-derived PDF URLs come from the adapter classes (answers before the move)."""

    CASES = (
        ("ieee", "10.1109/x.2026.1", "https://ieeexplore.ieee.org/document/11493918",
         "https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&isnumber=&arnumber=11493918"),
        ("aps", "10.1103/PhysRevE.1", "https://journals.aps.org/pre/abstract/10.1103/PhysRevE.1",
         "https://journals.aps.org/pre/pdf/10.1103/PhysRevE.1"),
        ("ams", "10.1175/JCLI-D-23-0001.1", "https://journals.ametsoc.org/view/journals/clim/37/1/JCLI-D-23-0001.1.xml",
         "https://journals.ametsoc.org/downloadpdf/view/journals/clim/37/1/JCLI-D-23-0001.1.pdf"),
        ("plos", "10.1371/journal.pone.0300000", "",
         "https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0300000&type=printable"),
        ("copernicus", "10.5194/acp-24-1-2024", "", "https://acp.copernicus.org/articles/24/1/2024/acp-24-1-2024.pdf"),
        ("mdpi", "10.3390/s24010123", "", "https://www.mdpi.com/1424-8220/24/1/123/pdf"),
    )

    def test_each_publishers_own_pdf_url_comes_first(self):
        from paper_search_school.adapters.base import adapter_class_for
        from paper_search_school.engine.router import build_pdf_candidates
        for key, doi, source, first in self.CASES:
            with self.subTest(publisher=key):
                profile = get_publisher_profile(key)
                self.assertEqual(adapter_class_for(profile).profile_pdf_candidates(doi, source)[0], first)
                self.assertEqual(build_pdf_candidates(profile, doi, source_url=source)[0], first)
        self.assertEqual(PublisherAdapter.profile_pdf_candidates("10.1/x", "https://example.org/a"), [])


class SilverchairArticlePageTests(unittest.TestCase):
    """Silverchair article pages, the DOI form included, are the platform's rule:
    RSC's Faraday Discussions (2026-11-03) and Karger's Dermatology (2026-11-02)."""

    def test_article_pages_with_and_without_the_doi(self):
        rsc = PublisherBatchDownloader({}, profile=get_publisher_profile("rsc"))
        karger = PublisherBatchDownloader({}, profile=get_publisher_profile("karger"))
        for d, url in ((rsc, "https://pubs.rsc.org/fd/article/doi/10.1039/D6FD00129G/1297624/Spiers-Memorial-Lecture"),
                       (rsc, "https://pubs.rsc.org/en/content/articlelanding/2026/fd/d6fd00129g"),
                       (karger, "https://karger.com/drm/article/doi/10.1159/drm/ackag031/1234567/Maternal-Diabetes"),
                       (karger, "https://karger.com/drm/article-abstract/241/3/215/1234567/Title")):
            with self.subTest(url):
                self.assertTrue(d._is_success_article_url(url))
        for d, url in ((rsc, "https://pubs.rsc.org/institutional-login"), (karger, "https://karger.com/drm"),
                       (karger, "https://karger.com/drm/article/doi/10.1159/drm/ackag031")):
            with self.subTest(url):
                self.assertFalse(d._is_success_article_url(url))


class SilverchairSupplementTests(unittest.TestCase):
    """Supplementary files on Silverchair sites (ACS Nano, OUP's form) and on JAMA (2026-11-03)."""

    def test_silverchair_supplements_by_article_id_and_by_doi_on_the_cdn(self):
        from paper_search_school.adapters.platforms import silverchair
        page = Mock(url="https://pubs.acs.org/ancac3/article/doi/10.1021/acsnano.6c15458/5461875/Third-Eigenmode")
        own = "https://pubs.acs.org/ancac3/article-supplement/5461875/pdf/nn6c15458_si_001/"
        cdn = "https://rscj.silverchair-cdn.com/rscj/content_public/journal/nn/10.1021_acsnano.6c15458/1/si.zip?Expires=1"
        page.evaluate.return_value = [
            {"href": own, "label": "Supporting Information", "in_section": True},
            {"href": own, "label": "Figures S1 and S2", "in_section": True},  # the same file again
            {"href": "https://pubs.acs.org/ancac3/article-supplement/5460000/pdf/other_si_001/", "label": "other article"},
            {"href": "https://acs.silverchair-cdn.com/DownloadFile/DownloadImage.aspx?image=x&10.1021_acsnano.6c15458",
             "label": "Download to Slide", "in_section": False},
            {"href": cdn, "label": "data", "in_section": True},
            {"href": cdn.replace("si.zip", "main.pdf"), "label": "PDF", "in_section": False},  # not in the section
            {"href": "https://evil.example/ancac3/article-supplement/5461875/pdf/x/", "label": "elsewhere"}]
        links = silverchair.supplement_links(page, "10.1021/acsnano.6c15458", frozenset({"pubs.acs.org"}))
        self.assertEqual([link.url for link in links], [own, cdn])
        self.assertEqual(links[0].label, "Supporting Information")

    def test_acs_karger_and_rsc_use_the_platforms_rule(self):
        for name in ("acs", "karger", "rsc"):
            with self.subTest(name):
                d = PublisherBatchDownloader({}, profile=get_publisher_profile(name))
                page = Mock(url="https://example.org/")
                page.evaluate.return_value = []
                self.assertEqual(d.adapter.supplement_links(page, "10.1/x"), [])  # supported: none here

    def test_jama_supplemental_content(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("jama"))
        page = Mock(url="https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2856026")
        s1 = "https://cdn.jamanetwork.com/ama/content_public/journal/jamanetworkopen/939919/zoi261124supp1_prod_1792770255.8182.pdf"
        page.evaluate.return_value = [{"href": s1, "label": "pdf"}, {"href": s1, "label": "again"},
                                      {"href": s1.replace("supp1", "supp2"), "label": ""},
                                      {"href": "https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2856026", "label": "Supplement 1"},
                                      {"href": "https://cdn.jamanetwork.com/ama/content_public/journal/x/cover.jpg", "label": "cover"}]
        links = d.adapter.supplement_links(page, "10.1001/jamanetworkopen.2026.41377")
        self.assertEqual([link.url for link in links], [s1, s1.replace("supp1", "supp2")])


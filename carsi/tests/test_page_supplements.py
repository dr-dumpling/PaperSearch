"""The shared supplementary-file rule for sites without one of their own, and
Figshare resources set aside (the Journal of Experimental Medicine, 2026-11-11)."""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from paper_search_carsi.adapters.base import SupplementLink
from paper_search_carsi.engine.batch import PublisherBatchDownloader
from paper_search_carsi.engine.page_supplements import listed_files

DOI = "10.1084/jem.20260506"
CDN = "https://cdn.rupress.org/rup/content_public/journal/jem/223/11/10.1084_jem.20260506/1/"
FIGSHARE = "https://doi.org/10.6084/m9.figshare.32725488"


def table(n, signature="a"):
    return f"{CDN}jem_20260506_tables{n}.xlsx?Expires=1797436934&Signature={signature}"


def page(rows, doi=DOI):
    return Mock(evaluate=Mock(return_value={"doi": doi, "rows": rows}))


def test_files_named_by_this_doi_in_the_supplementary_part_are_taken_once():
    rows = [{"href": table(1), "label": "Table S1"},
            {"href": table(1, "b"), "label": "Table S1 shows characteristics of eight patients"},
            {"href": table(2), "label": "Table S2"},
            {"href": "https://rupress.org/DownloadFile/DownloadImage.aspx?image=" + CDN + "jem_20260506_figs1.png",
             "label": "Download slide"},
            {"href": "https://rupress.org/view-large/figure/9969737/JEM_20260506_FigS1.tif", "label": "View large"},
            {"href": CDN.replace("20260506", "20260507") + "jem_20260507_tables1.xlsx", "label": "Other article"},
            {"href": "https://journal.example/doi/suppl/10.1084/jem.20260506/suppl_file/page.html", "label": "Page"},
            {"href": "http://journal.example/doi/suppl/10.1084/jem.20260506/suppl_file/s1.pdf", "label": "Plain http"},
            {"href": "https://journal.example/doi/suppl/10.1084/jem.20260506/suppl_file/s1.pdf", "label": "S1"},
            {"href": "https://journal.example/doi/pdf/10.1084/jem.20260506", "label": "PDF"},
            {"href": FIGSHARE, "label": "Figshare"}]
    links = listed_files(page(rows), DOI.upper())
    assert [(link.url, link.label) for link in links] == [
        (table(1), "Table S1"), (table(2), "Table S2"),
        ("https://journal.example/doi/suppl/10.1084/jem.20260506/suppl_file/s1.pdf", "S1")]


def test_another_articles_page_lists_nothing():
    assert listed_files(page([{"href": table(1), "label": "Table S1"}], doi="10.1084/jem.20260507"), DOI) == []
    assert listed_files(Mock(evaluate=Mock(return_value=None)), DOI) == []


def downloader(own, figshare):
    d = SimpleNamespace(adapter=SimpleNamespace(supplement_links=lambda *args: own), events=[])
    d._event = lambda result, state, detail: d.events.append((state, detail))
    return d


def settled(d, rows, figshare, monkeypatch, result=object()):
    from paper_search_carsi.adapters.platforms import figshare as module
    monkeypatch.setattr(module, "supplement_links", lambda page, doi: figshare)
    return PublisherBatchDownloader._settled_supplement_links(d, page(rows), DOI, result)


def test_a_site_without_a_rule_gets_its_listed_files_and_sets_the_unbound_dataset_aside(monkeypatch):
    aside = SupplementLink(FIGSHARE, "Figshare resource", set_aside="figshare_article_mismatch")
    d = downloader(None, [aside])
    links = settled(d, [{"href": table(1), "label": "Table S1"}], [aside], monkeypatch)
    assert [link.url for link in links] == [table(1)]
    assert d.events == [("supplements_set_aside", f"figshare_article_mismatch {FIGSHARE}")]


def test_only_a_dataset_set_aside_on_a_site_without_a_rule_says_nothing_about_its_files(monkeypatch):
    aside = SupplementLink(FIGSHARE, "Figshare resource", set_aside="figshare_article_mismatch")
    assert settled(downloader(None, [aside]), [], [aside], monkeypatch) is None


def test_a_sites_own_rule_is_not_widened(monkeypatch):
    own = SupplementLink("https://journal.example/own.pdf", "S1")
    assert settled(downloader([own], None), [{"href": table(1), "label": "Table S1"}], None, monkeypatch) == [own]
    assert settled(downloader([], None), [{"href": table(1), "label": "Table S1"}], None, monkeypatch) == []


@pytest.mark.skipif(os.getenv("CARSI_LOCAL_BROWSER_TEST") != "1", reason="local browser fixture opt-in")
def test_real_dom_supplementary_parts():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        try:
            browser_page = browser.new_page()
            browser_page.route("**/*", lambda route: route.abort())
            browser_page.set_content(f'''<meta name="citation_doi" content="{DOI}">
                <section><p>Detailed clinical information is provided in <a href="{table(9)}">Table S9</a>.</p></section>
                <div class="widget-ArticleDataSupplements"><h2>Supplementary data</h2>
                  <div class="dataSuppLink"><a href="{table(1)}">Table S1 shows characteristics</a></div></div>
                <section><h3>Online supplemental material</h3><p><a href="{table(2)}">Table S2</a></p></section>
                <section><h2>Data availability</h2><a href="{FIGSHARE}">{FIGSHARE}</a></section>''')
            assert [link.url for link in listed_files(browser_page, DOI)] == [table(1), table(2)]
        finally:
            browser.close()

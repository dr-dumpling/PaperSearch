"""Pages that move on while read, and PDF addresses that appear late (Chrome, 2026-11-07)."""
from fnmatch import fnmatch
from unittest.mock import Mock

import pytest
from patchright._impl._errors import Error

from paper_search_school.adapters.jama import JAMAAdapter
from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile

CUT = Error("Page.evaluate: Execution context was destroyed, most likely because of a navigation.")


def downloader(site):
    d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"}, profile=get_publisher_profile(site))
    d.events = []
    d._event = lambda result, state, detail="": d.events.append((state, detail))
    return d


def test_login_controls_cut_off_by_a_navigation_are_the_users_step(monkeypatch):
    d = downloader("lww")
    monkeypatch.setattr(d, "_is_idp_host", lambda host: True)
    monkeypatch.setattr(d, "_idp_confirmation", lambda page: "")
    page = Mock(url="https://idp.fixture.edu/login")
    page.evaluate.side_effect = CUT
    assert d._idp_user_action(page) is True
    assert d.events[0][0] == "page_read_interrupted"


def test_a_password_box_cut_off_by_a_navigation_is_the_users_step():
    d = downloader("lww")
    page = Mock(url="https://login.fixture.test/")
    page.locator.return_value.count.side_effect = CUT
    assert d._school_password_box(page, page.url) is True
    assert d.events[0][0] == "page_read_interrupted"


def test_a_closed_page_still_reaches_the_caller():
    d = downloader("lww")
    page = Mock(url="https://login.fixture.test/")
    page.locator.return_value.count.side_effect = Error("Target page, context or browser has been closed")
    with pytest.raises(Error):
        d._school_password_box(page, page.url)


def test_a_pdf_address_that_appears_after_loading_is_tried_again(monkeypatch):
    d = downloader("thieme")
    offers = iter([[], [], ["https://www.thieme-connect.de/products/ejournals/pdf/10.1055/a-1.pdf"]])
    monkeypatch.setattr(d, "_pdf_candidates", lambda page, doi: next(offers))
    assert d._wait_for_pdf_candidates(Mock(url="https://www.thieme-connect.de/x"), "10.1055/a-1", None) is True
    assert d.events[0][0] == "pdf_candidates_appeared"


def test_a_page_without_a_pdf_address_ends_the_wait(monkeypatch):
    d = downloader("thieme")
    d.PDF_CANDIDATE_WAIT_MS = 1_000
    monkeypatch.setattr(d, "_pdf_candidates", lambda page, doi: [])
    assert d._wait_for_pdf_candidates(Mock(url="https://www.thieme-connect.de/x"), "10.1055/a-1", None) is False
    assert d.events == []


def test_chrome_pauses_every_document_the_tab_opens_as_well_as_the_adapters_addresses():
    patterns = PublisherBatchDownloader._chromium_pdf_patterns(("https://jamanetwork.com/journals/*/articlepdf/*",))
    assert patterns == [
        {"urlPattern": "https://jamanetwork.com/journals/*/articlepdf/*", "requestStage": "Response"},
        {"urlPattern": "*", "resourceType": "Document", "requestStage": "Response"},
    ]


def test_the_bound_pdfs_copy_on_its_delivery_host_is_the_article():
    from types import SimpleNamespace

    d = downloader("jama")
    doi = "10.1001/jamanetworkopen.2026.41377"
    bound = "https://jamanetwork.com/journals/jamanetworkopen/articlepdf/2856026/weideman_2026.pdf"
    options = {"article_pdf_urls": frozenset({bound})}
    copy = "https://watermark02.silverchair.com/weideman_2026.pdf?token=abc"
    reached = SimpleNamespace(url=copy, headers={}, status=200, history=[SimpleNamespace(url=bound, headers={})])
    assert d._bound_pdf_copy(copy, reached, doi, options)
    other = "https://watermark02.silverchair.com/another_article.pdf?token=abc"
    assert not d._bound_pdf_copy(other, SimpleNamespace(url=other, headers={}, status=200,
                                                        history=reached.history), doi, options)

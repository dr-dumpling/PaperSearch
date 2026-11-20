"""The root visit made once per site before its first article."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from paper_search_school.browser import watchdog
from paper_search_school.browser.challenge import warmup as session_warmup


@pytest.fixture(autouse=True)
def _forget_sites():
    session_warmup.reset()
    yield
    session_warmup.reset()


def page_with_tab():
    tab = Mock()
    tab.is_closed.return_value = False
    context = Mock()
    context.new_page.return_value = tab
    return SimpleNamespace(context=context), context, tab


@pytest.mark.parametrize("url,expected", [
    ("https://link.springer.com/article/10.1007/x", "https://link.springer.com/"),
    ("https://academic.oup.com/eurheartj/article/1", "https://academic.oup.com/"),
    ("http://journal.example/a", "http://journal.example/"),
    ("file:///tmp/x.html", ""),
    ("", ""),
    ("not a url", ""),
])
def test_a_site_root_comes_from_the_article_url(url, expected):
    assert session_warmup.site_root(url) == expected


def test_the_root_is_opened_once_and_closed_again():
    page, context, tab = page_with_tab()
    assert session_warmup.warm(page, "https://journal.example/article/1", settle_ms=0) == "warmed"
    tab.goto.assert_called_once()
    assert tab.goto.call_args.args[0] == "https://journal.example/"
    tab.close.assert_called_once()


def test_a_second_article_on_the_same_site_is_not_warmed_again():
    page, context, tab = page_with_tab()
    session_warmup.warm(page, "https://journal.example/article/1", settle_ms=0)
    assert session_warmup.warm(page, "https://journal.example/article/2", settle_ms=0) == "skipped"
    assert context.new_page.call_count == 1


def test_another_site_is_warmed_on_its_own():
    page, context, tab = page_with_tab()
    session_warmup.warm(page, "https://journal.example/article/1", settle_ms=0)
    assert session_warmup.warm(page, "https://other.example/article/1", settle_ms=0) == "warmed"
    assert context.new_page.call_count == 2


def test_a_page_without_a_context_is_skipped():
    assert session_warmup.warm(SimpleNamespace(), "https://journal.example/a") == "skipped"


def test_a_root_that_does_not_load_is_reported_and_the_tab_closed():
    page, context, tab = page_with_tab()
    tab.goto.side_effect = RuntimeError("net::ERR_FAILED")
    assert session_warmup.warm(page, "https://journal.example/article/1", settle_ms=0) == "failed"
    tab.close.assert_called_once()


@pytest.mark.parametrize("error", [watchdog.CallAbandoned(), watchdog.BrowserUnresponsive("stalled")])
def test_cancellation_and_a_stalled_browser_reach_the_caller(error):
    page, context, tab = page_with_tab()
    tab.goto.side_effect = error
    with pytest.raises(type(error)):
        session_warmup.warm(page, "https://journal.example/article/1", settle_ms=0)
    tab.close.assert_called_once()


def test_an_unclosed_tab_does_not_fail_the_download():
    page, context, tab = page_with_tab()
    tab.close.side_effect = RuntimeError("already gone")
    assert session_warmup.warm(page, "https://journal.example/article/1", settle_ms=0) == "warmed"

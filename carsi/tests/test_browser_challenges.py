"""Verification evidence stays independent of browser drivers and task state."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from paper_search_carsi.browser import challenges, watchdog
from paper_search_carsi.engine.batch import PublisherBatchDownloader


@pytest.mark.parametrize("url,title,expected", [
    ("https://journal.example/article", " Just a moment... ", True),
    ("https://journal.example/article", "请稍候……", True),
    ("https://journal.example/article?__CF_CHL_TK=x", "", True),
    ("https://journal.example/cdn-cgi/challenge-platform/x", "", True),
    ("https://journal.example/article", "Attention Required! | Cloudflare", False),
    ("https://journal.example/article", "Open Access Article", False),
])
def test_lightweight_interstitial_evidence(url, title, expected):
    assert challenges.looks_like_challenge(url, title) is expected


@pytest.mark.parametrize("title,text,expected", [
    ("Validate User", "Please help us confirm that you are not a robot", True),
    ("", "VERIFY YOU ARE HUMAN", True),
    ("", "Checking your browser", True),
    ("", "Verifying your request", True),
    ("", "Automated-traffic protection needs a quick check", True),
    ("Cloudflare", "Security verification", True),
    ("Cloudflare", "Ray ID: example", True),
    ("Cloudflare", "瀹夊叏楠岃瘉", True),
    ("Article", "Powered by Cloudflare", False),
    ("Article", "Access through your institution", False),
    ("Article", "Free Access", False),
    ("", "", False),
])
def test_text_evidence_does_not_conflate_access_and_verification(title, text, expected):
    assert challenges.has_challenge_text(title, text) is expected


def test_crawl_prevention_checks_the_path_not_a_link_in_the_query():
    assert challenges.is_challenge_path("https://journal.example/crawlprevention/governor?content=x")
    assert not challenges.is_challenge_path("https://journal.example/article?ref=/crawlprevention/governor")


@pytest.mark.parametrize("path,expected", [
    ("/captcha", True),
    ("/captcha/", True),
    ("/captcha/(S(fixture))/", True),
    ("/CAPTCHA/index", True),
    ("/articles/captcha/recognition", False),
    ("/captcha-recognition", False),
    ("/article?return=/captcha/", False),
])
def test_captcha_routes_do_not_match_articles_or_query_links(path, expected):
    assert challenges.is_challenge_path("https://journal.example" + path) is expected


def downloader(title="Article", body=""):
    d = PublisherBatchDownloader({})
    d._title = Mock(return_value=title)
    d._body_text = Mock(return_value=body)
    d._publisher_access_blocked = Mock(return_value=False)
    return d


def test_interstitial_never_reads_body_or_publisher_block_dom():
    d = downloader(title="Just a moment...")
    assert d._is_challenge_page(SimpleNamespace(url="https://journal.example/article"))
    d._title.assert_called_once()
    d._body_text.assert_not_called()
    d._publisher_access_blocked.assert_not_called()


def test_explicit_block_precedes_broader_verification_markers():
    d = downloader(title="Attention Required! | Cloudflare", body="Verify you are human")
    d._publisher_access_blocked.return_value = True
    assert not d._is_challenge_page(SimpleNamespace(url="https://journal.example/crawlprevention/governor"))
    d._body_text.assert_not_called()


def test_explicit_block_precedes_a_captcha_route():
    d = downloader(title="Captcha", body="IP address blocked")
    d._publisher_access_blocked.return_value = True
    assert not d._is_challenge_page(SimpleNamespace(url="https://journal.example/captcha/"))
    d._body_text.assert_not_called()


def test_crawl_prevention_needs_no_additional_body_read_after_block_check():
    d = downloader()
    assert d._is_challenge_page(SimpleNamespace(url="https://journal.example/crawlprevention/governor"))
    d._publisher_access_blocked.assert_called_once()
    d._body_text.assert_not_called()


@pytest.mark.parametrize("reader", ["_title", "_body_text"])
def test_browser_timeouts_propagate_instead_of_becoming_no_challenge(reader):
    d = downloader()
    getattr(d, reader).side_effect = watchdog.BrowserUnresponsive("stalled browser")
    with pytest.raises(watchdog.BrowserUnresponsive):
        d._is_challenge_page(SimpleNamespace(url="https://journal.example/article"))

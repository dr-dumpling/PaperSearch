"""The look at a quiet page, in Chrome: which pages remind the user (the user, 2026-11-11)."""
import os

import pytest

from paper_search_carsi import progress_reporter
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.engine.page_activity import PageActivity

pytestmark = pytest.mark.skipif(os.environ.get("CARSI_LOCAL_BROWSER_TEST") != "1",
                                reason="local Chrome fixture opt-in")

PAGES = {
    "https://journal.example/hold": '<title>Please wait</title><p>Confirm to continue to the article.</p>'
                                   '<button>I am a person</button>',
    "https://journal.example/quiet": '<title>Please wait</title><p>Loading the article.</p>',
    "https://journal.example/article": '<title>A study</title><meta name="citation_doi" content="10.1/x">'
                                      '<p>Abstract</p><button>Download PDF</button>',
    "https://journal.example/long": '<title>Journal</title><p>' + 'Latest research and news. ' * 120 + '</p><button>Menu</button>',
    "https://journal.example/cloudflare": '<title>Just a moment...</title><p>Checking your browser.</p><button>Verify</button>',
    "https://idp.example.edu.cn/idp/login": '<title>统一身份认证</title><input name="user"><input type="password"><button>登录</button>',
}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from patchright.sync_api import sync_playwright

    monkeypatch.setenv("CARSI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CARSI_PROGRESS_BAR", "0")
    progress_reporter.start_task("fixture", total=1)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True, args=[
            "--disable-background-networking", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"])
        context = browser.new_context(service_workers="block")
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=PAGES.get(route.request.url, ""))
                      if route.request.resource_type == "document" else route.abort())
        page = context.new_page()
        try:
            yield page
        finally:
            browser.close()


def look(page, url, *, quiet=True):
    page.goto(url)
    now = [0.0]
    d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"})
    result = DownloadResult(doi="10.1/fixture", status="failed")
    activity = PageActivity(result.doi, {}, clock=lambda: now[0])
    activity.observe(page)
    now[0] = 31 if quiet else 10
    d._remind_on_unknown_page(activity, result)
    reminded = activity.key in progress_reporter.read_state()["attention"]
    activity.close()
    return reminded, [e for e in result.events if e["state"].startswith("unknown_page")]


def test_a_quiet_unknown_page_with_something_to_click_asks_the_user(setup):
    reminded, events = look(setup, "https://journal.example/hold")
    assert reminded
    assert events[0]["state"] == "unknown_page_attention" and '"I am a person"' in events[0]["detail"]


@pytest.mark.parametrize("url", [
    "https://journal.example/quiet",          # nothing to click: a page still loading
    "https://journal.example/article",        # an article
    "https://journal.example/long",           # an ordinary long page
    "https://journal.example/cloudflare",     # a recognised verification reminds the user itself
    "https://idp.example.edu.cn/idp/login",   # the school's login is the user's step already
])
def test_pages_that_ask_nobody(setup, url):
    assert look(setup, url) == (False, [])


def test_a_page_that_moved_lately_asks_nobody(setup):
    assert look(setup, "https://journal.example/hold", quiet=False) == (False, [])


def test_the_window_watcher_hands_the_look_to_the_browser_thread(setup):
    """Production path: the request watcher's thread sees the quiet page, the browser
    thread looks at it before its next call (``watchdog.run_soon``)."""
    import time
    from paper_search_carsi.browser import watchdog

    page = setup
    page.goto("https://journal.example/hold")
    d = PublisherBatchDownloader({"publisher_institution_federation": "carsi", "browser_stall_notify_after": 1})
    result = DownloadResult(doi="10.1/fixture", status="failed")
    stop = d._start_user_watch(page, result)
    try:
        end = time.monotonic() + 5
        while not watchdog._soon and time.monotonic() < end:
            time.sleep(0.05)
        assert watchdog._soon  # scheduled, nothing shown yet
        assert result._page_activity.key not in progress_reporter.read_state()["attention"]
        watchdog._run_soon_calls()  # what the browser thread does before its next call
        assert result._page_activity.key in progress_reporter.read_state()["attention"]
    finally:
        stop.set()
        watchdog._soon.clear()
    assert not progress_reporter.read_state()["attention"]  # the article's end clears it

"""Manual verification and supplement discovery, using only local browser replies."""
import json
import os
import time
from unittest.mock import Mock

import pytest

from paper_search_carsi import progress_reporter, progress_view
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.engine.batch_user import _UserWatch
from paper_search_carsi.publishers.profiles import SPRINGER_PROFILE


pytestmark = pytest.mark.skipif(os.environ.get("CARSI_LOCAL_BROWSER_TEST") != "1",
                                reason="local Chrome fixture opt-in")
ARTICLE = "https://link.springer.com/article/10.1007/fixture"
FRAME = "https://www.google.com/recaptcha/api2/anchor?fixture=1"
VERIFICATION = f"""<title>Article title</title><body>
<p>We are sorry, but we are experiencing unusual traffic at this time.
Please help us confirm that you are not a robot and we will take you to your content.</p>
<p>This verification must be submitted within 1 minute of completing it.</p>
<iframe src="{FRAME}" title="reCAPTCHA" style="width:304px;height:78px"></iframe>
<button onclick="document.body.innerHTML='<p>Article ready</p>'">Take me to my Content</button>
</body>"""


def test_image_only_human_verification_is_recognized_and_left_to_the_user(browser_page):
    from paper_search_carsi.browser import challenge_interaction
    page = browser_page
    page.set_content('<title>Human Verification</title><button><img alt="begin"></button>')
    d = PublisherBatchDownloader({})
    assert d._is_challenge_page(page)
    assert challenge_interaction.needs_manual_verification(page)
    page.set_content('<title>Human Verification</title><p>Select the matching image</p><button>Continue</button>')
    assert d._is_challenge_page(page)  # a task may start on a later puzzle step
    assert challenge_interaction.needs_manual_verification(page)
    page.set_content('<title>Human Verification</title><article>A study of automated verification</article>')
    assert not d._is_challenge_page(page)


def test_multistep_image_verification_does_not_finish_after_begin(browser_page, monkeypatch):
    from types import SimpleNamespace
    from paper_search_carsi.engine import batch_waits
    page = browser_page
    page.set_content('<title>Human Verification</title><button id="begin"><img alt="begin"></button>')
    page.evaluate("""() => document.querySelector('#begin').onclick = () => {
        document.body.innerHTML='<p>Select the matching image</p><button id="finish">Finish</button>';
        document.querySelector('#finish').onclick=() => {
            document.title='Article'; document.body.innerHTML='<p>Article ready</p>';
        };
    }""")
    clock = [1000.0]
    monkeypatch.setattr(batch_waits, "time", SimpleNamespace(time=lambda: clock[0]))
    pump = page.wait_for_timeout
    monkeypatch.setattr(page, "wait_for_timeout", lambda ms: (clock.__setitem__(0, clock[0] + ms / 1000), pump(1)))
    d = PublisherBatchDownloader({"browser_page_wait_timeout": 10}, login_timeout_sec=10)
    result = DownloadResult(doi="10.1/fixture", status="failed")
    clicked = []

    def act(*args):
        if getattr(result, "_verification_wait", None) and not clicked:
            page.locator('#begin').click()  # local fixture only
            clicked.append("begin")
        elif clock[0] >= 1020 and len(clicked) == 1:
            assert result._verification_wait.paused
            page.locator('#finish').click()
            clicked.append("finish")

    monkeypatch.setattr(d, "_check_user_decision", act)
    assert d._wait_for_challenge(page, result)
    assert clicked == ["begin", "finish"]
    assert clock[0] >= 1020
    assert result._user_wait_deadline > clock[0]


@pytest.fixture
def browser_page(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("CARSI_DATA_DIR", str(tmp_path / "data"))
    # The fixture's manual click below must run on the browser thread. The
    # production request watcher is covered separately by test_window_requests.
    def synchronous_watch(d, page, result):
        activity, _ = d._observe_page_activity(page, result)
        return _UserWatch(activity)
    monkeypatch.setattr(PublisherBatchDownloader, "_start_user_watch", synchronous_watch)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True, args=[
            "--disable-background-networking", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"])
        context = browser.new_context(service_workers="block")
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=(
            '<input type="checkbox" checked aria-label="I am not a robot">'
            if route.request.url == FRAME else VERIFICATION)))
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize("complete", [False, True])
def test_stalled_verification_uses_the_configured_reminder_delay(browser_page, monkeypatch, complete):
    page = browser_page
    page.goto(ARTICLE)
    d = PublisherBatchDownloader({"browser_stall_notify_after": 1}, profile=SPRINGER_PROFILE, login_timeout_sec=3)
    result = DownloadResult(doi="10.1007/fixture", status="failed", state="article_loaded")
    progress_reporter.start_task("论文下载", total=1)
    started = time.time()
    original = progress_reporter.set_attention
    prompts = []

    def attention(*args, **kwargs):
        original(*args, **kwargs)
        prompts.append(time.time() - started)
        assert result._attention_page is page
        view = progress_view.view(progress_reporter.read_state(), time.time())
        assert (view["mode"], view["tone"]) == ("attention", "warn")
        assert "没有进展" in args[1]
        if complete:
            # A local fixture's user action; never used against a real CAPTCHA.
            page.get_by_role("button", name="Take me to my Content").click()

    monkeypatch.setattr(progress_reporter, "set_attention", attention)
    assert d._wait_for_challenge(page, result) is complete
    assert len(prompts) == 1 and 1 <= prompts[0] < 2
    assert any(e["state"] == "challenge_resolved" for e in result.events) is complete
    assert not any(e["state"] == "challenge_interaction" for e in result.events)
    assert progress_reporter.read_state()["attention"] == {}
    assert result._attention_page is None


@pytest.mark.parametrize("appears", ["after_navigation", "during_parsing"])
@pytest.mark.parametrize("complete", [False, True])
def test_supplement_check_waits_for_manual_verification_instead_of_reporting_empty(
        browser_page, tmp_path, monkeypatch, appears, complete):
    page = browser_page
    delayed = ("<body><script>setTimeout(() => {document.open();document.write("
               + json.dumps(VERIFICATION) + ");document.close();}, 300);</script></body>")
    page.context.route(ARTICLE, lambda route: route.fulfill(content_type="text/html", body=(
        delayed if appears == "after_navigation" else "<body><p>Loading article</p></body>")))
    # collect_supplements creates its own tab; its page is still a real Chrome page.
    d = PublisherBatchDownloader({"browser_stall_notify_after": 1}, profile=SPRINGER_PROFILE, login_timeout_sec=3)
    adapter = Mock()
    adapter.supplements_page_urls.return_value = [ARTICLE]
    adapter.is_article_page_url.return_value = True
    adapter.is_institution_chooser.return_value = False
    parsed = []

    def links(tab, doi):
        parsed.append(tab.locator("body").inner_text())
        if appears == "during_parsing" and len(parsed) == 1:
            tab.set_content(VERIFICATION)
        return []

    adapter.supplement_links.side_effect = links
    monkeypatch.setattr(PublisherBatchDownloader, "adapter", adapter)
    result = DownloadResult(doi="10.1007/fixture", status="success", state="pdf_saved", pdf_path="saved.pdf")
    progress_reporter.start_task("论文下载", total=1)
    prompts = []
    original = progress_reporter.set_attention

    def attention(*args, **kwargs):
        original(*args, **kwargs)
        prompts.append(args[1])
        if complete:
            result._attention_page.get_by_role("button", name="Take me to my Content").click()

    monkeypatch.setattr(progress_reporter, "set_attention", attention)
    files = d.collect_supplements(page.context, result.doi, tmp_path / "downloads", result)
    assert len(prompts) == 1
    if complete:
        assert files == []
        assert parsed[-1] == "Article ready"
        assert any(e["state"] == "supplements_found" for e in result.events)
    else:
        assert files[0]["reason"] == "challenge_timeout"
        assert not any(e["state"] == "supplements_found" for e in result.events)
        assert len(parsed) == (0 if appears == "after_navigation" else 1)
    assert result.ok and (result.state, result.pdf_path) == ("pdf_saved", "saved.pdf")
    assert progress_reporter.read_state()["attention"] == {}


def test_checked_verification_that_advances_automatically_stays_quiet(browser_page, monkeypatch):
    page = browser_page
    page.goto(ARTICLE)
    page.evaluate("setTimeout(() => document.body.innerHTML='<p>Article ready</p>', 200)")
    d = PublisherBatchDownloader({"browser_stall_notify_after": 2}, profile=SPRINGER_PROFILE, login_timeout_sec=4)
    result = DownloadResult(doi="10.1007/fixture", status="failed", state="article_loaded")
    progress_reporter.start_task("论文下载", total=1)
    prompts = Mock(wraps=progress_reporter.set_attention)
    monkeypatch.setattr(progress_reporter, "set_attention", prompts)
    assert d._wait_for_challenge(page, result)
    assert result.state == "article_loaded"
    prompts.assert_not_called()

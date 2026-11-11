"""Verification widgets on local pages in Chrome: which pages count as verification."""
import os
import time

import pytest

from paper_search_carsi.browser import challenge_interaction
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader

pytestmark = pytest.mark.skipif(os.environ.get("CARSI_LOCAL_BROWSER_TEST") != "1",
                                reason="local Chrome fixture opt-in")

RECAPTCHA = "https://www.google.com/recaptcha/api2/anchor?k=fixture"
BADGE = "https://www.google.com/recaptcha/api2/anchor?k=fixture&size=invisible"
HCAPTCHA = "https://newassets.hcaptcha.com/captcha/v1/fixture/static/hcaptcha.html#frame=checkbox"
DATADOME = "https://geo.captcha-delivery.com/captcha/?initialCid=fixture"
SHORT = "<title>Security check</title><p>One moment, please.</p>"
PAGES = {
    "https://journal.example/recaptcha": SHORT + f'<iframe src="{RECAPTCHA}" style="width:304px;height:78px"></iframe>',
    "https://journal.example/hcaptcha": SHORT + f'<iframe src="{HCAPTCHA}" style="width:303px;height:78px"></iframe>',
    "https://journal.example/datadome": SHORT + f'<iframe src="{DATADOME}" style="width:400px;height:500px"></iframe>',
    "https://journal.example/geetest": SHORT + '<div class="geetest_box" style="width:300px;height:200px">slide</div>',
    "https://journal.example/aliyun": SHORT + '<div id="aliyunCaptcha-window-popup" style="width:300px;height:200px">slide</div>',
    "https://journal.example/px": SHORT + '<div id="px-captcha" style="width:300px;height:100px">Press &amp; Hold</div>',
    "https://journal.example/awswaf": SHORT + '<script src="https://fixture.us-east-1.captcha.awswaf.com/fixture/jsapi.js"></script>'
                                     '<div id="captcha-container" style="width:300px;height:200px"></div>',
    "https://journal.example/article": '<title>A study</title><meta name="citation_doi" content="10.1/x">'
                                      f'<p>Abstract</p><iframe src="{RECAPTCHA}" style="width:304px;height:78px"></iframe>',
    "https://journal.example/long": '<title>Sign in</title>' + '<p>' + 'Institutional access options. ' * 120 + '</p>'
                                   f'<iframe src="{RECAPTCHA}" style="width:304px;height:78px"></iframe>',
    "https://journal.example/hidden": SHORT + '<div class="geetest_box" style="display:none;width:300px;height:200px"></div>',
    "https://journal.example/badge": SHORT + f'<iframe src="{BADGE}" style="width:256px;height:60px"></iframe>',
    "https://idp.example.edu.cn/idp/login": '<title>统一身份认证</title><input name="user"><input type="password">'
                                           '<div class="geetest_box" style="width:300px;height:200px">slide</div>',
}


@pytest.fixture
def browser_page(tmp_path, monkeypatch):
    from patchright.sync_api import sync_playwright

    monkeypatch.setenv("CARSI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CARSI_PROGRESS_BAR", "0")
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True, args=[
            "--disable-background-networking", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"])
        context = browser.new_context(service_workers="block")
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=PAGES.get(
            route.request.url, '<input type="checkbox" aria-label="widget">'))
            if route.request.resource_type in ("document", "subdocument") else route.abort())
        page = context.new_page()
        try:
            yield page
        finally:
            browser.close()


@pytest.mark.parametrize("path,name", [
    ("recaptcha", "reCAPTCHA"), ("hcaptcha", "hCaptcha"), ("datadome", "DataDome"), ("geetest", "GeeTest"),
    ("aliyun", "Aliyun"), ("px", "PerimeterX"), ("awswaf", "AWS WAF"),
])
def test_a_page_made_of_a_widget_is_a_verification_left_to_the_user(browser_page, path, name):
    page = browser_page
    page.goto(f"https://journal.example/{path}")
    d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"})
    assert challenge_interaction.verification_widget(page) == name
    assert d._is_challenge_page(page)
    assert challenge_interaction.needs_manual_verification(page)
    # Handed to the user at once, with the provider named in the record.
    result = DownloadResult(doi="10.1/fixture", status="failed")
    assert d._automatic_challenge_step(page, result, {}, time.time() + 60) is False
    assert f"manual widget: {name}" in [e.get("detail") for e in result.events]


@pytest.mark.parametrize("url", [
    "https://journal.example/article",   # an article whose form carries a widget
    "https://journal.example/long",      # a widget among other forms of a long page
    "https://journal.example/hidden",    # not shown
    "https://journal.example/badge",     # reCAPTCHA v3's badge
    "https://idp.example.edu.cn/idp/login",  # the school's sign-in: its captcha is the user's login
])
def test_widgets_that_are_not_a_verification_page(browser_page, url):
    page = browser_page
    page.goto(url)
    d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"})
    assert not d._is_challenge_page(page)

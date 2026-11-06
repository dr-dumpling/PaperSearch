"""Trusted interaction detection on local login documents; no system input."""
import os

import pytest

from paper_search_carsi.engine.login_wait import LoginWait
from paper_search_carsi.engine.batch import PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import get_publisher_profile


pytestmark = pytest.mark.skipif(os.environ.get("CARSI_LOCAL_BROWSER_TEST") != "1",
                                reason="local Chrome fixture opt-in")
FORM = ('<form onsubmit="event.preventDefault()"><label>Fixture account<input name="account"></label>'
        '<button>Sign in</button></form>')


@pytest.mark.parametrize('site,url', [
    ('lww', 'https://login.wolterskluwer.com/login'),
    ('elsevier', 'https://www.sciencedirect.com/user/login'),
    ('elsevier', 'https://accounts.fixture.test/login'),
])
def test_publisher_password_with_institution_route_is_not_a_school_login(site, url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        page.route('**/*', lambda route: route.fulfill(content_type='text/html', body=(
            '<title>Publisher account</title><input type="password">'
            '<a id="athensLoginUrl" href="/institution">OpenAthens | Institutional</a>')))
        try:
            page.goto(url)
            d = PublisherBatchDownloader({'publisher_institution_federation': 'carsi'},
                                         profile=get_publisher_profile(site))
            d.institution_query = 'Fixture University'
            assert not d._school_password_box(page, page.url)
            assert not d._users_login_step(page)
            assert d._login_wait_page(page) != 'school_login'
            # A credential page on the school's IdP still requests the user,
            # even if it offers the same alternative institution link.
            page.goto('https://idp.fixture.edu/login')
            assert d._school_password_box(page, page.url)
            assert d._users_login_step(page)
            # An unknown external credential form without an institutional
            # route is left to the user; this change cannot click through it.
            page.goto('https://school-account.fixture.test/login')
            page.locator('a').evaluate('el => el.remove()')
            assert d._users_login_step(page)
            # Typing in a publisher account form is explicit user involvement.
            page.goto(url)
            page.locator('input').fill('local fixture only')
            assert d._users_login_step(page)
            # With no institution option, an unfamiliar standalone login form
            # must still be left to the user, even on the publisher's host.
            page.goto(url)
            page.locator('a').evaluate('el => el.remove()')
            assert d._users_login_step(page)
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize("target", ["main", "iframe", "popup"])
def test_trusted_login_input_pauses_but_script_updates_and_focus_do_not(target):
    from playwright.sync_api import sync_playwright

    clock = [1000.0]
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True, args=[
            "--disable-background-networking", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"])
        context = browser.new_context(service_workers="block")
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=FORM))
        page = context.new_page()
        try:
            page.goto("https://login.fixture.test/main")
            if target == "iframe":
                page.set_content('<iframe src="https://frame.fixture.test/login"></iframe>')
                frame = page.frame(url="https://frame.fixture.test/login")
                if frame is None:
                    page.wait_for_event("framenavigated")
                    frame = page.frame(url="https://frame.fixture.test/login")
            elif target == "popup":
                with page.expect_popup() as opened:
                    page.evaluate("window.open('https://login.fixture.test/popup')")
                page = opened.value
                page.wait_for_load_state()
                frame = page.main_frame
            else:
                frame = page.main_frame
            wait = LoginWait(1180, lambda: clock[0])
            wait.observe(page, True)
            field = frame.get_by_label("Fixture account")
            field.focus()
            field.evaluate("el => {el.value='script fixture';el.dispatchEvent(new InputEvent('input',{bubbles:true}));}")
            field.evaluate("""el => {
                el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));
                el.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,code:'ArrowRight'}));
                el.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerType:'mouse'}));
                el.dispatchEvent(new Event('change',{bubbles:true}));
            }""")
            field.evaluate("el => el.form.requestSubmit()")
            wait.observe(page, True)
            assert not wait.paused
            clock[0] += 10
            field.fill("user fixture")  # trusted events in this test page only
            wait.observe(page, True)
            assert wait.paused
            clock[0] += 400
            assert wait.deadline - clock[0] == 170
            page.goto("https://login.fixture.test/second-factor")
            wait.observe(page, True)
            assert wait.paused  # another authentication step keeps takeover
            wait.observe(page, False)
            assert not wait.paused
            assert page.evaluate("!window[Symbol.for('paper-search:login-activity')]")
            wait.close()
            for action in ("click", "keyboard"):
                wait = LoginWait(clock[0] + 180, lambda: clock[0])
                wait.observe(page, True)
                field = page.get_by_label("Fixture account")
                if action == "click":
                    field.click()
                else:
                    field.press("ArrowRight")
                wait.observe(page, True)
                assert wait.paused, action
                wait.close()
        finally:
            context.close()
            browser.close()


def test_idp_redirect_and_unknown_relay_are_not_human_steps_but_real_controls_are():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        page.route('**/*', lambda route: route.fulfill(content_type='text/html', body='<title>Authentication redirect</title><form><input type="hidden" name="SAMLResponse"></form>'))
        d = PublisherBatchDownloader({'publisher_institution_federation': 'carsi'},
                                     profile=get_publisher_profile('elsevier'), institution_query='Fixture University')
        try:
            for url in ('https://idp.fixture.edu/idp/profile/SAML2/POST/SSO', 'https://relay.fixture.test/sso'):
                page.goto(url)
                assert not d._users_login_step(page)
                assert not d._is_human_login_page(page)
            page.goto('https://idp.fixture.edu/login')
            for markup in ('<input type="password">', '<input autocomplete="one-time-code">',
                           '<input name="username">', '<canvas id="qrcode" width="100" height="100"></canvas>',
                           '<input name="_shib_idp_consentOptions" type="radio"><button>Accept</button>'):
                page.locator('body').evaluate('(el,html)=>el.innerHTML=html', markup)
                assert d._users_login_step(page), markup
                assert d._is_human_login_page(page), markup
            page.locator('body').evaluate('el=>el.innerHTML="Returning to the publisher"')
            assert not d._users_login_step(page)
        finally:
            context.close()
            browser.close()

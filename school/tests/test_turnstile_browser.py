"""Turnstile service continuation in isolated Chrome, with no paid requests."""
import os
import time
from contextlib import ExitStack
from unittest.mock import Mock

import pytest

from paper_search_school.browser.challenge import continuation
from paper_search_school.browser.challenge.local import interaction
from paper_search_school.browser.challenge.services import solver
from paper_search_school.browser.driver import main_world
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader

pytestmark = pytest.mark.skipif(os.environ.get('SCHOOL_LOCAL_BROWSER_TEST') != '1', reason='local Chrome opt-in')
CONFIG = {'captcha_service': 'yescaptcha', 'captcha_key': 'fixture'}
SITEKEY = '0x4AAAAAAATestWidgetKey'
ANSWER = solver.TurnstileAnswer('fixture-token', 'Fixture Service Browser/1.0')


@pytest.fixture(scope='module')
def browser():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    yield context.new_page()
    context.close()


def markup(*, button='<button>Verify</button>', attrs='', extra='', callback=''):
    return f'''<meta charset=utf-8><title>Human Verification</title><p>Please confirm that you are human</p>
    <form action=/verify method=post id=verification>
      <div id=widget class=cf-turnstile data-sitekey="{SITEKEY}" {attrs}
           style="width:300px;height:70px">
        <input type=hidden name=cf-turnstile-response id=response>
      </div>{button}{extra}
    </form><script>{callback}</script>'''


def serve(page, html, *, accepted=True):
    requests = []
    def reply(route):
        request = route.request
        if request.url.endswith('/verify'):
            requests.append({'body': request.post_data, 'agent': request.headers.get('user-agent')})
            body = '<title>Article</title><meta name=citation_doi content="10.1000/test"><article>Full text</article>' if accepted else html
        else:
            body = html
        route.fulfill(status=200, content_type='text/html', body=body)
    page.route('https://publisher.example/**', reply)
    page.goto('https://publisher.example/check?session=private-fixture')
    return requests


def resume(page, monkeypatch, *, cleanup=None, budget=1, response=ANSWER):
    ask = Mock(return_value=response)
    monkeypatch.setattr(solver, 'solve_turnstile', ask)
    notes = []
    limits = continuation.Limits(time.monotonic()+8, solver.Budget(budget), cleanup=cleanup)
    result = continuation.resume(page, CONFIG, kind='turnstile', limits=limits, observation=notes.append)
    return result, ask, notes, limits


@pytest.mark.parametrize('button', [
    '<button>Verify</button>', '<input type=submit value=Confirm>',
    '<button type=button onclick="this.form.requestSubmit()">Continue</button>',
    '<div role=button tabindex=0 onclick="this.closest(\'form\').requestSubmit()">验证</div>',
])
def test_response_submitted_by_real_controls_with_matching_user_agent(page, monkeypatch, button):
    requests = serve(page, markup(button=button))
    original_agent = page.evaluate('navigator.userAgent')
    with ExitStack() as cleanup:
        result, ask, _, limits = resume(page, monkeypatch, cleanup=cleanup)
        page.wait_for_url('**/verify')
        assert result and page.title() == 'Article'
        assert requests == [{'body': 'cf-turnstile-response=fixture-token', 'agent': ANSWER.user_agent}]
        assert ask.call_args.args[:2] == ('https://publisher.example/', SITEKEY)
        assert limits.budget.used == 1
        assert page.evaluate('navigator.userAgent') == original_agent
    page.goto('https://publisher.example/check')
    page.locator('form').evaluate('e=>e.requestSubmit()')
    page.wait_for_url('**/verify')
    assert requests[-1]['agent'] != ANSWER.user_agent


def test_named_callback_is_called_with_its_owner_and_token(page, monkeypatch):
    html = markup(button='', attrs='data-callback="site.done" data-action="verify"', callback='''
      window.site={done(token){window.received=[this===site,token];
        document.title='Article';document.body.innerHTML='<article>Full text</article>'}};
    ''')
    serve(page, html)
    result, ask, _, _ = resume(page, monkeypatch)
    assert result
    assert page.evaluate('window.received', **main_world(page)) == [True, ANSWER.token]
    assert ask.call_args.kwargs['action'] == 'verify'


def test_callback_can_enable_submit_before_native_click(page, monkeypatch):
    requests = serve(page, markup(button='<button disabled id=submit>Confirm</button>',
                                attrs='data-callback="ready"', callback='''
      window.ready=()=>setTimeout(()=>document.getElementById('submit').disabled=false,150);
    '''))
    result, _, _, _ = resume(page, monkeypatch)
    page.wait_for_url('**/verify')
    assert result and requests[0]['body'] == 'cf-turnstile-response=fixture-token'


@pytest.mark.parametrize('change', [
    "document.title='Just a moment...'", "window._cf_chl_opt={}",
    "document.querySelector('form').id='challenge-form'",
    "document.querySelector('form').insertAdjacentHTML('beforeend','<input type=password>')",
    "document.head.insertAdjacentHTML('beforeend','<meta name=citation_doi content=x>')",
    "widget.dataset.cdata='private-session'", "widget.dataset.chlPageData='private-session'",
    "widget.dataset.callback='missingCallback'", "response.value='local-answer'",
    "widget.insertAdjacentHTML('beforeend','<input type=hidden name=cf-turnstile-response>')",
    "document.querySelector('button').insertAdjacentHTML('afterend','<button>Submit</button>')",
    "widget.insertAdjacentHTML('afterend',widget.outerHTML)",
    "document.querySelector('button').remove()",
])
def test_unsupported_and_ambiguous_widgets_do_not_spend_a_task(page, monkeypatch, change):
    serve(page, markup())
    page.evaluate(change, **main_world(page))
    result, ask, _, limits = resume(page, monkeypatch)
    assert not result and limits.budget.used == 0
    ask.assert_not_called()


@pytest.mark.parametrize('change', [
    "widget.dataset.sitekey='0x4AAAAAAAChangedKey'",
    "widget.dataset.action='changed'",
    "widget.outerHTML=widget.outerHTML",
    "response.value='local-answer'",
    "history.replaceState(null,'','/new-challenge')",
    "window[Symbol.for('papersearch.turnstile.events')]=[{event:'tokenExpired',at:1}]",
    "document.querySelector('button').insertAdjacentHTML('afterend','<button>Submit</button>')",
])
def test_widget_changes_while_service_runs_discard_answer(page, monkeypatch, change):
    requests = serve(page, markup())
    def answer(*args, **kwargs):
        page.evaluate(change, **main_world(page))
        return ANSWER
    monkeypatch.setattr(solver, 'solve_turnstile', answer)
    assert not continuation.resume(page, CONFIG, kind='turnstile',
                                   limits=continuation.Limits(time.monotonic()+5, solver.Budget(1)),
                                   observation=Mock())
    assert not requests


def test_rejected_answer_is_not_a_site_pass(page, monkeypatch):
    requests = serve(page, markup(), accepted=False)
    result, _, notes, _ = resume(page, monkeypatch)
    page.wait_for_url('**/verify')
    assert result  # delivery asks the outer engine to look again
    assert requests and page.title() == 'Human Verification'
    assert interaction.verification_widget(page) == 'Turnstile'
    assert not any('passed' in note for note in notes)


def test_zero_budget_and_invalid_solution_do_not_submit(page, monkeypatch):
    requests = serve(page, markup())
    result, ask, _, _ = resume(page, monkeypatch, budget=0)
    assert not result
    ask.assert_not_called()
    result, ask, _, _ = resume(page, monkeypatch, response=None)
    assert not result and not requests
    ask.assert_called_once()


def test_embedded_widget_under_generic_verification_title_is_not_full_page_cf(page):
    serve(page, markup())
    page.evaluate("document.title='Verification required'")
    assert interaction.challenge_kind(page) == 'turnstile'
    page.evaluate("document.title='Just a moment...'")
    assert interaction.challenge_kind(page) == 'cloudflare'


@pytest.mark.parametrize('accepted', [True, False])
def test_engine_service_fallback_with_local_clicks_disabled_rechecks_access(page, monkeypatch, accepted):
    requests = serve(page, markup(), accepted=accepted)
    d = PublisherBatchDownloader({**CONFIG, 'browser_stall_notify_after': 0})
    d._check_user_decision = Mock(return_value=False)
    d._snapshot = Mock()
    d._verification_attention = Mock()
    d._observe_page_activity = Mock(return_value=(Mock(), False))
    monkeypatch.setattr(solver, 'solve_turnstile', Mock(return_value=ANSWER))
    local = Mock(side_effect=AssertionError('local clicks disabled for this test'))
    monkeypatch.setattr(interaction, 'click_checkbox', local)
    result = DownloadResult(doi='10.1000/test', status='failed')
    assert d._wait_for_challenge(page, result, deadline=time.time()+2) is accepted
    assert (page.title() == 'Article') is accepted
    assert len(requests) == 1
    assert d._captcha_budget.used == 1
    assert ('challenge_resolved' in [e['state'] for e in result.events]) is accepted
    local.assert_not_called()


def test_school_navigation_checkpoint_stops_response_delivery(page, monkeypatch):
    requests = serve(page, markup())
    d = PublisherBatchDownloader({**CONFIG, 'idp_domains': ['school.example']})
    d._check_user_decision = Mock(return_value=False)
    page.route('https://school.example/**', lambda r:r.fulfill(body='<title>School login</title>'))
    def answer(*args, **kwargs):
        page.goto('https://school.example/login')
        kwargs['checkpoint']()
        return ANSWER
    monkeypatch.setattr(solver, 'solve_turnstile', answer)
    attempt = {}
    try:
        assert not d._continue_challenge(page, DownloadResult(doi='10.1000/test', status='failed'),
                                         attempt, time.time()+8, 'turnstile')
        assert not requests
    finally:
        attempt['service_cleanup'].close()

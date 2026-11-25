"""Real Chrome local replay. API answers are fixtures, not live success evidence."""
import os
import time
from unittest.mock import Mock

import pytest

from paper_search_school.browser.challenge import continuation
from paper_search_school.browser.challenge.handlers import recaptcha_hcaptcha as tiles
from paper_search_school.browser.challenge.services import solver

pytestmark = pytest.mark.skipif(os.environ.get('SCHOOL_LOCAL_BROWSER_TEST') != '1',
                                reason='local Chrome fixture opt-in')
CONFIG = {'captcha_service': 'yescaptcha', 'captcha_key': 'fixture'}


def markup(kind, reject=False):
    if kind == 'hcaptcha':
        question = '<div class="prompt-text">Please click each image containing a bicycle</div>'
        cell = '<div class="task-image" aria-pressed="false"><div class="image" style="width:100px;height:100px;background:rgb(INDEX,40,80)"></div></div>'
        grid = '<div style="display:grid;grid-template-columns:repeat(3,100px);width:300px">' + ''.join(cell.replace('INDEX',str(i*20)) for i in range(9)) + '</div>'
        button = '<button class="button-submit">Verify</button>'
        selector = '.task-image'
    else:
        question = '<div class="rc-imageselect-desc-wrapper">Select all images with <strong>bicycles</strong></div>'
        grid = '<div class="rc-imageselect-table-33" style="display:grid;grid-template-columns:repeat(3,100px);width:300px;height:300px">' + ''.join(
            f'<div class="rc-imageselect-tile" aria-pressed="false"><img src="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'100\' height=\'100\'%3E%3Crect width=\'100\' height=\'100\' fill=\'red\'/%3E%3C/svg%3E" style="width:100px;height:100px" data-i="{i}"></div>' for i in range(9))+'</div>'
        button = '<button id="recaptcha-verify-button">Verify</button>'
        selector = '.rc-imageselect-tile'
    return f'''{question}{grid}{button}<script>
    const cells=[...document.querySelectorAll('{selector}')];
    cells.forEach(c=>c.onclick=()=>c.setAttribute('aria-pressed',c.getAttribute('aria-pressed')==='true'?'false':'true'));
    document.querySelector('button').onclick=()=>{{
      const chosen=cells.flatMap((c,i)=>c.getAttribute('aria-pressed')==='true'?[i]:[]);
      if({str(not reject).lower()} && JSON.stringify(chosen)==='[0,2]')parent.postMessage('accepted','*');
    }};
    </script>'''


@pytest.fixture
def browser():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome',headless=True,args=[
            '--disable-background-networking','--no-proxy-server','--host-resolver-rules=MAP * ~NOTFOUND'])
        yield browser
        browser.close()


def setup(browser,kind,reject=False):
    url = 'https://www.google.com/recaptcha/api2/bframe' if kind=='recaptcha' else 'https://newassets.hcaptcha.com/captcha/v1/test/static/hcaptcha.html?frame=challenge'
    context=browser.new_context(device_scale_factor=2,service_workers='block')
    outer=f'''<title>Verification</title><iframe src="{url}" style="width:500px;height:500px"></iframe>
    <script>onmessage=e=>{{if(e.data==='accepted'){{document.querySelector('iframe').remove();document.title='Article';document.body.insertAdjacentHTML('beforeend','<article>Full text</article>')}}}}</script>'''
    context.route('**/*',lambda route: route.fulfill(content_type='text/html',body=outer if 'journal.example' in route.request.url else markup(kind,reject)))
    page=context.new_page();page.goto('https://journal.example/check')
    return context,page


@pytest.mark.parametrize('kind',['recaptcha','hcaptcha'])
def test_real_grid_controls_use_the_right_image_task_then_continue(browser,kind,monkeypatch):
    context,page=setup(browser,kind)
    asked=[]
    def answer(images,question,config,**kwargs):
        asked.append((len(images),question,kwargs['count']))
        return [0,2]
    monkeypatch.setattr(solver,'solve_tiles',answer)
    notes=[]
    assert continuation.resume(page,CONFIG,kind=kind,limits=continuation.Limits(time.monotonic()+20,solver.Budget(3)),observation=notes.append)
    assert page.title()=='Article'
    assert asked==[(1,'/m/0199g',9)] if kind=='recaptcha' else asked==[(9,'Please click each image containing a bicycle',9)]
    assert any('answer submitted' in note for note in notes)
    context.close()


def test_rejected_grid_is_not_reported_passed_and_budget_is_shared(browser,monkeypatch):
    context,page=setup(browser,'hcaptcha',reject=True)
    answer=Mock(return_value=[0,2]);monkeypatch.setattr(solver,'solve_tiles',answer)
    budget=solver.Budget(1);notes=[]
    assert not continuation.resume(page,CONFIG,kind='hcaptcha',limits=continuation.Limits(time.monotonic()+20,budget),observation=notes.append)
    assert page.title()=='Verification'
    assert budget.used==1 and answer.call_count==1
    assert 'service budget exhausted' in notes
    context.close()


def test_picture_replaced_during_service_call_does_not_receive_old_clicks(browser,monkeypatch):
    context,page=setup(browser,'hcaptcha')
    def answer(*a,**kw):
        tiles._frame(page,'hcaptcha').locator('.image').first.evaluate("el=>el.style.backgroundImage='linear-gradient(red, blue)'")
        return [0,2]
    monkeypatch.setattr(solver,'solve_tiles',answer)
    notes=[]
    assert not continuation.resume(page,CONFIG,kind='hcaptcha',limits=continuation.Limits(time.monotonic()+20,solver.Budget(1)),observation=notes.append)
    assert tiles._frame(page,'hcaptcha').locator('[aria-pressed=true]').count()==0
    assert any('discard answer' in note for note in notes)
    context.close()


def test_retry_replaces_wrong_choices_instead_of_accumulating_them(browser,monkeypatch):
    context,page=setup(browser,'hcaptcha')
    answer=Mock(side_effect=[[0,1],[0,2]])
    monkeypatch.setattr(solver,'solve_tiles',answer)
    assert continuation.resume(page,CONFIG,kind='hcaptcha',
                               limits=continuation.Limits(time.monotonic()+20,solver.Budget(3)),
                               observation=Mock())
    assert page.title()=='Article'
    assert answer.call_count==2
    context.close()


def test_selection_animation_is_not_a_new_picture_and_example_is_sent(browser,monkeypatch):
    context,page=setup(browser,'hcaptcha')
    frame=tiles._frame(page,'hcaptcha')
    frame.evaluate("""() => {
      const prompt=document.querySelector('.prompt-text');
      prompt.insertAdjacentHTML('afterend',`<div class="example" style="width:80px;height:80px;background-image:url(data:image/svg+xml,%3Csvg%20xmlns=%27http://www.w3.org/2000/svg%27%20width=%2780%27%20height=%2780%27/%3E)"></div>`);
      document.querySelectorAll('.task-image').forEach(c=>c.addEventListener('click',()=>{
        c.querySelector('.image').style.transform='scale(0.95)';
        c.querySelector('.image').style.opacity='0.9';
      }));
    }""")
    def answer(images,question,config,**kwargs):
        assert len(images)==9
        assert len(kwargs['anchors'])==1
        return [0,2]
    ask=Mock(side_effect=answer);monkeypatch.setattr(solver,'solve_tiles',ask)
    assert continuation.resume(page,CONFIG,kind='hcaptcha',
                               limits=continuation.Limits(time.monotonic()+20,solver.Budget(3)),
                               observation=Mock())
    assert page.title()=='Article'
    ask.assert_called_once()
    context.close()


@pytest.mark.parametrize('label', ['Submit', 'Verify', '继续', ''])
def test_checked_widget_submits_its_form_independent_of_label(browser, label):
    from paper_search_school.engine.batch import PublisherBatchDownloader, DownloadResult
    context = browser.new_context(service_workers='block')
    provider = 'https://newassets.hcaptcha.com/captcha/v1/checkbox'
    outer = f'''<title>Verification</title>
      <form onsubmit="event.preventDefault();document.title='WRONG'"><button>Submit</button></form>
      <form id="verification" onsubmit="event.preventDefault();document.title='Article';this.remove()">
        <iframe src="{provider}"></iframe><input type="submit" value="{label}" disabled>
      </form>'''
    context.route('**/*', lambda route: route.fulfill(content_type='text/html', body=
        '<div id="checkbox" role="checkbox" aria-checked="false">Human</div>'
        if 'hcaptcha.com' in route.request.url else outer))
    page = context.new_page(); page.goto('https://journal.example/check')
    d = PublisherBatchDownloader({})
    d._check_user_decision = Mock(return_value=False)
    result = DownloadResult(doi='10.1000/test', status='failed')
    attempt = {'service_tried': {'hcaptcha'}}
    assert not d._forward_checked_challenge(page, result, attempt, time.time()+10)
    frame = next(f for f in page.frames if 'hcaptcha.com' in f.url)
    frame.locator('#checkbox').evaluate("el=>el.setAttribute('aria-checked','true')")
    # Provider acknowledgement can arrive before the publisher enables submit.
    assert d._forward_checked_challenge(page, result, attempt, time.time()+10)
    assert not attempt.get('forwarded')
    page.locator('#verification input').evaluate('el=>el.disabled=false')
    assert d._forward_checked_challenge(page, result, attempt, time.time()+10)
    assert attempt['forwarded']
    assert page.title() == 'Article'
    context.close()


@pytest.mark.parametrize('extra', ['<input type="password">', '<button>Another</button>'])
def test_checked_form_with_credentials_or_ambiguous_submits_is_left_alone(browser, extra):
    from paper_search_school.browser.challenge.local import prompt
    context = browser.new_context(service_workers='block')
    outer = f'''<title>Verification</title><form onsubmit="event.preventDefault();document.title='WRONG'">
      <iframe src="https://newassets.hcaptcha.com/captcha/v1/checkbox"></iframe>
      <button>Verify</button>{extra}</form>'''
    context.route('**/*', lambda route: route.fulfill(content_type='text/html', body=
        '<div id="checkbox" aria-checked="true">Human</div>' if 'hcaptcha.com' in route.request.url else outer))
    page = context.new_page(); page.goto('https://journal.example/check')
    assert prompt.press_forward(page, timeout_ms=500) == 'unavailable'
    assert page.title() == 'Verification'
    context.close()


def test_delayed_grid_acknowledgement_does_not_send_the_same_question_again(browser, monkeypatch):
    context, page = setup(browser, 'hcaptcha')
    page.evaluate('''() => {window.onmessage = e => {
      if(e.data==='accepted') setTimeout(() => {
        document.querySelector('iframe').remove(); document.title='Article';
      }, 3200);
    }}''')
    answer = Mock(return_value=[0, 2])
    monkeypatch.setattr(solver, 'solve_tiles', answer)
    assert continuation.resume(page, CONFIG, kind='hcaptcha',
        limits=continuation.Limits(time.monotonic()+15, solver.Budget(3)), observation=Mock())
    answer.assert_called_once()
    assert page.title() == 'Article'
    context.close()

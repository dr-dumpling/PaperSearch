"""Windows 0.4.8 report: evidence-based prompts and actual click accounting."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from paper_search_carsi import progress_reporter
from paper_search_carsi.browser import challenge_interaction as interaction
from paper_search_carsi.engine import batch_login
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from test_challenge_interaction import widget, wait_case


def test_inactive_first_widget_does_not_hide_an_actionable_second_widget():
    page, first, _, control = widget()
    control.is_checked.return_value = True
    _, second, _, second_control = widget()
    page.frames.append(second)
    reasons = []
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=lambda: None,
                                      observation=reasons.append) == 'clicked'
    control.click.assert_not_called()
    second_control.click.assert_called_once()
    assert reasons == ['disabled_or_checked', 'click_dispatched']


def test_closed_widget_uses_one_actionability_check_and_retains_readiness_on_timeout():
    from patchright.sync_api import TimeoutError
    page, _, element, _ = widget(count=0)
    element.click.side_effect = [TimeoutError('covered by a temporary overlay'), None]
    reasons = []
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=lambda: None,
                                      observation=reasons.append) == 'unavailable'
    assert reasons == ['actionability_timeout']
    assert not any('delete' in call.args[0] for call in element.evaluate.call_args_list)
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=lambda: None) == 'clicked'
    element.hover.assert_not_called()
    assert any('delete' in call.args[0] for call in element.evaluate.call_args_list)


@pytest.mark.parametrize('entry', ['article', 'pdf'])
def test_unavailable_does_not_spend_three_clicks_and_can_recover(wait_case, monkeypatch, entry):
    c = wait_case
    tries = []
    def click(*args, **kwargs):
        tries.append(c.clock[0])
        if len(tries) <= 4:
            if kwargs.get('observation'):
                kwargs['observation']('actionability_timeout')
            return 'unavailable'
        c.d._challenge_shell.return_value = c.d._is_challenge_page.return_value = False
        return 'clicked'
    monkeypatch.setattr(interaction, 'click_checkbox', click)
    if entry == 'article':
        assert c.d._wait_for_challenge(c.page, c.result)
    else:
        assert c.d._resolve_suspect_block(c.page, c.result, {
            'suspect_block': '403 https://journal.example/pdf', 'bytes': None, 'block_reason': None})
    assert len(tries) == 5
    inputs = [e for e in c.result.events if e['state'] == 'challenge_interaction']
    assert len(inputs) == 1 and 'attempt 1/3' in inputs[0]['detail']
    c.attention.assert_not_called()


@pytest.mark.parametrize('entry', ['article', 'pdf'])
def test_visible_unavailable_widget_gets_half_the_budget_for_handoff(wait_case, monkeypatch, entry):
    c = wait_case
    monkeypatch.setattr(interaction, 'click_checkbox', Mock(return_value='unavailable'))
    notices = []
    c.attention.side_effect = lambda *args, **kwargs: notices.append((c.clock[0], kwargs['deadline']))
    if entry == 'article':
        assert not c.d._wait_for_challenge(c.page, c.result)
    else:
        assert not c.d._resolve_suspect_block(c.page, c.result, {
            'suspect_block': '403 https://journal.example/pdf', 'bytes': None, 'block_reason': None})
    assert notices == [(1030, 1060)]
    assert c.clock[0] == 1060
    assert not any(e['state'] == 'challenge_interaction' for e in c.result.events)


def test_clearing_a_login_prompt_restores_the_machine_stage(tmp_path, monkeypatch):
    monkeypatch.setenv('CARSI_DATA_DIR', str(tmp_path))
    progress_reporter.start_task('fixture', total=1)
    d = PublisherBatchDownloader({})
    result = DownloadResult(doi='10.1234/fixture', status='failed')
    d._set_login_attention(result, 'Please sign in', 1234)
    assert progress_reporter.read_state()['stage'] == 'waiting_login'
    d._set_login_attention(result, '')
    assert not progress_reporter.read_state()['attention']
    assert progress_reporter.read_state()['stage'] == 'checking_access'


def test_humanized_motion_is_not_performed_twice_in_one_click_budget(monkeypatch):
    from patchright.sync_api import TimeoutError
    now = [0.0]
    monkeypatch.setattr(interaction, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    page, _, element, _ = widget(count=0)
    def motion(**kwargs):
        if kwargs['timeout'] < 1500:
            now[0] += kwargs['timeout'] / 1000
            raise TimeoutError('native movement exceeded remaining action budget')
        now[0] += 1.5
    element.hover.side_effect = element.click.side_effect = motion
    assert interaction.click_checkbox(page, timeout_ms=2500, checkpoint=lambda: None) == 'clicked'
    assert now[0] == 1.5


def test_login_reminder_rechecks_the_page_after_automatic_redirect(tmp_path, monkeypatch):
    monkeypatch.setenv('CARSI_DATA_DIR', str(tmp_path))
    progress_reporter.start_task('fixture', total=1)
    clock = [0.0]
    monkeypatch.setattr(batch_login.time, 'time', lambda: clock[0])
    monkeypatch.setattr(batch_login.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(batch_login, 'settle', lambda *args: None)
    d = PublisherBatchDownloader({}, login_timeout_sec=5)
    d._users_login_step = lambda page: clock[0] < 1  # auto-submit while settling
    page = Mock(url='https://relay.fixture.test/sso', frames=[])
    for name in ('_institution_pdf_entitlement_missing', '_click_sso_entry', '_may_offer_entry',
                 '_dismiss_cookie_banners', '_click_openathens_entry', '_select_institution',
                 '_check_user_decision', '_is_idp_host', '_is_auth_page', '_on_publisher_host',
                 '_stuck_on_school_site', '_follow_federated_login_option', '_is_human_login_page',
                 '_click_optional_continue', '_is_challenge_page', '_return_to_record_article_if_needed',
                 '_idp_confirmation', '_login_block_reason'):
        setattr(d, name, Mock(return_value=False))
    d._page_wait_over = lambda page, since: (False, since)
    d._article_access_available = lambda page: True
    result = DownloadResult(doi='10.1234/fixture', status='failed')
    with patch.object(progress_reporter, 'set_attention') as attention:
        assert d._complete_login_steps(page, result)
    attention.assert_not_called()

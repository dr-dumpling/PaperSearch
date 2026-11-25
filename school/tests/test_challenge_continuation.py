import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from paper_search_school.browser.challenge import continuation
from paper_search_school.browser.challenge.services import solver
from paper_search_school.browser.challenge.local import interaction
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader

CONFIG = {'captcha_service': 'yescaptcha', 'captcha_key': 'fixture', 'captcha_max_per_run': 2}


def test_unsupported_type_does_not_invoke_image_service(monkeypatch):
    post = Mock()
    monkeypatch.setattr(solver, '_post', post)
    note = Mock()
    assert not continuation.resume(Mock(), CONFIG, kind='cloudflare',
                                   limits=continuation.Limits(time.monotonic()+2, solver.Budget(2)),
                                   observation=note)
    post.assert_not_called()
    assert 'unsupported' in note.call_args.args[0]


def test_expired_wait_cannot_start_a_paid_task(monkeypatch):
    post = Mock()
    monkeypatch.setattr(solver, '_post', post)
    assert not continuation.resume(Mock(), CONFIG, kind='awswaf',
                                   limits=continuation.Limits(time.monotonic()-1, solver.Budget(2)),
                                   observation=Mock())
    post.assert_not_called()


def test_engine_hands_local_failure_to_one_service_continuation(monkeypatch):
    d = PublisherBatchDownloader(CONFIG)
    page = SimpleNamespace(url='https://journal.example/check', evaluate=Mock(return_value=None))
    result = DownloadResult(doi='10.1000/test', status='failed')
    d._press_confirm_control = Mock(return_value=False)
    monkeypatch.setattr(interaction, 'needs_manual_verification', lambda _: True)
    monkeypatch.setattr(interaction, 'verification_widget', lambda *a, **k: 'hCaptcha')
    monkeypatch.setattr(interaction, 'challenge_kind', lambda _: 'hcaptcha')
    resume = Mock(return_value=True)
    monkeypatch.setattr(continuation, 'resume', resume)
    attempt = {}
    assert d._automatic_challenge_step(page, result, attempt, time.time()+60)
    assert not d._automatic_challenge_step(page, result, attempt, time.time()+60)
    resume.assert_called_once()
    assert resume.call_args.kwargs['limits'].budget is d._captcha_budget
    assert resume.call_args.kwargs['kind'] == 'hcaptcha'


def test_navigation_to_school_stops_service_checkpoint():
    d = PublisherBatchDownloader({**CONFIG, 'idp_domains': ['school.example']})
    page = SimpleNamespace(url='https://cas.school.example/login')
    d._check_user_decision = Mock()
    result = DownloadResult(doi='10.1000/test', status='failed')
    assert not d._continue_challenge(page, result, {}, time.time()+60, 'awswaf')
    assert d._captcha_budget.used == 0


def test_cancel_exception_is_not_converted_to_service_failure():
    class Cancelled(Exception):
        pass
    def check():
        raise Cancelled
    with pytest.raises(Cancelled):
        continuation.resume(Mock(), CONFIG, kind='hcaptcha',
                            limits=continuation.Limits(time.monotonic()+5, solver.Budget(2), check),
                            observation=Mock())


def test_delayed_check_resumes_after_service_budget_was_used(monkeypatch):
    from paper_search_school.browser.challenge.local import prompt
    d = PublisherBatchDownloader(CONFIG)
    d._check_user_decision = Mock(return_value=False)
    result = DownloadResult(doi='10.1000/test', status='failed')
    page = SimpleNamespace(url='https://journal.example/check')
    attempt = {'service_tried': {'hcaptcha'}}
    monkeypatch.setattr(prompt, 'confirm_checked', lambda _: True)
    forward = Mock(side_effect=['unavailable', 'pressed'])
    monkeypatch.setattr(prompt, 'press_forward', forward)
    for _ in range(3):
        assert d._forward_checked_challenge(page, result, attempt, time.time()+5)
    assert forward.call_count == 2
    assert attempt['forwarded']
    assert d._captcha_budget.used == 0


def test_manual_wait_still_forwards_a_delayed_widget_and_rechecks_access(monkeypatch):
    from paper_search_school.browser.challenge.local import prompt
    clock = [1000.0]
    submitted = []
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    d = PublisherBatchDownloader({})
    d._check_user_decision = Mock(return_value=False)
    d._automatic_challenge_step = Mock(return_value=False)
    d._snapshot = Mock()
    d._verification_attention = Mock()
    d._raise_on_publisher_access_blocked = Mock()
    d._challenge_shell = lambda _: not submitted
    d._is_challenge_page = lambda _: not submitted
    d._challenge_continues = lambda _: not submitted
    monkeypatch.setattr(prompt, 'confirm_checked', lambda _: clock[0] >= 1002)
    forward = Mock(side_effect=lambda *a, **k: submitted.append(True) or 'pressed')
    monkeypatch.setattr(prompt, 'press_forward', forward)
    page = Mock(url='https://journal.example/check', frames=[])
    page.wait_for_timeout.side_effect = lambda ms: clock.__setitem__(0, clock[0]+ms/1000)
    result = DownloadResult(doi='10.1000/test', status='failed')
    assert d._wait_for_challenge(page, result, deadline=1010)
    states = [e['state'] for e in result.events]
    assert 'challenge_manual_wait' in states
    assert 'challenge_resolved' in states
    forward.assert_called_once()

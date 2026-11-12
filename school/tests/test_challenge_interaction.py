"""Observed widgets, bounded attempts and the two verification entry points."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from patchright.sync_api import Error, TimeoutError

from paper_search_school.browser import challenge_interaction as interaction, watchdog
from paper_search_school.engine import batch_waits
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.entitlements import UserStoppedBatch

FRAME = "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/fixture"


def test_readiness_listener_stays_on_owned_pages_and_is_installed_once():
    existing, created, popup = Mock(), Mock(), Mock()
    context = Mock(pages=[existing])
    context.new_page.return_value = created
    interaction.prepare_context(context)
    interaction.prepare_context(context)
    assert context.new_page() is created
    on_page = context.on.call_args.args[1]
    on_page(created)  # events and direct creation may refer to the same page
    on_page(popup)
    for page in (existing, created, popup):
        page.add_init_script.assert_called_once()
    context.add_init_script.assert_not_called()  # ego's shared user context
    context.on.assert_called_once()


def widget(*, url=FRAME, count=1):
    frame = Mock(url=url)
    element = frame.frame_element.return_value
    element.is_visible.return_value = True
    element.get_attribute.return_value = "Widget containing a Cloudflare security challenge"
    element.bounding_box.return_value = {"x": 10, "y": 20, "width": 300, "height": 65}
    element.evaluate.return_value = True
    controls = frame.locator.return_value
    controls.count.return_value = count
    control = controls.first
    control.is_visible.return_value = control.is_enabled.return_value = True
    control.is_checked.return_value = False
    return SimpleNamespace(frames=[frame], evaluate=Mock(), context=SimpleNamespace()), frame, element, control


@pytest.mark.parametrize("url", [
    "https://challenges.cloudflare.com.evil.example/cdn-cgi/challenge-platform/h/g/turnstile/if/x",
    "https://journal.example/?next=" + FRAME,
    "http://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/x",
    "https://challenges.cloudflare.com/turnstile/v0/api.js",
    "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/puzzle",
])
def test_unrelated_frame_is_never_clicked(url):
    page, frame, _, _ = widget(url=url)
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=Mock()) == "absent"
    frame.frame_element.assert_not_called()


@pytest.mark.parametrize("url,visible,expected", [
    ("https://www.google.com/recaptcha/api2/anchor", True, True),
    ("https://www.recaptcha.net/recaptcha/enterprise/anchor", True, True),
    ("https://www.google.com/recaptcha/api2/anchor", False, False),
    ("https://www.google.com.evil.example/recaptcha/api2/anchor", True, False),
    ("https://journal.example/article?next=https://www.google.com/recaptcha/api2/anchor", True, False),
    (FRAME, True, False),
])
def test_only_a_visible_manual_verification_frame_requests_handoff(url, visible, expected):
    page, _, element, _ = widget(url=url)
    element.is_visible.return_value = visible
    assert interaction.needs_manual_verification(page) is expected
    element.click.assert_not_called()


def test_a_visible_checkbox_is_clicked_once_without_force():
    page, _, element, control = widget()
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=Mock()) == "clicked"
    control.click.assert_called_once()
    assert 0 < control.click.call_args.kwargs["timeout"] <= 750
    assert "force" not in control.click.call_args.kwargs
    element.click.assert_not_called()


@pytest.mark.parametrize("case", ["hidden_frame", "hidden_control", "checked", "disabled", "multiple"])
def test_non_actionable_widgets_are_left_alone(case):
    page, frame, element, control = widget(count=2 if case == "multiple" else 1)
    if case == "hidden_frame":
        element.is_visible.return_value = False
    if case == "hidden_control":
        control.is_visible.return_value = False
    if case == "checked":
        control.is_checked.return_value = True
    if case == "disabled":
        control.is_enabled.return_value = False
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=Mock()) != "clicked"
    control.click.assert_not_called()
    element.click.assert_not_called()


def test_closed_shadow_widget_uses_one_native_actionable_click():
    page, _, element, _ = widget(count=0)
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=Mock()) == "clicked"
    assert element.click.call_args.kwargs["position"] == {"x": 28, "y": 32.5}
    assert "force" not in element.click.call_args.kwargs


def test_closed_widget_waits_for_interactive_readiness_before_spending_its_click():
    page, _, element, _ = widget(count=0)
    element.evaluate.return_value = False
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=Mock()) == "absent"
    element.click.assert_not_called()


@pytest.mark.parametrize("width,height,title", [
    (300, 400, "Cloudflare challenge"), (150, 140, "Cloudflare challenge"),
    (300, 65, "Advertisement"), (0, 0, "Cloudflare challenge"),
])
def test_unknown_or_expanded_frames_are_not_coordinate_clicked(width, height, title):
    page, _, element, _ = widget(count=0)
    element.bounding_box.return_value = {"width": width, "height": height}
    element.get_attribute.return_value = title
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=Mock()) == "unavailable"
    element.click.assert_not_called()


def test_a_covered_checkbox_returns_control_for_manual_handling():
    page, _, _, control = widget()
    control.click.side_effect = TimeoutError("another element intercepts pointer events")
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=Mock()) == "unavailable"
    control.click.assert_called_once()


@pytest.mark.parametrize("error", [Error("Target page has been closed"), watchdog.BrowserUnresponsive("stalled")])
def test_browser_failures_are_not_disguised_as_missing_widgets(error):
    page, _, _, control = widget()
    control.click.side_effect = error
    with pytest.raises(type(error)):
        interaction.click_checkbox(page, timeout_ms=750, checkpoint=Mock())


def test_stop_between_observation_and_click_prevents_the_click():
    page, _, _, control = widget()
    with pytest.raises(UserStoppedBatch):
        interaction.click_checkbox(page, timeout_ms=750,
                                   checkpoint=Mock(side_effect=[None, UserStoppedBatch("stop")]))
    control.click.assert_not_called()


@pytest.fixture
def wait_case(monkeypatch):
    clock = [1000.0]
    page = Mock(url="https://journal.example/article")
    page.frames = []
    page.context.pages = [page]
    page.is_closed.return_value = False
    page.wait_for_timeout.side_effect = lambda ms: clock.__setitem__(0, clock[0] + ms / 1000)
    monkeypatch.setattr(batch_waits.time, "time", lambda: clock[0])
    from paper_search_school.engine import page_activity
    monkeypatch.setattr(page_activity, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    d = PublisherBatchDownloader({}, require_interactive_browser=True)
    d._check_user_decision = Mock()
    d._raise_on_publisher_access_blocked = Mock()
    d._challenge_shell = Mock(return_value=True)
    d._is_challenge_page = Mock(return_value=True)
    d._pdf_step_needs_login = Mock(return_value=False)
    d._is_chromium = Mock(return_value=True)
    d._snapshot = Mock()
    result = DownloadResult(doi="10.1234/fixture", status="failed", state="article_loaded")
    from paper_search_school import progress_reporter
    attention = Mock()
    monkeypatch.setattr(progress_reporter, "set_attention", attention)
    monkeypatch.setattr(progress_reporter, "clear_attention", Mock())
    return SimpleNamespace(d=d, result=result, page=page, clock=clock, attention=attention)


def test_automatic_pass_does_not_ask_the_user_or_pause_automation(wait_case, monkeypatch):
    c = wait_case
    c.d._challenge_shell = lambda page: c.clock[0] < 1001
    c.d._is_challenge_page = c.d._challenge_shell
    click = Mock()
    pause = Mock()
    monkeypatch.setattr(interaction, "click_checkbox", click)
    monkeypatch.setattr(watchdog, "pause_operation", pause)
    from paper_search_school import progress_reporter
    update = Mock()
    monkeypatch.setattr(progress_reporter, "update", update)
    assert c.d._wait_for_challenge(c.page, c.result)
    assert c.result.state == "article_loaded"
    c.attention.assert_not_called()
    pause.assert_not_called()
    click.assert_not_called()
    assert not any("人工" in call.kwargs.get("phase", "") for call in update.call_args_list)


@pytest.mark.parametrize("pass_after", [55, 80])
@pytest.mark.parametrize("entry", ["article", "pdf"])
def test_known_manual_widget_preserves_automation_budget_with_delayed_reminder(
    wait_case, monkeypatch, pass_after, entry,
):
    c = wait_case
    c.d._challenge_shell = lambda page: c.clock[0] < 1000 + pass_after
    c.d._is_challenge_page = c.d._challenge_shell
    monkeypatch.setattr(interaction, "needs_manual_verification", lambda page: True)
    click = Mock(return_value="absent")
    monkeypatch.setattr(interaction, "click_checkbox", click)
    monkeypatch.setattr(watchdog, "time", SimpleNamespace(
        monotonic=lambda: c.clock[0], sleep=watchdog.time.sleep))
    from paper_search_school import progress_reporter
    monkeypatch.setattr(progress_reporter, "has_attention", lambda **kwargs: False)
    notified_at = []
    c.attention.side_effect = lambda *args, **kwargs: notified_at.append(c.clock[0])
    with watchdog.operation(60, "supplements"):
        if entry == "article":
            passed = c.d._wait_for_challenge(c.page, c.result)
        else:
            passed = c.d._resolve_suspect_block(c.page, c.result, {
                "suspect_block": "403 https://journal.example/pdf", "bytes": None, "block_reason": None})
        assert passed is (pass_after < 60)
        assert c.clock[0] == 1000 + min(pass_after, 60)
        assert notified_at == [1030]  # manual classification does not prompt early
        assert watchdog.operation_remaining() >= 59  # waiting is not browser work
    click.assert_not_called()


@pytest.mark.parametrize("entry", ["article", "pdf"])
def test_click_is_not_success_and_manual_handoff_keeps_the_original_deadline(wait_case, monkeypatch, entry):
    c = wait_case
    c.d.config["browser_page_wait_timeout"] = 10
    clicked = Mock(return_value="clicked")
    monkeypatch.setattr(interaction, "click_checkbox", clicked)
    if entry == "article":
        assert not c.d._wait_for_challenge(c.page, c.result)
        assert c.result.state == "challenge_or_viewer_timeout"
    else:
        captured = {"suspect_block": "403 https://journal.example/pdf", "bytes": None, "block_reason": None}
        assert not c.d._resolve_suspect_block(c.page, c.result, captured)
        assert captured["block_reason"] == "challenge_or_viewer_timeout"
    assert clicked.call_count == 3  # dispatched at 2, 5, 8 s; observing never extends the bound
    c.attention.assert_not_called()
    assert c.clock[0] == 1010
    assert not any(event["state"] == "challenge_resolved" for event in c.result.events)


def test_click_that_clears_challenge_continues_without_manual_handoff(wait_case, monkeypatch):
    c = wait_case
    def clicked(*args, **kwargs):
        c.d._challenge_shell.return_value = c.d._is_challenge_page.return_value = False
        return "clicked"
    monkeypatch.setattr(interaction, "click_checkbox", Mock(side_effect=clicked))
    assert c.d._wait_for_challenge(c.page, c.result)
    assert c.result.state == "article_loaded"
    assert c.clock[0] == 1003
    c.attention.assert_not_called()


@pytest.mark.parametrize("entry", ["article", "pdf"])
def test_three_attempt_limit_leaves_observation_time_after_each_action(wait_case, monkeypatch, entry):
    c = wait_case
    c.d.config["browser_page_wait_timeout"] = 30
    starts, ends = [], []
    def click(*args, **kwargs):
        starts.append(c.clock[0])
        c.clock[0] += 0.5  # interval starts after the native action finishes
        ends.append(c.clock[0])
        return "clicked"
    monkeypatch.setattr(interaction, "click_checkbox", click)
    if entry == "article":
        assert not c.d._wait_for_challenge(c.page, c.result)
    else:
        assert not c.d._resolve_suspect_block(c.page, c.result, {
            "suspect_block": "403 https://journal.example/pdf", "bytes": None, "block_reason": None})
    assert len(starts) == 3
    assert starts[0] >= 1002
    assert all(start - end >= 3 for start, end in zip(starts[1:], ends))
    assert c.clock[0] == 1030
    c.attention.assert_called_once()
    assert c.attention.call_args.kwargs["deadline"] == 1030
    assert not any(event["state"] == "challenge_resolved" for event in c.result.events)


@pytest.mark.parametrize("entry", ["article", "pdf"])
@pytest.mark.parametrize("pass_on", [2, 3])
def test_retry_that_clears_verification_stops_clicking(wait_case, monkeypatch, entry, pass_on):
    c = wait_case
    captured = {"suspect_block": "403 https://journal.example/pdf", "bytes": None, "block_reason": None}
    starts = []
    def click(*args, **kwargs):
        starts.append(c.clock[0])
        if len(starts) == pass_on:
            c.d._challenge_shell.return_value = c.d._is_challenge_page.return_value = False
            captured["bytes"] = b"%PDF-fixture"
        return "clicked"
    monkeypatch.setattr(interaction, "click_checkbox", click)
    if entry == "article":
        assert c.d._wait_for_challenge(c.page, c.result)
    else:
        assert c.d._resolve_suspect_block(c.page, c.result, captured)
    assert len(starts) == pass_on
    assert c.clock[0] == starts[-1] + 1
    c.attention.assert_not_called()


@pytest.mark.parametrize("entry", ["article", "pdf"])
@pytest.mark.parametrize("ready_after", [14, 25, 50])
def test_late_widget_is_handled_within_the_existing_wait(wait_case, monkeypatch, entry, ready_after):
    c = wait_case
    c.d.config["browser_page_wait_timeout"] = 60
    captured = {"suspect_block": "403 https://journal.example/pdf", "bytes": None, "block_reason": None}
    def click(*args, **kwargs):
        if c.clock[0] < 1000 + ready_after:
            return "absent"
        c.d._challenge_shell.return_value = c.d._is_challenge_page.return_value = False
        captured["bytes"] = b"%PDF-fixture"
        return "clicked"
    monkeypatch.setattr(interaction, "click_checkbox", Mock(side_effect=click))
    if entry == "article":
        assert c.d._wait_for_challenge(c.page, c.result)
    else:
        assert c.d._resolve_suspect_block(c.page, c.result, captured)
    assert c.clock[0] == 1001 + ready_after
    c.attention.assert_not_called()  # still inside the bounded automatic wait


@pytest.mark.parametrize("entry", ["article", "pdf"])
def test_background_idle_check_waits_for_automatic_handoff(wait_case, monkeypatch, entry):
    c = wait_case
    from paper_search_school import progress_reporter
    monkeypatch.setattr(progress_reporter, "has_attention", lambda **kwargs: False)
    monkeypatch.setattr(interaction, "needs_manual_verification", lambda page: False)
    notified_at = []
    c.attention.side_effect = lambda *args, **kwargs: notified_at.append(c.clock[0])
    def click(*args, **kwargs):
        # Model the independent watcher checking while a browser RPC is active.
        c.result._page_activity.check()
        assert not notified_at
        return "absent"
    monkeypatch.setattr(interaction, "click_checkbox", click)
    if entry == "article":
        assert not c.d._wait_for_challenge(c.page, c.result)
    else:
        assert not c.d._resolve_suspect_block(c.page, c.result, {
            "suspect_block": "403 https://journal.example/pdf", "bytes": None, "block_reason": None})
    assert notified_at == []  # absence of a widget does not prove a user action
    assert c.clock[0] == 1060


def test_expired_deadline_never_clicks_or_extends_the_wait(wait_case, monkeypatch):
    c = wait_case
    click = Mock()
    monkeypatch.setattr(interaction, "click_checkbox", click)
    assert not c.d._wait_for_challenge(c.page, c.result, deadline=999)
    assert c.clock[0] == 1000
    click.assert_not_called()


def test_native_mouse_motion_gets_time_but_cannot_extend_the_page_deadline(wait_case, monkeypatch):
    c = wait_case
    attempt = {"started": 998.0, "attempts": 0, "retry_at": 1000.0}
    click = Mock(return_value="absent")
    monkeypatch.setattr(interaction, "click_checkbox", click)
    assert c.d._automatic_challenge_step(c.page, c.result, attempt, deadline=1010)
    assert click.call_args.kwargs["timeout_ms"] == 2500
    c.clock[0] += 1
    assert c.d._automatic_challenge_step(c.page, c.result, attempt, deadline=1002.4)
    assert 0 < click.call_args.kwargs["timeout_ms"] <= 1400


@pytest.mark.parametrize("entry", ["article", "pdf"])
def test_cancellation_during_automatic_interaction_reaches_caller(wait_case, monkeypatch, entry):
    c = wait_case
    monkeypatch.setattr(interaction, "click_checkbox", Mock(side_effect=UserStoppedBatch("stop")))
    with pytest.raises(UserStoppedBatch):
        if entry == "article":
            c.d._wait_for_challenge(c.page, c.result)
        else:
            c.d._resolve_suspect_block(c.page, c.result, {
                "suspect_block": "403 https://journal.example/pdf", "bytes": None, "block_reason": None})
    c.attention.assert_not_called()

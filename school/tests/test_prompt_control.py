"""One bounded press on another provider's own confirmation control."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from paper_search_school.browser.challenge.local import prompt as prompt_control

RECAPTCHA = "https://www.google.com/recaptcha/api2/anchor?k=fixture"
HCAPTCHA = "https://newassets.hcaptcha.com/captcha/v1/fixture"


def provider_frame(url=RECAPTCHA, *, count=1, visible=True, enabled=True, aria="false"):
    frame = Mock(url=url)
    controls = frame.locator.return_value
    controls.count.return_value = count
    control = controls.first
    control.is_visible.return_value = visible
    control.is_enabled.return_value = enabled
    control.get_attribute.return_value = aria
    control.bounding_box.return_value = {"x": 10, "y": 20, "width": 30, "height": 30}
    return frame, control


def test_pressing_another_provider_is_on_unless_turned_off(monkeypatch):
    monkeypatch.delenv("PAPER_SEARCH_AUTO_CONFIRM", raising=False)
    assert prompt_control.enabled() is True
    monkeypatch.setenv("PAPER_SEARCH_AUTO_CONFIRM", "0")
    assert prompt_control.enabled() is False
    monkeypatch.setenv("PAPER_SEARCH_AUTO_CONFIRM", "yes")
    assert prompt_control.enabled() is True


@pytest.mark.parametrize("url", ["https://journal.example/article", "https://google.com.evil.example/recaptcha/api2/anchor"])
def test_an_unrelated_frame_is_never_pressed(url):
    frame, control = provider_frame(url)
    page = SimpleNamespace(frames=[frame], locator=Mock(return_value=Mock(all=Mock(return_value=[]))))
    assert prompt_control.click_confirm_control(page, timeout_ms=500) == "absent"
    control.click.assert_not_called()


def test_the_recaptcha_box_is_pressed_once_without_force():
    frame, control = provider_frame()
    page = SimpleNamespace(frames=[frame], locator=Mock(return_value=Mock(all=Mock(return_value=[]))))
    assert prompt_control.click_confirm_control(page, timeout_ms=750) == "clicked"
    control.click.assert_called_once()
    assert "force" not in control.click.call_args.kwargs


def test_the_hcaptcha_box_is_pressed_once_without_force():
    frame, control = provider_frame(HCAPTCHA)
    page = SimpleNamespace(frames=[frame], locator=Mock(return_value=Mock(all=Mock(return_value=[]))))
    assert prompt_control.click_confirm_control(page, timeout_ms=750) == "clicked"
    control.click.assert_called_once()
    assert "force" not in control.click.call_args.kwargs


def test_an_already_checked_box_is_left_alone():
    frame, control = provider_frame(aria="true")
    page = SimpleNamespace(frames=[frame], locator=Mock(return_value=Mock(all=Mock(return_value=[]))))
    assert prompt_control.click_confirm_control(page, timeout_ms=500) == "unavailable"
    control.click.assert_not_called()


def test_a_hidden_or_missing_control_is_not_pressed():
    frame, control = provider_frame(visible=False)
    page = SimpleNamespace(frames=[frame], locator=Mock(return_value=Mock(all=Mock(return_value=[]))))
    assert prompt_control.click_confirm_control(page, timeout_ms=500) == "unavailable"
    control.click.assert_not_called()

    frame, control = provider_frame(count=0)
    page = SimpleNamespace(frames=[frame], locator=Mock(return_value=Mock(all=Mock(return_value=[]))))
    assert prompt_control.click_confirm_control(page, timeout_ms=500) == "absent"
    control.click.assert_not_called()


def _page_with_forward(text="Take me to my Content", *, visible=True, enabled=True):
    button = Mock()
    button.is_visible.return_value = visible
    button.is_enabled.return_value = enabled
    button.bounding_box.return_value = {"x": 10, "y": 10, "width": 200, "height": 40}
    locator = Mock()
    locator.count.return_value = 1
    locator.first = button
    empty = Mock()
    empty.count.return_value = 0
    page = Mock()
    page.get_by_role.side_effect = lambda kind="button", *, name=None, exact=True: locator if name == text else empty
    page.get_by_text.side_effect = lambda needle, exact=True: empty
    return page, button


def test_the_forward_button_is_pressed_once_when_actionable():
    page, button = _page_with_forward()
    assert prompt_control.press_forward(page, timeout_ms=800) == "pressed"
    button.click.assert_called_once()
    assert "force" not in button.click.call_args.kwargs


def test_a_hidden_or_disabled_forward_button_is_not_pressed():
    for kwargs in ({"visible": False}, {"enabled": False}):
        page, button = _page_with_forward(**kwargs)
        assert prompt_control.press_forward(page, timeout_ms=800) == "unavailable"
        button.click.assert_not_called()


def test_no_forward_button_leaves_the_wait_alone():
    empty = Mock()
    empty.count.return_value = 0
    page = Mock()
    page.get_by_role.return_value = empty
    page.get_by_text.return_value = empty
    assert prompt_control.press_forward(page, timeout_ms=800) == "absent"


def test_a_checked_box_is_read_from_aria_checked_only():
    frame, control = provider_frame(aria="true")
    page = SimpleNamespace(frames=[frame])
    assert prompt_control.confirm_checked(page) is True
    assert control.click.call_count == 0

    frame, control = provider_frame(aria="false")
    page = SimpleNamespace(frames=[frame])
    assert prompt_control.confirm_checked(page) is False


def test_an_expired_interstitial_is_recognised():
    empty = Mock()
    empty.count.return_value = 0
    expired = Mock()
    expired.count.return_value = 1
    page = Mock()
    page.get_by_text.side_effect = lambda needle, exact=True: expired if "expired" in needle else empty
    assert prompt_control.expired(page) is True


def _pressable_downloader(*, widget):
    from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
    from paper_search_school.publishers.profiles import ELSEVIER_PROFILE

    downloader = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
    downloader._verification_widget_page = Mock(return_value=widget)
    # The page stays a verification page unless a test lets it through.
    downloader._challenge_shell = Mock(return_value=True)
    downloader._is_challenge_page = Mock(return_value=True)
    downloader._check_user_decision = Mock(return_value=False)
    downloader._event = Mock()
    downloader._await_check_then_forward = Mock()
    return downloader, DownloadResult(doi="10.1000/test", status="failed")


def test_a_control_that_is_not_rendered_yet_is_looked_for_again(monkeypatch):
    """Its widget shows but its button arrives late, so the first look is not final."""
    import time

    monkeypatch.setattr(prompt_control, "AWAIT_LIMIT_SEC", 0.35)
    monkeypatch.setattr(prompt_control, "AWAIT_STEP_SEC", 0.1)
    downloader, result = _pressable_downloader(widget=True)
    outcomes = ["absent", "clicked"]
    monkeypatch.setattr(prompt_control, "click_confirm_control",
                        lambda *args, **kwargs: outcomes.pop(0) if outcomes else "clicked")
    page = Mock(frames=[])
    assert downloader._press_confirm_control(page, result, {}, time.time() + 60) is True
    assert outcomes == []
    page.wait_for_timeout.assert_called_once_with(100)


def test_a_page_let_through_while_its_control_is_looked_for_is_left_to_the_wait(monkeypatch):
    """A verification that passed on its own while the control was looked for again: the wait
    sees the page and ends quietly, instead of asking the user to complete it (Windows, real
    Chrome, 2026-11-25: a page let through in 0.2 s was looked at for 3 s, then the user asked)."""
    import time

    monkeypatch.setattr(prompt_control, "AWAIT_LIMIT_SEC", 5.0)
    monkeypatch.setattr(prompt_control, "AWAIT_STEP_SEC", 0.01)
    downloader, result = _pressable_downloader(widget=True)
    looks = []
    monkeypatch.setattr(prompt_control, "click_confirm_control", lambda *args, **kwargs: looks.append(1) or "absent")
    downloader._challenge_shell = Mock(return_value=False)
    downloader._is_challenge_page = Mock(side_effect=lambda _page: len(looks) < 2)
    assert downloader._press_confirm_control(Mock(frames=[]), result, {}, time.time() + 60) is True
    assert len(looks) == 2
    assert any("page moved on" in str(call) for call in downloader._event.call_args_list)


def test_the_control_is_looked_for_again_only_until_the_user_is_to_be_asked(monkeypatch):
    """Looking again stops at the attempt's hand-over time, so the reminder comes when it is set to."""
    import time

    monkeypatch.setattr(prompt_control, "AWAIT_LIMIT_SEC", 5.0)
    monkeypatch.setattr(prompt_control, "AWAIT_STEP_SEC", 0.05)
    downloader, result = _pressable_downloader(widget=True)
    monkeypatch.setattr(prompt_control, "click_confirm_control", lambda *args, **kwargs: "absent")
    started = time.time()
    assert downloader._press_confirm_control(Mock(frames=[]), result, {"handoff_at": started + 0.3},
                                             started + 60) is False
    assert time.time() - started < 1.0


def test_without_its_widget_the_page_is_never_waited_on(monkeypatch):
    """No widget means no control is coming: handing the page out stays immediate."""
    import time

    monkeypatch.setattr(prompt_control, "AWAIT_LIMIT_SEC", 5.0)
    downloader, result = _pressable_downloader(widget=False)
    looks = []
    monkeypatch.setattr(prompt_control, "click_confirm_control",
                        lambda *args, **kwargs: looks.append(1) or "absent")
    page = Mock(frames=[])
    assert downloader._press_confirm_control(page, result, {}, time.time() + 60) is False
    assert len(looks) == 1
    page.wait_for_timeout.assert_not_called()


def test_the_recaptcha_press_is_still_followed(monkeypatch):
    import time

    from paper_search_school.browser.challenge.local import interaction as challenge_interaction

    downloader, result = _pressable_downloader(widget=True)
    monkeypatch.setattr(prompt_control, "click_confirm_control", lambda *args, **kwargs: "clicked")
    monkeypatch.setattr(challenge_interaction, "challenge_kind", lambda _page: "recaptcha")
    assert downloader._press_confirm_control(Mock(frames=[]), result, {}, time.time() + 60) is True
    downloader._await_check_then_forward.assert_called_once()


def test_an_aws_waf_page_is_handed_out_without_pressing(monkeypatch):
    """Its Begin button always opens a picture puzzle, so nothing here can pass it."""
    import time

    from paper_search_school.browser.challenge.local import interaction as challenge_interaction

    downloader, result = _pressable_downloader(widget=True)
    downloader._press_confirm_control = Mock()
    monkeypatch.setattr(challenge_interaction, "needs_manual_verification", lambda _page: True)
    monkeypatch.setattr(challenge_interaction, "verification_widget",
                        lambda _page, **_kwargs: "AWS WAF")
    monkeypatch.setattr(challenge_interaction, "challenge_kind", lambda _page: "awswaf")
    page = Mock(frames=[])
    assert downloader._automatic_challenge_step(page, result, {}, time.time() + 60) is False
    downloader._press_confirm_control.assert_not_called()


def widget_page(control):
    page = Mock()
    frame = Mock()
    frame.locator.return_value = frame
    frame.first = control
    frame.count.return_value = 1
    frame.is_visible.return_value = True
    frame.is_enabled.return_value = True
    frame.get_attribute.return_value = "false"
    frame.bounding_box.return_value = {"x": 10, "y": 20, "width": 30, "height": 30}
    page.frame_locator.return_value = frame
    page.frames = []
    return page


def test_friendly_captchas_box_is_pressed_in_its_own_widget():
    """Its box lives in a frame of the widget, which the frame list does not carry."""
    control = Mock()
    control.count.return_value = 1
    control.is_visible.return_value = True
    control.is_enabled.return_value = True
    control.get_attribute.return_value = "false"
    control.bounding_box.return_value = {"x": 10, "y": 20, "width": 30, "height": 30}
    page = widget_page(control)
    assert prompt_control.click_confirm_control(page, timeout_ms=2000) == "clicked"
    control.click.assert_called_once()

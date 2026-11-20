"""One bounded press on another provider's own confirmation control."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from paper_search_school.browser.challenge import prompt as prompt_control

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


def test_aws_waf_button_is_pressed_when_its_script_is_on_the_page():
    script = Mock()
    script.get_attribute.return_value = "https://abc123.captcha.awswaf.com/js/fixture.js"
    button = Mock()
    button.is_visible.return_value = button.is_enabled.return_value = True
    button.bounding_box.return_value = {"x": 5, "y": 6, "width": 120, "height": 30}
    script_locator = Mock()
    script_locator.count.return_value = 0
    script_locator.all.return_value = [script]
    button_locator = Mock()
    button_locator.count.return_value = 1
    button_locator.first = button
    page = SimpleNamespace(frames=[], locator=Mock(
        side_effect=lambda selector: script_locator if selector == "script[src]" else button_locator))
    assert prompt_control.click_confirm_control(page, timeout_ms=750) == "clicked"
    button.click.assert_called_once()

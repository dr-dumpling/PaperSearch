"""Other providers' verification widgets: recognised, never operated (the user, 2026-11-11)."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from paper_search_carsi.browser import challenge_interaction as interaction


def frame(url, visible=True):
    found = Mock(url=url)
    found.frame_element.return_value.is_visible.return_value = visible
    return found


def page(found="", frames=()):
    return SimpleNamespace(evaluate=Mock(return_value=found), frames=list(frames))


@pytest.mark.parametrize("url,name", [
    ("https://www.google.com/recaptcha/api2/anchor?k=x", "reCAPTCHA"),
    ("https://www.recaptcha.net/recaptcha/enterprise/bframe?k=x", "reCAPTCHA"),
    ("https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html#frame=checkbox", "hCaptcha"),
    ("https://geo.captcha-delivery.com/captcha/?initialCid=x", "DataDome"),
    ("https://client-api.arkoselabs.com/fc/gc/?token=x", "Arkose"),
    ("https://turing.captcha.qcloud.com/cap_union_new_show", "Tencent"),
])
def test_a_visible_frame_names_its_provider(url, name):
    assert interaction.verification_widget(page(frames=[frame(url)])) == name


@pytest.mark.parametrize("url", [
    "https://www.google.com/recaptcha/api2/anchor?k=x&size=invisible",  # v3's badge on ordinary pages
    "https://www.google.com.evil.example/recaptcha/api2/anchor",
    "https://journal.example/article?next=https://newassets.hcaptcha.com/captcha/v1/x",
    "https://journal.example/captcha-help",
])
def test_badges_lookalikes_and_ordinary_frames_are_not_widgets(url):
    assert interaction.verification_widget(page(frames=[frame(url)])) == ""


def test_a_hidden_frame_an_article_and_a_long_page_are_not_verification_pages():
    recaptcha = "https://www.google.com/recaptcha/api2/anchor?k=x"
    assert interaction.verification_widget(page(frames=[frame(recaptcha, visible=False)])) == ""
    # The page script says "#page" for an article (citation metadata) or a long page.
    assert interaction.verification_widget(page("#page", frames=[frame(recaptcha)])) == ""
    assert interaction.verification_widget(page("GeeTest")) == "GeeTest"


def test_turnstile_is_recognised_but_left_to_the_programs_own_click():
    turnstile = frame("https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/x")
    assert interaction.verification_widget(page(frames=[turnstile])) == "Turnstile"
    assert interaction.verification_widget(page(frames=[turnstile]), manual_only=True) == ""


def test_a_read_that_never_answers_is_no_widget():
    from paper_search_carsi.browser import watchdog
    stuck = SimpleNamespace(evaluate=Mock(side_effect=watchdog.CallAbandoned("Page.evaluate")), frames=[])
    assert interaction.verification_widget(stuck) == ""

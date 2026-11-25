"""The pointer approach, the retry offsets and the observed event record."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from paper_search_school.browser.challenge.local import interaction, pointer as human_pointer

FRAME = "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/fixture"


class RecordedMouse:
    """A pointer that records where it was sent."""

    def __init__(self):
        self.moves = []

    def move(self, x, y, steps=1):
        self.moves.append((x, y))


def test_a_page_without_a_pointer_is_left_alone():
    assert human_pointer.approach(SimpleNamespace(), {"x": 10, "y": 20, "width": 300, "height": 65}) is False


@pytest.mark.parametrize("rect", [
    {"width": 300, "height": 65},
    {"x": 10, "y": 20, "width": 0, "height": 65},
    {"x": 10, "y": 20, "width": 300, "height": 0},
    {"x": "none", "y": 20, "width": 300, "height": 65},
])
def test_a_box_without_usable_geometry_moves_nothing(rect):
    mouse = RecordedMouse()
    assert human_pointer.approach(SimpleNamespace(mouse=mouse), rect) is False
    assert mouse.moves == []


def test_the_path_ends_on_the_press_point_itself():
    mouse = RecordedMouse()
    page = SimpleNamespace(mouse=mouse)
    assert human_pointer.approach(page, {"x": 100, "y": 50, "width": 300, "height": 65},
                                  point={"x": 28, "y": 32.5}, limit_sec=0.25) is True
    assert len(mouse.moves) >= 5  # a path, not one jump
    assert mouse.moves[-1] == (128.0, 82.5)


def test_a_second_press_on_the_same_box_starts_from_where_the_hand_is():
    mouse = RecordedMouse()
    page = SimpleNamespace(mouse=mouse)
    box = {"x": 100, "y": 50, "width": 300, "height": 65}
    human_pointer.approach(page, box, point={"x": 28, "y": 32.5}, limit_sec=0.25)
    first = len(mouse.moves)
    human_pointer.approach(page, box, point={"x": 28, "y": 32.5}, limit_sec=0.25)
    second = mouse.moves[first]
    assert abs(second[0] - 128.0) <= 4 and abs(second[1] - 82.5) <= 4


def test_the_approach_never_takes_more_than_its_budget(monkeypatch):
    monkeypatch.delenv("PAPER_SEARCH_POINTER_PATH", raising=False)
    assert human_pointer.budget_for(2500) <= human_pointer.APPROACH_LIMIT_SEC
    assert human_pointer.budget_for(1) >= human_pointer.MIN_LIMIT_SEC
    assert human_pointer.budget_for(750) < human_pointer.budget_for(2500)


def test_the_path_can_be_turned_off_or_shortened(monkeypatch):
    monkeypatch.delenv("PAPER_SEARCH_POINTER_PATH", raising=False)
    assert human_pointer.budget_for(2500) == human_pointer.APPROACH_LIMIT_SEC
    monkeypatch.setenv("PAPER_SEARCH_POINTER_PATH", "off")
    assert human_pointer.budget_for(2500) == 0.0
    monkeypatch.setenv("PAPER_SEARCH_POINTER_PATH", "fast")
    assert human_pointer.budget_for(2500) == human_pointer.FAST_LIMIT_SEC


def test_a_zero_budget_moves_nothing():
    mouse = RecordedMouse()
    page = SimpleNamespace(mouse=mouse)
    assert human_pointer.approach(page, {"x": 1, "y": 2, "width": 30, "height": 30}, limit_sec=0) is False
    assert mouse.moves == []


def widget(*, count=1):
    frame = Mock(url=FRAME)
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
    return SimpleNamespace(frames=[frame], evaluate=Mock(), context=SimpleNamespace()), element, control


@pytest.mark.parametrize("attempt", [1, 2, 3])
def test_a_repeated_press_lands_a_little_off_the_first_pixel(attempt):
    page, element, _ = widget(count=0)
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=Mock(), attempt=attempt) == "clicked"
    point = element.click.call_args.kwargs["position"]
    assert point != {"x": 28, "y": 32.5}
    assert abs(point["x"] - 28) <= 2 and abs(point["y"] - 32.5) <= 2


def test_the_first_press_keeps_the_standard_box_position():
    page, element, _ = widget(count=0)
    assert interaction.click_checkbox(page, timeout_ms=750, checkpoint=Mock()) == "clicked"
    assert element.click.call_args.kwargs["position"] == {"x": 28, "y": 32.5}


def test_observed_events_are_returned_as_reported():
    page = SimpleNamespace(evaluate=Mock(return_value=[
        {"event": "interactiveBegin", "at": 1}, {"event": "complete", "at": 2}, "not an event"]))
    assert interaction.interaction_events(page) == [
        {"event": "interactiveBegin", "at": 1}, {"event": "complete", "at": 2}]


def test_an_unobserved_page_reports_no_events():
    page = SimpleNamespace(evaluate=Mock(return_value=None))
    assert interaction.interaction_events(page) == []

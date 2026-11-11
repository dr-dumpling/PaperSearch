"""A verification page that navigates while it is read is not a puzzle."""
from unittest.mock import Mock

import pytest
from patchright._impl._errors import Error

from paper_search_carsi.browser import challenge_interaction


def test_a_page_that_navigated_while_read_is_not_an_image_puzzle():
    page = Mock()
    page.evaluate.side_effect = Error("Page.evaluate: Execution context was destroyed, "
                                      "most likely because of a navigation.")
    assert challenge_interaction.is_image_verification(page) is False


def test_other_browser_errors_still_reach_the_caller():
    page = Mock()
    page.evaluate.side_effect = Error("Target page, context or browser has been closed")
    with pytest.raises(Error):
        challenge_interaction.is_image_verification(page)


def test_a_patchright_navigation_error_is_recognised_too():
    errors = pytest.importorskip("patchright._impl._errors")
    page = Mock()
    page.evaluate.side_effect = errors.Error("Execution context was destroyed, most likely because of a navigation")
    assert challenge_interaction.is_image_verification(page) is False


def test_a_read_still_waiting_after_its_limit_is_not_an_image_puzzle():
    # BMJ on Windows, 2026-11-11: after the checkbox one read waited 48 s for the next page.
    from paper_search_carsi.browser import watchdog
    page = Mock()
    page.evaluate.side_effect = watchdog.CallAbandoned("Page.evaluate")
    assert challenge_interaction.is_image_verification(page) is False
    frame = Mock(url="https://www.google.com/recaptcha/api2/anchor")
    frame.frame_element.return_value.is_visible.side_effect = watchdog.CallAbandoned("ElementHandle.is_visible")
    page.frames = [frame]
    assert challenge_interaction.has_visible_recaptcha(page) is False

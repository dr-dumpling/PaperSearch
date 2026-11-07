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

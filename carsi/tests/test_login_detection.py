import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_search_carsi.browser import login as browser_login


class LoginDetectionTests(unittest.TestCase):
    def test_manual_navigation_is_processed_before_detection(self):
        page = Mock()
        page.url = "https://www.sciencedirect.com/user/institution/login"

        def process_browser_events(milliseconds):
            page.url = "https://www.sciencedirect.com/"

        page.wait_for_timeout.side_effect = process_browser_events
        context = Mock()
        context.new_page.return_value = page
        context.cookies.return_value = []
        browser = Mock()
        browser.new_context.return_value = context
        with tempfile.TemporaryDirectory() as cache_dir:
            with (
                patch.object(browser_login, "_HAS_CLOAKBROWSER", True),
                patch.object(browser_login, "launch", return_value=browser),
                patch.object(browser_login.time, "sleep"),
                patch.object(browser_login, "_save_cookies_json") as save_json,
                patch.object(browser_login, "_save_cookies_netscape"),
            ):
                result = browser_login.open_login_browser(
                    page.url,
                    {},
                    cookie_file=Path(cache_dir) / "session.json",
                    detect_login=lambda context, page: page.url == "https://www.sciencedirect.com/",
                    max_wait=3,
                    auto_import=False,
                )
                self.assertTrue(result)
                save_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()

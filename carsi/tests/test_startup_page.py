"""A persistent profile's startup window is used for the first page, not left blank beside it."""
import unittest
from unittest.mock import Mock

from paper_search_carsi.browser.backend import _reuse_startup_page


def page(url="about:blank", closed=False):
    p = Mock(); p.url = url; p.is_closed.return_value = closed
    return p


class StartupPageTests(unittest.TestCase):
    def test_first_new_page_is_the_blank_startup_window_then_real_new_pages(self):
        startup, fresh = page(), page()
        context = Mock(); context.pages = [startup]; context.new_page.return_value = fresh
        opener = context.new_page
        _reuse_startup_page(context)
        self.assertIs(context.new_page(), startup)
        self.assertIs(context.new_page(), fresh)
        opener.assert_called_once_with()

    def test_used_or_closed_startup_pages_are_not_reused(self):
        for startup in (page("https://example.org/"), page(closed=True)):
            fresh = page()
            context = Mock(); context.pages = [startup]; context.new_page.return_value = fresh
            _reuse_startup_page(context)
            startup.url = startup.url  # navigated or closed before the first request
            self.assertIs(context.new_page(), fresh)

    def test_page_navigated_after_launch_is_not_handed_out(self):
        startup, fresh = page(), page()
        context = Mock(); context.pages = [startup]; context.new_page.return_value = fresh
        _reuse_startup_page(context)
        startup.url = "https://restored.example/"
        self.assertIs(context.new_page(), fresh)


class FakeContext:
    """Pages open and close like a browser's: ``pages`` lists the open ones."""

    def __init__(self):
        self.pages, self.opened = [], 0
        FakePage(self)

    def new_page(self):
        self.opened += 1
        return FakePage(self)


class FakePage:
    def __init__(self, context):
        self.context, self.url, self.closed = context, "about:blank", False
        context.pages.append(self)

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True
        self.context.pages.remove(self)


class LastWindowTests(unittest.TestCase):
    """Firefox on Windows cannot open a page once its last window is closed."""

    def launched(self):
        context = FakeContext()
        _reuse_startup_page(context)
        return context

    def test_closing_the_last_page_leaves_a_blank_one_for_the_next_page(self):
        context = self.launched()
        article = context.new_page()
        article.url = "https://www.tandfonline.com/doi/full/10.1080/x"
        article.close()
        self.assertEqual([p.url for p in context.pages], ["about:blank"])
        kept = context.pages[0]
        self.assertIs(context.new_page(), kept)
        self.assertEqual(context.opened, 1)
        kept.url = "https://example.org/"
        kept.close()  # the kept page is looked after the same way
        self.assertEqual([p.url for p in context.pages], ["about:blank"])

    def test_closing_a_page_while_another_is_open_adds_nothing(self):
        context = self.launched()
        article = context.new_page()
        article.url = "https://example.org/article"
        tab = context.new_page()
        tab.close()
        self.assertEqual(context.pages, [article])
        self.assertEqual(context.opened, 1)


if __name__ == "__main__":
    unittest.main()

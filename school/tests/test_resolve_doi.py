"""DOI resolution asks doi.org only, never the publisher."""
import types
import unittest
from unittest.mock import patch

import requests

from paper_search_school.engine import bridge


def head_response(location=""):
    return types.SimpleNamespace(headers={"Location": location} if location else {})


class ResolveDoiTests(unittest.TestCase):
    def test_the_first_publisher_redirect_is_the_answer(self):
        calls = []

        def head(url, **kwargs):
            calls.append(url)
            self.assertFalse(kwargs["allow_redirects"])
            return head_response("https://link.springer.com/article/10.1245/x")

        with patch.object(requests, "head", side_effect=head):
            self.assertEqual(bridge._resolve_doi("10.1245/x"), "https://link.springer.com/article/10.1245/x")
        self.assertEqual(calls, ["https://doi.org/10.1245/x"])

    def test_a_failed_lookup_is_retried_once(self):
        answers = [requests.ConnectionError("reset"), head_response("https://onlinelibrary.wiley.com/doi/10.1002/x")]
        with patch.object(requests, "head", side_effect=answers), patch.object(bridge.time, "sleep"):
            self.assertEqual(bridge._resolve_doi("10.1002/x"), "https://onlinelibrary.wiley.com/doi/10.1002/x")


if __name__ == "__main__":
    unittest.main()

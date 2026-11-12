"""An open-access licence statement is access, not a paywall marker."""
import unittest

from paper_search_school.engine import batch


class OpenAccessLicenceTests(unittest.TestCase):
    def test_licence_statement_is_open_access(self):
        text = "rights and permissions open access this article is licensed under a creative commons attribution 4.0"
        self.assertTrue(batch._OPEN_ACCESS_LICENSE.search(text))
        self.assertNotIn("access this article", batch._OPEN_ACCESS_LICENSE_PHRASE.sub(" ", text))

    def test_a_real_paywall_marker_stays(self):
        text = "log in or access this article for 39.95 usd"
        self.assertIsNone(batch._OPEN_ACCESS_LICENSE.search(text))
        self.assertIn("access this article", batch._OPEN_ACCESS_LICENSE_PHRASE.sub(" ", text))


if __name__ == "__main__":
    unittest.main()

"""At most ``publisher_hourly_limit`` articles per publisher in any hour (rate_limit.py)."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paper_search_school import progress_reporter, rate_limit
from paper_search_school.engine import bridge


class HourlyLimitTests(unittest.TestCase):
    def setUp(self):
        rate_limit.ledger_path().unlink(missing_ok=True)
        self.addCleanup(rate_limit.ledger_path().unlink, missing_ok=True)

    def test_the_next_article_waits_until_the_oldest_of_the_hour_is_an_hour_old(self):
        for at in (1000, 1100, 1200):
            rate_limit.record("Elsevier", now=at)
        rate_limit.record("Wiley", now=1200)
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 3, now=1300), 1000 + 3600 - 1300 + 1)
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 4, now=1300), 0)
        self.assertEqual(rate_limit.wait_seconds("Wiley", 3, now=1300), 0)  # each publisher on its own
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 3, now=4601), 0)
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 0, now=1300), 0)  # 0 = no limit
        rate_limit.record("Elsevier", now=4900)  # entries older than an hour are dropped
        self.assertEqual(rate_limit._read_json(rate_limit.ledger_path()), {"Elsevier": [4900]})

    def test_the_backend_answers_rate_limited_before_any_browser(self):
        profile = SimpleNamespace(name="Elsevier")
        config = {"publisher_institution_federation": "carsi", "publisher_hourly_limit": 2}

        def run():
            with patch.object(bridge, "_resolve_doi", return_value="https://www.sciencedirect.com/x"), \
                    patch.object(bridge, "_try_browser_batch_download", return_value=None) as browser:
                return bridge._try_builtin_institutional("10.1016/x", Path("/tmp/x.pdf"), config, profile), browser

        for _ in range(2):
            _, browser = run()
            browser.assert_called_once()
        result, browser = run()
        browser.assert_not_called()
        self.assertEqual((result["error_type"], result["publisher"], result["limit"]), ("rate_limited", "Elsevier", 2))
        self.assertTrue(3500 < result["retry_after_sec"] <= 3601)


class PausedArticleTests(unittest.TestCase):
    def test_a_paused_article_is_not_counted_and_the_window_stays_open(self):
        batch = progress_reporter.BatchContext.from_args("b-1", 3, 3, 2, 1, 1)
        with progress_reporter.tracked_download("10.1016/x", None, batch) as outcome:
            outcome["result"] = {"success": False, "error_type": "rate_limited"}
            outcome["paused"] = "Elsevier 一小时内已打开 100 篇（每小时上限），23:10 继续这一篇"
        state = progress_reporter.read_state()
        self.assertEqual((state["done"], state["failed"]), (2, 1))
        self.assertTrue(state["awaiting_next"])
        self.assertIn("23:10 继续", state["phase"])
        self.assertNotEqual(state.get("stage"), "failed")


if __name__ == "__main__":
    unittest.main()

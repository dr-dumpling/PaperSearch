"""At most ``publisher_hourly_limit`` articles per publisher in each hour (rate_limit.py)."""
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

    def test_an_hour_starts_with_its_first_article_and_its_count_starts_again_after_it(self):
        """Counted over any 60 minutes, a full hour let one article on as each aged out,
        which read as stopping again and again (the user, 2026-11-13)."""
        for at in (1000, 1100, 1200):
            rate_limit.record("Elsevier", now=at)
        rate_limit.record("Wiley", now=1200)
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 3, now=1300), 1000 + 3600 - 1300 + 1)
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 4, now=1300), 0)
        self.assertEqual(rate_limit.wait_seconds("Wiley", 3, now=1300), 0)  # each publisher on its own
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 0, now=1300), 0)  # 0 = no limit
        # The hour is over at 4600: the count starts again, with nothing of the last hour in it.
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 3, now=4601), 0)
        for at in (4601, 4650):
            rate_limit.record("Elsevier", now=at)
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 3, now=4700), 0)  # 2 of 3 in the new hour
        rate_limit.record("Elsevier", now=4700)
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 3, now=4800), 4601 + 3600 - 4800 + 1)
        self.assertEqual(rate_limit._read_json(rate_limit.ledger_path()),
                         {"Elsevier": {"start": 4601, "count": 3}, "Wiley": {"start": 1200, "count": 1}})
        rate_limit.record("Elsevier", now=8300)  # hours over are dropped (Wiley's ended at 4800)
        self.assertEqual(rate_limit._read_json(rate_limit.ledger_path()), {"Elsevier": {"start": 8300, "count": 1}})

    def test_a_ledger_of_the_times_opened_goes_on_as_an_hour_from_the_oldest(self):
        """Before 0.6.3 the ledger kept each article's time; an update in the middle of an
        hour goes on counting it."""
        rate_limit._write_json(rate_limit.ledger_path(), {"Elsevier": [100, 1000, 1100, 1200]})
        self.assertEqual(rate_limit.wait_seconds("Elsevier", 3, now=3900), 1000 + 3600 - 3900 + 1)
        rate_limit.record("Wiley", now=3900)
        self.assertEqual(rate_limit._read_json(rate_limit.ledger_path()),
                         {"Elsevier": {"start": 1000, "count": 3}, "Wiley": {"start": 3900, "count": 1}})

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

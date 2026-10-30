"""Regression checks for scanner coverage and quote-age safeguards."""
import unittest
from datetime import datetime, timedelta, timezone

from scripts import paper_engine


NOW = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)


class TestSharedCreditRotation(unittest.TestCase):
    def test_us_fx_use_all_eight_credits_without_duplicate_requests(self):
        scan = paper_engine.select_active_watchlist(
            NOW, {}, us_active=True, uk_active=False, fx_active=True,
            scan_state={"cfd_paper": {"positions": {}}}
        )
        self.assertEqual(len(scan), paper_engine.MAX_API_SYMBOLS_PER_SCAN)
        self.assertEqual(len(set(scan)), len(scan))
        self.assertEqual(scan[:2], list(paper_engine.FOREX_SYMBOLS))
        self.assertEqual(len([s for s in scan if s in paper_engine.FOCUS_SYMBOLS]), 6)

    def test_entire_focus_universe_rotates_in_three_scans(self):
        seen = set()
        for step in range(3):
            scan = paper_engine.select_active_watchlist(
                NOW + timedelta(minutes=15 * step),
                {}, True, False, True, {}
            )
            seen.update(s for s in scan if s in paper_engine.FOCUS_SYMBOLS)
        self.assertEqual(seen, set(paper_engine.FOCUS_SYMBOLS))

    def test_open_cfd_proxy_receives_priority_even_during_overlap(self):
        state = {"cfd_paper": {"positions": {"NVDA": {"side": "short"}}}}
        opened = {"XOM": {}, "CAT": {}, "META": {}}
        scan = paper_engine.select_active_watchlist(
            NOW, opened, True, False, True, state
        )
        self.assertEqual(scan[:3], list(opened))
        self.assertIn("NVDA", scan)
        self.assertEqual(len(scan), 8)
        self.assertEqual(len(set(scan)), 8)

    def test_open_equities_before_candidates_and_uk_stays_reserved(self):
        opened = {"XOM": {"currency": "USD"},
                  "SHEL": {"currency": "GBP"}}
        scan = paper_engine.select_active_watchlist(
            NOW, opened, True, True, True, {}
        )
        self.assertEqual(scan[:2], list(opened))
        self.assertIn("GBP/USD", scan)
        self.assertTrue(any(s in paper_engine.UK_FOCUS_SYMBOLS for s in scan[2:]))
        self.assertTrue(any(s in paper_engine.FOCUS_SYMBOLS for s in scan[2:]))
        self.assertLessEqual(len(scan), paper_engine.MAX_API_SYMBOLS_PER_SCAN)


class TestMarketDataAge(unittest.TestCase):
    def test_old_unchecked_quotes_are_not_labelled_current(self):
        quotes = {
            "NVDA": {"date": "2026-10-30T14:55:00+00:00"},
            "TSLA": {"date": "2026-10-28T14:55:00+00:00", "is_fresh": True},
            "AMD": {"date": "bad-date"},
            "MSFT": {"date": "2026-10-30T15:30:00+00:00"},
        }
        paper_engine.mark_quote_freshness(quotes, NOW)
        self.assertTrue(quotes["NVDA"]["is_fresh"])
        for ticker in ("TSLA", "AMD", "MSFT"):
            self.assertFalse(quotes[ticker]["is_fresh"])

    def test_25_minute_cutoff_and_missing_timezone(self):
        quotes = {
            "older": {"date": (NOW - timedelta(minutes=26)).isoformat()},
            "at_limit": {"date": (NOW - timedelta(minutes=25)).isoformat()},
            "naive": {"date": "2026-10-30T14:55:00"},
        }
        paper_engine.mark_quote_freshness(quotes, NOW)
        self.assertFalse(quotes["older"]["is_fresh"])
        self.assertTrue(quotes["at_limit"]["is_fresh"])
        self.assertFalse(quotes["naive"]["is_fresh"])


class TestRiskParametersUnchanged(unittest.TestCase):
    def test_more_coverage_does_not_increase_risk_or_api_budget(self):
        self.assertEqual(paper_engine.MAX_API_SYMBOLS_PER_SCAN, 8)
        self.assertEqual(paper_engine.MAX_DAILY_ENTRIES, 5)
        self.assertEqual(paper_engine.DAILY_LOSS_LIMIT_GBP, 15)
        self.assertEqual(paper_engine.RISK_GBP, 5)
        self.assertEqual(paper_engine.MAX_POSITION_GBP, 250)
        self.assertEqual(paper_engine.MAX_OPEN_POSITIONS, 4)
        self.assertEqual(paper_engine.STOP_PCT, 0.01)
        self.assertEqual(paper_engine.TARGET_PCT, 0.015)


if __name__ == "__main__":
    unittest.main()

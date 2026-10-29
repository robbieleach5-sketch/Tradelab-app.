"""Regression tests for 15-minute scheduled scans of 5-minute bars."""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from scripts import paper_engine
from scripts.paper_engine import settle_open_position, USD_PER_GBP


BASE = datetime(2026, 10, 26, 13, 30, tzinfo=timezone.utc)


def candle(minute, open_price=100, low=99, high=101):
    return {
        "timestamp": int((BASE + timedelta(minutes=minute)).timestamp()),
        "open": open_price, "low": low, "high": high, "close": open_price,
    }


def portfolio(opened_at=None, processed_minute=0):
    entry = (opened_at or BASE).isoformat()
    return {
        "cash_gbp": 1000.0,
        "positions": {"TEST": {
            "date": entry, "entry_usd": 100.0, "stop_usd": 98.0,
            "target_usd": 104.0, "qty": 1.0,
        }},
        "trades": [], "events": [],
        "last_processed_intraday": {"TEST": candle(processed_minute)["timestamp"]},
    }


class TestOpenPositionReplay(unittest.TestCase):
    def test_stop_in_intermediate_bar_is_not_missed(self):
        state = portfolio()
        bars = [candle(5, low=97), candle(10), candle(15, high=103)]
        self.assertTrue(settle_open_position(state, "TEST", bars))
        self.assertNotIn("TEST", state["positions"])
        self.assertEqual(state["trades"][0]["reason"], "stop")
        self.assertEqual(state["trades"][0]["exit_usd"], 98)
        self.assertEqual(state["trades"][0]["exit_date"], (BASE + timedelta(minutes=5)).isoformat())
        expected = (98 - 100) / USD_PER_GBP - (98 + 100) / USD_PER_GBP * 0.001
        self.assertEqual(state["trades"][0]["pnl_gbp"], round(expected, 2))

    def test_earliest_touch_wins_not_latest_candle(self):
        state = portfolio()
        bars = [candle(5, high=104.5), candle(10, low=95), candle(15)]
        self.assertTrue(settle_open_position(state, "TEST", bars))
        self.assertEqual(state["trades"][0]["reason"], "target")
        self.assertEqual(state["trades"][0]["exit_usd"], 104)

    def test_both_touched_uses_conservative_stop_first(self):
        state = portfolio()
        self.assertTrue(settle_open_position(state, "TEST", [candle(5, low=97, high=105)]))
        self.assertEqual(state["trades"][0]["reason"], "stop")

    def test_gap_below_stop_uses_bar_open(self):
        state = portfolio()
        self.assertTrue(settle_open_position(state, "TEST", [candle(5, open_price=96, low=95)]))
        self.assertEqual(state["trades"][0]["reason"], "gap below stop")
        self.assertEqual(state["trades"][0]["exit_usd"], 96)

    def test_ignores_candles_before_or_at_entry(self):
        state = portfolio(opened_at=BASE + timedelta(minutes=10))
        self.assertFalse(settle_open_position(state, "TEST", [
            candle(5, low=95), candle(10, low=95), candle(15),
        ]))
        self.assertEqual(len(state["trades"]), 0)

    def test_skips_already_processed_bars(self):
        state = portfolio(processed_minute=10)
        self.assertFalse(settle_open_position(state, "TEST", [
            candle(5, low=95), candle(10, low=95), candle(15),
        ]))
        self.assertIn("TEST", state["positions"])

    def test_does_not_double_close(self):
        state = portfolio()
        bars = [candle(5, low=95), candle(10, high=105)]
        self.assertTrue(settle_open_position(state, "TEST", bars))
        self.assertFalse(settle_open_position(state, "TEST", bars))
        self.assertEqual(len(state["trades"]), 1)



    def test_morning_standby_avoids_market_data_calls(self):
        """09:09 UK in winter runs a status check, not early US virtual trading."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_state.json"
            with patch.object(paper_engine, "STATE", path), \
                 patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "test-key"}), \
                 patch.object(paper_engine, "intraday_prices", side_effect=AssertionError("should not fetch")):
                paper_engine.main(now=datetime(2026, 10, 27, 9, 9, tzinfo=timezone.utc))
            result = json.loads(path.read_text())
            self.assertFalse(result["market_session_open"])
            self.assertIn("standby", result["model"])
            self.assertEqual(result["cash_gbp"], 1000)
            self.assertEqual(result["trades"], [])

class TestFocusedScanner(unittest.TestCase):
    def test_revisits_all_focused_symbols_within_four_scans(self):
        symbols = set()
        for step in range(4):
            now = BASE + timedelta(minutes=15 * step)
            symbols.update(paper_engine.selected_watchlist(now, {}))
        self.assertEqual(symbols, set(paper_engine.FOCUS_SYMBOLS))

    def test_open_virtual_positions_are_always_checked_first(self):
        positions = {"XOM": {}, "CAT": {}, "ORCL": {}}
        for step in range(4):
            chosen = paper_engine.selected_watchlist(BASE + timedelta(minutes=15*step), positions)
            self.assertEqual(chosen[:3], list(positions))
            self.assertEqual(len(chosen), 8)
            self.assertEqual(len(set(chosen)), 8)

    @staticmethod
    def rising_bars():
        bars = []
        for minute in range(50):
            close = 100 + minute * 0.01
            bars.append({"close": close, "high": close + 0.03, "volume": 100})
        bars.append({"close": 100.60, "high": 100.61, "volume": 200})
        return bars

    def test_only_confirmed_and_not_extended_breakouts_qualify(self):
        bars = self.rising_bars()
        self.assertEqual(paper_engine.assess_breakout(bars), (True, "qualified_breakout"))
        bars[-1]["close"] = 101.5
        self.assertEqual(paper_engine.assess_breakout(bars),
                         (False, "breakout_too_extended"))

    def test_missing_volume_or_weak_volume_rejects_entry(self):
        bars = self.rising_bars()
        bars[-2]["volume"] = 0
        self.assertEqual(paper_engine.assess_breakout(bars), (False, "missing_volume"))
        bars = self.rising_bars()
        bars[-1]["volume"] = 110
        self.assertEqual(paper_engine.assess_breakout(bars),
                         (False, "insufficient_breakout_volume"))

    def test_insufficient_history_is_not_traded(self):
        self.assertEqual(paper_engine.assess_breakout(self.rising_bars()[:35]),
                         (False, "insufficient_history"))



class TestSmallerWinsConfiguration(unittest.TestCase):
    def test_smaller_targets_and_capital_per_trade(self):
        self.assertEqual(paper_engine.STOP_PCT, 0.01)
        self.assertEqual(paper_engine.TARGET_PCT, 0.015)
        self.assertEqual(paper_engine.MAX_POSITION_GBP, 250.0)
        self.assertEqual(paper_engine.MAX_OPEN_POSITIONS, 4)

    def test_four_positions_still_respect_api_limit(self):
        positions = {k: {} for k in ("NVDA", "TSLA", "CAT", "XOM")}
        scan = paper_engine.selected_watchlist(BASE, positions)
        self.assertEqual(scan[:4], list(positions))
        self.assertEqual(len(scan), 8)
        self.assertEqual(len(set(scan)), 8)

    def test_volume_filter_is_moderately_more_permissive(self):
        bars = TestFocusedScanner.rising_bars()
        bars[-1]["volume"] = 140
        self.assertEqual(paper_engine.assess_breakout(bars), (True, "qualified_breakout"))
        bars[-1]["volume"] = 120
        self.assertEqual(paper_engine.assess_breakout(bars), (False, "insufficient_breakout_volume"))

    def test_daily_limits_count_entries_and_closed_losses(self):
        from zoneinfo import ZoneInfo
        day = datetime(2026, 10, 29, 15, tzinfo=timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
        state = {
            "positions": {"NVDA": {"date": "2026-10-29T14:55:00+00:00"}},
            "trades": [
                {"ticker": "TSLA", "entry_date": "2026-10-29T14:00:00+00:00",
                 "exit_date": "2026-10-29T14:30:00+00:00", "pnl_gbp": -3.1},
                {"ticker": "CAT", "entry_date": "2026-10-28T19:00:00+00:00",
                 "exit_date": "2026-10-29T15:00:00+00:00", "pnl_gbp": -5.2},
            ],
        }
        count, realized, tickers = paper_engine.daily_limits(state, day)
        self.assertEqual(count, 2)
        self.assertEqual(realized, -8.3)
        self.assertEqual(tickers, {"TSLA", "NVDA"})

    def test_new_entries_cap_250_gbp_each(self):
        now = datetime(2026, 10, 29, 15, tzinfo=timezone.utc)
        stamp = int((now - timedelta(minutes=10)).timestamp())
        bars = [{"timestamp": stamp, "close": 100.0, "open": 100.0,
                 "low": 99.0, "high": 101.0, "volume": 200}]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_state.json"
            with patch.object(paper_engine, "STATE", path), \
                 patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "fake-key"}), \
                 patch.object(paper_engine, "selected_watchlist", return_value=["NVDA", "TSLA"]), \
                 patch.object(paper_engine, "intraday_prices", return_value=bars), \
                 patch.object(paper_engine, "assess_breakout", return_value=(True, "qualified_breakout")):
                paper_engine.main(now=now)
            state = json.loads(path.read_text())
            self.assertEqual(set(state["positions"]), {"NVDA", "TSLA"})
            for position in state["positions"].values():
                self.assertLessEqual(
                    position["entry_usd"] * position["qty"] / paper_engine.USD_PER_GBP, 250.01
                )
                self.assertAlmostEqual(position["target_usd"] / position["entry_usd"], 1.015, places=4)


if __name__ == "__main__":
    unittest.main()

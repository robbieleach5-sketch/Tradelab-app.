"""One-off INO virtual entry: data freshness, expiry and risk protections."""
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import paper_engine


def completed_ino_bars():
    previous_session = datetime(2026, 10, 30, 14, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(50):
        price = 99.0 + i * 0.02
        bars.append({
            "timestamp": int((previous_session + timedelta(minutes=i * 5)).timestamp()),
            "open": price, "high": price + 0.03, "low": price - 0.03,
            "close": price, "volume": 100,
        })
    opening = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    for i, (close, high) in enumerate(((100.0, 100.20), (100.1, 100.30), (100.12, 100.40))):
        bars.append({
            "timestamp": int((opening + timedelta(minutes=i * 5)).timestamp()),
            "open": close - 0.02, "high": high, "low": close - 0.05,
            "close": close, "volume": 100,
        })
    bars.append({
        "timestamp": int((opening + timedelta(minutes=15)).timestamp()),
        "open": 100.32, "high": 100.47, "low": 100.30,
        "close": 100.45, "volume": 200,
    })
    return bars


class TestUserPaperINO(unittest.TestCase):
    def test_priority_when_us_market_open_with_same_api_budget(self):
        now = datetime(2026, 11, 2, 14, 55, tzinfo=timezone.utc)
        chosen = paper_engine.select_active_watchlist(now, {}, True, False, True, {})
        self.assertIn("INO", chosen)
        self.assertEqual(len(chosen), 8)
        self.assertEqual(len(set(chosen)), len(chosen))
        self.assertEqual(chosen[:2], list(paper_engine.FOREX_SYMBOLS))

    def test_not_priority_before_us_open_or_after_expiry(self):
        self.assertNotIn("INO", paper_engine.select_active_watchlist(
            datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc), {}, False, False, True, {}
        ))
        self.assertNotIn("INO", paper_engine.select_active_watchlist(
            datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc), {}, True, False, True, {}
        ))

    def test_no_repeat_after_trade_completed(self):
        now = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
        state = {"trades": [{"ticker": "INO", "entry_date": "2026-11-02T14:45:00+00:00"}]}
        self.assertEqual(paper_engine.ino_request_status(now, state), "paper_trade_completed")
        self.assertNotIn("INO", paper_engine.select_active_watchlist(now, {}, True, False, True, state))

    def test_opening_range_and_breakout_required(self):
        bars = completed_ino_bars()
        now = datetime(2026, 11, 2, 14, 55, tzinfo=timezone.utc)
        self.assertEqual(
            paper_engine.assess_ino_opening_breakout(bars, now),
            (True, "confirmed_ino_opening_range_breakout"),
        )
        self.assertEqual(
            paper_engine.assess_ino_opening_breakout(bars, now - timedelta(minutes=6)),
            (False, "ino_opening_range_wait"),
        )
        self.assertEqual(
            paper_engine.assess_ino_opening_breakout(bars[:52] + bars[53:], now),
            (False, "ino_opening_range_missing"),
        )

    def test_weak_volume_does_not_open(self):
        bars = completed_ino_bars()
        bars[-1]["volume"] = 100
        eligible, reason = paper_engine.assess_ino_opening_breakout(
            bars, datetime(2026, 11, 2, 14, 55, tzinfo=timezone.utc)
        )
        self.assertFalse(eligible)
        self.assertEqual(reason, "insufficient_breakout_volume")

    def test_real_paper_engine_records_entry_only_on_confirmed_candle(self):
        now = datetime(2026, 11, 2, 14, 55, tzinfo=timezone.utc)
        bars = completed_ino_bars()
        with TemporaryDirectory() as folder:
            state_path = Path(folder) / "paper_state.json"
            with patch.object(paper_engine, "STATE", state_path), \
                 patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "mock-test",
                                         "TRADELAB_UK_INTRADAY_ENABLED": "false",
                                         "TRADELAB_FX_ENABLED": "false"}), \
                 patch.object(paper_engine, "select_active_watchlist", return_value=["INO"]), \
                 patch.object(paper_engine, "intraday_prices", return_value=bars):
                paper_engine.main(now=now)
            state = json.loads(state_path.read_text())
            self.assertEqual(list(state["positions"]), ["INO"])
            self.assertEqual(state["scan_diagnostics"]["new_paper_entries"], ["INO"])
            self.assertEqual(state["user_paper_request"]["status"], "virtual_position_open")
            position = state["positions"]["INO"]
            self.assertLessEqual(
                position["qty"] * position["entry_usd"] / paper_engine.USD_PER_GBP,
                paper_engine.MAX_POSITION_GBP + 0.01,
            )
            self.assertEqual(state["cash_gbp"], 1000)
            self.assertEqual(state["trades"], [])


if __name__ == "__main__":
    unittest.main()

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
                 patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "test-key", "TRADELAB_FX_ENABLED": "false"}), \
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



class TestOptionalUKMarket(unittest.TestCase):
    def test_uk_disabled_does_not_request_live_data(self):
        now = datetime(2026, 10, 29, 8, 15, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_state.json"
            with patch.object(paper_engine, "STATE", path), \
                 patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "mock", "TRADELAB_UK_INTRADAY_ENABLED": "false", "TRADELAB_FX_ENABLED": "false"}), \
                 patch.object(paper_engine, "intraday_prices", side_effect=AssertionError("No UK entitlement")):
                paper_engine.main(now=now)
            saved = json.loads(path.read_text())
            self.assertEqual(saved["uk_feed_status"], "awaiting_live_uk_data_entitlement")
            self.assertFalse(saved["market_session_open"])
            self.assertEqual(saved["positions"], {})

    def test_uk_enabled_can_enter_uk_only_session_with_gbp_price(self):
        now = datetime(2026, 10, 29, 8, 40, tzinfo=timezone.utc)
        stamp = int((now - timedelta(minutes=10)).timestamp())
        bars = [{"timestamp": stamp, "close": 10.0, "open": 10.0,
                 "low": 9.9, "high": 10.1, "volume": 250}]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_state.json"
            with patch.object(paper_engine, "STATE", path), \
                 patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "mock", "TRADELAB_UK_INTRADAY_ENABLED": "true", "TRADELAB_FX_ENABLED": "false"}), \
                 patch.object(paper_engine, "selected_uk_candidates", return_value=["SHEL"]), \
                 patch.object(paper_engine, "intraday_prices", return_value=bars) as prices, \
                 patch.object(paper_engine, "assess_breakout", return_value=(True, "qualified_breakout")):
                paper_engine.main(now=now)
            saved = json.loads(path.read_text())
            self.assertTrue(saved["uk_market_session_open"])
            self.assertFalse(saved["us_market_session_open"])
            self.assertEqual(saved["uk_feed_status"], "active_market_hours")
            self.assertEqual(list(saved["positions"]), ["SHEL"])
            pos = saved["positions"]["SHEL"]
            self.assertEqual(pos["currency"], "GBP")
            self.assertLessEqual(pos["qty"] * pos["entry_usd"], 250.01)
            self.assertAlmostEqual(pos["stop_usd"], 9.9, places=4)
            self.assertAlmostEqual(pos["target_usd"], 10.15, places=4)
            prices.assert_called_once_with("SHEL", market="UK")

    def test_lse_currency_validation_and_gbx_conversion(self):
        from io import BytesIO
        base = {"meta": {"mic_code": "XLON", "exchange": "London Stock Exchange",
                         "currency": "GBX"}, "values": [{
            "datetime": "2026-10-29 08:10:00", "open": "1000",
            "high": "1005", "low": "995", "close": "1002", "volume": "1100",
        }]}
        class Response:
            def __init__(self, payload):
                self.payload = payload
            def __enter__(self):
                return BytesIO(json.dumps(self.payload).encode("utf-8"))
            def __exit__(self, *_):
                return False
        with patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "mock"}), \
             patch.object(paper_engine.urllib.request, "urlopen", return_value=Response(base)):
            bars = paper_engine.intraday_prices("SHEL", market="UK")
        self.assertEqual(bars[0]["close"], 10.02)
        self.assertEqual(bars[0]["volume"], 1100)
        # GBp (mixed-case pence) must not be mistaken for GBP pounds.
        pence = dict(base, meta=dict(base["meta"], currency="GBp"))
        with patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "mock"}), \
             patch.object(paper_engine.urllib.request, "urlopen", return_value=Response(pence)):
            self.assertEqual(paper_engine.intraday_prices("SHEL", market="UK")[0]["close"], 10.02)
        for meta in ({"mic_code": "XNAS", "currency": "GBP"},
                     {"mic_code": "XLON", "currency": "USD"}, {}):
            bad = dict(base, meta=meta)
            with patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "mock"}), \
                 patch.object(paper_engine.urllib.request, "urlopen", return_value=Response(bad)):
                with self.assertRaises(ValueError):
                    paper_engine.intraday_prices("SHEL", market="UK")

    def test_overlap_never_exceeds_eight_api_symbols(self):
        positions = {"CAT": {"currency": "USD"}, "XOM": {"currency": "USD"},
                     "SHEL": {"currency": "GBP"}, "AZN": {"currency": "GBP"}}
        scan = paper_engine.select_active_watchlist(BASE, positions, True, True)
        self.assertEqual(len(scan), 8)
        self.assertEqual(len(scan), len(set(scan)))
        self.assertEqual(scan[:4], list(positions))
        self.assertTrue(any(s in paper_engine.UK_FOCUS_SYMBOLS for s in scan[4:]))
        self.assertTrue(any(s in paper_engine.FOCUS_SYMBOLS for s in scan[4:]))

    def test_uk_settlement_uses_gbp_and_purchase_stamp_duty(self):
        state = portfolio()
        state["positions"]["TEST"]["currency"] = "GBP"
        state["positions"]["TEST"]["target_usd"] = 104.0
        state["positions"]["TEST"]["entry_usd"] = 100.0
        state["positions"]["TEST"]["qty"] = 1
        self.assertTrue(settle_open_position(state, "TEST", [candle(5, high=105)]))
        self.assertEqual(state["trades"][0]["pnl_gbp"], round(4.0 - 0.204 - 0.5, 2))

    def test_uk_scan_no_replay_on_future_candles(self):
        now = datetime(2026, 10, 29, 8, 40, tzinfo=timezone.utc)
        bars = [{"timestamp": int((now + timedelta(minutes=5)).timestamp()),
                 "close": 10.0, "open": 10.0, "low": 9.9,
                 "high": 10.1, "volume": 250}]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_state.json"
            with patch.object(paper_engine, "STATE", path), \
                 patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "mock", "TRADELAB_UK_INTRADAY_ENABLED": "true", "TRADELAB_FX_ENABLED": "false"}), \
                 patch.object(paper_engine, "selected_uk_candidates", return_value=["SHEL"]), \
                 patch.object(paper_engine, "intraday_prices", return_value=bars), \
                 patch.object(paper_engine, "assess_breakout", return_value=(True, "qualified_breakout")):
                paper_engine.main(now=now)
            saved = json.loads(path.read_text())
            self.assertNotIn("SHEL", saved["positions"])
            self.assertEqual(saved["scan_diagnostics"]["outcomes"]["SHEL"], "provider_error")



class TestFreeForexMarket(unittest.TestCase):
    def test_fx_morning_scans_use_existing_free_key(self):
        now = datetime(2026, 10, 29, 8, 40, tzinfo=timezone.utc)
        stamp = int((now - timedelta(minutes=10)).timestamp())
        bar = {"timestamp": stamp, "open": 1.3, "close": 1.3, "high": 1.301,
               "low": 1.299, "volume": 0}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_state.json"
            with patch.object(paper_engine, "STATE", path), \
                 patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "mock",
                                         "TRADELAB_FX_ENABLED": "true",
                                         "TRADELAB_UK_INTRADAY_ENABLED": "false"}), \
                 patch.object(paper_engine, "intraday_prices", return_value=[bar]) as api:
                paper_engine.main(now=now)
            state = json.loads(path.read_text())
            self.assertTrue(state["forex_session_open"])
            self.assertFalse(state["us_market_session_open"])
            self.assertEqual(api.call_count, 2)
            self.assertEqual(set(state["scan_diagnostics"]["checked"]), set(paper_engine.FOREX_SYMBOLS))
            self.assertEqual(state["uk_research_watchlist"], list(paper_engine.UK_FOCUS_SYMBOLS))
            self.assertFalse(state["positions"])

    def test_fx_breakout_accepts_unreported_volume(self):
        bars = []
        for i in range(50):
            close = 1.3 + i*0.00003
            bars.append({"close": close, "high": close + 0.0002,
                         "low": close - 0.0002, "volume": 0})
        next_close = bars[-1]["high"] + 0.0001
        bars.append({"close": next_close, "high": next_close + 0.0002,
                     "low": next_close - 0.0002, "volume": 0})
        self.assertEqual(paper_engine.assess_forex_breakout(bars),
                         (True, "qualified_fx_breakout"))
        self.assertEqual(paper_engine.assess_forex_breakout(bars[:30]),
                         (False, "fx_insufficient_history"))

    def test_fx_entry_targets_and_position_caps(self):
        now = datetime(2026, 10, 29, 8, 40, tzinfo=timezone.utc)
        stamp = int((now - timedelta(minutes=10)).timestamp())
        bar = {"timestamp": stamp, "close": 1.3, "open": 1.3,
               "low": 1.299, "high": 1.301, "volume": 0}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper_state.json"
            with patch.object(paper_engine, "STATE", path), \
                 patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "mock",
                                         "TRADELAB_FX_ENABLED": "true"}), \
                 patch.object(paper_engine, "intraday_prices", return_value=[bar]), \
                 patch.object(paper_engine, "assess_forex_breakout",
                              return_value=(True, "qualified_fx_breakout")):
                paper_engine.main(now=now)
            state = json.loads(path.read_text())
            self.assertEqual(len(state["positions"]), 2)
            for sym, p in state["positions"].items():
                self.assertIn(sym, paper_engine.FOREX_SYMBOLS)
                self.assertEqual(p["asset_class"], "forex")
                self.assertLessEqual(p["qty"] * p["entry_usd"] / USD_PER_GBP, 250.01)
                self.assertAlmostEqual(p["stop_usd"]/p["entry_usd"],
                                       1-paper_engine.FX_STOP_PCT, places=4)
                self.assertAlmostEqual(p["target_usd"]/p["entry_usd"],
                                       1+paper_engine.FX_TARGET_PCT, places=4)

    def test_fx_cost_and_credits(self):
        state = portfolio()
        state["positions"]["TEST"]["asset_class"] = "forex"
        self.assertTrue(settle_open_position(state, "TEST", [candle(5, high=105)]))
        pnl = (104-100)/USD_PER_GBP - 100/USD_PER_GBP*paper_engine.FX_ROUND_TRIP_COST_RATE
        self.assertEqual(state["trades"][0]["pnl_gbp"], round(pnl, 2))
        selected = paper_engine.select_active_watchlist(
            datetime(2026, 10, 29, 15, tzinfo=timezone.utc),
            {"XOM": {}, "CAT": {}, "GBP/USD": {}}, True, False, True)
        self.assertLessEqual(len(selected), 8)
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual(selected[:3], ["XOM", "CAT", "GBP/USD"])


class TestLegacyPositionRebalance(unittest.TestCase):
    def make_state(self):
        state = portfolio()
        state["positions"]["TEST"]["qty"] = 6.65
        state["positions"]["TEST"]["date"] = "2026-10-27T15:00:00+00:00"
        return state

    def test_reduce_only_at_fresh_completed_price_and_record_realized_pnl(self):
        now = datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc)
        bar = {"timestamp": int((now - timedelta(minutes=10)).timestamp()),
               "open": 99.0, "high": 100.4, "low": 98.9, "close": 99.7}
        state = self.make_state()
        original = state["positions"]["TEST"].copy()
        self.assertTrue(paper_engine.rebalance_legacy_position(state, "TEST", [bar], now))
        new_pos = state["positions"]["TEST"]
        self.assertEqual(new_pos["target_usd"], original["target_usd"])
        self.assertEqual(new_pos["stop_usd"], original["stop_usd"])
        self.assertLessEqual(new_pos["qty"]*new_pos["entry_usd"]/USD_PER_GBP, 200.01)
        sale_qty = state["trades"][-1]["qty"]
        expected = (99.7 - original["entry_usd"]) * sale_qty / USD_PER_GBP
        expected -= (99.7 + original["entry_usd"]) * sale_qty / USD_PER_GBP * 0.001
        self.assertEqual(state["trades"][-1]["pnl_gbp"], round(expected, 2))
        self.assertEqual(state["cash_gbp"], round(1000+round(expected, 2), 2))
        self.assertFalse(paper_engine.rebalance_legacy_position(state, "TEST", [bar], now))
        self.assertEqual(len(state["trades"]), 1)

    def test_no_legacy_trim_without_fresh_quote_or_for_new_positions(self):
        now = datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc)
        state = self.make_state()
        older = {"timestamp": int((now - timedelta(days=1)).timestamp()),
                 "close": 99.1}
        self.assertFalse(paper_engine.rebalance_legacy_position(state, "TEST", [older], now))
        self.assertEqual(state["cash_gbp"], 1000)
        self.assertEqual(state["positions"]["TEST"]["qty"], 6.65)
        fresh = {"timestamp": int((now - timedelta(minutes=10)).timestamp()),
                 "close": 99.1}
        state["positions"]["TEST"]["asset_class"] = "forex"
        self.assertFalse(paper_engine.rebalance_legacy_position(state, "TEST", [fresh], now))
        state["positions"]["TEST"]["asset_class"] = "equity"
        state["positions"]["TEST"]["currency"] = "GBP"
        self.assertFalse(paper_engine.rebalance_legacy_position(state, "TEST", [fresh], now))

    def test_current_legacy_portfolio_frees_at_least_500_virtual_pounds(self):
        from scripts.paper_engine import LEGACY_POSITION_CAP_GBP
        positions = {"XOM": {"entry_usd": 181.86000061035156, "qty": 3.65666},
                     "CAT": {"entry_usd": 709.485, "qty": 0.91623}}
        remaining = sum(LEGACY_POSITION_CAP_GBP for _ in positions)
        self.assertLessEqual(remaining, 400)
        self.assertGreater(988.76 - remaining, 500)


class TestRiskStatusDisplay(unittest.TestCase):
    def test_daily_gap_loss_halts_new_entries_and_reports_cash(self):
        now = datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc)
        from zoneinfo import ZoneInfo
        day = now.astimezone(ZoneInfo("America/New_York")).date()
        state = {"cash_gbp": 937.62,
                 "positions": {"XOM": {"entry_usd": 181.86000061035156, "qty": 3.65666}},
                 "trades": [{"ticker": "CAT", "entry_date": "2026-10-27T14:55:00+00:00",
                             "exit_date": "2026-10-29T13:30:00+00:00", "pnl_gbp": -51.14}]}
        paper_engine.publish_risk_status(state, day)
        risk = state["risk_status"]
        self.assertTrue(risk["daily_loss_halt"])
        self.assertEqual(risk["entry_pause_reason"], "daily_loss_limit")
        self.assertAlmostEqual(risk["available_virtual_cash_gbp"], 437.62, places=2)
        self.assertEqual(risk["entries_today"], 0)
        self.assertEqual(risk["daily_realized_pnl_gbp"], -51.14)

    def test_fresh_day_releases_loss_pause_without_fabricating_capital(self):
        from zoneinfo import ZoneInfo
        day = datetime(2026, 10, 30, 13, 40, tzinfo=timezone.utc).astimezone(
            ZoneInfo("America/New_York")).date()
        state = {"cash_gbp": 937.62, "positions": {}, "trades": [
            {"ticker": "CAT", "entry_date": "2026-10-27T14:55:00+00:00",
             "exit_date": "2026-10-29T13:30:00+00:00", "pnl_gbp": -51.14}
        ]}
        paper_engine.publish_risk_status(state, day)
        self.assertFalse(state["risk_status"]["daily_loss_halt"])
        self.assertEqual(state["risk_status"]["entry_pause_reason"], "none")
        self.assertEqual(state["risk_status"]["available_virtual_cash_gbp"], 937.62)


class TestConfirmedEquityProfitBank(unittest.TestCase):
    def test_legacy_target_four_pct_can_bank_small_confirmed_profit(self):
        state = portfolio()
        state["positions"]["TEST"]["target_usd"] = 104.0
        candle_at = candle(5)
        candle_at["close"] = 100.7
        candle_at["high"] = 101.0
        candle_at["low"] = 99.8
        self.assertTrue(settle_open_position(state, "TEST", [candle_at]))
        self.assertEqual(state["trades"][0]["reason"], "early_profit_bank")
        self.assertGreater(state["trades"][0]["pnl_gbp"], 0)

    def test_stop_always_precedes_early_profit_in_same_bar(self):
        state = portfolio()
        candle_at = candle(5, low=97.5)
        candle_at["close"] = 101.0
        self.assertTrue(settle_open_position(state, "TEST", [candle_at]))
        self.assertEqual(state["trades"][0]["reason"], "stop")

    def test_forex_positions_do_not_inherit_equity_profit_bank(self):
        state = portfolio()
        state["positions"]["TEST"]["asset_class"] = "forex"
        candle_at = candle(5)
        candle_at["close"] = 101.0
        candle_at["high"] = 102.0
        self.assertFalse(settle_open_position(state, "TEST", [candle_at]))

    def test_shared_underlying_scanner_stays_eight_requests(self):
        state = {"cfd_paper": {"positions": {"NVDA": {"side": "short"}}}}
        positions = {"XOM": {}, "CAT": {}}
        watch = paper_engine.select_active_watchlist(
            datetime(2026, 10, 29, 15, 10, tzinfo=timezone.utc),
            positions, True, False, True, state
        )
        self.assertEqual(watch[:2], list(positions))
        self.assertIn("NVDA", watch)
        self.assertLessEqual(len(watch), 8)
        self.assertEqual(len(watch), len(set(watch)))


class TestActionsScriptStartup(unittest.TestCase):
    def test_script_path_runs_without_package_import_error(self):
        """The exact command used by GitHub Actions must start successfully."""
        import subprocess
        import sys
        script = Path(__file__).resolve().parents[1] / "scripts" / "paper_engine.py"
        with TemporaryDirectory() as directory:
            proc = subprocess.run(
                [sys.executable, str(script)], cwd=directory,
                env={**os.environ, "TWELVE_DATA_API_KEY": ""},
                capture_output=True, text=True, timeout=12,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads((Path(directory)/"data"/"paper_state.json").read_text())
            self.assertIn("DATA_CONFIG", result["errors"])
            self.assertEqual(result["cfd_paper"]["single_test_request"]["remaining_entries"], 1)


if __name__ == "__main__":
    unittest.main()

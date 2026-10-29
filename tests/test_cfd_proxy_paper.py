"""Tests for *illustrative* stock-CFD proxy engine (never actual broker CFD fills)."""
import unittest
from datetime import datetime, timedelta, timezone
from scripts import cfd_proxy_paper as cfd

NOW = datetime(2026, 10, 29, 15, 10, tzinfo=timezone.utc)  # 11:10 New York


def bar(at, price, high=None, low=None, vol=100):
    return {"timestamp": int(at.timestamp()), "open": price, "close": price,
            "high": price if high is None else high,
            "low": price if low is None else low, "volume": vol}


def history(now=NOW, descending=False):
    start = now - timedelta(minutes=60*5+5)
    out = []
    for i in range(59):
        p = (105 - i*0.04) if descending else (100 + i*0.04)
        out.append(bar(start + timedelta(minutes=i*5), p, p+0.025, p-0.025))
    last = out[-1]["close"]
    value = last-0.15 if descending else last+0.15
    out.append(bar(start + timedelta(minutes=59*5), value, value+.025, value-.025, 160))
    return out


class TestCfdProxy(unittest.TestCase):
    def test_default_is_isolated_account_with_no_leverage_or_real_broker(self):
        state = {"cash_gbp": 937.62, "positions": {"XOM": {"qty": 1}}}
        book = cfd.initialize(state)
        self.assertEqual(book["cash_gbp"], 1000.0)
        self.assertTrue(book["separate_research_account"])
        self.assertIn("NOT_BROKER_CFD", book["source"])
        self.assertEqual(state["cash_gbp"], 937.62)
        self.assertEqual(cfd.MAX_POSITIONS, 2)
        self.assertEqual(cfd.POSITION_GBP, 150)

    def test_long_and_short_breakout_detection(self):
        long = history()
        short = history(descending=True)
        self.assertEqual(cfd.direction_signal(long)[0], "long")
        self.assertEqual(cfd.direction_signal(short)[0], "short")
        long[-1]["volume"] = 0
        self.assertEqual(cfd.direction_signal(long)[1], "missing_share_volume")

    def test_short_position_opens_and_target_profit_releases_cash(self):
        state = {}
        book = cfd.initialize(state)
        bars = history(descending=True)
        signal = cfd.evaluate(book, "AMD", bars, NOW)
        self.assertEqual(signal, "paper_cfd_proxy_entry_short")
        pos = book["positions"]["AMD"]
        self.assertEqual(pos["side"], "short")
        self.assertEqual(pos["leverage"], 1.0)
        self.assertLessEqual(pos["qty"]*pos["entry_usd"]/cfd.USD_PER_GBP_ASSUMED, 150.01)
        next_at = NOW + timedelta(minutes=15)
        candle = bar(next_at-timedelta(minutes=10), pos["target_usd"]-.05,
                     high=pos["target_usd"]+.15, low=pos["target_usd"]-.1)
        self.assertEqual(cfd.evaluate(book, "AMD", [candle], next_at), "closed_at_target")
        self.assertEqual(book["positions"], {})
        self.assertGreater(book["cash_gbp"], 1000.0)
        self.assertEqual(book["trades"][0]["reason"], "target")
        self.assertEqual(book["trades"][0]["quote_type"], "underlying_stock_proxy")
        self.assertEqual(cfd.evaluate(book, "AMD", [candle], next_at), "already_processed")

    def test_long_stop_wins_over_target_if_same_candle(self):
        book = cfd.initialize({})
        h = history()
        self.assertEqual(cfd.evaluate(book, "NVDA", h, NOW), "paper_cfd_proxy_entry_long")
        pos = book["positions"]["NVDA"]
        next_at = NOW+timedelta(minutes=15)
        b = bar(next_at-timedelta(minutes=10), pos["entry_usd"],
                high=pos["target_usd"]+1, low=pos["stop_usd"]-1)
        self.assertEqual(cfd.evaluate(book, "NVDA", [b], next_at), "closed_at_stop")
        self.assertLess(book["cash_gbp"], 1000.0)

    def test_early_profit_bank_for_short_and_costs_deducted(self):
        book = cfd.initialize({})
        h = history(descending=True)
        self.assertEqual(cfd.evaluate(book, "TSLA", h, NOW), "paper_cfd_proxy_entry_short")
        position = book["positions"]["TSLA"]
        next_at = NOW+timedelta(minutes=15)
        close_price = position["entry_usd"]*(1-cfd.EARLY_PROFIT_CLOSE_PCT-0.0001)
        b = bar(next_at-timedelta(minutes=10), close_price,
                high=close_price+.01, low=close_price-.01)
        self.assertEqual(cfd.evaluate(book, "TSLA", [b], next_at), "early_profit_bank")
        self.assertGreater(book["trades"][0]["pnl_gbp"], 0)
        self.assertGreater(book["trades"][0]["estimated_cost_gbp"], 0)

    def test_reject_future_or_stale_quotes(self):
        book = cfd.initialize({})
        self.assertEqual(cfd.evaluate(book, "TSLA", [bar(NOW + timedelta(minutes=30), 100)], NOW),
                         "no_completed_bars")
        self.assertEqual(cfd.evaluate(book, "TSLA", [bar(NOW-timedelta(minutes=60), 100)], NOW),
                         "stale_underlying_quote")

    def test_loss_cap_does_not_prevent_existing_position_management(self):
        book = cfd.initialize({})
        h = history()
        self.assertEqual(cfd.evaluate(book, "NVDA", h, NOW), "paper_cfd_proxy_entry_long")
        book["trades"].append({"ticker": "AMD", "entry_day": NOW.date().isoformat(),
                               "exit_day": NOW.date().isoformat(), "pnl_gbp": -12.0})
        after = NOW + timedelta(minutes=15)
        pos = book["positions"]["NVDA"]
        b = bar(after-timedelta(minutes=10), pos["stop_usd"]-.2,
                high=pos["stop_usd"]+.3, low=pos["stop_usd"]-.4)
        self.assertEqual(cfd.evaluate(book, "NVDA", [b], after, allow_new=False), "closed_at_stop")
        self.assertNotIn("NVDA", book["positions"])
        self.assertEqual(cfd.evaluate(book, "TSLA", [bar(after-timedelta(minutes=10), 100)],
                                      after), "cfd_daily_risk_halt")

    def test_session_cutoff_closes_open_position_without_overnight(self):
        book = cfd.initialize({})
        h = history()
        self.assertEqual(cfd.evaluate(book, "NVDA", h, NOW), "paper_cfd_proxy_entry_long")
        ny_close = datetime(2026, 10, 29, 19, 42, tzinfo=timezone.utc)  # 15:42 NY
        p = book["positions"]["NVDA"]
        b = bar(ny_close-timedelta(minutes=10), p["entry_usd"],
                high=p["entry_usd"]+.1, low=p["entry_usd"]-.1)
        self.assertEqual(cfd.evaluate(book, "NVDA", [b], ny_close), "session_exit")
        self.assertEqual(book["positions"], {})



    def test_user_one_shot_allows_exactly_one_demo_entry(self):
        book = cfd.initialize({})
        self.assertEqual(book["single_test_request"]["remaining_entries"], 1)
        self.assertEqual(cfd.evaluate(book, "NVDA", history(), NOW),
                         "paper_cfd_proxy_entry_long")
        self.assertEqual(book["single_test_request"]["remaining_entries"], 0)
        self.assertEqual(book["single_test_request"]["status"], "entry_opened")
        self.assertEqual(cfd.evaluate(book, "AMD", history(descending=True), NOW),
                         "single_test_request_fulfilled")
        self.assertEqual(len(book["positions"]), 1)

    def test_one_shot_expiration_does_not_create_demo_position(self):
        book = cfd.initialize({})
        book["single_test_request"]["expires_utc"] = (NOW-timedelta(minutes=1)).isoformat()
        self.assertEqual(cfd.evaluate(book, "NVDA", history(), NOW),
                         "single_test_request_expired")
        self.assertEqual(book["single_test_request"]["status"], "expired_without_entry")
        self.assertFalse(book["positions"])

    def test_daily_loss_lock_precedes_one_shot_entry(self):
        book = cfd.initialize({})
        self.assertEqual(cfd.evaluate(book, "NVDA", history(), NOW, allow_new=False),
                         "entries_paused")
        self.assertEqual(book["single_test_request"]["remaining_entries"], 1)
        self.assertFalse(book["positions"])

if __name__ == "__main__":
    unittest.main()

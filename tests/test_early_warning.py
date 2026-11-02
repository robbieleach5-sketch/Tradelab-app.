"""Research-only early-warning regression tests (no automatic trade entries)."""
import unittest

from scripts.paper_engine import assess_early_warning, assess_breakout


def candles():
    rows = []
    for i in range(50):
        close = 100 + i * 0.01
        rows.append({
            "open": close, "high": close + 0.03, "low": close - 0.03,
            "close": close, "volume": 100,
        })
    rows.append({
        "open": 100.49, "high": 100.53, "low": 100.48,
        "close": 100.51, "volume": 145,
    })
    return rows


class TestEarlyWarning(unittest.TestCase):
    def test_near_breakout_is_research_only_not_entry(self):
        rows = candles()
        signal = assess_early_warning(rows)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["status"], "near_resistance_research_only")
        self.assertEqual(signal["trigger_price"], 100.52)
        self.assertEqual(signal["volume_multiple"], 1.45)
        self.assertEqual(assess_breakout(rows), (False, "no_15bar_breakout"))

    def test_needs_full_history(self):
        self.assertIsNone(assess_early_warning(candles()[-50:]))

    def test_missing_or_low_volume(self):
        rows = candles()
        rows[-1]["volume"] = 0
        self.assertIsNone(assess_early_warning(rows))
        rows = candles()
        rows[-1]["volume"] = 105
        self.assertIsNone(assess_early_warning(rows))
        rows = candles()
        rows[-4]["volume"] = 0
        self.assertIsNone(assess_early_warning(rows))

    def test_too_far_from_breakout(self):
        rows = candles()
        rows[-1]["close"] = 99.0
        self.assertIsNone(assess_early_warning(rows))

    def test_already_above_breakout_is_not_early_warning(self):
        rows = candles()
        rows[-1]["close"] = 100.8
        self.assertIsNone(assess_early_warning(rows))

    def test_no_positive_trend(self):
        rows = candles()
        for bar in rows[:-1]:
            bar["close"] = 100
        self.assertIsNone(assess_early_warning(rows))

    def test_rejects_wide_range(self):
        rows = candles()
        rows[-2]["low"] = 95
        self.assertIsNone(assess_early_warning(rows))

    def test_rejects_falling_recent_lows(self):
        rows = candles()
        rows[-2]["low"] = 99
        self.assertIsNone(assess_early_warning(rows))

    def test_malformed_provider_values_fail_closed(self):
        rows = candles()
        del rows[-1]["volume"]
        self.assertIsNone(assess_early_warning(rows))


if __name__ == "__main__":
    unittest.main()

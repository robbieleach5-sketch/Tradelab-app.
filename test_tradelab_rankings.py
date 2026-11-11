import tempfile
import unittest
from pathlib import Path
from tradelab_rankings import ClosedTrade, score_trader, record_signal

class RankingTests(unittest.TestCase):
    def test_insufficient_data(self):
        self.assertIsNone(score_trader([ClosedTrade(1, 1)])["score"])

    def test_losses_lower_score(self):
        good = score_trader([ClosedTrade(2, 1)] * 25 + [ClosedTrade(-1, 1)] * 5)
        bad = score_trader([ClosedTrade(-1, 1)] * 25 + [ClosedTrade(2, 1)] * 5)
        self.assertGreater(good["score"], bad["score"])

    def test_signal_is_paper_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "signals.jsonl")
            row = record_signal(path, source="manual", symbol="TEST", side="BUY",
                                entry=100, stop=99, target=102,
                                observed_at="2026-11-11T15:00:00+00:00")
            self.assertEqual(row["reward_risk"], 2.0)
            self.assertTrue(Path(path).exists())

    def test_reject_invalid_levels(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                record_signal(str(Path(d)/"x"), source="manual", symbol="TEST",
                              side="SELL", entry=100, stop=99, target=102,
                              observed_at="2026-11-11T15:00:00Z")

if __name__ == "__main__":
    unittest.main()

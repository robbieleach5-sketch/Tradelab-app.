"""Offline tests for the isolated research-only Alpaca feed prototype."""
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from scripts.verified_iex_feed import get_closed_five_minute_bars


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, *args):
        return json.dumps(self.payload).encode()


class VerifiedFeedTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 5, 15, 2, tzinfo=timezone.utc)
        self.keys = {"APCA_API_KEY_ID": "test", "APCA_API_SECRET_KEY": "test"}

    def test_rejects_missing_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                get_closed_five_minute_bars("QCOM", self.now)

    def test_rejects_stale_candle(self):
        data = {"bars": [{"t": "2026-11-05T14:45:00Z", "o": 100, "h": 102, "l": 99, "c": 101, "v": 1200}]}
        with patch.dict(os.environ, self.keys), patch("urllib.request.urlopen", return_value=FakeResponse(data)):
            with self.assertRaisesRegex(ValueError, "stale"):
                get_closed_five_minute_bars("QCOM", self.now)

    def test_only_closed_bars_and_source_disclosure(self):
        data = {"bars": [
            {"t": "2026-11-05T14:55:00Z", "o": 100, "h": 102, "l": 99, "c": 101, "v": 1200},
            {"t": "2026-11-05T15:00:00Z", "o": 101, "h": 103, "l": 100, "c": 102, "v": 100},
        ]}
        with patch.dict(os.environ, self.keys), patch("urllib.request.urlopen", return_value=FakeResponse(data)):
            result = get_closed_five_minute_bars("QCOM", self.now)
        self.assertEqual(len(result["bars"]), 1)
        self.assertIn("IEX only", result["feed"])
        self.assertIsNone(result["broker_cfd_spread"])


if __name__ == "__main__":
    unittest.main()

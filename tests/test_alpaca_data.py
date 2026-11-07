import io
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from scripts import alpaca_data, paper_engine

NOW = datetime(2026, 11, 6, 15, tzinfo=timezone.utc)
BAR = dict(t='2026-11-06T14:35:00Z', o=100, h=102, l=99, c=101, v=123)
ENV = {'APCA_API_KEY_ID': 'test-key', 'APCA_API_SECRET_KEY': 'test-secret'}

class AlpacaTests(unittest.TestCase):
    def fetch(self, bars, symbol='NVDA'):
        response = io.BytesIO(json.dumps(dict(symbol=symbol, bars=bars)).encode())
        with patch.dict(os.environ, ENV), patch('urllib.request.urlopen', return_value=response) as call:
            result = alpaca_data.prices('NVDA', NOW)
            request = call.call_args.args[0]
            self.assertIn('feed=iex', request.full_url)
            self.assertIn('timeframe=5Min', request.full_url)
            self.assertNotIn('test-secret', request.full_url)
            self.assertEqual(request.get_method(), 'GET')
            return result

    def test_normalizes_orders_and_deduplicates(self):
        later = dict(BAR, t='2026-11-06T14:40:00Z')
        rows = self.fetch([later, BAR, BAR])
        self.assertEqual(len(rows), 2)
        self.assertLess(rows[0]['timestamp'], rows[1]['timestamp'])
        self.assertEqual(rows[0]['volume'], 123)

    def test_bad_prices_timestamps_and_symbols_rejected(self):
        for bar in [dict(BAR, c=float('nan')), dict(BAR, h=98),
                    dict(BAR, t='2026-11-06T14:35:00'), dict(BAR, v=-1),
                    dict(BAR, t='2026-11-06T15:05:00Z')]:
            with self.subTest(bar=bar), self.assertRaises(ValueError):
                self.fetch([bar])
        with self.assertRaises(ValueError):
            self.fetch([BAR], 'AMD')

    def test_no_credentials_no_request(self):
        with patch.dict(os.environ, {}, clear=True), patch('urllib.request.urlopen') as request:
            with self.assertRaises(RuntimeError):
                alpaca_data.prices('NVDA', NOW)
            request.assert_not_called()

    def test_explicit_routing_and_no_silent_fallback(self):
        with patch.dict(os.environ, {'TRADELAB_US_DATA_PROVIDER': 'alpaca'}), patch.object(alpaca_data, 'prices', return_value=[BAR]) as fetch:
            self.assertEqual(paper_engine.intraday_prices('NVDA'), [BAR])
            fetch.assert_called_once_with('NVDA')
            fetch.side_effect = ValueError('unavailable')
            with self.assertRaises(ValueError):
                paper_engine.intraday_prices('NVDA')
        with patch.dict(os.environ, {'TRADELAB_US_DATA_PROVIDER': 'wrong'}):
            with self.assertRaises(ValueError):
                paper_engine.us_data_provider()

class AlpacaEngineTests(unittest.TestCase):
    def test_alpaca_only_engine_fetches_us_and_labels_quotes(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        bars = [dict(timestamp=int(datetime(2026, 11, 6, 14, 50, tzinfo=timezone.utc).timestamp()),
                     open=100, high=102, low=99, close=101, volume=123)]
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {**ENV, 'TRADELAB_US_DATA_PROVIDER': 'alpaca'}, clear=True), patch.object(alpaca_data, 'prices', return_value=bars) as fetch, patch.object(paper_engine, 'STATE', Path(tmp)/'state.json'):
            paper_engine.main(NOW)
            state = json.loads(paper_engine.STATE.read_text())
            self.assertTrue(fetch.called)
            self.assertNotIn('DATA_CONFIG', state['errors'])
            self.assertFalse(state['forex_session_open'])
            self.assertEqual(state['us_data_provider'], 'alpaca')
            self.assertTrue(all('Alpaca IEX' in q['source'] for q in state['quotes'].values()))

    def test_missing_alpaca_key_pauses_even_with_twelve_key(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {'TRADELAB_US_DATA_PROVIDER': 'alpaca', 'TWELVE_DATA_API_KEY': 'test'}, clear=True), patch('urllib.request.urlopen') as request, patch.object(paper_engine, 'STATE', Path(tmp)/'state.json'):
            paper_engine.main(NOW)
            state = json.loads(paper_engine.STATE.read_text())
            self.assertIn('DATA_CONFIG', state['errors'])
            request.assert_not_called()

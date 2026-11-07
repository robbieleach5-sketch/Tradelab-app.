"""Read-only Alpaca IEX data adapter. Never submits broker orders."""
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


def prices(ticker, now=None):
    key = os.environ.get('APCA_API_KEY_ID')
    secret = os.environ.get('APCA_API_SECRET_KEY')
    if not key or not secret:
        raise RuntimeError('Missing APCA_API_KEY_ID or APCA_API_SECRET_KEY')
    now = now or datetime.now(timezone.utc)
    params = {'timeframe': '5Min', 'feed': 'iex', 'adjustment': 'raw',
              'start': (now-timedelta(days=7)).isoformat(), 'end': now.isoformat(),
              'sort': 'desc', 'limit': 1000}
    url = 'https://data.alpaca.markets/v2/stocks/' + urllib.parse.quote(ticker, safe='') + '/bars?'
    request = urllib.request.Request(url + urllib.parse.urlencode(params), headers={
        'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    if payload.get('symbol') != ticker:
        raise ValueError('Alpaca returned an unexpected symbol')
    rows = {}
    for item in payload.get('bars') or []:
        try:
            stamp = datetime.fromisoformat(item['t'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                continue
            o, h, low, close, volume = (float(item[k]) for k in ('o', 'h', 'l', 'c', 'v'))
            if not all(math.isfinite(v) for v in (o, h, low, close, volume)):
                continue
            if not (0 < low <= min(o, close) <= max(o, close) <= h and volume >= 0):
                continue
            ts = int(stamp.timestamp())
            if ts % 300 or ts > now.timestamp():
                continue
            rows[ts] = dict(timestamp=ts, open=o, high=h, low=low, close=close, volume=volume)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    if not rows:
        raise ValueError('No valid Alpaca IEX bars')
    return [rows[k] for k in sorted(rows)]

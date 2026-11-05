"""Research-only Alpaca IEX five-minute feed. Not an execution or CFD quote feed.

This is deliberately isolated from paper_engine.py until credentials, tests,
and source freshness checks have been validated.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

API = "https://data.alpaca.markets/v2/stocks/bars"
MAX_AGE_SECONDS = 120


def get_closed_five_minute_bars(symbol, now=None):
    """Return verified closed IEX bars, or fail closed. No order endpoints."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Alpaca market-data credentials not configured")
    if not symbol or not symbol.replace(".", "").isalnum():
        raise ValueError("Invalid stock ticker")
    # Request only IEX: free, live but limited venue. Never label as SIP.
    params = urllib.parse.urlencode({
        "timeframe": "5Min", "feed": "iex", "limit": 100,
        "start": (now - timedelta(hours=12)).isoformat(),
        "end": now.isoformat(),
        "adjustment": "raw",
    })
    url = f"{API}/{urllib.parse.quote(symbol, safe='') }?{params}"
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=12) as response:
        payload = json.load(response)
    if payload.get("next_page_token"):
        raise ValueError("Unexpected paginated bars; fail closed")
    bars = []
    for raw in payload.get("bars", []):
        stamp = datetime.fromisoformat(raw["t"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Bar timestamp has no timezone")
        stamp = stamp.astimezone(timezone.utc)
        if stamp + timedelta(minutes=5) > now:
            continue  # current, incomplete candle
        values = [float(raw[k]) for k in ("o", "h", "l", "c", "v")]
        if min(values) <= 0 or values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
            continue
        bars.append({"timestamp": stamp.isoformat(), "open": values[0],
                     "high": values[1], "low": values[2],
                     "close": values[3], "volume": values[4]})
    bars.sort(key=lambda b: b["timestamp"])
    if not bars:
        raise ValueError("No completed positive-volume IEX candles")
    last_end = datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=5)
    age = (now - last_end).total_seconds()
    if age < 0 or age > MAX_AGE_SECONDS:
        raise ValueError(f"Latest completed IEX candle stale ({age:.0f}s)")
    return {"symbol": symbol, "feed": "Alpaca IEX only (not consolidated US volume)",
            "asof_utc": last_end.isoformat(), "bars": bars,
            "broker_cfd_spread": None, "broker_cfd_eligibility": "unverified"}

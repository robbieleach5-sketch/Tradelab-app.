#!/usr/bin/env python3
"""Alpaca IEX intraday educational paper engine. No broker orders."""
import json, os, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

SYMBOLS = {
    "TSLA": "tsla.us",
    "NVDA": "nvda.us",
    "AAPL": "aapl.us",
    "MSFT": "msft.us",
    "AMZN": "amzn.us",
    "GOOGL": "googl.us",
    "META": "meta.us",
    "AVGO": "avgo.us",
    "AMD": "amd.us",
    "NFLX": "nflx.us",
    "PLTR": "pltr.us",
    "CRWD": "crwd.us",
    "NET": "net.us",
    "ORCL": "orcl.us",
    "CRM": "crm.us",
    "ADBE": "adbe.us",
    "INTC": "intc.us",
    "MU": "mu.us",
    "QCOM": "qcom.us",
    "TXN": "txn.us",
    "AMAT": "amat.us",
    "LRCX": "lrcx.us",
    "KLAC": "klac.us",
    "PANW": "panw.us",
    "NOW": "now.us",
    "UBER": "uber.us",
    "SHOP": "shop.us",
    "COIN": "coin.us",
    "PYPL": "pypl.us",
    "SQ": "xyz.us",
    "JPM": "jpm.us",
    "BAC": "bac.us",
    "GS": "gs.us",
    "MS": "ms.us",
    "V": "v.us",
    "MA": "ma.us",
    "BRK.B": "brk-b.us",
    "UNH": "unh.us",
    "JNJ": "jnj.us",
    "LLY": "lly.us",
    "ABBV": "abbv.us",
    "XOM": "xom.us",
    "CVX": "cvx.us",
    "CAT": "cat.us",
    "DE": "de.us",
    "WMT": "wmt.us",
    "COST": "cost.us",
    "SPY": "spy.us",
    "QQQ": "qqq.us",
    "IWM": "iwm.us",
}
STATE = Path("data/paper_state.json")
RISK_GBP = 10.0
START_GBP = 1000.0
STOP_PCT = 0.02
TARGET_PCT = 0.04
# Fixed conversion assumption, NOT a live FX rate.
USD_PER_GBP = 1.33

def load_state():
    if STATE.exists():
        try:
            s = json.loads(STATE.read_text())
            if isinstance(s.get("positions"), dict) and isinstance(s.get("trades"), list):
                return s
        except (ValueError, OSError):
            pass
    return {"cash_gbp": START_GBP, "positions": {}, "trades": [], "last_processed": {}}

def intraday_prices(ticker):
    """Twelve Data 5-minute US stock bars. No fallback to Yahoo or Alpaca."""
    from zoneinfo import ZoneInfo
    key = os.environ.get("TWELVE_DATA_API_KEY")
    if not key:
        raise RuntimeError("Missing GitHub Actions secret TWELVE_DATA_API_KEY")
    params = urllib.parse.urlencode({"symbol": ticker, "interval": "5min",
                                      "outputsize": 90, "timezone": "America/New_York"})
    req = urllib.request.Request("https://api.twelvedata.com/time_series?" + params,
                                 headers={"Authorization": "apikey " + key,
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        payload = json.load(response)
    if payload.get("status") == "error" or "values" not in payload:
        raise ValueError("Twelve Data: " + str(payload.get("message", "No bars returned"))[:130])
    rows = []
    tz = ZoneInfo("America/New_York")
    for item in payload["values"]:
        try:
            stamp = datetime.strptime(item["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            o, h, low, close = (float(item[k]) for k in ("open", "high", "low", "close"))
            if min(o, h, low, close) > 0:
                rows.append({"timestamp": int(stamp.timestamp()), "open": o,
                             "high": h, "low": low, "close": close,
                             "volume": float(item.get("volume") or 0)})
        except (KeyError, ValueError, TypeError):
            continue
    rows.sort(key=lambda x: x["timestamp"])
    if not rows:
        raise ValueError("No valid Twelve Data bars")
    return rows


def settle_open_position(state, ticker, completed):
    """Settle the FIRST stop/target touch across ALL newly observed 5m bars.

    Scheduled scans are around 15 minutes apart, so the latest bar alone
    cannot reliably tell whether an open position hit its stop in between.
    This replays completed bars oldest first; it never retroactively opens
    a new trade based on an intermediate candle.
    """
    position = state["positions"].get(ticker)
    if not position:
        return False

    previous_timestamp = state["last_processed_intraday"].get(ticker, 0)
    try:
        entry_time = datetime.fromisoformat(position["date"])
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        entry_timestamp = int(entry_time.timestamp())
    except (ValueError, TypeError, KeyError):
        entry_timestamp = 0  # Legacy position without a parseable entry time.

    for candle in completed:
        if candle["timestamp"] <= max(previous_timestamp, entry_timestamp):
            continue
        stop_hit = candle["low"] <= position["stop_usd"]
        target_hit = candle["high"] >= position["target_usd"]
        if not stop_hit and not target_hit:
            continue

        # If both touched, assume stop first. Account for adverse open gaps.
        reason = "stop" if stop_hit else "target"
        exit_price = position["stop_usd"] if stop_hit else position["target_usd"]
        if candle["open"] < position["stop_usd"]:
            exit_price, reason = candle["open"], "gap below stop"
        elif candle["open"] > position["target_usd"]:
            exit_price, reason = candle["open"], "gap above target"

        pnl = (exit_price - position["entry_usd"]) * position["qty"] / USD_PER_GBP
        costs = (exit_price + position["entry_usd"]) * position["qty"] / USD_PER_GBP * 0.001
        pnl = round(pnl - costs, 2)
        state["cash_gbp"] = round(state["cash_gbp"] + pnl, 2)
        exit_time = datetime.fromtimestamp(candle["timestamp"], timezone.utc).isoformat()
        state["trades"].append({
            "ticker": ticker, "entry_date": position["date"],
            "exit_date": exit_time, "entry_usd": position["entry_usd"],
            "exit_usd": exit_price, "qty": position["qty"],
            "pnl_gbp": pnl, "reason": reason,
        })
        del state["positions"][ticker]
        state["events"].append(exit_time + " " + ticker + " closed " + reason)
        return True
    return False

def main(now=None):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    now = now if now is not None else datetime.now(timezone.utc)
    ny = now.astimezone(ZoneInfo("America/New_York"))
    # Avoid trading premarket, weekends and the last 15 minutes of regular session.
    regular = ny.weekday() < 5 and (9, 35) <= (ny.hour, ny.minute) < (16, 0)
    allow_entry = regular and (ny.hour, ny.minute) < (15, 45)
    state = load_state()
    for key, default in (("last_processed_intraday", {}), ("errors", {}), ("quotes", {}),
                         ("events", []), ("positions", {}), ("trades", [])):
        state.setdefault(key, default)
    if not os.environ.get("TWELVE_DATA_API_KEY"):
        state["errors"]["DATA_CONFIG"] = "Missing GitHub Actions secret TWELVE_DATA_API_KEY"
        state["updated_utc"] = now.isoformat()
        state["model"] = "Twelve Data configuration required; trading paused"
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2)+"\n")
        print("Twelve Data key not configured; no simulated trades placed")
        return
    state["errors"].pop("DATA_CONFIG", None)
    # Morning UK heartbeat: the US session is still shut. Publishing a status
    # snapshot confirms the scheduler is alive without using Twelve Data credits
    # or inventing US fills/prices before New York opens.
    if not regular:
        state["updated_utc"] = now.isoformat()
        state["run_event"] = os.environ.get("GITHUB_EVENT_NAME", "local")
        state["run_id"] = os.environ.get("GITHUB_RUN_ID", "")
        state["market_session_open"] = False
        state["model"] = ("TradeLab paper simulator on standby while US market is closed. "
                          "No US quotes fetched and no virtual trades executed.")
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2) + "\n")
        print("US market closed: TradeLab standing by, no provider requests")
        return
    # Free tier: 8 credits/minute and 800/day. Check open positions first;
    # rotate 5 additional symbols per 15-minute run to stay under limits.
    universe = list(SYMBOLS)
    slot = int(now.timestamp() // 900)
    start = (slot * 5) % len(universe)
    rotating = [universe[(start + k) % len(universe)] for k in range(5)]
    watchlist = list(state["positions"])[:3] + [s for s in rotating if s not in state["positions"]]
    watchlist = watchlist[:8]
    for ticker in watchlist:
        try:
            rows = intraday_prices(ticker)
            # Only fully completed candles; provider may include an unfinished current candle.
            completed = [b for b in rows if b["timestamp"] + 300 <= int(now.timestamp()) - 30]
            if not completed:
                raise ValueError("No completed 5-minute candles")
            bar = completed[-1]
            bar_time = datetime.fromtimestamp(bar["timestamp"], timezone.utc)
            ny_bar = bar_time.astimezone(ZoneInfo("America/New_York"))
            state["quotes"][ticker] = {"date": bar_time.isoformat(), "close_usd": round(bar["close"], 4),
                                       "source": "Twelve Data 5-minute bars (limited-venue US feed)"}
            # Never trade old candles or repeat a previously processed candle.
            if not regular or ny_bar.date() != ny.date() or (now - bar_time) > timedelta(minutes=25):
                state["errors"].pop(ticker, None)
                continue
            if bar["timestamp"] <= state["last_processed_intraday"].get(ticker, 0):
                state["errors"].pop(ticker, None)
                continue
            position = state["positions"].get(ticker)
            if position:
                settle_open_position(state, ticker, completed)
            elif allow_entry and len(state["positions"]) < 3:
                # Use completed candles only; buy at latest observed close, not a past open.
                # This is a proxy fill, not a broker-executable quote.
                previous = completed[:-1]
                if len(previous) >= 50:
                    last20 = sum(b["close"] for b in previous[-20:])/20
                    last50 = sum(b["close"] for b in previous[-50:])/50
                    breakout = bar["close"] > max(b["high"] for b in previous[-20:])
                    # Conservative entry filter: strong established uptrend, confirmed
                    # breakout, no chasing extended candles, and genuine volume.
                    # Missing/zero provider volume means NO new trade.
                    volumes = [b["volume"] for b in previous[-20:] if b.get("volume", 0) > 0]
                    avg_volume = sum(volumes) / len(volumes) if len(volumes) == 20 else 0
                    volume_ok = avg_volume > 0 and bar.get("volume", 0) >= 1.5 * avg_volume
                    trend_ok = last20 > last50 and bar["close"] > last20
                    breakout_level = max(b["high"] for b in previous[-20:])
                    not_extended = bar["close"] <= breakout_level * 1.005
                    if trend_ok and breakout and volume_ok and not_extended:
                        entry = bar["close"]
                        stop, target = entry*(1-STOP_PCT), entry*(1+TARGET_PCT)
                        risk_qty = RISK_GBP*USD_PER_GBP/(entry-stop)
                        reserved = sum(p["entry_usd"]*p["qty"]/USD_PER_GBP
                                       for p in state["positions"].values())
                        available = max(0, state["cash_gbp"]-reserved)
                        qty = round(max(0, min(risk_qty, available*USD_PER_GBP/entry)), 5)
                        if qty > 0:
                            state["positions"][ticker] = {"date": bar_time.isoformat(),
                                "entry_usd": entry, "stop_usd": round(stop, 4),
                                "target_usd": round(target, 4), "qty": qty}
                            state["events"].append(bar_time.isoformat()+" "+ticker+" opened virtual long (5m)")
            state["last_processed_intraday"][ticker] = bar["timestamp"]
            state["errors"].pop(ticker, None)
        except Exception as exc:
            state["errors"][ticker] = str(exc)[:200]
    state["updated_utc"] = now.isoformat()
    state["run_event"] = os.environ.get("GITHUB_EVENT_NAME", "local")
    state["run_id"] = os.environ.get("GITHUB_RUN_ID", "")
    state["market_session_open"] = regular
    state["model"] = ("Educational intraday 5-minute paper simulator; Twelve Data free limited-venue feed. "
                      "Proxy fills at observed candle closes; no live broker execution.")
    state["assumptions"] = {"usd_per_gbp_fixed": USD_PER_GBP, "max_risk_gbp": RISK_GBP,
                            "stop_pct": STOP_PCT*100, "target_pct": TARGET_PCT*100,
                            "round_trip_cost_pct": 0.2}
    state["events"] = state["events"][-40:]
    state["trades"] = state["trades"][-500:]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2)+"\n")
    print("Updated", state["updated_utc"], "positions", len(state["positions"]), "errors", len(state["errors"]))

if __name__ == "__main__":
    main()

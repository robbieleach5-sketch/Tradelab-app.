#!/usr/bin/env python3
"""Daily educational paper-trading engine. Never connects to a broker."""
import csv, io, json, os, urllib.request, urllib.parse
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

def prices(symbol):
    """Try Yahoo daily chart first, then Stooq. Reject unusable feeds explicitly."""
    rows = []
    errors = []
    yahoo_symbol = symbol.upper().removesuffix(".US").replace("BRK-B", "BRK-B")
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(yahoo_symbol, safe="-")
           + "?range=2y&interval=1d")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; TradeLabPaper/1.0)",
            "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = json.load(response)
        result = payload["chart"]["result"][0]
        quotes = result["indicators"]["quote"][0]
        for i, timestamp in enumerate(result["timestamp"]):
            try:
                o, h, l, c = (float(quotes[k][i]) for k in ("open", "high", "low", "close"))
                if min(o, h, l, c) <= 0:
                    continue
                day = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
                rows.append({"date": day, "open": o, "high": h, "low": l, "close": c})
            except (TypeError, ValueError, IndexError):
                continue
    except Exception as exc:
        errors.append("Yahoo: " + str(exc)[:100])
    if len(rows) < 75:
        rows = []
        try:
            url = "https://stooq.com/q/d/l/?s=" + urllib.parse.quote(symbol) + "&i=d"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as response:
                data = response.read().decode("utf-8-sig")
            for r in csv.DictReader(io.StringIO(data)):
                try:
                    row = {"date": r["Date"], "open": float(r["Open"]), "high": float(r["High"]),
                           "low": float(r["Low"]), "close": float(r["Close"])}
                    if min(row["open"], row["high"], row["low"], row["close"]) > 0:
                        rows.append(row)
                except (KeyError, ValueError, TypeError):
                    continue
        except Exception as exc:
            errors.append("Stooq: " + str(exc)[:100])
    rows.sort(key=lambda r: r["date"])
    if len(rows) < 75:
        raise ValueError("Only %d valid bars. %s" % (len(rows), "; ".join(errors)))
    return rows[-250:]

def sma(rows, end, n):
    return sum(r["close"] for r in rows[end-n:end]) / n

def signal(rows):
    # Signal on prior completed session, enter at latest session's open.
    prev = len(rows) - 1
    if prev < 71:
        return False
    prior = rows[:prev]
    return (sma(prior, len(prior), 20) > sma(prior, len(prior), 50)
            and prior[-1]["close"] > max(x["high"] for x in prior[-21:-1]))

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
    """Yahoo 5-minute candles; no daily-bar fallback or invented live prices."""
    symbol = ticker.replace("BRK.B", "BRK-B")
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(symbol, safe="-") + "?range=5d&interval=5m")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as response:
        payload = json.load(response)
    result = payload["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    rows = []
    for i, ts in enumerate(result["timestamp"]):
        try:
            o, h, l, close = (float(quote[k][i]) for k in ("open", "high", "low", "close"))
            if min(o, h, l, close) > 0:
                rows.append({"timestamp": int(ts), "open": o, "high": h, "low": l, "close": close})
        except (TypeError, ValueError, IndexError):
            pass
    return rows

def main():
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    now = datetime.now(timezone.utc)
    ny = now.astimezone(ZoneInfo("America/New_York"))
    # Avoid trading premarket, weekends and the last 15 minutes of regular session.
    regular = ny.weekday() < 5 and (9, 35) <= (ny.hour, ny.minute) < (16, 0)
    allow_entry = regular and (ny.hour, ny.minute) < (15, 45)
    state = load_state()
    for key, default in (("last_processed_intraday", {}), ("errors", {}), ("quotes", {}),
                         ("events", []), ("positions", {}), ("trades", [])):
        state.setdefault(key, default)
    for ticker in SYMBOLS:
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
                                       "source": "Yahoo Finance 5-minute candles (may be delayed)"}
            # Never trade old candles or repeat a previously processed candle.
            if not regular or ny_bar.date() != ny.date() or (now - bar_time) > timedelta(minutes=25):
                state["errors"].pop(ticker, None)
                continue
            if bar["timestamp"] <= state["last_processed_intraday"].get(ticker, 0):
                state["errors"].pop(ticker, None)
                continue
            position = state["positions"].get(ticker)
            if position:
                # Existing positions from the daily engine remain open; only process candles
                # strictly after their entry timestamp when present. Legacy positions are
                # treated as already open, not newly entered.
                if bar["low"] <= position["stop_usd"] or bar["high"] >= position["target_usd"]:
                    # Conservative stop-first assumption if both levels touched in one candle.
                    reason = "stop" if bar["low"] <= position["stop_usd"] else "target"
                    exit_price = position["stop_usd"] if reason == "stop" else position["target_usd"]
                    if bar["open"] < position["stop_usd"]:
                        exit_price, reason = bar["open"], "gap below stop"
                    elif bar["open"] > position["target_usd"]:
                        exit_price, reason = bar["open"], "gap above target"
                    pnl = (exit_price-position["entry_usd"])*position["qty"]/USD_PER_GBP
                    costs = (exit_price+position["entry_usd"])*position["qty"]/USD_PER_GBP*0.001
                    pnl = round(pnl-costs, 2)
                    state["cash_gbp"] = round(state["cash_gbp"]+pnl, 2)
                    state["trades"].append({"ticker": ticker, "entry_date": position["date"],
                        "exit_date": bar_time.isoformat(), "entry_usd": position["entry_usd"],
                        "exit_usd": exit_price, "qty": position["qty"], "pnl_gbp": pnl, "reason": reason})
                    del state["positions"][ticker]
                    state["events"].append(bar_time.isoformat()+" "+ticker+" closed "+reason)
            elif allow_entry and len(state["positions"]) < 3:
                # Use completed candles only; buy at latest observed close, not a past open.
                # This is a proxy fill, not a broker-executable quote.
                previous = completed[:-1]
                if len(previous) >= 50:
                    last20 = sum(b["close"] for b in previous[-20:])/20
                    last50 = sum(b["close"] for b in previous[-50:])/50
                    breakout = bar["close"] > max(b["high"] for b in previous[-20:])
                    if last20 > last50 and breakout:
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
    state["model"] = ("Educational intraday 5-minute paper simulator; Yahoo data may be delayed. "
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

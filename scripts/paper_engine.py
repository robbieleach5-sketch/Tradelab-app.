#!/usr/bin/env python3
"""Daily educational paper-trading engine. Never connects to a broker."""
import csv, io, json, os, urllib.request
from datetime import datetime, timezone
from pathlib import Path

SYMBOLS = {"TSLA": "tsla.us", "NVDA": "nvda.us", "AAPL": "aapl.us", "MSFT": "msft.us", "SPY": "spy.us", "QQQ": "qqq.us"}
STATE = Path("data/paper_state.json")
RISK_GBP = 10.0
START_GBP = 1000.0
STOP_PCT = 0.02
TARGET_PCT = 0.04
# Fixed conversion assumption, NOT a live FX rate.
USD_PER_GBP = 1.33

def prices(symbol):
    url = "https://stooq.com/q/d/l/?s=" + symbol + "&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "TradeLab educational paper simulator/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        data = response.read().decode("utf-8-sig")
    rows = []
    for r in csv.DictReader(io.StringIO(data)):
        try:
            row = {"date": r["Date"], "open": float(r["Open"]), "high": float(r["High"]),
                   "low": float(r["Low"]), "close": float(r["Close"])}
            if min(row["open"], row["high"], row["low"], row["close"]) > 0:
                rows.append(row)
        except (KeyError, ValueError, TypeError):
            continue
    rows.sort(key=lambda r: r["date"])
    if len(rows) < 75:
        raise ValueError("Insufficient price history")
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

def main():
    state = load_state()
    state.setdefault("last_processed", {})
    state.setdefault("errors", {})
    state.setdefault("quotes", {})
    state.setdefault("events", [])
    for ticker, code in SYMBOLS.items():
        try:
            rows = prices(code)
            bar = rows[-1]
            date = bar["date"]
            state["quotes"][ticker] = {"date": date, "close_usd": bar["close"], "source": "Stooq daily historical CSV"}
            if state["last_processed"].get(ticker) == date:
                continue
            position = state["positions"].get(ticker)
            if position:
                exit_price = None
                reason = None
                if bar["open"] <= position["stop_usd"]:
                    exit_price, reason = bar["open"], "gap below stop"
                elif bar["open"] >= position["target_usd"]:
                    exit_price, reason = bar["open"], "gap above target"
                elif bar["low"] <= position["stop_usd"]:
                    exit_price, reason = position["stop_usd"], "stop"
                elif bar["high"] >= position["target_usd"]:
                    exit_price, reason = position["target_usd"], "target"
                if exit_price is not None:
                    # 0.20% approximate round-trip costs; does not model financing.
                    pnl = (exit_price-position["entry_usd"])*position["qty"]/USD_PER_GBP
                    costs = (exit_price+position["entry_usd"])*position["qty"]/USD_PER_GBP*0.001
                    pnl = round(pnl-costs, 2)
                    state["cash_gbp"] = round(state["cash_gbp"]+pnl, 2)
                    state["trades"].append({"ticker": ticker, "entry_date": position["date"], "exit_date": date,
                                            "entry_usd": position["entry_usd"], "exit_usd": exit_price,
                                            "qty": position["qty"], "pnl_gbp": pnl, "reason": reason})
                    del state["positions"][ticker]
                    state["events"].append(date+" "+ticker+" closed "+reason)
            # Do not open and close on same bar as an existing position.
            elif signal(rows) and len(state["positions"]) < 3:
                entry = bar["open"]
                stop = entry*(1-STOP_PCT)
                target = entry*(1+TARGET_PCT)
                risk_qty = RISK_GBP*USD_PER_GBP/(entry-stop)
                # Cap exposure to available cash, accounting for other positions.
                reserved = sum(p["entry_usd"]*p["qty"]/USD_PER_GBP for p in state["positions"].values())
                available = max(0, state["cash_gbp"]-reserved)
                qty = round(max(0, min(risk_qty, available*USD_PER_GBP/entry)), 5)
                if qty > 0:
                    state["positions"][ticker] = {"date": date, "entry_usd": entry, "stop_usd": round(stop, 4),
                                                   "target_usd": round(target, 4), "qty": qty}
                    state["events"].append(date+" "+ticker+" opened virtual long")
                    # This model intentionally does NOT assess same-day stop/target for new positions.
            state["last_processed"][ticker] = date
            state["errors"].pop(ticker, None)
        except Exception as exc:
            state["errors"][ticker] = str(exc)[:200]
    state["updated_utc"] = datetime.now(timezone.utc).isoformat()
    state["model"] = "Educational daily OHLC simulator. Long-only. Historical daily feed may be delayed. No live execution."
    state["assumptions"] = {"usd_per_gbp_fixed": USD_PER_GBP, "max_risk_gbp": RISK_GBP,
                            "stop_pct": STOP_PCT*100, "target_pct": TARGET_PCT*100,
                            "round_trip_cost_pct": 0.2}
    state["events"] = state["events"][-40:]
    state["trades"] = state["trades"][-500:]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2)+"\n")
    print("Updated", state["updated_utc"], "positions", len(state["positions"]), "errors", state["errors"])

if __name__ == "__main__":
    main()

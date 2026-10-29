"""Isolated educational CFD-*style* stock proxy simulator. No CFD feed or orders.

Uses limited-venue underlying US stock OHLC bars, NOT Trading 212 CFD bid/ask
quotes. Never describes these simulated fills as executable broker prices.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PROXY_SYMBOLS = ("NVDA", "TSLA", "AMD")
START_BALANCE_GBP = 1000.0  # Separate research ledger, not added to the stock account.
MAX_POSITIONS = 2
POSITION_GBP = 150.0
MAX_ENTRIES_DAY = 3
LOSS_CUTOFF_GBP = 10.0
STOP_PCT = 0.006
TARGET_PCT = 0.012
EARLY_PROFIT_CLOSE_PCT = 0.0085
ESTIMATED_ROUND_TRIP_COST_PCT = 0.0025
ESTIMATED_DAILY_FINANCING_PCT = 0.0003
ESTIMATED_FX_RESULT_FEE_PCT = 0.005
USD_PER_GBP_ASSUMED = 1.33


def initialize(state):
    book = state.setdefault("cfd_paper", {})
    book.setdefault("cash_gbp", START_BALANCE_GBP)
    book.setdefault("positions", {})
    book.setdefault("trades", [])
    book.setdefault("last_processed", {})
    book.setdefault("diagnostics", {})
    book["source"] = "UNDERLYING_US_SHARE_PROXY_NOT_BROKER_CFD_QUOTE"
    book["execution"] = "SIMULATED_ONLY_NO_LEVERAGE_NO_BROKER_ORDERS"
    book["separate_research_account"] = True
    book["starting_balance_gbp"] = START_BALANCE_GBP
    return book


def direction_signal(bars):
    """Trend-following 5-minute long/short on verified volume and 12-bar break."""
    before = bars[:-1]
    if len(before) < 50:
        return None, "insufficient_history"
    bar = bars[-1]
    vols = [float(c.get("volume") or 0) for c in before[-20:]]
    if any(v <= 0 for v in vols) or float(bar.get("volume") or 0) <= 0:
        return None, "missing_share_volume"
    if bar["volume"] < sum(vols) / 20 * 1.3:
        return None, "weak_breakout_volume"
    slow = sum(c["close"] for c in before[-50:]) / 50
    fast = sum(c["close"] for c in before[-20:]) / 20
    high = max(c["high"] for c in before[-12:])
    low = min(c["low"] for c in before[-12:])
    if fast > slow and high < bar["close"] <= high * 1.004:
        return "long", "confirmed_long_breakout"
    if fast < slow and low * 0.996 <= bar["close"] < low:
        return "short", "confirmed_short_breakdown"
    return None, "no_qualified_long_or_short_signal"


def today_metrics(book, today):
    entries = sum(1 for p in book["positions"].values() if p["entry_day"] == today)
    entries += sum(1 for t in book["trades"] if t.get("entry_day") == today)
    realized = round(sum(float(t["pnl_gbp"]) for t in book["trades"] if t.get("exit_day") == today), 2)
    seen = {s for s, p in book["positions"].items() if p["entry_day"] == today}
    seen.update(t["ticker"] for t in book["trades"] if t.get("entry_day") == today)
    return entries, realized, seen


def close(book, ticker, bar, reason):
    pos = book["positions"][ticker]
    side = pos["side"]
    mid_exit = float(bar["close"]) if reason in ("session_exit", "early_profit_bank") else (
        float(bar["exit_proxy"])
    )
    gross = (mid_exit - pos["entry_usd"]) * pos["qty"] / USD_PER_GBP_ASSUMED
    if side == "short":
        gross = -gross
    notional = pos["entry_usd"] * pos["qty"] / USD_PER_GBP_ASSUMED
    fees = notional * ESTIMATED_ROUND_TRIP_COST_PCT
    exit_day = datetime.fromtimestamp(bar["timestamp"], timezone.utc).astimezone(
        ZoneInfo("America/New_York")).date()
    entry_day = datetime.fromisoformat(pos["entry_day"]).date()
    held_days = max(0, (exit_day - entry_day).days)
    fees += notional * ESTIMATED_DAILY_FINANCING_PCT * held_days
    fees += abs(gross) * ESTIMATED_FX_RESULT_FEE_PCT
    pnl = round(gross - fees, 2)
    book["cash_gbp"] = round(book["cash_gbp"] + pnl, 2)
    trade = {
        "ticker": ticker, "side": side, "entry_day": pos["entry_day"],
        "exit_day": exit_day.isoformat(), "entry_usd": pos["entry_usd"],
        "exit_usd": mid_exit, "qty": pos["qty"], "pnl_gbp": pnl,
        "reason": reason, "estimated_cost_gbp": round(fees, 2),
        "quote_type": "underlying_stock_proxy",
        "exit_utc": datetime.fromtimestamp(bar["timestamp"], timezone.utc).isoformat(),
    }
    book["trades"].append(trade)
    del book["positions"][ticker]
    return trade


def evaluate(book, ticker, bars, now, *, allow_new=True):
    """Update one share-CFD proxy from complete fresh underlying 5m bars."""
    if ticker not in PROXY_SYMBOLS:
        return "not_cfd_proxy"
    if not bars:
        return "no_bars"
    from datetime import timedelta
    # Only accept fresh complete candles; callers must also validate the venue.
    completed = [b for b in bars if b["timestamp"] + 300 <= now.timestamp() - 30]
    if not completed:
        return "no_completed_bars"
    latest = completed[-1]
    age = now - datetime.fromtimestamp(latest["timestamp"], timezone.utc)
    if not timedelta(minutes=5) <= age <= timedelta(minutes=25):
        return "stale_underlying_quote"
    local = now.astimezone(ZoneInfo("America/New_York"))
    candle_day = datetime.fromtimestamp(latest["timestamp"], timezone.utc).astimezone(
        ZoneInfo("America/New_York")).date()
    if local.date() != candle_day or local.weekday() >= 5:
        return "out_of_session"
    old = book["positions"].get(ticker)
    last_seen = int(book["last_processed"].get(ticker, 0))
    outcome = "no_action"
    if old:
        prior_ts = max(last_seen, int(old["entry_timestamp"]))
        for b in completed:
            if b["timestamp"] <= prior_ts:
                continue
            entry, stop, target = old["entry_usd"], old["stop_usd"], old["target_usd"]
            if old["side"] == "long":
                hit_stop, hit_target = b["low"] <= stop, b["high"] >= target
                if hit_stop or hit_target:
                    chosen = stop if hit_stop else target
                    if b["open"] < stop:
                        chosen = b["open"]
                    elif not hit_stop and b["open"] > target:
                        chosen = b["open"]
                    b = dict(b, exit_proxy=chosen)
                    close(book, ticker, b, "stop" if hit_stop else "target")
                    outcome = "closed_at_stop" if hit_stop else "closed_at_target"
                    break
                if b["close"] >= entry * (1 + EARLY_PROFIT_CLOSE_PCT):
                    close(book, ticker, b, "early_profit_bank")
                    outcome = "early_profit_bank"
                    break
            else:
                hit_stop, hit_target = b["high"] >= stop, b["low"] <= target
                if hit_stop or hit_target:
                    chosen = stop if hit_stop else target
                    if b["open"] > stop:
                        chosen = b["open"]
                    elif not hit_stop and b["open"] < target:
                        chosen = b["open"]
                    b = dict(b, exit_proxy=chosen)
                    close(book, ticker, b, "stop" if hit_stop else "target")
                    outcome = "closed_at_stop" if hit_stop else "closed_at_target"
                    break
                if b["close"] <= entry * (1 - EARLY_PROFIT_CLOSE_PCT):
                    close(book, ticker, b, "early_profit_bank")
                    outcome = "early_profit_bank"
                    break
        if ticker in book["positions"] and (local.hour, local.minute) >= (15, 35):
            close(book, ticker, latest, "session_exit")
            outcome = "session_exit"
        elif ticker in book["positions"]:
            outcome = "position_monitored"
        # No same-bar re-entry after an exit.
        book["last_processed"][ticker] = latest["timestamp"]
        return outcome
    if latest["timestamp"] <= last_seen:
        return "already_processed"
    book["last_processed"][ticker] = latest["timestamp"]
    if not allow_new or not (9, 45) <= (local.hour, local.minute) < (15, 0):
        return "entries_paused"
    today = local.date().isoformat()
    count, realized, traded = today_metrics(book, today)
    if realized <= -LOSS_CUTOFF_GBP or count >= MAX_ENTRIES_DAY:
        return "cfd_daily_risk_halt"
    if len(book["positions"]) >= MAX_POSITIONS:
        return "cfd_position_limit"
    if ticker in traded:
        return "already_traded_today"
    side, reason = direction_signal(completed)
    if not side:
        return reason
    entry = float(latest["close"])
    stop = entry * (1 - STOP_PCT if side == "long" else 1 + STOP_PCT)
    target = entry * (1 + TARGET_PCT if side == "long" else 1 - TARGET_PCT)
    reserved = sum(p["entry_usd"] * p["qty"] / USD_PER_GBP_ASSUMED
                   for p in book["positions"].values())
    available = max(0.0, book["cash_gbp"] - reserved)
    notional = min(POSITION_GBP, available)
    qty = round(notional * USD_PER_GBP_ASSUMED / entry, 6)
    if qty <= 0:
        return "insufficient_cash"
    book["positions"][ticker] = {
        "side": side, "entry_day": today, "entry_timestamp": latest["timestamp"],
        "entry_usd": entry, "stop_usd": round(stop, 5),
        "target_usd": round(target, 5), "qty": qty,
        "quote_type": "underlying_stock_proxy", "leverage": 1.0,
    }
    return "paper_cfd_proxy_entry_" + side

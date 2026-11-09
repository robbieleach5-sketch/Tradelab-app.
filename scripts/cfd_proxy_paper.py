"""Isolated educational CFD-style share and spot-gold simulator. No broker orders.

Uses underlying stock and indicative spot-gold OHLC bars, NOT Trading 212 CFD bid/ask
quotes. Never describes these simulated fills as executable broker prices.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PROXY_SYMBOLS = ("NVDA", "TSLA", "AMD")
GOLD_SYMBOL = "XAU/USD"
START_BALANCE_GBP = 1000.0  # Separate research ledger, not added to the stock account.
MAX_POSITIONS = 2
POSITION_GBP = 1000.0
MAX_ENTRIES_DAY = 3
LOSS_CUTOFF_GBP = 10.0
STOP_PCT = 0.006
TARGET_PCT = 0.012
EARLY_PROFIT_CLOSE_PCT = 0.0085
ESTIMATED_ROUND_TRIP_COST_PCT = 0.0025
ESTIMATED_DAILY_FINANCING_PCT = 0.0003
ESTIMATED_FX_RESULT_FEE_PCT = 0.005
USD_PER_GBP_ASSUMED = 1.33
# Explicit one-time user paper test request: no new entries beyond this.
# It is eligible at the next safe session ONLY if the portfolio's daily
# risk lock is cleared and an actual fresh qualifying signal is available.
ONE_SHOT_REQUESTED_UTC = "2026-10-29T14:15:28+00:00"
ONE_SHOT_EXPIRES_UTC = "2026-10-30T19:00:00+00:00"


def initialize(state):
    book = state.setdefault("cfd_paper", {})
    book.setdefault("cash_gbp", START_BALANCE_GBP)
    book.setdefault("positions", {})
    book.setdefault("trades", [])
    book.setdefault("last_processed", {})
    book.setdefault("diagnostics", {})
    book.setdefault("single_test_request", {
        "requested_utc": ONE_SHOT_REQUESTED_UTC,
        "expires_utc": ONE_SHOT_EXPIRES_UTC,
        "remaining_entries": 1,
        "status": "pending_risk_and_signal",
    })
    book["strategy"] = "ORB_5M"
    book["entry_mode"] = "recurring_paper_sessions"
    book["position_value_gbp"] = POSITION_GBP
    book["sizing_mode"] = "fixed_notional_skip_if_underfunded"
    book["source"] = "SHARE_AND_SPOT_GOLD_PROXIES_NOT_BROKER_CFD_QUOTES"
    book["gold_strategy"] = "NY_0930_ORB_5M_WITH_EURUSD_DIRECTION_FILTER"
    book["gold_macro_coverage"] = "EURUSD_PROXY_ONLY_NO_NEWS_OR_REAL_YIELD_FEED"
    book["execution"] = "SIMULATED_ONLY_NO_LEVERAGE_NO_BROKER_ORDERS"
    book["separate_research_account"] = True
    book["starting_balance_gbp"] = START_BALANCE_GBP
    return book


def opening_range(bars):
    """Require the exact regular-session opening candle, never premarket."""
    if not bars:
        return None
    day = datetime.fromtimestamp(bars[-1]["timestamp"], timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
    for bar in bars:
        at = datetime.fromtimestamp(bar["timestamp"], timezone.utc).astimezone(ZoneInfo("America/New_York"))
        if at.date() == day and (at.hour, at.minute, at.second) == (9, 30, 0):
            if 0 < bar["low"] < bar["high"]:
                return bar
    return None


def direction_signal(bars, *, require_volume=True):
    """Five-minute ORB: fresh crossing on a completed regular-session bar."""
    opening = opening_range(bars)
    if opening is None:
        return None, "missing_opening_range"
    bar = bars[-1]
    at = datetime.fromtimestamp(bar["timestamp"], timezone.utc).astimezone(ZoneInfo("America/New_York"))
    if at.weekday() >= 5 or not (9, 35) <= (at.hour, at.minute) < (10, 55):
        return None, "outside_orb_entry_window"
    if len(bars) < 2 or bars[-2]["timestamp"] != bar["timestamp"] - 300:
        return None, "missing_previous_candle"
    if require_volume and (float(bar.get("volume") or 0) <= 0 or float(opening.get("volume") or 0) <= 0):
        return None, "missing_share_volume"
    previous = bars[-2]["close"]
    if previous <= opening["high"] < bar["close"]:
        return "long", "orb_5m_long_breakout"
    if previous >= opening["low"] > bar["close"]:
        return "short", "orb_5m_short_breakout"
    return None, "no_fresh_orb_breakout"


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
        "strategy": pos.get("strategy", "legacy_breakout"),
        "ticker": ticker, "side": side, "entry_day": pos["entry_day"],
        "exit_day": exit_day.isoformat(), "entry_usd": pos["entry_usd"],
        "exit_usd": mid_exit, "qty": pos["qty"], "pnl_gbp": pnl,
        "reason": reason, "estimated_cost_gbp": round(fees, 2),
        "quote_type": pos.get("quote_type", "underlying_stock_proxy"),
        "exit_utc": datetime.fromtimestamp(bar["timestamp"], timezone.utc).isoformat(),
    }
    book["trades"].append(trade)
    del book["positions"][ticker]
    return trade


def evaluate(book, ticker, bars, now, *, allow_new=True, dollar_bars=None):
    """Update one paper share/gold proxy from complete fresh 5m bars."""
    if ticker not in (*PROXY_SYMBOLS, GOLD_SYMBOL):
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
                if old.get("strategy") != "ORB_5M" and b["close"] >= entry * (1 + EARLY_PROFIT_CLOSE_PCT):
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
                if old.get("strategy") != "ORB_5M" and b["close"] <= entry * (1 - EARLY_PROFIT_CLOSE_PCT):
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
    if not allow_new or not (9, 40) <= (local.hour, local.minute) < (11, 0):
        return "entries_paused"
    # Exits may catch up across missed scans; new entries must be timely.
    if age.total_seconds() > 420:
        return "stale_orb_entry"
    today = local.date().isoformat()
    count, realized, traded = today_metrics(book, today)
    if realized <= -LOSS_CUTOFF_GBP or count >= MAX_ENTRIES_DAY:
        return "cfd_daily_risk_halt"
    if len(book["positions"]) >= MAX_POSITIONS:
        return "cfd_position_limit"
    if ticker in traded:
        return "already_traded_today"
    side, reason = direction_signal(completed, require_volume=ticker != GOLD_SYMBOL)
    if not side:
        return reason
    if ticker == GOLD_SYMBOL:
        confirmed, reason = gold_dollar_confirmation(dollar_bars or [], latest["timestamp"], side)
        if not confirmed:
            return reason
    entry = float(latest["close"])
    opening = opening_range(completed)
    stop = float(opening["low"] if side == "long" else opening["high"])
    distance = abs(entry - stop)
    target = entry + 2 * distance if side == "long" else entry - 2 * distance
    if target <= 0:
        return "invalid_orb_target"
    reserved = sum(p["entry_usd"] * p["qty"] / USD_PER_GBP_ASSUMED
                   for p in book["positions"].values())
    available = max(0.0, book["cash_gbp"] - reserved)
    # Fixed user-requested position value; never silently downsize or borrow.
    if available < POSITION_GBP:
        return "insufficient_cash_for_fixed_position"
    from math import floor
    qty = floor(POSITION_GBP * USD_PER_GBP_ASSUMED / entry * 1e6) / 1e6
    if qty <= 0:
        return "insufficient_cash"
    book["positions"][ticker] = {
        "strategy": "ORB_5M", "opening_high": opening["high"], "opening_low": opening["low"],
        "side": side, "entry_day": today, "entry_timestamp": latest["timestamp"],
        "entry_usd": entry, "stop_usd": round(stop, 5),
        "target_usd": round(target, 5), "qty": qty,
        "quote_type": "indicative_spot_gold" if ticker == GOLD_SYMBOL else "underlying_stock_proxy", "leverage": 1.0,
        "macro_filter": "EURUSD_30M_DIRECTION_PROXY" if ticker == GOLD_SYMBOL else None,
        "requested_notional_gbp": POSITION_GBP,
        "entry_notional_gbp": entry * qty / USD_PER_GBP_ASSUMED,
        "planned_gross_stop_risk_gbp": distance * qty / USD_PER_GBP_ASSUMED,
    }
    return "paper_cfd_proxy_entry_" + side



def gold_dollar_confirmation(bars, signal_timestamp, side):
    """EUR/USD is a narrow dollar-direction proxy, NOT DXY, yields or news.

    Only use seven consecutive completed bars ending at the gold signal bar.
    EUR/USD rising supports long gold; falling supports short. Flat blocks both.
    """
    from math import isfinite
    by_time = {b["timestamp"]: b for b in bars if b["timestamp"] <= signal_timestamp}
    stamps = [signal_timestamp - 300 * i for i in range(6, -1, -1)]
    if any(t not in by_time for t in stamps):
        return False, "gold_missing_aligned_dollar_data"
    closes = [float(by_time[t]["close"]) for t in stamps]
    if any(not isfinite(c) or c <= 0 for c in closes):
        return False, "gold_invalid_dollar_data"
    change = closes[-1] / closes[0] - 1
    if (side == "long" and change > 0) or (side == "short" and change < 0):
        return True, "gold_dollar_proxy_confirmed"
    return False, "gold_dollar_proxy_not_aligned"

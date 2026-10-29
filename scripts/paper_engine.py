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
# A focused, diversified paper-trading watchlist is revisited much more
# often than the previous ~50-name full-universe rotation. These names are
# hypotheses to test, NOT proven winning stocks or live recommendations.
FOCUS_SYMBOLS = (
    "NVDA", "TSLA", "AMD", "META", "MSFT", "AAPL", "AMZN", "AVGO",
    "PLTR", "MU", "CRWD", "JPM", "XOM", "CAT", "UNH", "COST",
)
# UK large-caps are monitored only when a licensed intraday London feed
# is explicitly enabled. Twelve Data Basic does NOT offer live UK coverage.
UK_FOCUS_SYMBOLS = ("SHEL", "AZN", "HSBA", "ULVR", "BARC", "LLOY", "VOD", "BP.")
UK_CANDIDATES_PER_SCAN = 5
FOREX_SYMBOLS = ("GBP/USD", "EUR/USD")
FOREX_CANDIDATES_PER_SCAN = 2
FX_STOP_PCT = 0.0015
FX_TARGET_PCT = 0.0025
# Indicative FX mid prices are not executable; approximate round-trip spreads,
# slippage and fees via a 0.04% notional cost. No FX leverage is simulated.
FX_ROUND_TRIP_COST_RATE = 0.0004
CANDIDATES_PER_SCAN = 5
MAX_API_SYMBOLS_PER_SCAN = 8
MAX_OPEN_POSITIONS = 4
MAX_POSITION_GBP = 250.0
# Trim only oversized pre-existing positions, and only at a verified fresh
# completed market candle. Preserve their stop/target for the remaining qty.
LEGACY_POSITION_CAP_GBP = 200.0
MAX_DAILY_ENTRIES = 5
DAILY_LOSS_LIMIT_GBP = 15.0
STATE = Path("data/paper_state.json")
RISK_GBP = 5.0
START_GBP = 1000.0
STOP_PCT = 0.01
TARGET_PCT = 0.015
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

def intraday_prices(ticker, market="US"):
    """Five-minute bars for US shares, or licensed LSE intraday UK shares.

    UK prices are normalized to GBP per share. UK prices in GBX are pence,
    which must be divided by 100; never treat GBX figures as pounds.
    Missing permissions, wrong venue, stale dates or missing volumes cannot
    open a virtual trade.
    """
    from zoneinfo import ZoneInfo
    key = os.environ.get("TWELVE_DATA_API_KEY")
    if not key:
        raise RuntimeError("Missing GitHub Actions secret TWELVE_DATA_API_KEY")
    if market not in ("US", "UK", "FX"):
        raise ValueError("Unsupported exchange")
    tz_name = "Europe/London" if market == "UK" else "UTC" if market == "FX" else "America/New_York"
    params = {"symbol": ticker, "interval": "5min",
              "outputsize": 90, "timezone": tz_name}
    if market == "UK":
        params["exchange"] = "LSE"
    req = urllib.request.Request(
        "https://api.twelvedata.com/time_series?" + urllib.parse.urlencode(params),
        headers={"Authorization": "apikey " + key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        payload = json.load(response)
    if payload.get("status") == "error" or "values" not in payload:
        raise ValueError("Twelve Data: " + str(payload.get("message", "No bars returned"))[:130])
    multiplier = 1.0
    if market == "FX":
        provider_symbol = str((payload.get("meta") or {}).get("symbol") or "")
        if provider_symbol and provider_symbol.upper() != ticker.upper():
            raise ValueError("Forex provider returned a different currency pair")
    if market == "UK":
        meta = payload.get("meta") or {}
        venue = str(meta.get("exchange") or "").lower()
        if str(meta.get("mic_code") or "").upper() != "XLON" and "london" not in venue and venue != "lse":
            raise ValueError("UK data rejected: provider did not confirm London Stock Exchange")
        raw_currency = str(meta.get("currency") or "")
        if raw_currency in ("GBX", "GBp", "GBpence", "GB PENCE"):
            multiplier = 0.01
        elif raw_currency != "GBP":
            raise ValueError("UK data rejected: unsupported or missing price currency")
    rows = []
    tz = ZoneInfo(tz_name)
    for item in payload["values"]:
        try:
            stamp = datetime.strptime(item["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            o, h, low, close = (float(item[k]) * multiplier for k in ("open", "high", "low", "close"))
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


def selected_uk_candidates(now, positions):
    """Rotate a small LSE watchlist without ever requesting duplicate tickers."""
    slot = int(now.timestamp() // 900)
    start = (slot * UK_CANDIDATES_PER_SCAN) % len(UK_FOCUS_SYMBOLS)
    return [
        UK_FOCUS_SYMBOLS[(start + step) % len(UK_FOCUS_SYMBOLS)]
        for step in range(len(UK_FOCUS_SYMBOLS))
        if UK_FOCUS_SYMBOLS[(start + step) % len(UK_FOCUS_SYMBOLS)] not in positions
    ][:UK_CANDIDATES_PER_SCAN]


def select_active_watchlist(now, positions, us_active, uk_active, fx_active=False):
    """Prioritize open positions, then rotate candidates within eight API credits.

    FX and US/UK equities are allocated slots fairly when their sessions overlap.
    """
    opened = [
        ticker for ticker, pos in positions.items()
        if (ticker in FOREX_SYMBOLS and fx_active)
        or (ticker in UK_FOCUS_SYMBOLS and uk_active)
        or (ticker not in FOREX_SYMBOLS and ticker not in UK_FOCUS_SYMBOLS and us_active)
    ]
    if len(opened) >= MAX_API_SYMBOLS_PER_SCAN:
        return opened[:MAX_API_SYMBOLS_PER_SCAN]
    remaining = MAX_API_SYMBOLS_PER_SCAN - len(opened)
    us_open = {k: v for k, v in positions.items()
               if k not in FOREX_SYMBOLS and k not in UK_FOCUS_SYMBOLS}
    us_candidates = [
        ticker for ticker in selected_watchlist(now, us_open)
        if ticker not in positions
    ] if us_active else []
    uk_candidates = selected_uk_candidates(now, positions) if uk_active else []
    fx_candidates = [s for s in FOREX_SYMBOLS if s not in positions] if fx_active else []
    # Monitor every FX pair when possible. Spare credits support other exchanges.
    chosen = fx_candidates[:min(FOREX_CANDIDATES_PER_SCAN, remaining)]
    for candidate_list, cap in ((uk_candidates, 2 if us_active else UK_CANDIDATES_PER_SCAN),
                                 (us_candidates, CANDIDATES_PER_SCAN),
                                 (uk_candidates, UK_CANDIDATES_PER_SCAN)):
        for symbol in candidate_list[:cap]:
            if len(chosen) >= remaining:
                break
            if symbol not in chosen:
                chosen.append(symbol)
    return opened + chosen[:remaining]


def selected_watchlist(now, positions):
    """Monitor up to four positions first, then rotate focused entry candidates.

    Never exceed eight data calls per scan on the limited free API plan.
    """
    universe = FOCUS_SYMBOLS
    slot = int(now.timestamp() // 900)
    start = (slot * CANDIDATES_PER_SCAN) % len(universe)
    opened = list(positions)[:MAX_OPEN_POSITIONS]
    candidates = []
    for step in range(len(universe)):
        ticker = universe[(start + step) % len(universe)]
        if ticker not in positions and ticker not in candidates:
            candidates.append(ticker)
        if len(candidates) >= min(CANDIDATES_PER_SCAN, MAX_API_SYMBOLS_PER_SCAN - len(opened)):
            break
    return opened + candidates


def assess_breakout(completed):
    """Identify why a new 5-minute paper entry is rejected.

    Retain the long-term trend, positive volume and 0.5% anti-chase checks.
    A 15-bar breakout and 1.35x volume are exploratory, not validated edge.
    """
    previous = completed[:-1]
    if len(previous) < 50:
        return False, "insufficient_history"
    bar = completed[-1]
    last20 = sum(b["close"] for b in previous[-20:]) / 20
    last50 = sum(b["close"] for b in previous[-50:]) / 50
    breakout_level = max(b["high"] for b in previous[-15:])
    volumes = [b.get("volume", 0) for b in previous[-20:]]
    if len(volumes) != 20 or any(v <= 0 for v in volumes) or bar.get("volume", 0) <= 0:
        return False, "missing_volume"
    if not (last20 > last50 and bar["close"] > last20):
        return False, "trend_not_confirmed"
    if bar["close"] <= breakout_level:
        return False, "no_15bar_breakout"
    avg_volume = sum(volumes) / 20
    if bar["volume"] < 1.35 * avg_volume:
        return False, "insufficient_breakout_volume"
    if bar["close"] > breakout_level * 1.005:
        return False, "breakout_too_extended"
    return True, "qualified_breakout"


def assess_forex_breakout(completed):
    """Exploratory FX momentum breakout without fabricated spot-FX volume."""
    previous = completed[:-1]
    if len(previous) < 50:
        return False, "fx_insufficient_history"
    bar = completed[-1]
    mean20 = sum(x["close"] for x in previous[-20:]) / 20
    mean50 = sum(x["close"] for x in previous[-50:]) / 50
    level = max(x["high"] for x in previous[-12:])
    if not (mean20 > mean50 and bar["close"] > mean20):
        return False, "fx_trend_not_confirmed"
    if bar["close"] <= level:
        return False, "fx_no_breakout"
    if bar["close"] > level * 1.0015:
        return False, "fx_chase_filter"
    # Ignore flat/inactive markets; volume is not reliably available for spot FX.
    mean_range = sum((x["high"] - x["low"]) / x["close"] for x in previous[-10:]) / 10
    if mean_range < 0.00015:
        return False, "fx_low_volatility"
    return True, "qualified_fx_breakout"


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

        conversion = 1.0 if position.get("currency") == "GBP" else USD_PER_GBP
        pnl = (exit_price - position["entry_usd"]) * position["qty"] / conversion
        if position.get("asset_class") == "forex":
            # The quote is a mid, not an executable bid/ask; penalize round trip.
            costs = position["entry_usd"] * position["qty"] / conversion * FX_ROUND_TRIP_COST_RATE
        else:
            costs = (exit_price + position["entry_usd"]) * position["qty"] / conversion * 0.001
        if position.get("currency") == "GBP" and position.get("asset_class") != "forex":
            # Conservative approximation of UK share stamp duty on purchases.
            costs += position["entry_usd"] * position["qty"] * 0.005
        pnl = round(pnl - costs, 2)
        state["cash_gbp"] = round(state["cash_gbp"] + pnl, 2)
        exit_time = datetime.fromtimestamp(candle["timestamp"], timezone.utc).isoformat()
        state["trades"].append({
            "ticker": ticker, "entry_date": position["date"],
            "exit_date": exit_time, "entry_usd": position["entry_usd"],
            "exit_usd": exit_price, "qty": position["qty"],
            "pnl_gbp": pnl, "reason": reason,
            "currency": position.get("currency", "USD"),
            "asset_class": position.get("asset_class", "equity"),
        })
        del state["positions"][ticker]
        state["events"].append(exit_time + " " + ticker + " closed " + reason)
        return True
    return False

def rebalance_legacy_position(state, ticker, completed, now):
    """Partially close oversized historical US paper positions at a fresh bar.

    Do not manufacture cash by rewriting old entry sizes, sell at yesterday's
    close, or claim any realised P/L until a fresh completed candle exists.
    The existing stop/target must be checked before this optional trim.
    """
    position = state["positions"].get(ticker)
    if not position or position.get("currency", "USD") != "USD":
        return False
    if position.get("asset_class") == "forex" or position.get("rebalance_done"):
        return False
    original_qty = position["qty"]
    entry = position["entry_usd"]
    allocated = entry * original_qty / USD_PER_GBP
    if allocated <= MAX_POSITION_GBP:
        return False
    remaining_qty = round(LEGACY_POSITION_CAP_GBP * USD_PER_GBP / entry, 5)
    sale_qty = round(original_qty - remaining_qty, 5)
    if sale_qty <= 0 or not completed:
        return False
    bar = completed[-1]
    from datetime import timedelta
    if not timedelta(minutes=5) <= now - datetime.fromtimestamp(bar["timestamp"], timezone.utc) <= timedelta(minutes=25):
        return False
    exit_price = bar["close"]
    cost = (entry + exit_price) * sale_qty / USD_PER_GBP * 0.001
    pnl = round((exit_price - entry) * sale_qty / USD_PER_GBP - cost, 2)
    exit_date = datetime.fromtimestamp(bar["timestamp"], timezone.utc).isoformat()
    position["qty"] = remaining_qty
    position["rebalance_done"] = True
    state["cash_gbp"] = round(state["cash_gbp"] + pnl, 2)
    state["trades"].append({
        "ticker": ticker, "entry_date": position["date"],
        "exit_date": exit_date, "entry_usd": entry,
        "exit_usd": exit_price, "qty": sale_qty,
        "pnl_gbp": pnl, "reason": "legacy_position_partial_trim",
        "currency": "USD", "asset_class": "equity",
    })
    state["events"].append(exit_date + " " + ticker + " reduced to free virtual capital")
    return True


def ny_trade_date(value):
    """Resolve ISO timestamps to the US stock-market session day."""
    from zoneinfo import ZoneInfo
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(ZoneInfo("America/New_York")).date()
    except (TypeError, ValueError):
        return None


def daily_limits(state, session_day):
    """Count today's simulated entries and realized P/L, including older holds."""
    trades = state.get("trades", [])
    positions = state.get("positions", {})
    today_closed_entries = [t for t in trades if ny_trade_date(t.get("entry_date")) == session_day]
    today_open_entries = [
        ticker for ticker, position in positions.items()
        if ny_trade_date(position.get("date")) == session_day
    ]
    traded_today = {t.get("ticker") for t in today_closed_entries} | set(today_open_entries)
    realized = sum(
        float(t.get("pnl_gbp") or 0) for t in trades
        if ny_trade_date(t.get("exit_date")) == session_day
    )
    return len(today_closed_entries) + len(today_open_entries), round(realized, 2), traded_today


def publish_risk_status(state, session_day):
    """Expose reasons the paper engine cannot open trades today."""
    entries, realized, _ = daily_limits(state, session_day)
    committed = sum(
        p["entry_usd"] * p["qty"] /
        (1.0 if p.get("currency") == "GBP" else USD_PER_GBP)
        for p in state.get("positions", {}).values()
    )
    available = round(max(0.0, state["cash_gbp"] - committed), 2)
    hit_daily_stop = realized <= -DAILY_LOSS_LIMIT_GBP
    hit_entry_cap = entries >= MAX_DAILY_ENTRIES
    state["risk_status"] = {
        "date_us": session_day.isoformat(),
        "daily_realized_pnl_gbp": realized,
        "entries_today": entries,
        "daily_loss_halt": hit_daily_stop,
        "daily_entry_cap_reached": hit_entry_cap,
        "available_virtual_cash_gbp": available,
        "entry_pause_reason": (
            "daily_loss_limit" if hit_daily_stop else
            "daily_entry_limit" if hit_entry_cap else
            "all_cash_reserved" if available < 1.0 else
            "none"
        ),
    }


def main(now=None):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    now = now if now is not None else datetime.now(timezone.utc)
    ny = now.astimezone(ZoneInfo("America/New_York"))
    uk = now.astimezone(ZoneInfo("Europe/London"))
    # NY and London sessions are independent across daylight saving changes.
    regular = ny.weekday() < 5 and (9, 35) <= (ny.hour, ny.minute) < (16, 0)
    uk_hours = uk.weekday() < 5 and (8, 5) <= (uk.hour, uk.minute) < (16, 30)
    uk_enabled = os.environ.get("TRADELAB_UK_INTRADAY_ENABLED", "").lower() == "true"
    uk_active = uk_hours and uk_enabled
    # Default-on for free Twelve Data Basic forex; separate opt-out available.
    fx_enabled = os.environ.get("TRADELAB_FX_ENABLED", "").lower() not in ("false", "0", "off")
    fx_active = fx_enabled and uk.weekday() < 5 and (8, 5) <= (uk.hour, uk.minute) < (21, 0)
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
    state["uk_feed_status"] = ("active_market_hours" if uk_active else
                               "awaiting_live_uk_data_entitlement" if uk_hours and not uk_enabled else
                               "outside_uk_session")
    # Standby until at least one eligible exchange opens. The default UK
    # status heartbeat does NOT make paid UK requests using a Basic plan.
    if not regular and not uk_active and not fx_active:
        publish_risk_status(state, ny.date())
        state["updated_utc"] = now.isoformat()
        state["run_event"] = os.environ.get("TRADELAB_TRIGGER") or os.environ.get("GITHUB_EVENT_NAME", "local")
        state["run_id"] = os.environ.get("GITHUB_RUN_ID", "")
        state["market_session_open"] = False
        state["us_market_session_open"] = False
        state["uk_market_session_open"] = False
        state["forex_session_open"] = False
        state["model"] = ("TradeLab paper simulator on standby. US shares require the US open; "
                          "UK entries require an explicitly enabled licensed live UK feed.")
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2) + "\n")
        print("US market closed: TradeLab standing by, no provider requests")
        return
    # UK and US share one eight-credit request budget and the same virtual cash.
    # The separate UK session is opt-in until an intraday LSE entitlement exists.
    watchlist = select_active_watchlist(now, state["positions"], regular, uk_active, fx_active)
    # UK names stay visible for research, never trading via unlicensed/delayed sources.
    state["uk_research_watchlist"] = list(UK_FOCUS_SYMBOLS)
    state["uk_research_status"] = "watchlist_only_no_verified_free_live_intraday_feed"
    report = {"utc": now.isoformat(), "universe_size": len(FOCUS_SYMBOLS) + (len(UK_FOCUS_SYMBOLS) if uk_active else 0) + (len(FOREX_SYMBOLS) if fx_active else 0),
              "us_market_hours": regular, "uk_market_hours": uk_hours, "forex_market_hours": fx_active,
              "uk_feed_status": state["uk_feed_status"],
              "checked": list(watchlist), "outcomes": {}, "new_paper_entries": []}
    for ticker in watchlist:
        try:
            market = "FX" if ticker in FOREX_SYMBOLS else "UK" if ticker in UK_FOCUS_SYMBOLS else "US"
            rows = intraday_prices(ticker, market=market) if market != "US" else intraday_prices(ticker)
            # Only fully completed candles; provider may include an unfinished current candle.
            completed = [b for b in rows if b["timestamp"] + 300 <= int(now.timestamp()) - 30]
            if not completed:
                raise ValueError("No completed 5-minute candles")
            bar = completed[-1]
            bar_time = datetime.fromtimestamp(bar["timestamp"], timezone.utc)
            local_bar = bar_time.astimezone(ZoneInfo("Europe/London") if market in ("UK", "FX") else ZoneInfo("America/New_York"))
            today_local = uk.date() if market in ("UK", "FX") else ny.date()
            state["quotes"][ticker] = {"date": bar_time.isoformat(), "close_usd": round(bar["close"], 6 if market == "FX" else 4),
                                       "currency": "GBP" if market == "UK" else "USD",
                                       "asset_class": "forex" if market == "FX" else "equity",
                                       "source": "Twelve Data 5-minute forex (indicative mid)" if market == "FX"
                                                 else "Twelve Data 5-minute bars (LSE live entitlement)" if market == "UK"
                                                 else "Twelve Data 5-minute bars (limited-venue US feed)"}
            # Never trade old candles or repeat a previously processed candle.
            if local_bar.date() != today_local or not timedelta(0) <= (now - bar_time) <= timedelta(minutes=25):
                report["outcomes"][ticker] = "stale_or_outside_session"
                state["errors"].pop(ticker, None)
                continue
            if bar["timestamp"] <= state["last_processed_intraday"].get(ticker, 0):
                report["outcomes"][ticker] = "already_processed"
                state["errors"].pop(ticker, None)
                continue
            position = state["positions"].get(ticker)
            if position:
                closed = settle_open_position(state, ticker, completed)
                trimmed = (
                    not closed and market == "US" and
                    rebalance_legacy_position(state, ticker, completed, now)
                )
                report["outcomes"][ticker] = (
                    "position_closed" if closed else
                    "legacy_position_trimmed" if trimmed else "position_monitored"
                )
            elif not ((uk_active and (uk.hour, uk.minute) < (16, 15)) if market == "UK" else
                      (fx_active and (uk.hour, uk.minute) < (20, 45)) if market == "FX" else allow_entry):
                report["outcomes"][ticker] = "new_entries_closed"
            else:
                eligible, reason = (assess_forex_breakout(completed) if market == "FX"
                                    else assess_breakout(completed))
                # Re-check limits after every entry/exit in this scan.
                entries_today, realized_today, traded_today = daily_limits(state, ny.date())
                if eligible and len(state["positions"]) >= MAX_OPEN_POSITIONS:
                    reason = "portfolio_full"
                elif eligible and entries_today >= MAX_DAILY_ENTRIES:
                    reason = "daily_entry_limit"
                elif eligible and realized_today <= -DAILY_LOSS_LIMIT_GBP:
                    reason = "daily_loss_limit"
                elif eligible and ticker in traded_today:
                    reason = "already_traded_this_session"
                elif eligible:
                    entry = bar["close"]
                    stop_pct = FX_STOP_PCT if market == "FX" else STOP_PCT
                    target_pct = FX_TARGET_PCT if market == "FX" else TARGET_PCT
                    stop, target = entry*(1-stop_pct), entry*(1+target_pct)
                    fx = 1.0 if market == "UK" else USD_PER_GBP
                    risk_qty = RISK_GBP * fx / (entry-stop)
                    reserved = sum(
                        p["entry_usd"] * p["qty"] / (1.0 if p.get("currency") == "GBP" else USD_PER_GBP)
                        for p in state["positions"].values())
                    available = max(0, state["cash_gbp"] - reserved)
                    qty = round(max(0, min(risk_qty, min(available, MAX_POSITION_GBP)*fx/entry)), 5)
                    if qty > 0:
                        state["positions"][ticker] = {"date": bar_time.isoformat(),
                            "entry_usd": entry, "stop_usd": round(stop, 5 if market == "FX" else 4),
                            "target_usd": round(target, 5 if market == "FX" else 4), "qty": qty,
                            "currency": "GBP" if market == "UK" else "USD",
                            "asset_class": "forex" if market == "FX" else "equity"}
                        state["events"].append(bar_time.isoformat()+" "+ticker+" opened virtual long (5m)")
                        report["new_paper_entries"].append(ticker)
                        reason = "paper_entry_opened"
                    else:
                        reason = "insufficient_unreserved_cash"
                report["outcomes"][ticker] = reason
            state["last_processed_intraday"][ticker] = bar["timestamp"]
            state["errors"].pop(ticker, None)
        except Exception as exc:
            report["outcomes"][ticker] = "provider_error"
            state["errors"][ticker] = str(exc)[:200]
    entries_today, realized_today, _ = daily_limits(state, ny.date())
    report["entries_today"] = entries_today
    report["realized_pnl_today_gbp"] = realized_today
    publish_risk_status(state, ny.date())
    state["scan_diagnostics"] = report
    history = state.get("scan_history", [])
    if not isinstance(history, list):
        history = []
    state["scan_history"] = (history + [report])[-80:]
    state["updated_utc"] = now.isoformat()
    state["run_event"] = os.environ.get("TRADELAB_TRIGGER") or os.environ.get("GITHUB_EVENT_NAME", "local")
    state["run_id"] = os.environ.get("GITHUB_RUN_ID", "")
    state["market_session_open"] = regular or uk_active or fx_active
    state["us_market_session_open"] = regular
    state["uk_market_session_open"] = uk_active
    state["forex_session_open"] = fx_active
    state["model"] = ("Educational intraday 5-minute paper simulator; Twelve Data US limited-venue feed "
                      "and optional licensed UK intraday feed, plus indicative forex mid prices. Proxy fills at observed candle closes; "
                      "no live broker execution.")
    state["assumptions"] = {"usd_per_gbp_fixed": USD_PER_GBP, "max_risk_gbp": RISK_GBP,
                            "stop_pct": STOP_PCT*100, "target_pct": TARGET_PCT*100,
                            "max_position_gbp": MAX_POSITION_GBP,
                            "legacy_position_trim_cap_gbp": LEGACY_POSITION_CAP_GBP,
                            "max_open_positions": MAX_OPEN_POSITIONS,
                            "max_daily_entries": MAX_DAILY_ENTRIES,
                            "daily_loss_limit_gbp": DAILY_LOSS_LIMIT_GBP,
                            "breakout_bars": 15, "min_breakout_volume_multiple": 1.35,
                            "round_trip_cost_pct": 0.2,
                            "uk_share_purchase_stamp_duty_pct": 0.5,
                            "uk_intraday_enabled": uk_enabled,
                            "forex_enabled": fx_enabled,
                            "forex_stop_pct": FX_STOP_PCT*100,
                            "forex_target_pct": FX_TARGET_PCT*100,
                            "forex_cost_rate_pct": FX_ROUND_TRIP_COST_RATE*100}
    state["events"] = state["events"][-40:]
    state["trades"] = state["trades"][-500:]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2)+"\n")
    print("Updated", state["updated_utc"], "positions", len(state["positions"]), "errors", len(state["errors"]))

if __name__ == "__main__":
    main()

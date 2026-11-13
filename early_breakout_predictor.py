"""Paper-only early breakout candidate detector. No brokerage/order integration."""
from dataclasses import dataclass
from statistics import mean
from typing import Sequence

@dataclass(frozen=True)
class Candle:
    high: float
    low: float
    close: float
    volume: float

def evaluate(candles: Sequence[Candle], opening_high: float, opening_low: float) -> dict:
    """Use completed 5-minute candles only; returns an unvalidated watch signal."""
    if len(candles) < 21:
        return {"signal": "WAIT", "reason": "Need 21 completed candles"}
    if opening_high <= opening_low or any(
        c.low <= 0 or c.high < c.low or not c.low <= c.close <= c.high or c.volume < 0
        for c in candles
    ):
        return {"signal": "WAIT", "reason": "Invalid market data"}
    recent = candles[-5:]
    baseline = candles[-21:-1]
    avg_volume = mean(c.volume for c in baseline)
    if avg_volume <= 0:
        return {"signal": "WAIT", "reason": "No usable volume baseline"}
    volume_ratio = candles[-1].volume / avg_volume
    recent_range = max(c.high for c in recent) - min(c.low for c in recent)
    earlier = candles[-15:-5]
    earlier_range = max(c.high for c in earlier) - min(c.low for c in earlier)
    compression = earlier_range > 0 and recent_range <= earlier_range * 0.65
    last = candles[-1]
    upper = max(c.high for c in recent[:-1])
    lower = min(c.low for c in recent[:-1])
    bullish = last.close > upper and last.close > opening_high
    bearish = last.close < lower and last.close < opening_low
    if not compression or volume_ratio < 1.5 or not (bullish or bearish):
        return {"signal": "WAIT", "compression": compression,
                "volume_ratio": round(volume_ratio, 2), "reason": "No confirmed setup"}
    direction = "BUY" if bullish else "SELL"
    entry = last.close
    stop = min(c.low for c in recent) if bullish else max(c.high for c in recent)
    risk = abs(entry - stop)
    if risk <= 0:
        return {"signal": "WAIT", "reason": "Invalid stop distance"}
    target = entry + 2 * risk if bullish else entry - 2 * risk
    if target <= 0:
        return {"signal": "WAIT", "reason": "Invalid target"}
    return {"signal": direction, "entry": entry, "stop": stop,
            "target": target, "reward_risk": 2.0,
            "volume_ratio": round(volume_ratio, 2),
            "compression": compression, "mode": "PAPER_ONLY",
            "warning": "Candidate signal, not a calibrated probability or prediction"}

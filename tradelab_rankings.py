"""Dependency-free, paper-only trader ranking and signal journal."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import math

@dataclass(frozen=True)
class ClosedTrade:
    pnl: float
    risk: float  # positive amount initially risked

def score_trader(trades: list[ClosedTrade]) -> dict:
    """Score verified closed trades only; no data means unranked."""
    if len(trades) < 30 or any(not math.isfinite(t.pnl) or not math.isfinite(t.risk) or t.risk <= 0 for t in trades):
        return {"score": None, "rank": "Unranked", "reason": "Need >=30 valid closed trades"}
    returns = [t.pnl / t.risk for t in trades]
    wins = sum(x > 0 for x in returns)
    gross_win = sum(max(x, 0) for x in returns)
    gross_loss = -sum(min(x, 0) for x in returns)
    pf = gross_win / gross_loss if gross_loss else (5.0 if gross_win else 0.0)
    equity = peak = drawdown = 0.0
    for x in returns:
        equity += x
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    # Scores reflect both return quality and risk; cap outsized metrics.
    score = round(min(10.0, max(0.0,
        3.0 + min(pf, 3.0) * 1.2 + min(max(sum(returns)/len(returns), -1), 1) * 1.5
        + wins/len(returns) * 1.5 - min(drawdown, 10) * 0.3)), 2)
    rank = "Diamond" if score >= 9.75 else "Gold" if score >= 8.5 else "Silver" if score >= 7.5 else "Unranked"
    return {"score": score, "rank": rank, "trades": len(trades), "win_rate": round(wins/len(trades), 4),
            "profit_factor": round(pf, 3), "max_drawdown_r": round(drawdown, 3)}

def record_signal(path: str, *, source: str, symbol: str, side: str,
                  entry: float, stop: float, target: float, observed_at: str,
                  strategy: str = "ORB", status: str = "observed") -> dict:
    """Append a timestamped observation. Never places an order."""
    if side not in ("BUY", "SELL") or status not in ("observed", "paper_only"):
        raise ValueError("Invalid side or status")
    if not all(math.isfinite(x) and x > 0 for x in (entry, stop, target)):
        raise ValueError("Prices must be positive and finite")
    if not ((stop < entry < target) if side == "BUY" else (target < entry < stop)):
        raise ValueError("Stop/entry/target ordering invalid")
    timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Signal timestamp must include timezone")
    if not source.strip() or not symbol.strip():
        raise ValueError("Source and symbol required")
    row = {"source": source, "symbol": symbol, "side": side, "entry": entry,
           "stop": stop, "target": target, "observed_at": timestamp.isoformat(),
           "strategy": strategy, "status": status,
           "reward_risk": round(abs(target-entry)/abs(entry-stop), 3),
           "recorded_at": datetime.now(timezone.utc).isoformat()}
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row

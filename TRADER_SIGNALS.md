# TradeLab trader ranking and signal journal (experimental)

This module is **paper-only**. It never sends broker orders, subscribes to external trader feeds, or changes the live scanner.

## Run tests
```bash
python -m unittest -v test_tradelab_rankings
```

## Ranking
Use `score_trader([ClosedTrade(pnl, initial_risk), ...])` with at least 30 **verified, closed** trades. Profit factor, win rate, expectancy in R, and drawdown in R contribute to a provisional 0–10 score. These thresholds and weights are **experimental**, not independently validated or a prediction of future performance. Unverified or insufficient history is unranked.

## Signals
`record_signal(...)` appends a JSONL observation with source, instrument, side, UTC-offset timestamp, stop, target, and reward/risk. Entries are **not** executions. Do not confuse observed signals with filled trades. No broker credentials or secrets are needed.

## Integration gates
1. Inventory the actual running scanner deployment and its provider errors.
2. Confirm legitimate access and terms for any external trader signal feed (including Invo); do not scrape protected endpoints.
3. Map source timestamps, exchange timezone, stale-data limits, symbols, spread, and commissions.
4. Add deterministic backtests, forward paper tests, and monitoring for missing/duplicate signals.
5. Require explicit opt-in before any live execution. Default remains disabled.

Current repository root README is minimal; this branch deliberately avoids guessing the scanner's runtime or deployment structure.

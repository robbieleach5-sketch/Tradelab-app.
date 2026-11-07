# CFD-style paper research (NOT real CFD trading)

## Five-minute opening range breakout (7 November 2026)

The user-requested ORB replaces the expired one-shot entry restriction with recurring paper sessions. Historical trades, cash and existing positions are retained. Old positions retain their original exits.

- Use the exact 09:30–09:35 America/New_York stock candle; missing opening data means no entry. Time zone conversion follows US daylight saving.
- A later completed five-minute candle must close across the opening high (long) or low (short), with the preceding consecutive candle closing on or inside that boundary. Wicks and continuation candles do not trigger entries. Opening and signal volume must be positive; no relative-volume filter is imposed.
- Earliest entry is after 09:40 plus the existing 30-second completion buffer. No entries at/after 11:00 New York. The latest bar must be at most seven minutes old measured from its start. Quotes remain underlying-share proxies, and entries are hypothetical observed candle closes, not broker fills.
- Stop at the opposite opening-range edge; gross target at twice the entry-to-stop distance. ORB positions do not use the old early-profit bank. Each new entry uses £1,000 of unleveraged position value (rounded down to six decimal shares). This replaces the £5 gross-stop-risk sizing cap: planned loss varies with range width, and gaps/costs can increase losses. Skip entries with less than £1,000 unreserved cash; no borrowing, automatic funding or smaller entries. Existing positions keep their quantities.
- One entry per symbol per New York day, three total, two simultaneous positions; £10 CFD daily realised-loss lock and the primary account loss lock continue. Session exits remain best-effort.
- NVDA, TSLA and AMD receive priority during the entry window within the existing eight-symbol data budget. Open primary positions take precedence. The roughly ten-minute GitHub schedule can miss signals; freshness checks intentionally skip late entries.
- No brokerage connection or real orders are added. No profitability claim or historical performance backtest is implied.

## What is supported
- A *separate* initial £1,000 demonstration ledger (`cfd_paper` inside the published `data/paper_state.json`). It is not added to or funded from the main stock/forex paper account. All balances are hypothetical.
- Long **and** short CFD-*style* exposure to NVDA, TSLA and AMD, using the very same limited-venue Twelve Data **underlying stock 5-minute OHLC bars** the main scanner already fetches. **No genuine CFD bid/ask quotes are available**, so simulated spreads and fills cannot be validated as executable Trading 212 CFD prices.
- One-times notional exposure (no actual leverage), £1,000 simulated position value per new trade, up to 2 open positions, 3 entries per US session, £10 maximum daily realised loss before halting new demo entries. Only fresh, completed 5-minute bars can open or settle a paper position; if a scheduled job is missed, exits are also missed until the next usable scan.
- ORB range-based stops and 2R gross targets as above, with stop-first conservative ordering when both levels are touched within a five-minute candle. Legacy positions retain their previous fixed stop/target and early profit bank.
- Costs are synthetic assumptions: 0.25% of entry notional per round trip for spread/slippage, 0.03% notional/day held for financing, plus 0.5% of *gross* result as an approximate FX conversion fee. Costs are not broker quotes; actual costs/spread can change. Targets are not net guaranteed returns.
- Tries to close remaining positions from 15:35 New York time using fresh completed candles; **not a guaranteed flat-at-close strategy** because GitHub Actions can be late or unavailable. Overnight positions incur the synthetic financing assumption at next observed exit.
- If the primary TradeLab account has already hit its £15 realised daily loss limit, no new CFD demo entries are permitted that day. Existing demo positions continue to be monitored.
- Read all CFD demo trades and current positions under **CFD-style DEMO** in the bot dashboard, distinctly from the original paper portfolio.

## Why no real CFD execution
Trading 212's public API currently supports Invest and Stocks ISA accounts only; its CFD account does not expose API order entry. TradeLab has **no broker account integration** and creates **no actual orders**. A real CFD implementation would require a properly supported, separately authorized brokerage API and reliable provider bid/ask prices.

CFDs are high-risk leveraged derivatives with variable spreads, potential margin calls and overnight financing. This model intentionally avoids leverage, and its proxy price results should not be treated as evidence of achievable CFD profits. Do not fund live leveraged trading based on early paper results.

References:
- https://docs.trading212.com/api/positions
- https://helpcentre.trading212.com/hc/en-us/articles/11471872562461-What-are-the-fees-in-the-CFD-account
- https://www.fca.org.uk/firms/contract-for-differences


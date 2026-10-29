# CFD-style paper research (NOT real CFD trading)

## What is supported
- A *separate* initial £1,000 demonstration ledger (`cfd_paper` inside the published `data/paper_state.json`). It is not added to or funded from the main stock/forex paper account. All balances are hypothetical.
- Long **and** short CFD-*style* exposure to NVDA, TSLA and AMD, using the very same limited-venue Twelve Data **underlying stock 5-minute OHLC bars** the main scanner already fetches. **No genuine CFD bid/ask quotes are available**, so simulated spreads and fills cannot be validated as executable Trading 212 CFD prices.
- One-times notional exposure (no actual leverage), up to £150 simulated position value per trade, up to 2 open positions, 3 entries per US session, £10 maximum daily realised loss before halting new demo entries. Only fresh, completed 5-minute bars can open or settle a paper position; if a scheduled job is missed, exits are also missed until the next usable scan.
- 0.6% underlying stop distance, 1.2% target and optional early profit bank at 0.85% move (gross), with stop-first conservative order when both levels are touched within a 5-minute candle.
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

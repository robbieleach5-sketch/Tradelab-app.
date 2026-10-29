# TradeLab free three-market research and paper trading

## Active with existing Twelve Data Basic API key

- US stock paper trading: existing 5-minute Twelve Data limited-venue US feed, same open, risk limits, and legacy positions.
- London morning forex paper trading: GBP/USD and EUR/USD, weekday scans from the first scheduled run around 08:09 Europe/London to approximately 21:00 UK. Forex is enabled by default; to disable, set the GitHub Actions repository variable `TRADELAB_FX_ENABLED=false` (and, when used, pass that variable through the workflow environment).
- London shares: a visible research watchlist (SHEL, AZN, HSBA, ULVR, BARC, LLOY, VOD, BP.). No automatic UK share paper entries using unofficial, delayed, or unlicensed quotes. The separate opt-in Twelve Data UK live intraday integration remains disabled unless the user has access and enables `TRADELAB_UK_INTRADAY_ENABLED=true`.

## Risk and market-data limitations

- The free Twelve Data Basic quota is 8 API credits/minute, 800/day; one 5-minute time series costs approximately 1 credit/symbol. The engine caps itself at eight series/scan while the 15-minute scheduler is active. GitHub Actions cron is best effort, so this is *not* a continuous execution system.
- Forex is not exchange-traded share volume; it uses a separate breakout filter with trend and volatility rather than making up spot-FX volume. The strategy is experimental and not validated for profitability.
- New forex trades use a 0.15% stop, 0.25% profit target, £250 maximum allocated notional per trade, *no leverage*, and a modelled 0.04% round-trip mid-price cost. These are assumptions, not actual firm bids/asks. Real spreads can vary substantially, especially near data releases; no profit edge is implied.
- All open positions compete for the same £1,000 original virtual cash. Older XOM and CAT paper holdings reserve most of it; *no extra virtual capital is created* for forex. All assets share the existing overall maximum 4 positions, 5 paper entries/day, and £15 realised daily loss gate.
- Quote timestamps, market hours, completed-bar checks, per-position stops and targets, and per-symbol anti-reentry checks remain in place. Forex stop/target prices retain five decimals.
- Yahoo Finance's official help lists LSE data at about 20 minutes delay and says the information is not intended for trading. Do not use delayed Yahoo prices to simulate executable live London stock entry fills.
- This app places NO actual broker orders. All cash conversion from USD quotes uses the pre-existing fixed assumed rate USD_PER_GBP=1.33. The paper history is not an audited brokerage performance record.

Sources:
- https://twelvedata.com/pricing
- https://twelvedata.com/forex
- https://help.yahoo.com/kb/finance/article-exchanges-data-delays-sln2310.html

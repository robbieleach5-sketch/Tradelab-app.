# Optional 08:00 London paper-trading session

## Default (no extra subscription)
- US virtual trading is unchanged and continues to use the existing Twelve Data feed.
- The automatic workflow now publishes a status heartbeat from about 08:09 UK time on weekdays (GitHub Actions scheduling is best effort and can be delayed).
- UK paper entries remain **off** unless GitHub Actions repository variable `TRADELAB_UK_INTRADAY_ENABLED` is explicitly set to `true`. The state reports `uk_feed_status: awaiting_live_uk_data_entitlement`.
- A free Basic Twelve Data API key does **not** provide UK real-time LSE 5-minute bars. Grow has UK EOD coverage; Twelve Data lists UK real-time market data under Pro. Do not upgrade just to test a £1,000 paper strategy without evaluating costs.
  Source: https://twelvedata.com/stocks

## Activation after independently verifying live market-data rights
1. Confirm the connected Twelve Data account permits **live LSE 5-minute** time series for the desired LSE symbols and your intended usage (including non-display bot usage). Do not confuse EOD or delayed data with live intraday access.
2. Retain `TWELVE_DATA_API_KEY` as a GitHub Actions **secret**. Never place API keys in source files.
3. Set Actions repository **variable** `TRADELAB_UK_INTRADAY_ENABLED=true`. The default when absent is off.
4. Inspect the first UK scan diagnostics, `uk_feed_status`, venue and GBP quote labels, then evaluate paper trading against real intraday price timestamps. Disable the variable immediately if provider responses are rejected or stale.
5. UK listed tickers are a starter hypothesis: SHEL, AZN, HSBA, ULVR, BARC, LLOY, VOD, BP. Provider symbols/eligibility may need validation before enablement. The engine rejects uncertain venue and currency metadata.

## Risk and simulation limits
- This is **paper trading only**; no broker orders.
- London shares: LSE main hours 08:00–16:30 Europe/London on eligible weekdays. The bot waits until 08:05 for completed 5-minute candles, attempts its first scheduled check around 08:09, stops opening new UK positions after 16:15, and never opens on stale, wrong-date or future-dated bars.
- Existing US trades keep their USD position fields and targets. New UK prices are normalized to GBP, with GBX and GBp converted from pence. Legacy `entry_usd`/stop/target keys hold UK GBP prices when `currency: GBP` is present; both dashboards display the correct currency.
- Both sessions share the same virtual cash, position ceiling (4), session entry ceiling (5), daily realized loss guard (£15), and 8-request-per-scan API limit.
- UK paper settlement includes approximate 0.5% share purchase stamp duty and 0.2% round-trip trading cost. This is a simplification (instrument exemptions, stamp taxes, spread, volatility, market holidays, corporate actions and trading fees vary). No strategy edge is established by these settings.
- GitHub scheduled runs are best effort, not guaranteed at precise times.

Source: https://www.londonstockexchange.com/en/resources/faqs/personal-investing

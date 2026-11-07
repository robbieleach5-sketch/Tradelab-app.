# Alpaca IEX data for the personal paper bot

Implemented, but activation requires account credentials. No TradingView subscription or broker funding is needed for this integration. The adapter only makes GET requests to Alpaca's data host; it cannot submit real orders.

## Activate

1. Use an Alpaca paper account with Basic market data and generate paper API credentials in its dashboard.
2. In this repository's Settings > Secrets and variables > Actions, save repository secrets `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`. Never paste keys into chat, source code or an issue.
3. Set repository variable `TRADELAB_US_DATA_PROVIDER` to `alpaca`.
4. Run the **Twelve Data virtual trading** workflow manually during US market hours. The existing name is retained for compatibility. Verify `us_data_provider: alpaca`, `us_feed_coverage: IEX_ONLY`, and fresh quote timestamps in the portfolio. Confirm `errors` contains no configuration or US-symbol failures.

The tools available during implementation cannot provision these account credentials or change Actions secrets/variables. Until step 3, the existing Twelve Data configuration stays selected. This is not a verified live connection yet.

Alpaca supplies US equities only here. Existing Twelve Data credentials remain necessary for FX and the separately opted-in UK feed. Without those credentials, the Alpaca-only configuration disables FX/UK requests. Provider failures never silently switch US feeds.

## ORB behaviour

The existing simulator retains its NVDA/TSLA/AMD universe, first 09:30–09:35 New York candle range, later completed-candle crossing, maximum three entries per day, one entry per symbol, and £1,000 fixed notional. Existing cash, position and loss limits still apply. £1,000 is position value, not a promised profit or leverage setting.

When Alpaca is selected, scheduled US-session checks target five-minute intervals. Other times and the Twelve Data configuration retain a ten-minute throttle. GitHub Actions is best-effort: queued/delayed jobs can miss an entry. Freshness filters remain enforced; this is not continuous real-time execution. A persistent worker is needed for dependable every-candle evaluation.

IEX is a single exchange: its candles and volume differ from consolidated US data and Trading 212 CFD quotes. Historical data already in the ledger retains its original source. Do not interpret mixed-provider performance as a clean strategy comparison. Only personal paper research is intended; external redistribution requires separate entitlement review.

## Validation

Unit tests cover read-only request construction, required credentials, IEX selection, malformed/nonfinite bars, wrong symbols, ordering, duplicate bars and explicit provider routing. Existing paper-engine regression tests also run. Live data validation still requires credentials and an open market; no performance or profitability claim follows from passing tests.

References: https://docs.alpaca.markets/us/docs/about-market-data-api and https://docs.alpaca.markets/us/reference/stockbarsingle-1

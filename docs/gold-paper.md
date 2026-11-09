# Gold paper trading (9 November 2026)

XAU/USD uses Twelve Data indicative spot gold, not futures, a gold ETF or an executable Trading 212 CFD quote. The existing key must have commodity data access; provider denial/missing data blocks entries and is shown in Feed status. No subscription is purchased or real orders placed.

## Rules

- Shares the existing `cfd_paper` ledger: no additional funding, £1,000 fixed unleveraged exposure, up to three combined entries/day, two open positions, one entry/instrument/day, £10 realised daily loss pause. Primary-account loss protection remains. Underfunded trades are skipped.
- Uses the 09:30–09:35 New York gold candle as a **chosen reference range**, not a gold exchange opening. Completed five-minute close crossing above/below this range triggers a candidate long/short. No invented spot volume requirement. Entry window ends at 11:00 New York. DST follows New York; normally 14:30 reference time in Britain, with seasonal mismatch weeks.
- Requires seven consecutive EUR/USD bars ending at the same timestamp as the gold signal. Its 30-minute change must be positive for long gold, negative for short. Flat, missing, future-only or stale alignment blocks entry. EUR/USD is an imperfect dollar-direction proxy, not DXY or a direct causal predictor.
- No live news, economic calendar, central-bank purchases or real-yield feed is connected. This is a technical-plus-currency research hypothesis, not a full macro strategy or evidence of profitability.
- Stop at the opposite reference-range edge; target at 2x gross stop distance. No early profit bank. Conservative stop-first ordering if both touched; gaps can exceed the stop. Modelled costs reduce net reward/risk below 2:1. Existing synthetic costs and fixed GBP/USD 1.33 conversion are unchanged.
- Stop/target evaluation does not require EUR/USD. Session close is best-effort from 15:35 New York using fresh completed gold bars. No fills are invented if gold data is unavailable. Scheduled scans may miss signals/exits; this is not continuous broker execution.
- Gold and EUR/USD fit inside the eight-symbol scan budget. Primary open positions and held CFD demo positions take priority. No gold request goes to Alpaca's stock API. Existing stock strategies and historical balances remain intact.

## Verification

Offline regression tests cover both sides, dollar alignment, stop-first exits without dollar data, shared capital/risk limits, provider identity, malformed quotes and main-engine integration. Manually dispatch `Gold data availability check` to verify the existing key can fetch XAU/USD; this check places no simulated or real trades and changes no portfolio state.

Provider reference: https://twelvedata.com/exchanges/COMMODITY

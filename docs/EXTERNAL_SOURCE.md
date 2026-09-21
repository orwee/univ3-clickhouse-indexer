# The external source: GeckoTerminal daily volume

A second source of daily USD volume per pool, independent of this pipeline, to
reconcile against. No API key. Loaded by `make fetch-external` into
`external_daily_volume` (`sql/002_external_daily_volume.sql`).

## What the official documentation says (read on 2026-09-20)

| Fact | Source |
|---|---|
| Endpoint `GET /networks/{network}/pools/{pool_address}/ohlcv/{timeframe}`, base URL `https://api.geckoterminal.com/api/v2`, `timeframe` one of `day`, `hour`, `minute` | OpenAPI spec: <https://api.geckoterminal.com/docs/v2/swagger.json> |
| `limit` up to 1000 candles, `before_timestamp` to page backwards, `currency` `usd` or `token`, `aggregate` 1 for `day` | same |
| Version header `Accept: application/json;version=20230203` | same |
| "All endpoints listed below are cached for **1 minute**" | same |
| Rate limit: "approximately **10 calls/minute**, which may fluctuate based on network traffic" | same |
| Rate limit: "set at **30 calls per minute**" | FAQ: <https://apiguide.geckoterminal.com/faq> |

The two official pages disagree on the rate limit. The client assumes the lower
one and leaves 7 seconds between requests.

**Not documented anywhere I found:** how far back the daily history goes, which
day boundary a daily candle uses, how volume is converted to USD, and whether
any trades are filtered. The first two were observed; the last two are unknown.

## What was observed (2026-09-20, 4 pools, 6 real calls in total)

- **Day boundary: 00:00:00 UTC.** Every one of the 735 candles has a timestamp
  that is an exact multiple of 86,400. A test asserts it on the recorded
  responses. This project's `block_date` is also the UTC day.
- **History: 184 candles per pool**, reaching back to 2026-03-20 (about six
  months), although 1,000 were asked for. The 30-day window is covered. (Fetched again on
  2026-09-20 and 2026-09-21: 184 to 185 candles per pool, 739 rows in all, still reaching
  back to March, and the 43-day window is covered too.)
- **Days without trades are omitted**, not reported as zero: the quiet pool
  (wstETH/USDC 0.3%) has fewer candles than days in its span. A missing day is
  not a zero.
- **The source repeated a candle.** For wstETH/USDC 0.3%, 2026-03-19 came twice:
  same timestamp, same volume, a different `open`. It is outside the window. The
  parser keeps one copy when timestamp and volume are identical, logs a warning,
  and refuses to choose if two candles of one day differ in volume.
- The last candle is the current, still open day: its volume keeps changing
  until midnight UTC.

## The table

`ReplacingMergeTree(fetched_at)`, `ORDER BY (source, pool_address, date)`. This
data can be fetched again and can change, so a new fetch inserts new rows and the
newest `fetched_at` wins **when parts merge**. Until then both are there:

```
pool 0xe055…, fetched twice:  368 rows, 184 distinct days
sum(volume_usd) over the window without FINAL:  2,962,008,967   (twice the real figure)
```

**Every read of this table says `FINAL`.** With a few hundred rows it costs
nothing. `volume_usd` is `Float64` because the source publishes a JSON float.

Raw response bodies are kept outside the working copy, under
`<data dir>/external/geckoterminal/`. The four bodies of the first load are
committed unmodified as test fixtures in `tests/fixtures/geckoterminal/`.

## Hourly candles, for localising a day that differs

`make fetch-external-hourly` loads the last 1,000 hourly candles per pool (about 41 days; the
same endpoint with the `hour` timeframe, one call per pool) into `external_hourly_volume`
(`sql/004_external_hourly_volume.sql`, same `ReplacingMergeTree(fetched_at)` + `FINAL` rules).
They are not part of the reconciliation itself. The evidence report uses them to say in which
hours of a flagged pool-day the two sources part. Observed on 2026-09-20: the 24 hourly
candles of a day add up to its daily candle to the dollar, every timestamp is on the hour, and
hours without trades are omitted, as days are.

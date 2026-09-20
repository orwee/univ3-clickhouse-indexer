-- Hourly USD volume per pool from the same external source as the daily table. It exists for
-- one purpose: when a pool-day does not reconcile, to see in WHICH HOURS the two sources part.
-- Same rules as external_daily_volume: re-fetchable, ReplacingMergeTree(fetched_at), FINAL on
-- every read. The source serves at most 1,000 hourly candles per call (about 41 days).

CREATE TABLE IF NOT EXISTS external_hourly_volume
(
    source        LowCardinality(String),
    pool_address  LowCardinality(String),
    hour          DateTime('UTC'),          -- start of the hour, the source's own timestamp
    volume_usd    Float64,
    fetched_at    DateTime('UTC')
)
ENGINE = ReplacingMergeTree(fetched_at)
ORDER BY (source, pool_address, hour)

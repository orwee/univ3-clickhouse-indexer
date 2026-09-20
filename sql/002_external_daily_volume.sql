-- Daily volume per pool as published by an EXTERNAL source, kept to reconcile against.
-- Unqualified name: the database comes from the session, like raw_swaps.
--
-- ReplacingMergeTree(fetched_at): unlike chain data, this data is re-fetchable and can
-- change (a source revises a day, or today's candle is still open). Fetching again
-- inserts new rows with a newer fetched_at; rows with the same sorting key are replaced
-- by the newest one WHEN PARTS MERGE, which is eventual. So every read of this table
-- says FINAL (or argMax(..., fetched_at)). It is a few hundred rows: FINAL is free here.
--
-- volume_usd is Float64 because the source publishes a JSON float. Storing it as a
-- Decimal would claim a precision the source does not have.

CREATE TABLE IF NOT EXISTS external_daily_volume
(
    source        LowCardinality(String),   -- 'geckoterminal'
    pool_address  LowCardinality(String),   -- lower-case, as everywhere in ClickHouse
    date          Date,                     -- the source's own day; see docs/EXTERNAL_SOURCE.md
    volume_usd    Float64,
    close_usd     Float64,                  -- closing price of the pool's base token, in USD
    fetched_at    DateTime('UTC')
)
ENGINE = ReplacingMergeTree(fetched_at)
ORDER BY (source, pool_address, date)

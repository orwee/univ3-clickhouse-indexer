-- Aggregate of the cross between raw_swaps and the smart-money DEX trades of the Nansen API:
-- per pool and UTC day, how many of OUR swaps sit in a transaction that Nansen attributes to
-- a smart-money trader, and their USD volume (stablecoin leg at 1 USD).
--
-- Aggregates only. No transaction hash, no address and no label reaches ClickHouse: the raw
-- responses stay outside the repo and outside the database (docs/NANSEN.md).
--
-- A row exists for every pool-day INSIDE the window that was fetched, zeros included: a
-- missing row means "not fetched", never "no smart money". ReplacingMergeTree(computed_at):
-- recomputing inserts newer rows for the same key, so every read says FINAL.

CREATE TABLE IF NOT EXISTS nansen_smart_money_daily
(
    pool_address        LowCardinality(String),
    date                Date,                    -- UTC day, as block_date everywhere else
    named_swaps         UInt64,                  -- our swaps whose transaction Nansen names
    named_transactions  UInt64,
    named_volume_usd    Float64,                 -- Float64: it is divided by a float share
    token_symbol        LowCardinality(String),  -- the token whose trades were fetched
    window_from         DateTime('UTC'),         -- the fetched window this row belongs to
    window_to           DateTime('UTC'),
    computed_at         DateTime('UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (pool_address, date)

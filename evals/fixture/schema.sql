-- The five dbt marts, as `SHOW CREATE TABLE` printed them, with the database name
-- removed: the database comes from the session. Written by
-- scripts/export_marts_fixture.py; do not edit by hand.

CREATE TABLE dim_pools
(
    `pool_address` String,
    `pool_label` String,
    `token0` String,
    `token1` String,
    `decimals0` UInt8,
    `decimals1` UInt8,
    `fee` UInt32,
    `fee_fraction` Decimal(18, 6),
    `fee_percent` Decimal(18, 4)
)
ENGINE = MergeTree
ORDER BY tuple()
SETTINGS replicated_deduplication_window = '0', index_granularity = 8192;

CREATE TABLE fct_pool_daily
(
    `pool_address` LowCardinality(String),
    `block_date` Date,
    `pool_label` String,
    `fee` UInt32,
    `swaps` UInt64,
    `volume_token0` Decimal(76, 18),
    `volume_token1` Decimal(76, 18),
    `volume_usd` Nullable(Decimal(76, 18)),
    `fees_usd` Nullable(Decimal(76, 18))
)
ENGINE = MergeTree
ORDER BY (pool_address, block_date)
SETTINGS replicated_deduplication_window = '0', index_granularity = 8192;

CREATE TABLE fct_pool_daily_round_trips
(
    `pool_address` LowCardinality(String),
    `block_date` Date,
    `pool_label` String,
    `swaps` UInt64,
    `volume_usd` Nullable(Decimal(76, 18)),
    `round_trips` UInt64,
    `round_trip_swaps` UInt64,
    `round_trip_swaps_in_one_transaction` UInt64,
    `round_trip_volume_usd` Decimal(76, 18),
    `net_volume_usd` Nullable(Decimal(76, 18)),
    `round_trip_share_of_volume_usd` Float64
)
ENGINE = MergeTree
ORDER BY (pool_address, block_date)
SETTINGS replicated_deduplication_window = '0', index_granularity = 8192;

CREATE TABLE fct_pool_daily_smart_money
(
    `pool_address` LowCardinality(String),
    `block_date` Date,
    `pool_label` String,
    `swaps` UInt64,
    `volume_usd` Nullable(Decimal(76, 18)),
    `smart_money_swaps` UInt64,
    `smart_money_transactions` UInt64,
    `smart_money_volume_usd` Float64,
    `smart_money_share_of_swaps` Float64,
    `smart_money_share_of_volume_usd` Nullable(Float64),
    `fetched_by_token` LowCardinality(String),
    `computed_at` DateTime('UTC')
)
ENGINE = MergeTree
ORDER BY (pool_address, block_date)
SETTINGS replicated_deduplication_window = '0', index_granularity = 8192;

CREATE TABLE fct_round_trip_legs
(
    `pool_address` LowCardinality(String),
    `block_number` UInt64,
    `log_index` UInt32,
    `block_timestamp` DateTime('UTC'),
    `block_date` Date,
    `tx_hash` String,
    `sender` String,
    `pairs_opened` UInt64,
    `pairs_closed` UInt64,
    `in_a_one_transaction_pair` UInt8,
    `volume_usd` Nullable(Decimal(76, 18))
)
ENGINE = MergeTree
ORDER BY (pool_address, block_number, log_index)
SETTINGS replicated_deduplication_window = '0', index_granularity = 8192;

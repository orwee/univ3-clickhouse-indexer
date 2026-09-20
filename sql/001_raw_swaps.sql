-- Raw Uniswap v3 Swap events, one row per log. Decisions: DECISIONS.md #10 to #14.
--
-- The table name is unqualified on purpose: the database comes from the session
-- (`onchain` in production, a throw-away `test_*` database in the tests).
--
-- Integers are stored RAW, exactly as emitted: no scaling by token decimals here.
-- Hashes and addresses are stored as BINARY (FixedString), not as hex text:
--   unhex('…') to filter, lower(hex(col)) to display.
-- Nothing from pools.yml is denormalised into this table.
-- Deduplication is NOT the engine's job: the load is idempotent because it is
-- rebuilt from the JSONL landing zone (see src/univ3_indexer/loader.py).

CREATE TABLE IF NOT EXISTS raw_swaps
(
    pool_address    LowCardinality(String),  -- lower-case 0x hex: 4 distinct values
    block_number    UInt64,
    block_timestamp DateTime('UTC'),
    tx_hash         FixedString(32),         -- binary
    log_index       UInt32,                  -- index of the log within the BLOCK
    sender          FixedString(20),         -- binary
    recipient       FixedString(20),         -- binary
    amount0         Int256,                  -- signed, pool's point of view: > 0 received
    amount1         Int256,                  -- signed
    sqrt_price_x96  UInt256,                 -- uint160 on chain; no 160-bit type exists
    liquidity       UInt128,
    tick            Int32                    -- int24 on chain; no 24-bit type exists
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(block_timestamp)
PRIMARY KEY (pool_address, block_timestamp)
ORDER BY (pool_address, block_timestamp, block_number, log_index)

-- Our swaps inside a time window, per pool, and how many of them sit in a transaction
-- that the external list names.
--
--   {hashes:Array(String)}   transaction hashes, 64 hex digits, no 0x prefix
--   {window_from:DateTime}   first second of the window, UTC, inclusive
--   {window_to:DateTime}     last second of the window, UTC, inclusive
--   stable_*                 the same three aligned arrays as sql/reconciliation/03_external_b.sql
--
-- The match is on the transaction, not on the log: one transaction can hold several of our
-- swaps (a route through two of the pools, or the same pool twice) and all of them count.
-- USD is the stablecoin leg at exactly 1 USD, as everywhere else in this project.
-- Output: one row per pool that traded in the window. Nothing identifies a transaction.

WITH
    named AS
    (
        SELECT toFixedString(unhex(arrayJoin({hashes:Array(String)})), 32) AS tx_hash
    ),
    ours AS
    (
        SELECT
            pool_address,
            tx_hash,
            tx_hash IN (SELECT tx_hash FROM named) AS is_named,
            toFloat64(if(arrayElement({stable_is_token0:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)) = 1,
                         abs(amount0), abs(amount1)))
                / pow(10, arrayElement({stable_decimals:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)))
                                                   AS usd
        FROM raw_swaps
        WHERE block_timestamp >= {window_from:DateTime('UTC')}
          AND block_timestamp <= {window_to:DateTime('UTC')}
          AND has({stable_pools:Array(String)}, pool_address)
    )
SELECT
    pool_address,
    count()                       AS swaps,
    sum(usd)                      AS volume_usd,
    countIf(is_named)             AS named_swaps,
    uniqExactIf(tx_hash, is_named) AS named_transactions,
    sumIf(usd, is_named)          AS named_volume_usd
FROM ours
GROUP BY pool_address
ORDER BY pool_address

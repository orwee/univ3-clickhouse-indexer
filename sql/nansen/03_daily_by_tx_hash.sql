-- Per pool and UTC day inside a window: our swaps, and those whose transaction is named.
--
--   {hashes:Array(String)}    transaction hashes, 64 hex digits, no 0x prefix
--   {pools:Array(String)}     the pools this list of trades can speak for
--   {window_from:DateTime}    inclusive, UTC      {window_to:DateTime}  inclusive, UTC
--   stable_*                  as in sql/reconciliation/03_external_b.sql
--
-- Every pool-day with at least one swap in the window comes back, with zeros when nothing
-- is named: the caller stores the zeros, because "fetched and nothing found" is a result.

WITH
    named AS
    (
        SELECT toFixedString(unhex(arrayJoin({hashes:Array(String)})), 32) AS tx_hash
    ),
    ours AS
    (
        SELECT
            pool_address,
            toDate(block_timestamp, 'UTC')         AS day,
            tx_hash,
            tx_hash IN (SELECT tx_hash FROM named) AS is_named,
            toFloat64(if(arrayElement({stable_is_token0:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)) = 1,
                         abs(amount0), abs(amount1)))
                / pow(10, arrayElement({stable_decimals:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)))
                                                   AS usd
        FROM raw_swaps
        WHERE block_timestamp >= {window_from:DateTime('UTC')}
          AND block_timestamp <= {window_to:DateTime('UTC')}
          AND has({pools:Array(String)}, pool_address)
          AND has({stable_pools:Array(String)}, pool_address)
    )
SELECT
    pool_address,
    day,
    count()                        AS swaps,
    sum(usd)                       AS volume_usd,
    countIf(is_named)              AS named_swaps,
    uniqExactIf(tx_hash, is_named) AS named_transactions,
    sumIf(usd, is_named)           AS named_volume_usd
FROM ours
GROUP BY pool_address, day
ORDER BY pool_address, day

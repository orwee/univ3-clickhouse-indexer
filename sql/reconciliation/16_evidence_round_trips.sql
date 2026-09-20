-- EVIDENCE: round trips inside one block. Two swaps of the same pool, in the same block, by the
-- same sender, in opposite directions, the second undoing at least 90% of the first (measured
-- on the non-stable leg), in one pool-day.
--
--   {pool:String} {day:Date}   the pool-day       stable_*   as in 03_external_b.sql
--
-- For each pair: both legs with their transaction, position in the block, USD, the tick and
-- liquidity before and after, how many swaps of OTHER senders sit between the two legs, and
-- the net of the pair. Transaction hashes and addresses are public chain data.

WITH
    arrayElement({stable_is_token0:Array(UInt8)}, indexOf({stable_pools:Array(String)}, {pool:String})) = 1 AS stable_is_0,
    arrayElement({stable_decimals:Array(UInt8)}, indexOf({stable_pools:Array(String)}, {pool:String}))      AS stable_dec,
    swaps AS
    (
        SELECT
            block_number, log_index, block_timestamp, tx_hash, sender, recipient,
            if(stable_is_0, amount0, amount1)                        AS stable_raw,
            if(stable_is_0, amount1, amount0)                        AS other_raw,
            tick                                                     AS tick_after,
            toFloat64(liquidity)                                     AS liquidity_after,
            lagInFrame(tick, 1, tick) OVER previous                  AS tick_before,
            lagInFrame(toFloat64(liquidity), 1, toFloat64(liquidity)) OVER previous AS liquidity_before
        FROM raw_swaps
        WHERE pool_address = {pool:String}
          AND block_timestamp >= toDateTime({day:Date}, 'UTC') - INTERVAL 1 HOUR
          AND block_timestamp <  toDateTime({day:Date}, 'UTC') + INTERVAL 1 DAY
        WINDOW previous AS (ORDER BY block_number, log_index ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)
    )
SELECT
    toString(a.block_timestamp)                                      AS block_time,
    a.block_number                                                   AS block_number,
    a.log_index                                                      AS first_log_index,
    b.log_index                                                      AS second_log_index,
    lower(hex(a.tx_hash)) = lower(hex(b.tx_hash))                    AS same_transaction,
    concat('0x', lower(hex(a.sender)))                               AS sender_address,
    a.sender = a.recipient AND b.sender = b.recipient                AS sender_is_recipient,
    toFloat64(abs(a.stable_raw)) / pow(10, stable_dec)               AS first_usd,
    toFloat64(abs(b.stable_raw)) / pow(10, stable_dec)               AS second_usd,
    toFloat64(a.stable_raw + b.stable_raw) / pow(10, stable_dec)     AS net_stable_paid_to_pool,
    toFloat64(a.other_raw + b.other_raw) / toFloat64(abs(a.other_raw)) AS net_other_over_first,
    a.tick_before AS first_tick_before, a.tick_after AS first_tick_after,
    b.tick_before AS second_tick_before, b.tick_after AS second_tick_after,
    a.liquidity_before AS liquidity_before, a.liquidity_after AS liquidity_between,
    b.liquidity_after AS liquidity_after,
    arrayCount(x -> x.1 > a.log_index AND x.1 < b.log_index AND x.2 != a.sender, k.in_block)
                                                                     AS swaps_of_others_between
FROM swaps AS a
INNER JOIN swaps AS b
    ON b.block_number = a.block_number AND b.sender = a.sender
INNER JOIN
(
    SELECT block_number, groupArray((log_index, sender)) AS in_block FROM swaps GROUP BY block_number
) AS k ON k.block_number = a.block_number
WHERE b.log_index > a.log_index
  AND a.block_timestamp >= toDateTime({day:Date}, 'UTC')
  AND sign(a.other_raw) != sign(b.other_raw)
  AND abs(toFloat64(a.other_raw + b.other_raw)) <= 0.1 * toFloat64(abs(a.other_raw))
ORDER BY first_usd DESC
LIMIT 10

-- ANALYSIS: how much the round-trip figures depend on the 10% tolerance of the definition.
--
--   {stable_pools:Array(String)} {stable_is_token0:Array(UInt8)}   as in 03_external_b.sql
--   {stable_decimals:Array(UInt8)}
--
-- The pairs are those of sql/reconciliation/16_evidence_round_trips.sql, recomputed here from
-- the raw table with the tolerance left open up to 50%: same pool, same block, same sender,
-- the second later, the non-stable leg in the opposite direction, and
-- |first + second| / |first| on that leg, the residual, at most 0.5. For each tolerance
-- the legs are counted once, as in dbt/models/marts/fct_round_trip_legs.sql. At 10% this must
-- reproduce the mart exactly; src/univ3_indexer/analysis.py checks that it does.

WITH
    swaps AS
    (
        SELECT
            pool_address, block_number, log_index, sender, tx_hash,
            arrayElement({stable_is_token0:Array(UInt8)},
                         indexOf({stable_pools:Array(String)}, pool_address)) = 1        AS s0,
            arrayElement({stable_decimals:Array(UInt8)},
                         indexOf({stable_pools:Array(String)}, pool_address))            AS sdec,
            if(s0, amount1, amount0)                                                     AS other_raw,
            toFloat64(abs(if(s0, amount0, amount1))) / pow(10, sdec)                     AS usd
        FROM raw_swaps
    ),
    pairs AS
    (
        SELECT
            a.pool_address AS pool_address, a.block_number AS block_number,
            a.log_index AS first_log_index, b.log_index AS second_log_index,
            abs(toFloat64(a.other_raw + b.other_raw)) / toFloat64(abs(a.other_raw))      AS residual
        FROM swaps AS a
        INNER JOIN swaps AS b
            ON  b.pool_address = a.pool_address
            AND b.block_number = a.block_number
            AND b.sender       = a.sender
        WHERE b.log_index > a.log_index
          AND sign(a.other_raw) != sign(b.other_raw)
          AND abs(toFloat64(a.other_raw + b.other_raw)) <= 0.5 * toFloat64(abs(a.other_raw))
    ),
    legs AS
    (
        SELECT tolerance, pool_address, block_number, log_index
        FROM
        (
            SELECT pool_address, block_number, first_log_index AS log_index, residual FROM pairs
            UNION ALL
            SELECT pool_address, block_number, second_log_index AS log_index, residual FROM pairs
        )
        ARRAY JOIN [0.0, 0.01, 0.05, 0.10, 0.20, 0.50] AS tolerance
        WHERE residual <= tolerance
        GROUP BY tolerance, pool_address, block_number, log_index
    ),
    totals AS
    (
        SELECT sum(usd) AS all_usd, count() AS all_swaps FROM swaps
    )
SELECT
    l.tolerance                                                   AS tolerance,
    (SELECT countIf(residual <= l.tolerance) FROM pairs)          AS pairs,
    count()                                                       AS legs,
    sum(s.usd)                                                    AS legs_usd,
    legs_usd / any(t.all_usd)                                     AS share_of_usd,
    legs / any(t.all_swaps)                                       AS share_of_swaps
FROM legs AS l
INNER JOIN swaps AS s
    ON s.pool_address = l.pool_address AND s.block_number = l.block_number
   AND s.log_index = l.log_index
CROSS JOIN totals AS t
GROUP BY tolerance
ORDER BY tolerance

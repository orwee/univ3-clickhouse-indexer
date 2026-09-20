-- EVIDENCE: is the revaluation of DISPLACED swaps special, or would revaluing any swaps do?
--
-- Same definitions as 14_evidence_displaced_swaps.sql (reference tick = centred 21-swap
-- median; displaced = more than {ticks:UInt32} ticks from it; usd = stablecoin leg;
-- usd_at_reference = the other leg valued at the reference tick).
--
-- Per pool and UTC day, three adjustments to our volume:
--   delta_all        revalue EVERY swap                      (H2 as first tested)
--   delta_displaced  revalue only the k displaced swaps      (H2 restricted to what it is about)
--   delta_placebo    revalue k NON-displaced swaps instead, picked by a hash of
--                    ({seed:UInt64}, block_number, log_index): the same k, a fixed seed,
--                    reproducible. When a pool-day has fewer than k such swaps, all of them.
-- A placebo that brings as many days inside the threshold as the real thing means the real
-- thing explains nothing.

WITH
    swaps AS
    (
        SELECT
            pool_address,
            toDate(block_timestamp, 'UTC')                                        AS day,
            block_number,
            log_index,
            tick                                                                  AS end_tick,
            lagInFrame(tick, 1, tick) OVER previous                               AS start_tick,
            quantileExact(0.5)(tick) OVER around                                  AS reference_tick,
            arrayElement({stable_is_token0:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)) = 1
                                                                                  AS stable_is_0,
            arrayElement({stable_decimals:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address))
                                                                                  AS stable_dec,
            toFloat64(abs(amount0))                                               AS a0,
            toFloat64(abs(amount1))                                               AS a1
        FROM raw_swaps
        WHERE has({stable_pools:Array(String)}, pool_address)
        WINDOW
            previous AS (PARTITION BY pool_address ORDER BY block_number, log_index
                         ROWS BETWEEN 1 PRECEDING AND CURRENT ROW),
            around   AS (PARTITION BY pool_address ORDER BY block_number, log_index
                         ROWS BETWEEN 10 PRECEDING AND 10 FOLLOWING)
    ),
    valued AS
    (
        SELECT
            pool_address,
            day,
            greatest(abs(start_tick - reference_tick), abs(end_tick - reference_tick)) > {ticks:UInt32}
                                                                                  AS is_displaced,
            cityHash64({seed:UInt64}, block_number, log_index)                    AS pick,
            if(stable_is_0, a0, a1) / pow(10, stable_dec)                         AS usd,
            if(stable_is_0, a1 / pow(1.0001, reference_tick), a0 * pow(1.0001, reference_tick))
                / pow(10, stable_dec)                                             AS usd_at_reference
        FROM swaps
    ),
    ranked AS
    (
        SELECT
            *,
            countIf(is_displaced) OVER (PARTITION BY pool_address, day)                      AS k,
            row_number() OVER (PARTITION BY pool_address, day, is_displaced ORDER BY pick)   AS position
        FROM valued
    )
SELECT
    pool_address,
    day,
    count()                                                            AS swaps,
    any(k)                                                             AS displaced_swaps,
    sum(usd)                                                           AS volume_usd,
    sum(usd_at_reference - usd)                                        AS delta_all,
    sumIf(usd_at_reference - usd, is_displaced)                        AS delta_displaced,
    sumIf(usd_at_reference - usd, NOT is_displaced AND position <= k)  AS delta_placebo,
    countIf(NOT is_displaced AND position <= k)                        AS placebo_swaps
FROM ranked
GROUP BY pool_address, day
ORDER BY pool_address, day

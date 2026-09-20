-- EVIDENCE: how the displacement of 14_evidence_displaced_swaps.sql is distributed, per pool.
-- This is what the threshold N is chosen from. Same definition, no USD.

WITH
    swaps AS
    (
        SELECT
            pool_address,
            tick                                     AS end_tick,
            lagInFrame(tick, 1, tick) OVER previous  AS start_tick,
            quantileExact(0.5)(tick) OVER around     AS reference_tick
        FROM raw_swaps
        WINDOW
            previous AS (PARTITION BY pool_address ORDER BY block_number, log_index
                         ROWS BETWEEN 1 PRECEDING AND CURRENT ROW),
            around   AS (PARTITION BY pool_address ORDER BY block_number, log_index
                         ROWS BETWEEN 10 PRECEDING AND 10 FOLLOWING)
    )
SELECT
    pool_address,
    count()                                                        AS swaps,
    quantilesExact(0.5, 0.9, 0.99, 0.999, 0.9999)(displacement)    AS quantiles,
    max(displacement)                                              AS largest,
    sumForEach(arrayMap(n -> toUInt64(displacement > n), {thresholds:Array(UInt32)})) AS beyond
FROM (SELECT pool_address,
             greatest(abs(start_tick - reference_tick), abs(end_tick - reference_tick)) AS displacement
      FROM swaps)
GROUP BY pool_address
ORDER BY swaps DESC

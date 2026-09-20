-- EVIDENCE: swaps executed away from the pool's own recent price, per pool and UTC day.
--
-- Definition, the same for every pool:
--   reference tick  = median of the pool's tick over the 21 consecutive swaps centred on
--                     this one (10 before, itself, 10 after), in (block_number, log_index) order
--   start tick      = the tick the previous swap of the pool left
--   displacement    = greatest(|start tick - reference|, |tick after the swap - reference|)
-- A swap is "displaced beyond N" when displacement > N ticks (1 tick = 0.01% in price).
-- Both ends count: the swap that pushes the price away ends far from the reference, and the
-- swap that brings it back starts far from it.
--
--   {thresholds:Array(UInt32)}  the values of N to report, in ticks
--   stable_*                    as in 03_external_b.sql
--
-- Two USD figures per swap: `usd` is this project's (the stablecoin leg at 1 USD);
-- `usd_at_reference` values the OTHER leg at the reference tick instead. For a swap executed
-- at the going price the two agree; for a displaced swap they do not.
-- Output per pool-day: totals, and per threshold the number and USD of displaced swaps.

WITH
    swaps AS
    (
        SELECT
            pool_address,
            toDate(block_timestamp, 'UTC')                                        AS day,
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
            greatest(abs(start_tick - reference_tick), abs(end_tick - reference_tick)) AS displacement,
            if(stable_is_0, a0, a1) / pow(10, stable_dec)                              AS usd,
            -- 1.0001^tick = raw units of token1 per raw unit of token0 (the price of token0
            -- in token1); the stable leg's decimals do the rest
            if(stable_is_0, a1 / pow(1.0001, reference_tick), a0 * pow(1.0001, reference_tick))
                / pow(10, stable_dec)                                                  AS usd_at_reference
        FROM swaps
    )
SELECT
    pool_address,
    day,
    count()                                                                         AS swaps,
    sum(usd)                                                                        AS volume_usd,
    sum(usd_at_reference)                                                           AS volume_usd_at_reference,
    sumForEach(arrayMap(n -> toUInt64(displacement > n), {thresholds:Array(UInt32)}))       AS displaced_swaps,
    sumForEach(arrayMap(n -> if(displacement > n, usd, 0), {thresholds:Array(UInt32)}))     AS displaced_usd
FROM valued
GROUP BY pool_address, day
ORDER BY pool_address, day

-- EVIDENCE: does it matter WHICH LEG of a swap is valued? It does NOT test whether a
-- stablecoin is worth 1 USD: both valuations end up in the same stablecoin, so what this
-- measures is the fee plus the price impact. Two valuations of the same swaps:
--   stable_leg_usd   |stablecoin leg| / 10^decimals          (what volume_usd uses)
--   other_leg_usd    |other leg| converted into the stablecoin at the pool's OWN price
--                    right after that swap, from sqrt_price_x96:
--                    price = (sqrt_price_x96 / 2^96)^2 = token1 raw units per token0 raw unit
-- Swaps that left the pool AT THE PRICE LIMIT (|tick| > 800,000, next to the protocol's
-- +-887,272) are counted apart and left out of the valuation: there the "price right after
-- the swap" is the limit itself. Seen for real: 3 swaps of wstETH/USDC 0.3% ended at tick
-- 887,271 with liquidity 0.
-- Floats on purpose: this is a comparison of two approximations, not an accounting figure.
-- (inner columns are named stable_usd / other_usd because an outer alias equal to an inner
--  column name makes ClickHouse read sum(x) AS x as a nested aggregate: ILLEGAL_AGGREGATION)

SELECT
    pool_address,
    countIf(NOT at_price_limit)                                  AS swaps,
    countIf(at_price_limit)                                      AS swaps_at_price_limit,
    sumIf(stable_usd, NOT at_price_limit)                                          AS stable_leg_usd,
    sumIf(other_usd, NOT at_price_limit)                                           AS other_leg_usd,
    sumIf(other_usd, NOT at_price_limit) / sumIf(stable_usd, NOT at_price_limit) - 1 AS other_over_stable_minus_1,
    quantileExactIf(0.5)(other_usd / stable_usd - 1, NOT at_price_limit)       AS median_per_swap,
    quantileExactIf(0.01)(other_usd / stable_usd - 1, NOT at_price_limit)      AS p01_per_swap,
    quantileExactIf(0.99)(other_usd / stable_usd - 1, NOT at_price_limit)      AS p99_per_swap
FROM
(
    SELECT
        pool_address,
        arrayElement({stable_is_token0:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)) = 1 AS stable_is_0,
        pow(10, arrayElement({stable_decimals:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address))) AS unit,
        pow(toFloat64(sqrt_price_x96) / pow(2, 96), 2)           AS price_1_per_0,
        abs(tick) > 800000                                       AS at_price_limit,
        toFloat64(abs(if(stable_is_0, amount0, amount1))) / unit AS stable_usd,
        if(stable_is_0,
           toFloat64(abs(amount1)) / price_1_per_0,
           toFloat64(abs(amount0)) * price_1_per_0) / unit       AS other_usd
    FROM raw_swaps
    WHERE has({stable_pools:Array(String)}, pool_address)
      AND amount0 != 0 AND amount1 != 0
)
GROUP BY pool_address
ORDER BY pool_address

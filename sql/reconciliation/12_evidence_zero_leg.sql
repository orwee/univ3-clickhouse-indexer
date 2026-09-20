-- EVIDENCE, swaps with a zero leg. This pipeline keeps every Swap log: nothing is
-- filtered. How many have a zero leg, and how much USD volume they carry.

SELECT
    pool_address,
    count()                                                       AS swaps,
    countIf(amount0 = 0 OR amount1 = 0)                           AS zero_leg_swaps,
    countIf(amount0 = 0 AND amount1 = 0)                          AS both_zero_swaps,
    sumIf(toFloat64(abs(if(arrayElement({stable_is_token0:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)) = 1, amount0, amount1)))
          / pow(10, arrayElement({stable_decimals:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address))),
          amount0 = 0 OR amount1 = 0)                             AS zero_leg_volume_usd
FROM raw_swaps
WHERE has({stable_pools:Array(String)}, pool_address)
GROUP BY pool_address
ORDER BY pool_address

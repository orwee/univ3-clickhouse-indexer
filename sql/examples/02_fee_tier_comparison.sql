-- USDC/WETH in two fee tiers, side by side, per day: where does the volume go, and which
-- tier earns more for its liquidity providers? The 0.05% tier charges 5x per dollar, so
-- it can earn more with less volume. Run inside the dbt database (USE onchain_dbt).
--
-- sumIf / -If combinators pivot the two pools into columns in one pass, without a self-join.
SELECT
    block_date,
    round(sumIf(volume_usd, fee = 100), 0)                                   AS volume_usd_001,
    round(sumIf(volume_usd, fee = 500), 0)                                   AS volume_usd_005,
    round(100 * volume_usd_005 / (volume_usd_001 + volume_usd_005), 1)       AS pct_volume_in_005,
    round(sumIf(fees_usd, fee = 100), 0)                                     AS fees_usd_001,
    round(sumIf(fees_usd, fee = 500), 0)                                     AS fees_usd_005,
    round(fees_usd_005 / fees_usd_001, 2)                                    AS fees_ratio_005_over_001,
    sumIf(swaps, fee = 100)                                                  AS swaps_001,
    sumIf(swaps, fee = 500)                                                  AS swaps_005
FROM fct_pool_daily
WHERE pool_label IN ('USDC/WETH 0.01%', 'USDC/WETH 0.05%')
GROUP BY block_date
ORDER BY block_date

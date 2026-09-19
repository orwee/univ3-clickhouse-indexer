-- Top 10 pool-days by USD volume. Run inside the dbt database:
--   make ch-client   then   USE onchain_dbt;
-- No JOIN: pool_label and fee are denormalised into the mart on purpose.
SELECT
    block_date,
    pool_label,
    swaps,
    round(volume_usd, 0)                      AS volume_usd,
    round(fees_usd, 0)                        AS fees_usd,
    round(volume_usd / swaps, 0)              AS avg_swap_usd
FROM fct_pool_daily
ORDER BY volume_usd DESC
LIMIT 10

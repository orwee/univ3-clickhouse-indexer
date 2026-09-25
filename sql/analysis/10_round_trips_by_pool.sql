-- ANALYSIS: same-block round trips over the whole dataset, per pool and in total.
--
--   {dbt:Identifier}  the database dbt writes to (onchain_dbt)
--
-- Reads the marts built from the definition of sql/reconciliation/16_evidence_round_trips.sql
-- (dbt/models/marts/fct_round_trip_legs.sql). Aliases never repeat a column name: in
-- ClickHouse an alias that shadows a column is resolved everywhere in the query.

SELECT
    pool_label                                                       AS pool,
    count()                                                          AS pool_days,
    countIf(round_trips > 0)                                         AS pool_days_with_any,
    sum(swaps)                                                       AS all_swaps,
    sum(round_trips)                                                 AS pairs,
    sum(round_trip_swaps)                                            AS legs,
    sum(round_trip_swaps_in_one_transaction)                         AS legs_in_one_transaction_pairs,
    toFloat64(sum(volume_usd))                                       AS all_usd,
    toFloat64(sum(round_trip_volume_usd))                            AS legs_usd,
    toFloat64(sum(net_volume_usd))                                   AS net_usd,
    legs_usd / all_usd                                               AS share_of_usd,
    legs / all_swaps                                                 AS share_of_swaps,
    quantileExact(0.5)(round_trip_share_of_volume_usd)               AS median_daily_share_of_usd,
    max(round_trip_share_of_volume_usd)                              AS largest_daily_share_of_usd
FROM {dbt:Identifier}.fct_pool_daily_round_trips
GROUP BY pool_label WITH ROLLUP
ORDER BY pool = '', all_usd DESC

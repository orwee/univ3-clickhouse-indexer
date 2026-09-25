-- ANALYSIS: when in the day round trips happen: per hour of the day (UTC), all pools, the
-- swaps and USD that are legs of a round trip against everything swapped in that hour.
--
--   {dbt:Identifier}  the database dbt writes to (onchain_dbt)

WITH
    legs AS
    (
        SELECT toHour(block_timestamp, 'UTC')                                    AS hour_utc,
               count()                                                           AS leg_swaps,
               toFloat64(sum(ifNull(volume_usd, toDecimal256(0, 18))))           AS leg_usd
        FROM {dbt:Identifier}.fct_round_trip_legs
        GROUP BY hour_utc
    ),
    everything AS
    (
        SELECT toHour(block_timestamp, 'UTC')                                    AS hour_utc,
               count()                                                           AS hour_swaps,
               toFloat64(sum(ifNull(volume_usd, toDecimal256(0, 18))))           AS hour_usd
        FROM {dbt:Identifier}.stg_swaps
        GROUP BY hour_utc
    )
SELECT
    e.hour_utc                                       AS hour_utc,
    e.hour_swaps                                     AS hour_swaps,
    e.hour_usd                                       AS hour_usd,
    l.leg_swaps                                      AS leg_swaps,
    l.leg_usd                                        AS leg_usd,
    if(e.hour_usd > 0, l.leg_usd / e.hour_usd, 0)    AS share_of_usd
FROM everything AS e
LEFT JOIN legs AS l ON l.hour_utc = e.hour_utc
ORDER BY hour_utc
SETTINGS join_use_nulls = 0

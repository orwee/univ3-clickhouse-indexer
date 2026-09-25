-- ANALYSIS: the size of the swaps that are round-trip legs, and the part of their USD that is
-- the SECOND leg (the swap that undoes the first), which is the volume that comes back.
--
--   {dbt:Identifier}  the database dbt writes to (onchain_dbt)

WITH
    legs AS
    (
        SELECT toFloat64(ifNull(volume_usd, toDecimal256(0, 18))) AS leg_usd, pairs_closed
        FROM {dbt:Identifier}.fct_round_trip_legs
    )
SELECT
    multiIf(leg_usd < 1e3, '1. under 1k', leg_usd < 1e4, '2. 1k to 10k',
            leg_usd < 1e5, '3. 10k to 100k', leg_usd < 1e6, '4. 100k to 1M',
            '5. 1M and more')                                        AS leg_size_usd,
    count()                                                          AS legs,
    sum(leg_usd)                                                     AS usd,
    usd / (SELECT sum(leg_usd) FROM legs)                            AS share_of_round_trip_usd,
    sumIf(leg_usd, pairs_closed > 0)                                 AS usd_of_legs_that_undo
FROM legs
GROUP BY leg_size_usd WITH ROLLUP
ORDER BY leg_size_usd = '', leg_size_usd

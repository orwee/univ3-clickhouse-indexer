-- ANALYSIS: how concentrated round trips are by `sender`, the contract that called the pool.
-- Ranks only: the address is used to group and to break ties, and is never selected.
--
--   {dbt:Identifier}  the database dbt writes to (onchain_dbt)

WITH
    per_sender AS
    (
        SELECT sender,
               count()                                                     AS sender_legs,
               toFloat64(sum(ifNull(volume_usd, toDecimal256(0, 18))))     AS sender_usd
        FROM {dbt:Identifier}.fct_round_trip_legs
        GROUP BY sender
    ),
    ranked AS
    (
        SELECT sender_legs, sender_usd,
               row_number() OVER (ORDER BY sender_usd DESC, sender_legs DESC, sender) AS usd_rank
        FROM per_sender
    )
SELECT
    count()                                                   AS senders,
    sum(sender_legs)                                          AS total_legs,
    sum(sender_usd)                                           AS total_usd,
    sumIf(sender_usd, usd_rank <= 1)  / total_usd             AS top1_share_of_usd,
    sumIf(sender_usd, usd_rank <= 3)  / total_usd             AS top3_share_of_usd,
    sumIf(sender_usd, usd_rank <= 10) / total_usd             AS top10_share_of_usd,
    sumIf(sender_legs, usd_rank <= 1)  / total_legs           AS top1_share_of_legs,
    sumIf(sender_legs, usd_rank <= 10) / total_legs           AS top10_share_of_legs,
    countIf(sender_legs <= 2)                                 AS senders_with_one_pair_at_most
FROM ranked

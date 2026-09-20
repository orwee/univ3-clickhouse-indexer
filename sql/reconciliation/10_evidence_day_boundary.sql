-- EVIDENCE, day boundary. Our USD volume per pool with the day cut moved by
-- {shift_hours:Int32} hours (a swap at 23:30 UTC belongs to the NEXT day when the shift
-- is +1), against the external source's days, over {first_full_day:Date} to
-- {last_full_day:Date}: days that are complete on our side under every shift tried.
-- One row per pool: how far apart the two sources are with this shift.

WITH
    ours AS
    (
        SELECT
            pool_address,
            toDate(toStartOfDay(block_timestamp + toIntervalHour({shift_hours:Int32}), 'UTC')) AS date,
            toFloat64(sum(
                if(arrayElement({stable_is_token0:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)) = 1,
                   abs(amount0), abs(amount1))
            )) / pow(10, any(arrayElement({stable_decimals:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address))))
                AS volume_usd
        FROM raw_swaps
        WHERE has({stable_pools:Array(String)}, pool_address)
        GROUP BY pool_address, date
    ),
    theirs AS
    (
        SELECT pool_address, date, volume_usd
        FROM external_daily_volume FINAL
        WHERE source = {source:String}
    )
SELECT
    t.pool_address                                                    AS pool_address,
    count()                                                           AS days,
    sum(abs(o.volume_usd - t.volume_usd))                             AS sum_abs_diff_usd,
    sum(t.volume_usd)                                                 AS external_usd,
    sum(abs(o.volume_usd - t.volume_usd)) / sum(t.volume_usd)         AS abs_diff_over_external,
    (sum(o.volume_usd) - sum(t.volume_usd)) / sum(t.volume_usd)       AS total_rel_diff
FROM theirs AS t
INNER JOIN ours AS o ON o.pool_address = t.pool_address AND o.date = t.date
WHERE t.date BETWEEN {first_full_day:Date} AND {last_full_day:Date}
GROUP BY t.pool_address
ORDER BY t.pool_address

-- fct_pool_daily_round_trips describes a PART of each pool-day: never more swaps or more USD
-- than the pool-day has, at least two swaps whenever there is a round trip, both counts zero
-- together, the round trips it counts equal to what fct_round_trip_legs holds for that day,
-- and one row for every pool-day of fct_pool_daily.
-- Rows returned = pool-days where one of those does not hold.

with mart as (

    select * from {{ ref('fct_pool_daily_round_trips') }}

),

legs as (

    select pool_address, block_date, count() as swaps_in_legs, sum(pairs_opened) as pairs
    from {{ ref('fct_round_trip_legs') }}
    group by pool_address, block_date

)

select m.pool_address, m.block_date, 'out of range' as problem
from mart as m
left join legs as l on l.pool_address = m.pool_address and l.block_date = m.block_date
where m.round_trip_swaps > m.swaps
   or m.round_trip_volume_usd > ifNull(m.volume_usd, toDecimal256(0, 18))
   or (m.round_trips > 0 and m.round_trip_swaps < 2)
   or (m.round_trips = 0) != (m.round_trip_swaps = 0)
   or m.round_trip_swaps_in_one_transaction > m.round_trip_swaps
   or m.round_trip_swaps != ifNull(l.swaps_in_legs, 0)
   or m.round_trips != ifNull(l.pairs, 0)

union all

select d.pool_address, d.block_date, 'missing from the mart' as problem
from {{ ref('fct_pool_daily') }} as d
left anti join mart as m on m.pool_address = d.pool_address and m.block_date = d.block_date

{#
  Per pool and UTC day: how much of the reported activity is same-block round trips
  (fct_round_trip_legs), and what is left without them.

  Every pool-day of fct_pool_daily has a row, with zeros when it holds no round trip: the
  LEFT JOIN runs with join_use_nulls = 0, and the round-trip sums are made non-Nullable in
  the CTE, so an unmatched pool-day gets 0 and not NULL. volume_usd and net_volume_usd stay
  Nullable because fct_pool_daily.volume_usd is (a pool without a stablecoin has no USD).

  round_trips counts pairs; round_trip_swaps counts distinct swaps, each once, even when one
  swap is a leg of two pairs. round_trip_volume_usd is the USD of those swaps, both legs.
  assert_round_trips_are_a_part_of_the_pool_day checks the ranges and that no pool-day of
  fct_pool_daily is missing.
#}

{{ config(
    materialized='table',
    engine='MergeTree()',
    order_by='(pool_address, block_date)'
) }}

with daily as (

    select * from {{ ref('fct_pool_daily') }}

),

legs as (

    select
        pool_address,
        block_date,
        toUInt64(sum(pairs_opened))                                     as round_trips,
        count()                                                         as round_trip_swaps,
        countIf(in_a_one_transaction_pair)                              as round_trip_swaps_in_one_transaction,
        sum(ifNull(volume_usd, toDecimal256(0, 18)))                    as round_trip_volume_usd
    from {{ ref('fct_round_trip_legs') }}
    group by pool_address, block_date

)

select
    d.pool_address                                                      as pool_address,
    d.block_date                                                        as block_date,
    d.pool_label                                                        as pool_label,
    d.swaps                                                             as swaps,
    d.volume_usd                                                        as volume_usd,
    l.round_trips                                                       as round_trips,
    l.round_trip_swaps                                                  as round_trip_swaps,
    l.round_trip_swaps_in_one_transaction                               as round_trip_swaps_in_one_transaction,
    l.round_trip_volume_usd                                             as round_trip_volume_usd,
    d.volume_usd - l.round_trip_volume_usd                              as net_volume_usd,
    if(ifNull(d.volume_usd, toDecimal256(0, 18)) > toDecimal256(0, 18),
       toFloat64(l.round_trip_volume_usd) / toFloat64(assumeNotNull(d.volume_usd)),
       0.0)                                                             as round_trip_share_of_volume_usd
from daily as d
left join legs as l
    on  l.pool_address = d.pool_address
    and l.block_date   = d.block_date
settings join_use_nulls = 0

{#
  Smart-money share per pool and UTC day: the part of fct_pool_daily that sits in
  transactions the Nansen API attributes to a smart-money trader (docs/NANSEN.md).

  INNER JOIN on purpose. The source holds a row for every pool-day that was FETCHED, zeros
  included, so a pool-day missing there is "not looked at" and must not show up here as 0%.
  ClickHouse would make that mistake silently with a LEFT JOIN: with join_use_nulls = 0
  (the default) an unmatched row gets 0 and '', not NULL.

  The source is a ReplacingMergeTree: FINAL, always. A few hundred rows.

  Both shares are of OUR totals for the same pool-day, so they are between 0 and 1 by
  construction; a dbt test checks it anyway, because the numerator comes from another run.
#}

{{ config(
    materialized='table',
    engine='MergeTree()',
    order_by='(pool_address, block_date)'
) }}

with daily as (

    select * from {{ ref('fct_pool_daily') }}

),

smart as (

    select * from {{ source('raw', 'nansen_smart_money_daily') }} final

)

select
    d.pool_address                                       as pool_address,
    d.block_date                                         as block_date,
    d.pool_label                                         as pool_label,
    d.swaps                                              as swaps,
    d.volume_usd                                         as volume_usd,
    s.named_swaps                                        as smart_money_swaps,
    s.named_transactions                                 as smart_money_transactions,
    s.named_volume_usd                                   as smart_money_volume_usd,
    s.named_swaps / d.swaps                              as smart_money_share_of_swaps,
    s.named_volume_usd / toFloat64(d.volume_usd)         as smart_money_share_of_volume_usd,
    s.token_symbol                                       as fetched_by_token,
    s.computed_at                                        as computed_at
from daily as d
inner join smart as s
    on s.pool_address = d.pool_address and s.date = d.block_date
where d.volume_usd is not null and d.volume_usd > 0

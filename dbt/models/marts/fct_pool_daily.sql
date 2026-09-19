{#
  One row per pool and UTC day.

  DELIBERATE DENORMALISATION: pool_label and fee are copied into every row instead of
  being joined from dim_pools at query time. This is the example of the opposite choice
  to the raw table (DECISIONS.md #14): a mart is rebuilt by `dbt build` in under a
  second, so a changed label costs one rebuild, and whoever queries this table gets a
  readable result without a JOIN. With 4 pools and ~120 rows the saving is nil; it is
  here to show the pattern and its price (the label now lives in two places, and this
  one is only as fresh as the last build).

  fees_usd = volume_usd * fee / 1e6. The unit was checked against pools.yml: fee is in
  hundredths of a basis point (100 -> 0.01%, 500 -> 0.05%, 3000 -> 0.3%), so / 1e6 gives
  the fraction. It is an ESTIMATE: Uniswap charges the fee on the INPUT token, and
  volume_usd is the stablecoin leg whichever direction the swap went, so on swaps where
  the stablecoin is the output the true fee is higher by a factor of 1 / (1 - fee).
  At most 0.3% of the fee itself.
#}

{{ config(
    materialized='table',
    engine='MergeTree()',
    order_by='(pool_address, block_date)'
) }}

with swaps as (

    select * from {{ ref('stg_swaps') }}

),

pools as (

    select * from {{ ref('dim_pools') }}

),

daily as (

    select
        pool_address,
        block_date,
        count()            as swaps,
        sum(amount0_abs)   as volume_token0,
        sum(amount1_abs)   as volume_token1,
        sum(volume_usd)    as volume_usd
    from swaps
    group by pool_address, block_date

)

select
    d.pool_address                                                          as pool_address,
    d.block_date                                                            as block_date,
    p.pool_label                                                            as pool_label,
    p.fee                                                                   as fee,
    d.swaps                                                                 as swaps,
    d.volume_token0                                                         as volume_token0,
    d.volume_token1                                                         as volume_token1,
    d.volume_usd                                                            as volume_usd,
    d.volume_usd * toDecimal256(p.fee, 0) / toDecimal256(1000000, 0)        as fees_usd
from daily as d
inner join pools as p on p.pool_address = d.pool_address

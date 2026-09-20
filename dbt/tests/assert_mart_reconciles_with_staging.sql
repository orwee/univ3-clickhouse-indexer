-- Internal reconciliation: the mart must account for every swap and every dollar of
-- staging, exactly. Decimals make "exactly" possible. Any row returned is a failure.
with mart as (
    select sum(swaps) as swaps, sum(volume_usd) as volume_usd, sum(volume_token0) as t0
    from {{ ref('fct_pool_daily') }}
),
staging as (
    select count() as swaps, sum(volume_usd) as volume_usd, sum(amount0_abs) as t0
    from {{ ref('stg_swaps') }}
)
select mart.swaps as mart_swaps, staging.swaps as staging_swaps,
       mart.volume_usd as mart_usd, staging.volume_usd as staging_usd
from mart, staging
where mart.swaps != staging.swaps
   or mart.volume_usd != staging.volume_usd
   or mart.t0 != staging.t0

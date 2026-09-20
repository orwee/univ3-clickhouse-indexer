-- The daily mart against the SOURCE, not against staging: per pool and UTC day, the number of
-- swaps and the raw integer volume of both tokens, recomputed here from raw_swaps with the
-- decimals of the seed, must equal what the mart says. Exact: Int256 and Decimal, no float.
--
-- What makes it fail (each one proven in scripts/prove_dbt_tests_can_fail.py): a mart that is
-- older than the raw table (rows loaded, `dbt test` run without rebuilding), a pool dropped by
-- the staging join, a fan-out from a duplicated seed row, a scaling that loses digits.
-- Any row returned is a pool-day that does not add up.

with source as (
    select
        r.pool_address                                as pool_address,
        toDate(r.block_timestamp, 'UTC')              as block_date,
        count()                                       as swaps,
        sum(abs(r.amount0))                           as raw0,
        sum(abs(r.amount1))                           as raw1
    from {{ source('raw', 'raw_swaps') }} as r
    group by pool_address, block_date
),

mart as (
    select
        f.pool_address                                                        as pool_address,
        f.block_date                                                          as block_date,
        f.swaps                                                               as swaps,
        f.volume_token0 * toDecimal256(intExp10(p.decimals0), 0)              as raw0,
        f.volume_token1 * toDecimal256(intExp10(p.decimals1), 0)              as raw1
    from {{ ref('fct_pool_daily') }} as f
    inner join {{ ref('pools') }} as p on p.pool_address = f.pool_address
)

select
    if(s.swaps > 0, s.pool_address, m.pool_address)   as pool,
    if(s.swaps > 0, s.block_date, m.block_date)       as day,
    s.swaps                                           as source_swaps,
    m.swaps                                           as mart_swaps
from source as s
full outer join mart as m on m.pool_address = s.pool_address and m.block_date = s.block_date
where s.swaps != m.swaps
   or toDecimal256(s.raw0, 0) != m.raw0
   or toDecimal256(s.raw1, 0) != m.raw1
settings join_use_nulls = 0

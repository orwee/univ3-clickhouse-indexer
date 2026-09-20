-- stg_swaps INNER JOINs the seed, so a swap of a pool that is not in pools.yml would vanish
-- from every model without a trace, and the relationships tests downstream could never see
-- it (every row that survives the join matches by construction). This test looks at the
-- SOURCE instead. Rows returned = pools present in raw_swaps and absent from the seed.

select r.pool_address, count() as swaps
from {{ source('raw', 'raw_swaps') }} as r
left anti join {{ ref('pools') }} as p on p.pool_address = r.pool_address
group by r.pool_address

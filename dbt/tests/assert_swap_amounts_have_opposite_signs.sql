-- A swap moves one token into the pool and the other out: the signs must be opposite.
-- Zero legs (dust) are allowed; two amounts of the same sign are not. Any row fails.
select pool_address, block_number, log_index, amount0_raw, amount1_raw
from {{ ref('stg_swaps') }}
where (amount0_raw > 0 and amount1_raw > 0) or (amount0_raw < 0 and amount1_raw < 0)

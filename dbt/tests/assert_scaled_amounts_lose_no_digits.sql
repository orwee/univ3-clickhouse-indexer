-- stg_swaps turns a raw Int256 into a Decimal(76, 18) by dividing by 10^decimals. The result
-- keeps 18 decimal places, so a token with MORE than 18 decimals would be truncated in
-- silence. Multiplying back must give the raw integer exactly. Every token here has at most
-- 18 decimals, which is the only reason this passes today.
-- Rows returned = swaps whose scaled amount no longer carries every digit of the raw one.

select s.pool_address, s.block_number, s.log_index, s.amount0_raw, s.amount0, s.amount1_raw, s.amount1
from {{ ref('stg_swaps') }} as s
inner join {{ ref('pools') }} as p on p.pool_address = s.pool_address
where s.amount0 * toDecimal256(intExp10(p.decimals0), 0) != toDecimal256(s.amount0_raw, 0)
   or s.amount1 * toDecimal256(intExp10(p.decimals1), 0) != toDecimal256(s.amount1_raw, 0)

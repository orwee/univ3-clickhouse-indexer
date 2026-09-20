-- pools.yml is filled in by hand, and the fee tier is written twice: as the integer `fee`
-- (500) and inside the label ("USDC/WETH 0.05%"). fees_usd uses the integer; people read the
-- label. Rows returned = pools where the two disagree.

select pool_address, pool_label, fee, fee_percent
from {{ ref('dim_pools') }}
where not endsWith(pool_label, concat(' ', toString(fee_percent), '%'))

-- fees_usd must be exactly volume_usd * fee / 1e6 with the fee of pools.yml, and the fee
-- copied into the mart must still be the one in the dimension (the price of denormalising).
select f.pool_address, f.block_date, f.fee, p.fee as dim_fee, f.volume_usd, f.fees_usd
from {{ ref('fct_pool_daily') }} as f
inner join {{ ref('dim_pools') }} as p on p.pool_address = f.pool_address
where f.fee != p.fee
   or f.fees_usd != f.volume_usd * p.fee_fraction

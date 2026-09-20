-- fct_pool_daily copies pool_label and fee from dim_pools on purpose (see the model). The
-- price of that is staleness: after pools.yml changes, a run that rebuilds the dimension and
-- not the mart leaves two different answers in the warehouse. Inside one full `dbt build`
-- this cannot fail; after a partial run (`dbt run -s dim_pools`) it can, and that is when it
-- matters. Rows returned = pool-days whose copy differs from the dimension.

select f.pool_address, f.block_date, f.pool_label, p.pool_label as dim_label, f.fee, p.fee as dim_fee
from {{ ref('fct_pool_daily') }} as f
inner join {{ ref('dim_pools') }} as p on p.pool_address = f.pool_address
where f.fee != p.fee or f.pool_label != p.pool_label

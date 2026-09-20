-- pools.yml keeps EIP-55 mixed-case addresses; everything inside ClickHouse is lower-case
-- (src/univ3_indexer/addresses.py is the one place that converts). A mixed-case address
-- in the seed or in the raw table would make the join in stg_swaps silently match nothing.
select 'seed' as origin, pool_address from {{ ref('pools') }} where pool_address != lower(pool_address)
union all
select 'raw_swaps' as origin, pool_address from {{ source('raw', 'raw_swaps') }}
where pool_address != lower(pool_address)
group by pool_address

-- fct_round_trip_legs must hold exactly the swaps that the definition of
-- sql/reconciliation/16_evidence_round_trips.sql finds in the RAW table: recomputed here
-- from source('raw', 'raw_swaps'), not from stg_swaps, so a stale mart or a broken model
-- both show. The non-stable leg is picked from the seed with the same rule as stg_swaps.
-- Rows returned = legs in one set and not in the other.

{% set stables = "'" ~ var('stablecoin_symbols') | join("', '") ~ "'" %}

with raw_swaps as (

    select
        s.pool_address                                                  as pool_address,
        s.block_number                                                  as block_number,
        s.log_index                                                     as log_index,
        s.sender                                                        as sender,
        if(p.token0 in ({{ stables }}), s.amount1, s.amount0)           as other_raw
    from {{ source('raw', 'raw_swaps') }} as s
    inner join {{ ref('pools') }} as p on p.pool_address = s.pool_address

),

pairs as (

    select a.pool_address as pool_address, a.block_number as block_number,
           a.log_index as first_log_index, b.log_index as second_log_index
    from raw_swaps as a
    inner join raw_swaps as b
        on  b.pool_address = a.pool_address
        and b.block_number = a.block_number
        and b.sender       = a.sender
    where b.log_index > a.log_index
      and sign(a.other_raw) != sign(b.other_raw)
      and abs(toFloat64(a.other_raw + b.other_raw)) <= 0.1 * toFloat64(abs(a.other_raw))

),

expected as (

    select distinct pool_address, block_number, log_index from (
        select pool_address, block_number, first_log_index as log_index from pairs
        union all
        select pool_address, block_number, second_log_index as log_index from pairs
    )

),

actual as (

    select pool_address, block_number, log_index from {{ ref('fct_round_trip_legs') }}

)

select pool_address, block_number, log_index, 'in the raw table, not in the mart' as problem
from expected
where (pool_address, block_number, log_index) not in (select pool_address, block_number, log_index from actual)

union all

select pool_address, block_number, log_index, 'in the mart, not in the raw table' as problem
from actual
where (pool_address, block_number, log_index) not in (select pool_address, block_number, log_index from expected)

union all

select pool_address, block_number, log_index, 'listed twice' as problem
from actual
group by pool_address, block_number, log_index
having count() > 1

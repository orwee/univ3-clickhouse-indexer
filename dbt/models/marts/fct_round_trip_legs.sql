{#
  Every swap that is a leg of a same-block round trip, one row per swap, over the whole
  dataset.

  The definition is the one in sql/reconciliation/16_evidence_round_trips.sql, unchanged,
  applied to every pool-day instead of one: two swaps of the same pool, in the same block,
  by the same `sender`, the second later in the block, moving the non-stable leg in the
  opposite direction and undoing between 90% and 110% of it
  (|first + second| <= 0.1 * |first| on the raw non-stable amount, in Float64 as there).
  The non-stable leg is picked with the same rule as stg_swaps: the token that is not in the
  `stablecoin_symbols` var, token0 winning if both are.

  `sender` in a Swap log is the contract that called the pool, not the account that signed
  the transaction. Nothing here says who that account is, and nothing here says why the two
  swaps were made: the pattern is consistent with a sandwich, and this model does not claim
  one.

  A swap can be a leg of more than one pair (a sender with three swaps in one block). It is
  listed ONCE, with how many pairs it opens and how many it closes, so a volume summed from
  this table counts every swap once. dbt/tests/assert_round_trip_legs_match_their_definition
  recomputes the legs from the raw table and fails on any difference.
#}

{{ config(
    materialized='table',
    engine='MergeTree()',
    order_by='(pool_address, block_number, log_index)'
) }}

{% set stables = "'" ~ var('stablecoin_symbols') | join("', '") ~ "'" %}

with swaps as (

    select
        pool_address,
        block_number,
        log_index,
        block_timestamp,
        block_date,
        tx_hash,
        sender,
        if(token0 in ({{ stables }}), amount1_raw, amount0_raw)  as other_raw,
        volume_usd
    from {{ ref('stg_swaps') }}

),

pairs as (

    select
        a.pool_address                  as pool_address,
        a.block_number                  as block_number,
        a.log_index                     as first_log_index,
        b.log_index                     as second_log_index,
        a.tx_hash = b.tx_hash           as same_transaction
    from swaps as a
    inner join swaps as b
        on  b.pool_address = a.pool_address
        and b.block_number = a.block_number
        and b.sender       = a.sender
    where b.log_index > a.log_index
      and sign(a.other_raw) != sign(b.other_raw)
      and abs(toFloat64(a.other_raw + b.other_raw)) <= 0.1 * toFloat64(abs(a.other_raw))

),

legs as (

    select
        pool_address,
        block_number,
        log_index,
        sum(opens)                      as pairs_opened,
        sum(closes)                     as pairs_closed,
        max(same_transaction)           as in_a_one_transaction_pair
    from (
        select pool_address, block_number, first_log_index  as log_index,
               toUInt32(1) as opens, toUInt32(0) as closes, same_transaction
        from pairs
        union all
        select pool_address, block_number, second_log_index as log_index,
               toUInt32(0) as opens, toUInt32(1) as closes, same_transaction
        from pairs
    )
    group by pool_address, block_number, log_index

)

select
    l.pool_address                      as pool_address,
    l.block_number                      as block_number,
    l.log_index                         as log_index,
    s.block_timestamp                   as block_timestamp,
    s.block_date                        as block_date,
    s.tx_hash                           as tx_hash,
    s.sender                            as sender,
    l.pairs_opened                      as pairs_opened,
    l.pairs_closed                      as pairs_closed,
    l.in_a_one_transaction_pair         as in_a_one_transaction_pair,
    s.volume_usd                        as volume_usd
from legs as l
inner join swaps as s
    on  s.pool_address = l.pool_address
    and s.block_number = l.block_number
    and s.log_index    = l.log_index

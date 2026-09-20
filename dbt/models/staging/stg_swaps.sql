{#
  One row per swap, made readable. Nothing is aggregated. The INNER JOIN with the seed
  DROPS any swap whose pool is not in pools.yml; the loader only loads those pools, and
  dbt/tests/assert_every_raw_pool_is_in_the_seed.sql fails if one ever slips through.

  * Hashes and addresses: binary in the raw table, '0x…' lower-case hex here.
  * Amounts: the raw Int256 is kept (amount0_raw, amount1_raw) and a scaled Decimal is
    added. Scaling never touches a float: Decimal256(18) divided by intExp10(decimals),
    which is an exact integer. 18 is the largest number of decimals of any token here.
  * volume_usd: absolute value of the stablecoin leg. Stablecoins are named in ONE
    place, the `stablecoin_symbols` var in dbt_project.yml. If both tokens are stable,
    token0 wins. If neither is, volume_usd is NULL: there is no oracle here and no price
    is invented. A stablecoin is taken at exactly 1 USD, which is an approximation.
#}

{% set stables = "'" ~ var('stablecoin_symbols') | join("', '") ~ "'" %}

with swaps as (

    select * from {{ source('raw', 'raw_swaps') }}

),

pools as (

    select * from {{ ref('pools') }}

),

scaled as (

    select
        s.pool_address                                        as pool_address,
        s.block_number                                        as block_number,
        s.log_index                                           as log_index,
        s.block_timestamp                                     as block_timestamp,
        toDate(s.block_timestamp, 'UTC')                      as block_date,
        concat('0x', lower(hex(s.tx_hash)))                   as tx_hash,
        concat('0x', lower(hex(s.sender)))                    as sender,
        concat('0x', lower(hex(s.recipient)))                 as recipient,

        p.token0                                              as token0,
        p.token1                                              as token1,

        s.amount0                                             as amount0_raw,
        s.amount1                                             as amount1_raw,
        toDecimal256(s.amount0, 18) / toDecimal256(intExp10(p.decimals0), 0) as amount0,
        toDecimal256(s.amount1, 18) / toDecimal256(intExp10(p.decimals1), 0) as amount1,

        s.sqrt_price_x96                                      as sqrt_price_x96,
        s.liquidity                                           as liquidity,
        s.tick                                                as tick
    from swaps as s
    inner join pools as p on p.pool_address = s.pool_address

)

select
    pool_address,
    block_number,
    log_index,
    block_timestamp,
    block_date,
    tx_hash,
    sender,
    recipient,
    token0,
    token1,
    amount0_raw,
    amount1_raw,
    amount0,
    amount1,
    abs(amount0)                                              as amount0_abs,
    abs(amount1)                                              as amount1_abs,
    multiIf(
        token0 in ({{ stables }}), toNullable(abs(amount0)),
        token1 in ({{ stables }}), toNullable(abs(amount1)),
        NULL
    )                                                         as volume_usd,
    sqrt_price_x96,
    liquidity,
    tick
from scaled

{#
  The pool dimension, straight from the seed (which is generated from pools.yml).
  fee is in hundredths of a basis point: 500 means 0.05%, so fee / 1e6 is the fraction.
#}

select
    pool_address,
    label                                                    as pool_label,
    token0,
    token1,
    decimals0,
    decimals1,
    fee,
    toDecimal64(fee, 6) / toDecimal64(1000000, 0)            as fee_fraction,
    toDecimal64(fee, 4) / toDecimal64(10000, 0)              as fee_percent
from {{ ref('pools') }}

-- The smart-money figures come from another run (the Nansen cross) than the totals they are
-- divided by. If raw_swaps was reloaded or extended in between, a part could exceed its whole.
-- Rows returned = pool-days where it does.

select pool_address, block_date, swaps, smart_money_swaps, smart_money_share_of_volume_usd
from {{ ref('fct_pool_daily_smart_money') }}
where smart_money_swaps > swaps
   or smart_money_transactions > smart_money_swaps
   or smart_money_share_of_swaps < 0 or smart_money_share_of_swaps > 1
   or smart_money_share_of_volume_usd < 0 or smart_money_share_of_volume_usd > 1.000001

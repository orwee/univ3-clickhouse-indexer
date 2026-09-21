-- tx_hash, sender and recipient are binary in the raw table and hex text here. They are not
-- Nullable, so a decode that lost one would leave zero bytes, not NULL: '0x000…0'. A zero
-- transaction hash or a zero sender cannot exist on chain (a zero RECIPIENT can: burning).
-- Rows returned = swaps with a malformed or all-zero hash, or a malformed or zero sender.

select block_number, log_index, tx_hash, sender, recipient
from {{ ref('stg_swaps') }}
where not match(tx_hash, '^0x[0-9a-f]{64}$')
   or tx_hash = concat('0x', repeat('0', 64))
   or not match(sender, '^0x[0-9a-f]{40}$')
   or sender = concat('0x', repeat('0', 40))
   or not match(recipient, '^0x[0-9a-f]{40}$')

-- title: Swaps with a zero amount
-- question: Which swaps have amount0 = 0 or amount1 = 0?
-- problem: both zero is always wrong. ONE zero leg can be legitimate: a dust swap whose
--          output rounds down to nothing. Many of them, or large ones, deserve a look.
--          Listed, not filtered: the staging model keeps them.
-- expect: informational
SELECT
    pool_address,
    block_number,
    log_index,
    lower(hex(tx_hash)) AS tx_hash,
    amount0,
    amount1,
    if(amount0 = 0 AND amount1 = 0, 'BOTH ZERO', 'one zero leg') AS kind
FROM raw_swaps
WHERE amount0 = 0 OR amount1 = 0
ORDER BY kind, block_number, log_index

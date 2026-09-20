-- title: Swaps whose two amounts have the same sign
-- question: Does any swap move both tokens in the same direction? The pool receives one
--           token (positive) and pays the other (negative), so the signs must be opposite.
-- problem: ANY row. It would mean the int256 decoding is wrong (sign or word order) or the
--          log is not a Swap. These rows are LISTED here, never filtered out downstream.
-- expect: empty
SELECT
    pool_address,
    block_number,
    log_index,
    lower(hex(tx_hash)) AS tx_hash,
    amount0,
    amount1
FROM raw_swaps
WHERE (amount0 > 0 AND amount1 > 0) OR (amount0 < 0 AND amount1 < 0)
ORDER BY block_number, log_index

-- title: Duplicated logs
-- question: Is any log stored more than once? A log is identified by (block_number, log_index):
--           log_index is the position of the log inside the BLOCK, not inside the transaction.
-- problem: ANY row. The engine is a plain MergeTree and removes nothing, so a duplicate
--          means the load ran twice over the same file. Fix: `make load-full`.
-- expect: empty
SELECT
    block_number,
    log_index,
    count() AS copies,
    groupUniqArray(pool_address) AS pools,
    lower(hex(any(tx_hash))) AS tx_hash
FROM raw_swaps
GROUP BY block_number, log_index
HAVING copies > 1
ORDER BY block_number, log_index

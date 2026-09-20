-- How many of the named transactions appear in raw_swaps at all, in any pool, inside the
-- window. Same parameters as 01_cross_by_tx_hash.sql. One number; a transaction that routes
-- through two of the pools counts once here and twice in the per-pool rows of 01.

SELECT uniqExact(tx_hash) AS named_transactions
FROM raw_swaps
WHERE block_timestamp >= {window_from:DateTime('UTC')}
  AND block_timestamp <= {window_to:DateTime('UTC')}
  AND tx_hash IN (SELECT toFixedString(unhex(arrayJoin({hashes:Array(String)})), 32))

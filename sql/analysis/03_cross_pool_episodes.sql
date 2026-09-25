-- ANALYSIS: divergences wider than the combined fee, how long they last and who moves first.
--
--   {lo:String} {hi:String}  as in 01_cross_pool_gap.sql
--   {fee_bps:Float64}        the combined fee of the two pools, in bps (1 + 5 = 6 for 0.01%/0.05%)
--
-- The swaps of both pools are merged into one sequence in chain order. At every swap the gap
-- is recomputed from the two prices in effect (01_cross_pool_gap.sql). An EPISODE is a
-- maximal run of consecutive swaps with |gap| > fee_bps. It OPENS at the first swap of the run
-- (opened_by: the pool whose swap took |gap| past the fee; NOT a claim about which market leads,
-- since that pool is also the one with most swaps) and CLOSES at the first swap after it with
-- |gap| <= fee_bps (closed_by: the pool whose swap brought it back). Duration is
-- in blocks: the block of the closing swap minus the block of the opening one, so 0 means it
-- opened and closed inside one block. An episode still open at the last swap is counted apart.
-- Runs are numbered by the running count of changes between open and closed (gaps and
-- islands); lagInFrame and leadInFrame need their explicit one-row frames.

WITH
    lo AS
    (
        SELECT block_number AS blk, bitShiftLeft(block_number, 32) + log_index AS pos, toUInt8(1) AS pair,
               toFloat64(sqrt_price_x96) AS sp, tx_hash AS tx
        FROM raw_swaps
        WHERE pool_address = {lo:String}
    ),
    hi AS
    (
        SELECT block_number AS blk, bitShiftLeft(block_number, 32) + log_index AS pos, toUInt8(1) AS pair,
               toFloat64(sqrt_price_x96) AS sp, tx_hash AS tx
        FROM raw_swaps
        WHERE pool_address = {hi:String}
    ),
    events AS
    (
        SELECT lo.blk AS blk, lo.pos AS pos, lo.tx AS tx, 'lo' AS mover, 2e4 * log(lo.sp / hi.sp) AS gap_bps
        FROM lo ASOF JOIN hi ON lo.pair = hi.pair AND lo.pos > hi.pos
        UNION ALL
        SELECT hi.blk AS blk, hi.pos AS pos, hi.tx AS tx, 'hi' AS mover, 2e4 * log(lo.sp / hi.sp) AS gap_bps
        FROM hi ASOF JOIN lo ON hi.pair = lo.pair AND hi.pos > lo.pos
    ),
    marked AS
    (
        SELECT blk, pos, tx, mover, gap_bps,
               abs(gap_bps) > {fee_bps:Float64}                                   AS is_open,
               lagInFrame(abs(gap_bps) > {fee_bps:Float64}, 1, 0) OVER previous   AS was_open
        FROM events
        WINDOW previous AS (ORDER BY pos ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)
    ),
    runs AS
    (
        SELECT blk, pos, tx, mover, gap_bps, is_open,
               sum(toUInt32(is_open != was_open)) OVER (ORDER BY pos ROWS UNBOUNDED PRECEDING) AS run_id
        FROM marked
    ),
    per_run AS
    (
        SELECT run_id, any(is_open) AS open, argMin(blk, pos) AS start_blk,
               argMin(tx, pos) AS start_tx, argMin(mover, pos) AS opened_by, count() AS swaps_in_run, max(abs(gap_bps)) AS peak_bps
        FROM runs
        GROUP BY run_id
    ),
    episodes AS
    (
        SELECT run_id, open, start_blk, opened_by, swaps_in_run, peak_bps, start_tx,
               leadInFrame(start_blk, 1, 0) OVER next_run  AS close_blk,
               leadInFrame(opened_by, 1, '') OVER next_run AS closed_by,
               leadInFrame(start_tx, 1, start_tx) OVER next_run AS close_tx
        FROM per_run
        WINDOW next_run AS (ORDER BY run_id ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING)
    )
SELECT
    count()                                                           AS episodes,
    countIf(close_blk = 0)                                            AS still_open_at_the_end,
    countIf(close_blk = start_blk)                                    AS closed_in_the_same_block,
    countIf(close_blk > 0 AND close_blk - start_blk = 1)              AS closed_one_block_later,
    countIf(close_blk > 0 AND close_blk - start_blk >= 2)             AS closed_two_or_more_blocks_later,
    quantileExactIf(0.50)(close_blk - start_blk, close_blk > 0)       AS blocks_open_p50,
    quantileExactIf(0.90)(close_blk - start_blk, close_blk > 0)       AS blocks_open_p90,
    quantileExactIf(0.99)(close_blk - start_blk, close_blk > 0)       AS blocks_open_p99,
    maxIf(close_blk - start_blk, close_blk > 0)                       AS blocks_open_max,
    countIf(opened_by = 'lo')                                         AS opened_by_lo,
    countIf(opened_by = 'hi')                                         AS opened_by_hi,
    countIf(close_blk > 0 AND closed_by = 'lo')                       AS closed_by_lo,
    countIf(close_blk > 0 AND closed_by = 'hi')                       AS closed_by_hi,
    countIf(close_blk > 0 AND closed_by != opened_by)                 AS closed_by_the_other_pool,
    countIf(close_blk > 0 AND closed_by = opened_by)                  AS closed_by_the_same_pool,
    countIf(opened_by = 'lo' AND close_blk > 0 AND closed_by = 'hi')  AS opened_by_lo_closed_by_hi,
    countIf(opened_by = 'hi' AND close_blk > 0 AND closed_by = 'lo')  AS opened_by_hi_closed_by_lo,
    countIf(close_blk > 0 AND close_tx = start_tx)                    AS never_left_one_transaction,
    quantileExact(0.50)(peak_bps)                                     AS peak_gap_p50_bps,
    quantileExact(0.99)(peak_bps)                                     AS peak_gap_p99_bps
FROM episodes
WHERE open

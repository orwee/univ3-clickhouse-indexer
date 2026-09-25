# Two fee tiers of one pair: how far apart, and for how long

**The question.** USDC/WETH trades in two Uniswap v3 pools of this repository, one charging
0.01% and one 0.05%. They quote one price. How far apart do they get, how long does a gap wider
than their fees survive, and does one of them lead the other?

Every figure below is from the run of 2026-09-25 (1,240,618 swaps, 2026-08-09 to 2026-09-25),
in the committed report [evidence/2026-09-25/analysis.md](evidence/2026-09-25/analysis.md).
The queries are [sql/analysis/01 to 04](../sql/analysis/01_cross_pool_gap.sql), run by
`make analysis`, which finds the two pools in `pools.yml` (same tokens, different fees) rather
than naming them.

## Method

- **The price.** A Swap log carries `sqrtPriceX96`, the pool's price after that swap. Both pools
  hold USDC as token0 and WETH as token1, so the ratio of their prices is the square of the
  ratio of their `sqrtPriceX96` and the decimals cancel.
- **The price in effect elsewhere.** For every swap of one pool, the other pool's price is the
  one its last swap left, strictly earlier in chain order. That is an `ASOF JOIN` on the
  position in the chain, `block_number * 2^32 + log_index` in one integer. A swap that comes
  before the other pool's first swap has nothing to join to and is left out.
- **The gap** is `10,000 × ln(P_0.01% / P_0.05%)`, in basis points. For gaps of a few bps it is
  the relative difference to within a hundredth of a bp; unlike it, a price that doubles and
  one that halves come out the same size.
- **The fee band.** 1 bp + 5 bps = **6 bps**. Inside it, trading one pool against the other
  loses money on fees alone (before gas; in log terms the band is 6.0013 bps, which changes
  nothing here).
- **An episode** is a run of consecutive swaps, both pools merged in chain order, with the gap
  wider than 6 bps. It opens at its first swap and closes at the first swap that brings the gap
  back inside the band. Its length is counted in blocks: 0 means it opened and closed in one
  block.

## What it shows

| | All swaps | Swaps of the 0.01% pool | Swaps of the 0.05% pool |
|---|---|---|---|
| swaps with a gap | 1,233,584 | 926,413 | 307,171 |
| median absolute gap | 2.85 bps | 2.79 bps | 3.00 bps |
| 95th percentile | 6.30 bps | 6.10 bps | 7.14 bps |
| 99th percentile | 12.64 bps | 11.15 bps | 16.93 bps |
| within the 6 bps band | **94.1%** | 94.7% | 92.4% |

- **Measured swap by swap, the two pools sit within their fees 94.1% of the time.** A gap
  counted at every swap includes states inside a transaction and inside a block that nobody
  outside could trade. **Measured where each block ends**, after its last swap of either pool
  ([04_cross_pool_block_ends.sql](../sql/analysis/04_cross_pool_block_ends.sql)), they are
  within the band in **97.9%** of 290,270 blocks, with a median gap of 2.68 bps.
- **A divergence rarely outlives its block.** 29,474 episodes; **80.8% close in the same
  block** they opened in, 5,008 one block later, 637 two or more blocks later. The longest
  lasted 6 blocks. 3,874 of them (13.1%) opened and closed inside one transaction: a state
  that existed only between two steps of that transaction, not a gap anyone else could trade.
- **Neither pool leads.** The swap that opens a divergence is in the 0.01% pool 76.9% of the
  time, about its share of the swaps (75.1%). 57.5% of the divergences are closed by a later
  swap in the same pool that opened them; when the other pool closes one, the split is 6,872
  to 5,657. The data show which pool's swap crossed the band,
  which is not the same thing as which market moved first.
- **The tail is real and rare.** The largest gap is about 16,000 bps, a price five times the
  other pool's, left by a swap of the 0.01% pool. A swap that far from its neighbours is a
  displaced swap in the sense of finding 7 of the reconciliation (more than 100 ticks away).

## The thin pair is not comparable

The same queries on wstETH/USDC (0.05% against 0.3%, a combined fee of 35 bps) show a median
gap of 27 bps and divergences that last a median of 38 blocks. Part of it is thin liquidity:
the 0.3% pool has 931 swaps in the whole window. Part of it is a price nobody could trade at:
five swaps left the 0.3% pool with no liquidity in range and three ended at the edge of its
tick range, and every swap of the 0.05% pool while it sat there is measured against that edge.
The report keeps the figures; this document draws no conclusion from them.

## What ClickHouse does with these queries

- **The sorting key does the pruning.** `raw_swaps` is ordered by
  `(pool_address, block_timestamp, block_number, log_index)`. Every scan filters on one pool,
  so the primary index keeps only that pool's granules: 117 of 153 for the 0.01% pool and 42
  of 153 for the 0.05% pool (`EXPLAIN indexes = 1`, kept in the report). The time part of the
  key does nothing here: there is no time filter.
- **A CTE is not a temporary table.** Each query names each pool's CTE twice (once on each side
  of the two ASOF joins), and ClickHouse reads it twice: 2,576,810 rows read for 1,233,584
  swaps.
- **Two join algorithms, one answer.** ClickHouse 26.3 runs an ASOF JOIN as a hash join or as a
  full sorting merge. On the gap query, over three runs each, the hash join took a median of
  228 ms and 214 MB, the sorting merge 637 ms and 186 MB, and both returned the same answer. At
  this size the hash join wins on time. The sorting merge sorts both sides instead of building
  a hash table of one, and can spill to disk; here the memory is dominated by the exact
  quantiles, so the two are close.
- **The query condition cache is off** for every query of the report, so the rows read are what
  the key prunes and not what an earlier run left in the cache (see
  [SCHEMA_EXPERIMENTS.md](SCHEMA_EXPERIMENTS.md) for why that matters).

## Limitations

- **Pool prices, not executable prices.** `sqrtPriceX96` is the marginal price after a swap. A
  trade of any size moves it; the gap says nothing about what size could have been traded
  across the two pools, and gas is ignored.
- **Block order is the builder's.** Which swap comes first inside a block is decided by whoever
  built the block, so "closed in the same block" measures how blocks are built as much as how
  markets move.
- **One pair.** The analysis runs on every pair of `pools.yml` with two fee tiers; USDC/WETH is
  the only one liquid enough to read.

## Why it matters

Two pools of one pair are two measurements of one price. In this window they did not disagree
beyond their fees for more than six blocks, and rarely at the end of a block, which is
what lets each serve as a check on a price or a volume taken from the other. It is also a
check on this pipeline: a decoding or ordering error in either pool would show up as a gap
that does not close.

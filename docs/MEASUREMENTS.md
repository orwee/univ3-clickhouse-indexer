# Measurements

Numbers taken from the real endpoint, so that design decisions rest on
observations and not on guesses. Each section says when and how it was taken.

## 2026-09-18: `eth_getLogs` on the Alchemy free tier

Endpoint: Alchemy, Ethereum mainnet, free tier. Filter: the three pools in
`pools.yml` in one call, `topics[0]` = Swap. End of the window: block
26,003,970 (chain tip minus 20). 156 calls in total for everything below.

### Block range limit

| Range (inclusive) | HTTP | Result |
|---|---|---|
| 10 blocks | 200 | 23 logs, 20,535 bytes, 41 ms |
| 11 blocks | 400 | JSON-RPC error `-32600` |
| 100 blocks | 400 | same error |
| 1,000 blocks | 400 | same error |
| 10,000 blocks | 400 | same error |

The error text, identical in every case: *"Under the Free tier plan, you can
make eth_getLogs requests with up to a 10 block range. Based on your
parameters, this block range should work: [0x…, 0x…]. Upgrade to PAYG for
expanded block range."*

So the limit is exactly 10 blocks, inclusive on both ends (`toBlock -
fromBlock = 9`). The rejection is an HTTP 400, not a 429: it must not be
retried. The client treats it as a permanent error.

### Latency

Eight consecutive 10-block calls on a warm connection: 36 to 43 ms, median
40.5 ms. Over the 90 sampling calls below: median 44 ms, p95 50 ms, max 135 ms.
No `Retry-After` or rate-limit headers in any response, and no HTTP 429 in 156
calls paced at 4 per second.

### Swap density, and what 30 days looks like

90 windows of 10 blocks, evenly spread over the last 216,000 blocks (30 days
of 12-second slots): 900 blocks, 2,852 logs.

| | Sample | Extrapolated to 30 days |
|---|---|---|
| All pools | 3.17 logs per block | **~684,000 rows** |
| USDC/WETH 0.01% | 2,839 logs (99.5%) | ~681,000 |
| wstETH/USDC 0.05% | 13 logs | ~3,100 |
| wstETH/USDC 0.3% | 0 logs | a few hundred at most |

Logs per 10-block window: min 10, median 29.5, max 142. The distribution is
bursty, so the total is good to perhaps ±15%, and the two wstETH figures are
order-of-magnitude only: 13 and 0 events are too few to extrapolate from. In
520 consecutive blocks fetched for the fixtures, the 0.3% pool had 3 swaps
(which would be ~1,200 in 30 days).

**The data set is extremely skewed: one pool is 99.5% of the rows.**

Raw JSON on the wire: ~890 bytes per log, so ~610 MB for the 30 days.

### Backfill time for 30 days

216,000 blocks / 10 = **21,600 calls**.

| Pace | Time | Comment |
|---|---|---|
| Unpaced, sequential, ~44 ms per call | ~16 min | ~23 calls/s: expect to be throttled |
| 5 calls/s (client default, `min_interval=0.2`) | **~72 min** | the pace used for sampling was 4/s, with no 429 |
| 2 calls/s | ~3 h | conservative |

The free-tier throughput and monthly quota are expressed in compute units. I
did not verify the current figures: **check the Alchemy dashboard for the CU
cost of `eth_getLogs` and the monthly allowance before launching.**

### Provider detail worth knowing

Each log carries a non-standard `blockTimestamp` field (hex seconds). With it
the block time comes for free; without it, one `eth_getBlockByNumber` call per
distinct block would be needed (~200,000 more calls). The decoder treats the
field as optional because other providers may not send it.

## 2026-09-19: the same measurement with four pools

USDC/WETH 0.05% was added (DECISIONS.md #9) to have the same pair in two fee
tiers and a less lopsided data set. 120 windows of 10 blocks spread evenly over
the last 216,000 blocks, ending at block 26,010,715 (tip minus 64): 1,200
blocks, 4,896 logs, 121 requests through `rpc.JsonRpcClient` at 4 calls per
second, no retries.

| | Sample | Share | Extrapolated to 30 days |
|---|---|---|---|
| All pools | 4.08 logs per block | | **~881,000 rows** |
| USDC/WETH 0.01% | 3,571 | 72.9% | ~643,000 |
| USDC/WETH 0.05% | 1,282 | 26.2% | ~231,000 |
| wstETH/USDC 0.05% | 41 | 0.8% | ~7,400 |
| wstETH/USDC 0.3% | 2 | 0.04% | a few hundred |

Logs per 10-block window: min 14, median 38, max 177. Same caveat as before:
the total is good to perhaps ±15%, the two wstETH figures are order of
magnitude only. Note that yesterday's sample put wstETH/USDC 0.05% at ~3,100
rows and today's at ~7,400: with counts this small the estimate moves a lot.

The skew went from 99.5% in one pool to 73% / 26% / 1%.

**Disk.** Raw JSON is 891 bytes per log: ~785 MB for 30 days. The JSONL landing
zone stores the raw log plus its decoded form on each line; the measured size
per line is in the README section on the backfill.

**Time.** Unchanged. The cost is per call, not per address, and all four pools
travel in one call: still 21,600 calls, ~72 minutes at 5 calls per second.

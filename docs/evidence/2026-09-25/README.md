# Snapshot of the run of 2026-09-25: five more days, round trips, cross-pool, the open case

Made with the code of branch `feat/week-2`. The landing zone was extended from block
26,019,266 to block 26,050,796, the block the node reported as `finalized` at 00:24 UTC
(its timestamp: 2026-09-25 00:09:59 UTC), as a new plan of its own; no earlier plan moved. The
last swap landed is in block 26,050,795, at 00:09:47 UTC.

| File | Made by |
|---|---|
| [reconciliation.md](reconciliation.md), [reconciliation_evidence.md](reconciliation_evidence.md), `reconciliation.csv` | `make reconcile`, over all 48 days |
| [analysis.md](analysis.md), `analysis.json` | `make analysis`: round trips ([docs/ROUND_TRIPS.md](../../ROUND_TRIPS.md)) and the gap between fee tiers ([docs/CROSS_POOL.md](../../CROSS_POOL.md)) |
| [receipts_2026-08-19_15h.md](receipts_2026-08-19_15h.md), `receipts_2026-08-19_15h.json` | `python -m univ3_indexer.receipts --report`, from 820 receipts cached outside the repository |

Data at that moment: 1,240,618 swaps, 4 pools, 2026-08-09 to 2026-09-25 (the last day holds
only its first ten minutes and is excluded from the comparison as partial). 188 pool-days on
both sides, 183 compared, 18 flagged.

**What changed against the run of 2026-09-21** ([its snapshot](../2026-09-21/README.md)):

- None of the 163 pool-days compared then changed, on our side or on the external source's:
  the daily candles downloaded again on 2026-09-25 give the same values for every day already
  compared.
- 2026-09-20 was partial then (the landing stopped at block 26,019,265, 14:16 UTC) and
  excluded. It is complete now, and its four pool-days are compared: all four within 1%.
- The 16 pool-days of 2026-09-21 to 2026-09-24 are new. One is flagged: wstETH/USDC 0.05% on
  2026-09-24, where the external source has more than the chain (10,514 against 14,022 USD).
  One more is beyond 1% but below 1,000 USD.

External calls for this run, from the ledger kept outside the repository: to the node,
3,156 for the landing (3,154 `eth_getLogs` and the two reads of the head the CLI makes before
it starts), 820 receipts, and 4 reads of the head while waiting for the finalized block to
pass midnight, 3,980 in all; to GeckoTerminal, 8 (daily and hourly candles of the four pools).

# Changelog

What changed, by date. The why of each decision is in [DECISIONS.md](DECISIONS.md); what was
found is in [docs/RECONCILIATION_FINDINGS.md](docs/RECONCILIATION_FINDINGS.md). Figures quoted
here are the ones of that day's run.

## 2026-09-25 — week 2: more data, round trips, cross-pool, the open case

- **More data, up to the finalized block.** The landing zone was extended by five days to
  block 26,050,796 (129,942 swaps, 1,240,618 in all), loaded incrementally with the
  materialized view fed by its trigger. The reconciliation over 48 days compares 183 pool-days
  and flags 18; none of the pool-days compared before changed
  ([snapshot](docs/evidence/2026-09-25/README.md)).
- **Round trips over the whole dataset.** Two dbt marts with five tests that can fail (29 in
  the project, each shown failing by `make dbt-prove`): 9.8% of all USD volume is the two legs
  of swaps undone in the same block by the same sender, 4.9% counting only the half that comes
  back, 24.4% of one pool and under 1% of its sibling ([ROUND_TRIPS.md](docs/ROUND_TRIPS.md)).
- **Two fee tiers of one pair, with ASOF JOIN.** The USDC/WETH pools sit within their combined
  fee at 94.1% of swaps and 97.9% of block ends; 80.8% of divergences close in the block they
  opened; neither opens divergences more often than its share of swaps predicts
  ([CROSS_POOL.md](docs/CROSS_POOL.md)).
- **The largest open case, from its receipts.** 820 transactions read once from the node:
  netting inside a transaction does not explain the hour, and the case stays open
  ([findings](docs/RECONCILIATION_FINDINGS.md#what-is-still-open)).
- **Smart money on the new days.** One call to the Nansen API (1 credit, 90 left): 20 more
  pool-days; over the 35 days now fetched, smart-money transactions hold 0.091% of the USD
  volume ([NANSEN.md](docs/NANSEN.md)). Smart-money data: Powered by Nansen API.
- **The page at full width**, with a dated what's-new block and three sections for the above; a
  caption bug on the published page fixed. Before publishing, a second agent given only the
  repository re-derived the new figures from `raw_swaps` with its own queries, and another
  checked every figure of the text against the snapshots; what they found is fixed and listed
  in the pull request.

## 2026-09-23 — the published page

- The dashboard takes the design tokens of robertofajardoduro.com: dark first, a light scheme,
  a hero header, a series palette derived from the site's accent and validated for contrast and
  colour-vision deficiency, a dash pattern per line.
- A clean clone could not run `make test` or `make dashboard`: both read the git-ignored
  `reports/`. The page is now built from committed snapshots only, and three of its links that
  pointed into `reports/` (404 on GitHub) point at them.

## 2026-09-21 — out of sample, and a page anyone can open

- The explanation of the largest differences was frozen in a commit, then tested on ten days it
  had not seen and against a placebo ([H2_PREREGISTRATION.md](docs/H2_PREREGISTRATION.md)).
- 30 of the 55 dbt tests could not fail; they were replaced, leaving 24, and `make dbt-prove`
  breaks the data on purpose to show that every remaining test can.
- `FINAL` was measured again with the real sorting key; a published claim about it was retracted.
- Ingestion stops at the node's `finalized` block; 680 landed block hashes were checked canonical.
- Everything in English, a dashboard on GitHub Pages, and the `protect-main` ruleset enforced.

## 2026-09-20 — reconciliation

- A second, independent source (GeckoTerminal, daily and hourly candles) and `make reconcile`:
  internal check exact, external differences located to a pool, a day and usually an hour.
- Rules for what is compared (complete days, closed candles) and flagged (1% and 1,000 USD).
- Ten findings with their state, an adversarial review, and the Nansen API for smart-money
  aggregates (aggregates only).

## 2026-09-19 — from the chain to dbt

- A fourth pool, derived from the factory. The backfill CLI, a JSONL landing zone, the raw table,
  an idempotent loader that verifies itself, sanity queries, the daily materialized view.
- Schema candidates measured on the real data before any decision; the dbt project: staging,
  dimension, daily mart and tests.

## 2026-09-18 — foundations

- ClickHouse 26.3 LTS in Docker with a hard memory limit, the Python package, pools verified on
  chain, a JSON-RPC client with pacing and backoff, lossless Swap decoding, ABI constants checked
  by keccak, agent rules and the first decisions.

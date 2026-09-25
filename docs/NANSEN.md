# Nansen: what it adds to a Swap log, what runs today, and what production would add

A Uniswap v3 `Swap` log says which pool traded, how much, at what price, and names two
addresses: `sender` and `recipient`. It does **not** say who signed the transaction.
`sender` is the caller of the pool's `swap()`, and Uniswap v3 collects the input token through
a callback on that caller, so a sender is always a contract (a router, an aggregator, a bot's
own contract) and never the wallet behind it. In this dataset the eight largest senders carry
70% of the USD volume and the largest one 33%
([sql/examples/03_sender_concentration.sql](../sql/examples/03_sender_concentration.sql)).

Nansen brings the two things the log lacks:

- **`tx.from`, the signer of the transaction.** Its DEX-trade endpoints report
  `trader_address`, documented as "the signer of the transaction". Getting that from the chain
  would take one `eth_getTransactionByHash` per transaction: hundreds of thousands of calls
  for this window.
- **What that signer is.** `trader_address_label` and the smart-money classification (Fund,
  Smart Trader, 30D/90D/180D Smart Trader): Nansen's own, proprietary attribution. No amount
  of on-chain reading produces it.

The join key between the two worlds is the transaction hash, which both sides have.

## What runs today on the free tier

Everything below was run on 2026-09-20 with a Free plan key. Costs come from the official
table (<https://docs.nansen.ai/getting-started/credits.md>, "Endpoint Credit Cost"), read
**before** each call; every response confirmed its cost in `X-Nansen-Credits-Used`.

| Call | Endpoint | Documented cost | Calls | Credits |
|---|---|---|---|---|
| Trailing 24 h of smart-money trades, all tokens ([NANSEN_CROSS.md](NANSEN_CROSS.md)) | `smart-money/dex-trades` | 5 | 1 | 5 |
| Probe: WETH, one day | `tgm/dex-trades` | 1 | 1 | 1 |
| Probe: USDC, one day | `tgm/dex-trades` | 1 | 1 | 1 |
| USDC, 2026-08-21 to 2026-09-19, smart money only | `tgm/dex-trades` | 1 | 2 | 2 |
| USDC, 2026-09-20 to 2026-09-24, smart money only (run of 2026-09-25) | `tgm/dex-trades` | 1 | 1 | 1 |
| **Total** | | | **6** | **10** |

Balance: 100 trial credits at the start, 91 left on 2026-09-20, **90 left** on 2026-09-25 (the
response of that call: documented 1, quoted 1, used 1). The Free plan is 100 one-time trial
credits and, once they are gone, a daily top-up back to a 10-credit balance: that steady
state is the "10 credits a day" of DECISIONS.md #4 and AGENTS.md, written before the trial
credits were known to be intact. The ceiling for the `tgm/dex-trades` campaign, 40 credits,
was the owner's cap out of the 95 then left, not a function of the allowance; it used 4.

### The probe, and why the token is USDC and not WETH

`tgm/dex-trades` takes one token address, a date range and `only_smart_money`. The WETH
address (from `pools.yml`, checked against the on-chain evidence in `docs/verification/`)
returned **zero trades** for a whole day. Nansen files trades in ether under the native
placeholder `0xeeee…eeee`, not under the WETH contract: in the 24-hour response, 67 of 181
trades name ETH and none names WETH. That placeholder is not a token of `pools.yml`, and the
client refuses any address that is not. USDC is: it is one leg of all four pools, so one
series of USDC trades speaks for all of them. The probe for one day returned 48 trades in a
single page, which put 30 days at about 1,440 trades, two pages of 1,000. The real figure:
**1,498 trades, 2 pages, 2 credits**. The whole window fitted; it was not reduced.

### The result

`PYTHONPATH=src uv run python -m univ3_indexer.nansen --daily USDC …` crosses the cached trades with `raw_swaps` by
transaction hash and stores one row per pool and UTC day in `nansen_smart_money_daily`
(`sql/003_nansen_smart_money_daily.sql`); the dbt model `fct_pool_daily_smart_money` divides
by `fct_pool_daily`. 30 complete days, 120 pool-days, 2026-08-21 to 2026-09-19:

> **Smart-money data: Powered by Nansen API.** The aggregates below are derived from Nansen's
> proprietary smart-money classification. Only aggregates per pool and day are published here;
> no address, label or transaction hash from their responses is redistributed, following their
> redistribution guidelines (<https://docs.nansen.ai/mcp/redistribution-guidelines.md>).

| Pool | Our swaps | In smart-money transactions | Our USD | Smart-money USD | Share of swaps | Share of USD | Days with any | Highest daily share of USD |
|---|---|---|---|---|---|---|---|---|
| USDC/WETH 0.05% | 227,562 | 153 | 2,438,587,799 | 1,698,906 | 0.067% | 0.070% | 27 of 30 | 0.39% |
| USDC/WETH 0.01% | 626,933 | 521 | 1,368,378,340 | 1,320,570 | 0.083% | 0.097% | 30 of 30 | 0.23% |
| wstETH/USDC 0.05% | 4,594 | 2 | 26,352,526 | 4,195 | 0.044% | 0.016% | 2 of 30 | 4.21% |
| wstETH/USDC 0.3% | 602 | 1 | 57,219 | 50 | 0.166% | 0.087% | 1 of 30 | 0.62% |
| **All four** | 859,691 | 677 | 3,833,375,884 | 3,023,721 | 0.079% | 0.079% | | |

Of the 1,498 transactions Nansen lists, 666 pool-transactions are in `raw_swaps` (a
transaction routed through two of the pools counts once in each). What these shares mean is
not decided here.

**Five more days (2026-09-25).** One more call, for the five days the landing gained: 329
trades in one page, the window closed (newest trade 23:53 UTC on 2026-09-24), cached like the
others and crossed the same way. 20 pool-days, 2026-09-20 to 2026-09-24:

| Pool | Our swaps | In smart-money transactions | Our USD | Smart-money USD | Share of swaps | Share of USD | Days with any | Highest daily share of USD |
|---|---|---|---|---|---|---|---|---|
| USDC/WETH 0.01% | 110,804 | 145 | 414,591,114 | 602,432 | 0.131% | 0.145% | 5 of 5 | 0.31% |
| USDC/WETH 0.05% | 34,124 | 42 | 341,467,959 | 545,946 | 0.123% | 0.160% | 5 of 5 | 0.43% |
| wstETH/USDC 0.3% | 273 | 0 | 35,372 | 0 | 0% | 0% | 0 of 5 | 0% |
| wstETH/USDC 0.05% | 469 | 1 | 22,490 | 5 | 0.213% | 0.022% | 1 of 5 | 0.38% |
| **All four** | 145,670 | 188 | 756,116,935 | 1,148,383 | 0.129% | 0.152% | | |

Over the 35 days now fetched (2026-08-21 to 2026-09-24, 140 pool-days): 865 of 1,005,361 swaps
(0.086%) and 4,172,105 of 4,589,492,820 USD (0.091%). The five new days are higher than the
thirty before them in both pools of USDC/WETH; five days are too few to say more.

What this measures and what it does not:

- It is the share of **our swaps** that belong to transactions **signed by** a wallet Nansen
  classifies as smart money **and** filed as a USDC trade. A smart-money wallet that trades
  through a contract that signs for it, or whose trade Nansen files under another token pair,
  is not in it.
- USD is this project's figure (the stablecoin leg at 1 USD), not Nansen's
  `estimated_value_usd`, so the share divides like by like.
- A pool-day without a row was **not fetched**. Zeros are stored, so "fetched, nothing found"
  and "not looked at" stay different; the dbt model uses an INNER JOIN for the same reason.

### How to run it

```
# as the user who can read the API key; 1 credit per page that is not cached yet
PYTHONPATH=src uv run python -m univ3_indexer.nansen --fetch-tgm USDC --from 2026-08-21 --to 2026-09-19 --max-pages 10
# no call: cross the cached pages and store the aggregate; then the mart
PYTHONPATH=src uv run python -m univ3_indexer.nansen --daily USDC --from 2026-08-21 --to 2026-09-19
make dbt-build
```

Without a key nothing breaks: `scripts/run_dbt.py` creates `nansen_smart_money_daily` empty
when it is missing, and the mart builds with no rows (`make demo` does exactly that).

### How the spending is kept under control

- The cost of every call is checked against a ceiling **before** it is sent. The ceiling
  outlives the process: spent credits are appended to a ledger next to the cache, and a new
  run starts from what the ledger says (`--max-credits`, 40 by default, per endpoint).
- No retries, ever. A request that failed may have been billed; a network failure is booked
  as if it had been.
- A cached page is never requested again. Pages are asked oldest first over a closed window,
  so page 2 is the same page 2 tomorrow.
- The API key travels in one header and is in no log, error, ledger or cached file.

### What stays out of the repo

Raw responses name wallets and carry Nansen's labels: they are Nansen's data about third
parties. They live under `<data dir>/nansen/` (mode 600, outside the working copy and outside
ClickHouse). The repo holds the client, tests that use **synthetic** responses only, and
aggregates per pool and day. A test fails if a report contains a transaction hash, an address
or a label.

## What production would add

**A design. None of this has been run**, and none of it fits the free tier.

### Labels for the main counterparties, served from a ClickHouse dictionary

`profiler/address/labels` costs **100 credits per call**, one address per call
(<https://docs.nansen.ai/api/profiler/address-labels.md>). The eight largest senders and
recipients are nine distinct addresses and about 70% of the volume on either side: 900
credits to know who moves two thirds of the money. On a Pro plan (2,000 credits a month) that is affordable once, not
per run, which shapes the design:

- **Refresh in batches, not per query.** A scheduled job picks the addresses worth labelling
  (top N by trailing 30-day volume, not yet labelled or older than a TTL of, say, 90 days),
  spends a fixed monthly credit budget on them through the same budgeted client, and appends
  to a small table `address_labels (address, category, label, fetched_at)`,
  `ReplacingMergeTree(fetched_at)`. Labels change slowly; volume concentration means a few
  dozen addresses cover most of the money.
- **Serve with a dictionary, not a JOIN.** `CREATE DICTIONARY address_label_dict` with the
  table as source, `LAYOUT(HASHED())` and a `LIFETIME` of hours. Queries use
  `dictGet('address_label_dict', 'category', sender)`. A dictionary lives in memory, is looked
  up by key inside the expression, does not make ClickHouse build the right-hand side of a
  join for every query, and reloads itself from its source. With `join_use_nulls = 0` a JOIN
  would also turn "no label" into an empty string silently; `dictGetOrDefault` makes the
  default explicit (`'unlabelled'`).
- **In dbt**, the dictionary is a source; a mart `fct_pool_daily_by_counterparty` gives volume
  per pool, day and category. The share of volume that is `'unlabelled'` is published next to
  it, because a breakdown that hides its own coverage reads as complete when it is not.
- **Redistribution.** Labels are licensed data. They would stay in the warehouse and out of
  any public repo or export, as the raw responses do today.

### Premium labels

`profiler/address/premium-labels` costs **500 credits per call**; several Token God Mode
endpoints go from 5 to 150 credits with `premium_labels=true`. They would be bought for a
named question (for example: is the one address behind 33% of the volume a market maker, a
solver or an exchange?), never as a default column. The batch job takes the endpoint as a
parameter and has a separate, smaller budget for it.

### The Nansen MCP for investigation, the API for the pipeline

Nansen publishes an MCP server (<https://docs.nansen.ai/mcp/overview.md>) that exposes its
data as tools to an AI agent; credits apply to it as well.

- **The pipeline uses the API.** A scheduled load has to be deterministic: a fixed request, a
  cost known before the call, a cached and replayable response, a test with a synthetic body.
  An agent choosing tools at run time gives none of those.
- **The investigation of a mismatch is where the MCP fits.** Reconciliation leaves questions
  that are exploratory by nature. One from this dataset: on 2026-09-11 USDC/WETH 0.01% is 3.14%
  (1,615,421 USD) above the external source, and four swaps of about 1.59 million USD sit in
  two timestamps, one of each pair leaving the pool about 4,100 and 7,100 ticks away from the
  day's median. Who signed those transactions, what else those wallets did that hour, whether the
  same pattern shows in other pools: a person with an agent and the MCP can follow that thread
  in minutes, and none of it belongs in a DAG.
- **The boundary.** What an investigation finds becomes a pipeline rule only after it has been
  written as a deterministic query with a test. The agent proposes; the pipeline never depends
  on it. The MCP redistribution guidelines
  (<https://docs.nansen.ai/mcp/redistribution-guidelines.md>) apply to whatever is written
  down from such a session.

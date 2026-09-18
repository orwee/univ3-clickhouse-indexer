# Decisions

Why things are the way they are, written when the decision was made, including
what I gave up. Newest entries go at the bottom. An entry is never rewritten:
if I change my mind, I add a new entry and mark the old one `Superseded by #N`.

## Entry template

```
## N. Short title

- Date: YYYY-MM-DD
- Status: Accepted | Superseded by #N

**Context.** What forced a choice.
**Decision.** What I chose.
**Why.** The reasoning, in my own words.
**Tradeoff.** What this costs me or leaves out.
**Revisit when.** The signal that would make me reopen it.
```

---

## 1. Local Docker instead of the ClickHouse Cloud trial

- Date: 2026-09-18
- Status: Accepted

**Context.** I am learning ClickHouse for an interview and will show this repo
publicly. I can run the server locally or use the Cloud trial.

**Decision.** A single ClickHouse server in Docker, started with `make up`.

**Why.** I need to observe the real MergeTree engine: parts, merges and the
system tables that describe them. Cloud swaps in SharedMergeTree, so what I
would be looking at is not the engine I want to understand. And the repo has to
be reproducible by anyone with one command, without an account or a trial that
expires.

**Tradeoff.** I get no experience of the managed product: no SharedMergeTree,
no separation of storage and compute, no Cloud console.

**Revisit when.** Stretch goal: load the same data into a Cloud trial and
compare parts, merges and query plans side by side.

## 2. RPC as the raw source, the subgraph only as an external check

- Date: 2026-09-18
- Status: Accepted

**Context.** Swap events are available from an Ethereum JSON-RPC node and,
already decoded, from the Uniswap subgraph.

**Decision.** Ingest from RPC (`eth_getLogs`). Use the subgraph only to
reconcile against.

**Why.** Reconciling against the same source you ingested from proves nothing.
The check is only worth something if the two paths are independent: raw logs
decoded by me on one side, someone else's indexer on the other.

**Tradeoff.** The free tier limits `eth_getLogs` to a 10-block range, which
means about 21k calls for the window I want. Checkpointing is mandatory, not
optional: the backfill must be resumable from the last completed range.

**Revisit when.** The call count or rate limits make the backfill impractical,
or I need a window long enough to justify a paid tier.

## 3. Plain JSON-RPC over `requests`, not web3.py

- Date: 2026-09-18
- Status: Accepted

**Context.** I need an Ethereum client in Python. web3.py is the default choice.

**Decision.** Plain JSON-RPC calls over `requests`. No web3.py.

**Why.** I only need two methods, `eth_blockNumber` and `eth_getLogs`. I want
to control the chunking into 10-block ranges, the retries and the checkpoint
myself, because that is where this pipeline can go wrong. And decoding the Swap
event by hand is something I want to be able to explain in an interview.

**Tradeoff.** I write and test the decoding of signed `int256` values myself
(`amount0` and `amount1` are two's complement; `tick` is a signed `int24`).

**Rule that follows.** The Swap `topic0` is not written from memory. It is a
constant with the event signature in a comment next to it, and a test verifies
it against the real logs in the fixtures.

**Revisit when.** I need more than a handful of methods, or ABI decoding for
many event types.

## 4. Two secrets files, split by who is allowed to read them

- Date: 2026-09-18
- Status: Accepted

**Context.** The first version of this setup had a single env file holding both
the ClickHouse credentials and the API keys. Autonomous agents work on this
repo over the weekend as an unprivileged user.

**Decision.** Two files outside the repo, both mode 600:

- `clickhouse.env`, owned by the unprivileged user: `CLICKHOUSE_*` and `CH_*`.
  It is the compose `env_file` and what the tests use.
- `api-keys.env`, owned by root: `ALCHEMY_API_KEY` and `NANSEN_API_KEY`. Only
  interactive sessions and the backfill I launch myself can read it.

The config module loads both paths. The API keys file is optional: it is read
only when a key is requested, and only then does it fail loudly.

**Why.** The agents must not be able to read the API keys. A rule telling them
not to is weaker than a file permission that stops them. Nansen gives me 10
credits a day; one careless loop would burn them.

**Tradeoff.** Two files and two path pointers instead of one. Anything that
needs an API key has to run as a user who can read the second file, so the
backfill cannot be delegated to an agent.

**Revisit when.** A job that needs a key has to run unattended. Then: a
dedicated key with its own quota for that job, not a wider file permission.

## 5. Pinned versions: ClickHouse 26.3 LTS and Python 3.12

- Date: 2026-09-18
- Status: Accepted

**Context.** The repo must behave the same next month as today.

**Decision.** `clickhouse/clickhouse-server:26.3.33.24`, an exact patch of the
26.3 LTS line, never `:latest`. Python 3.12 via `.python-version`, dependencies
locked in `uv.lock`.

**Why.** On the day of the decision there were two live LTS lines. 26.3 had
six months of patches behind it; 26.8 was a month old and had shipped four
patch releases in four days. For watching parts and merges I need stability,
not the newest features. Python 3.12 is the version the whole planned stack
declares: dbt-core 1.12 lists 3.10 to 3.14, but dbt-clickhouse 1.10.3 only
lists up to 3.13, and 3.12 is the most exercised with dbt.

**Tradeoff.** I do not get 26.8 features. Found while checking: dbt-clickhouse
1.10.3 requires `dbt-adapters<1.25` and dbt-core 1.12.5 requires
`dbt-adapters>=1.24.5`, so exactly one dbt-adapters version satisfies both.
That will need an explicit pin when dbt is added.

**Revisit when.** 26.3 stops receiving patches, or dbt-clickhouse declares a
newer Python.

## 6. A hard 3 GiB memory limit with no swap, and what ClickHouse does with it

- Date: 2026-09-18
- Status: Accepted

**Context.** The container shares an 11 GiB machine with other services. The
first compose file set only `mem_limit: 3g`. `docker inspect` showed
`MemorySwap` at 6 GiB: with `memswap_limit` unset, Docker allows as much swap
again on top of the RAM limit.

**Decision.** `mem_limit: 3g` and `memswap_limit: 3g`. `memswap_limit` is RAM
plus swap, so making both equal means no swap at all. Verified:
`HostConfig.MemorySwap` equals `HostConfig.Memory` and `memory.swap.max` is 0
inside the container.

**Why.** A database that swaps does not fail, it just gets slow in a way that
is hard to attribute. I would rather have a query die with a clear memory error
than have timings I cannot trust while I am learning what is expensive.

**What ClickHouse does with the limit.** The server reads the cgroup limit, not
the host RAM, and applies `max_server_memory_usage_to_ram_ratio` (0.9) to it:
`max_server_memory_usage` comes out at 2.70 GiB, not 3. That is the number a
`MEMORY_LIMIT_EXCEEDED` error will refer to. The remaining 10% is headroom for
allocations the server does not track, so the kernel OOM killer stays out of it.

**Tradeoff.** Large merges or a careless `GROUP BY` over the whole backfill can
hit 2.70 GiB and fail. I will have to size inserts and queries with that in
mind, or use the external aggregation and sorting settings.

**Revisit when.** Merges or dbt models fail on memory with reasonable batch
sizes. First lever is the query, second is raising the limit.

## 7. dbt-adapters must be pinned to 1.24.5 when dbt is added

- Date: 2026-09-18
- Status: Accepted (applies from the session that adds dbt)

**Context.** Found while checking Python support for the dbt stack, before any
dbt code exists. dbt-clickhouse 1.10.3 requires `dbt-adapters>=1.22.0,<1.25.0`.
dbt-core 1.12.5 requires `dbt-adapters>=1.24.5,<2.0`. The intersection is a
single version.

**Decision.** When dbt goes into `pyproject.toml`, pin `dbt-adapters==1.24.5`
explicitly, next to dbt-core and dbt-clickhouse, and let `uv.lock` hold it.

**Why.** Today the resolver lands on 1.24.5 by itself, so the constraint is
invisible. The day dbt-core raises its floor, the resolver will quietly walk
dbt-core backwards instead of failing, and I would find out from a behaviour
change. An explicit pin turns that into a resolution error I can read. Related:
uv already resolves dbt-core to 1.12.0 rather than 1.12.5. My unverified guess
is that 1.12.5 requires `dbt-core-experimental-parser>=2.0.0b1`, a pre-release
that uv will not select by default. To be checked when dbt is added.

**Tradeoff.** One more pin to maintain by hand, and no newer dbt-core until
dbt-clickhouse widens its range.

**Revisit when.** dbt-clickhouse publishes a release that accepts
`dbt-adapters>=1.25`.

---

## Agent corrections

Things the coding agent got wrong or that I had to redirect, one line each.

- 2026-09-18: The repo and the clone directory carried a company's brand name.
  Renamed to `univ3-clickhouse-indexer`; using a company's brand on a public
  repo that is not theirs is not appropriate. The seeded README title was
  replaced too.
- 2026-09-18: The agent proposed installing `python3-venv` and building on the
  system Python (3.14). Redirected to uv with a pinned interpreter, chosen only
  after checking which versions dbt-core and dbt-clickhouse support.
- 2026-09-18: The single secrets file let the unprivileged agent user read the
  API keys. Split in two before any code depended on it (entry 4).

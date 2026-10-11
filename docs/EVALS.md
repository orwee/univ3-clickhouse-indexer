# The evaluation: questions whose answer is computed

The agent ([AGENT.md](AGENT.md)) answers questions about the marts by writing SQL. To say
how often it is right, each question needs a right answer that does not depend on anybody's
opinion, and above all not on a model's.

So the right answer to every question here is **computed by deterministic SQL on verified
data**. A case holds a question and a reference query; the answer is whatever that query
returns on the committed fixture ([`evals/fixture/`](../evals/fixture/fingerprint.json)),
which is the marts as the warehouse served them and which the reconciliation checks against
the raw table. Nobody types an answer, and no model takes part in producing one.

## What a case is

One case per line in [`evals/golden.jsonl`](../evals/golden.jsonl):

| Field | What it holds |
|---|---|
| `id` | stable and readable, for example `t-volume-day-007` |
| `question` | in English, as a person would ask it |
| `kind` | `template` (drawn from a template), `hand` (written by hand) or `unanswerable` |
| `family` | the template family, or the category for the other kinds |
| `split` | `dev` or `test` |
| `answer_type` | `number`, `label`, `date`, `list` or `refusal` |
| `expected` | the value; a number is text, so no digit is lost; null for a refusal |
| `accepted` | other values that are also right, for a question with more than one reasonable reading |
| `unit` | what a number is in |
| `tolerance` | `{"abs": "...", "rel": "..."}`: a number passes when it is within either; null for anything that is not a number |
| `reference_sql` | the query that produces `expected`: one statement, on the marts, table names without a database |
| `notes` | why the case exists and what it is meant to catch |

## How the answers are computed

`make golden` runs [`evalkit.golden`](../src/evalkit/golden.py):

1. It collects the cases without their answers. The template cases are drawn by
   [`evals/golden_templates.py`](../evals/golden_templates.py) with a fixed seed. Drawing
   needs no server: which pools and which days exist is read from the fixture files.
2. It creates a database named `test_<random>`, loads the fixture into it, and runs every
   `reference_sql` there. **Never against the live marts**: the answers have to be the same
   for anyone who clones the repository.
3. It writes the file and drops the database, also when something fails.

A reference query has to give exactly one answer: one row of one column for a number, a
label or a date, one column for a list. `NULL`, no rows or two rows stop the generator. The
same seed and the same fixture give the same file, byte for byte; a test regenerates it and
compares.

`src/evalkit/` is generic: it names no table, column or token of this warehouse, and a
test keeps it that way. Everything that does lives under `evals/`.

## The split

Stratified by family: within each family `round(n / 3)` cases go to `dev` and the rest to
`test`, drawn with a fixed seed that depends on the family alone. With ten cases per
family that is 3 and 7: 36 `dev` and 84 `test` of the 120 template cases. `dev` is for
working on the prompt; `test` is for the number that gets reported.

## The tolerances, and why

A number passes when it is within the absolute bound **or** within the relative one.

| Kind of number | `abs` | `rel` | Why |
|---|---|---|---|
| a count | 0 | 0 | A count is an integer. One swap off is wrong |
| a sum, in dollars or in a token | 0.01 | 0.001 | A cent covers rounding to two decimals. A tenth of a percent covers a sum done in floating point over many rows, and nothing else: an off-by-one day on a range moves a sum by far more |
| a ratio, a share or a price | 0 | 0.005 | A ratio has no natural absolute scale. Half a percent accepts a price computed from rounded volumes and rejects a different definition, such as an average that is not weighted |

A case may override them, and then its `notes` say why. No template case does.

A label is compared exactly, after trimming and case-folding. A date is compared as a
date. A list is compared element by element, in order.

## The twelve template families

Ten cases each, 120 in all. Each family has two or three wordings, and every question
states its unit.

| Family | Question | Answer |
|---|---|---|
| `volume-day` | dollar volume of one pool on one day | number, USD |
| `swaps-day` | number of swaps of one pool on one day | number, exact |
| `token-volume-day` | volume of one named token in one pool on one day | number, in that token |
| `volume-all-day` | dollar volume of all pools together on one day | number, USD |
| `volume-range` | dollar volume of one pool over a range of days | number, USD |
| `swaps-all-range` | number of swaps of all pools over a range of days | number, exact |
| `vwap-day` | volume-weighted average price of the non-stable token on one day in one pool: the stable token's volume divided by the other token's volume. The question says "volume-weighted" | number, stable per token |
| `top-pool-day` | which pool had the most swaps, or the most dollar volume, on one day, among all pools or among the fee tiers of one pair | label |
| `peak-day-range` | on which day of a range one pool had its highest dollar volume | date |
| `volume-change` | the change in dollar volume of one pool between two days, absolute or in percent; the question says which | number, USD or percent |
| `fees` | estimated fees of one pool on one day or over a range | number, USD |
| `share` | the share of a pair's volume that went through one fee tier on a day; the share of a pool's volume that is round trips; or its volume without them | number, percent or USD |

What the draws respect, checked on the fixture and by tests:

- **Complete days only**, 2026-08-10 to 2026-09-24. The first and the last day of the
  data, 2026-08-09 and 2026-09-25, hold part of a day.
- **Never a pool on a day it has no row for.** Four pool-days have none: `wstETH/USDC
  0.3%` on 2026-08-09, 2026-08-15 and 2026-09-25, and `wstETH/USDC 0.05%` on 2026-09-25. A
  range for one pool is only drawn where the pool has a row on every day of it.
- **One answer.** A question whose answer is a pool or a day is only drawn where the
  maximum is not tied.

Two independent checks on the answers themselves:

- every case of `volume-day` and `swaps-day` agrees with
  [`docs/evidence/2026-09-25/reconciliation.csv`](evidence/2026-09-25/reconciliation.csv),
  which `make reconcile` computes from the raw table, by another path;
- every reference query, run again on the fixture, returns exactly the stored answer.

## What is deliberately left out of the templates

- **Partial days and missing pool-days.** They are the interesting cases (is a missing
  row zero swaps, or no data?), and that is exactly why they are not drawn at random: they
  are written by hand, one by one.
- **Smart money.** `fct_pool_daily_smart_money` is empty in the fixture
  ([decision 20](../DECISIONS.md#20-the-fixture-carries-no-smart-money-rows)). A question
  about it has no answer here, and belongs with the questions that must be refused.
- **Questions with no answer.** A template always has one. Refusing is tested with cases
  written for it.
- **The legs table.** `fct_round_trip_legs` holds only the legs of round trips, so most
  questions that sound answerable from it are not. That is a trap to set on purpose, not
  to draw.
- **Ambiguity.** A template question has one reading. "The last week" with a partial last
  day does not.
- **Fee units.** The fee tier appears only inside a pool's label. A question that asks for
  a fee in basis points or in percent is written by hand.
- **Anything a model would have to compute outside SQL.** Every template answer is one
  query.

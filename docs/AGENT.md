# The agent: one question, answered with SQL

`python -m agent` gives a model three tools, lets it write SQL against the dbt marts, and
prints an answer that the last result supports, a refusal, or nothing. It lives in
[`src/agent/`](../src/agent/__init__.py), a package that knows nothing about this
warehouse: the database, the tables and the limits come from
[`evals/warehouse.yml`](../evals/warehouse.yml), and column names and types from the
database itself.

**Status on 2026-10-11: the agent has never answered a real question.** There is no model
key on this server, and the real server has no read-only user
([AGENT_ACCESS.md](AGENT_ACCESS.md)). Everything below is what the code does, checked by
tests that drive it with a scripted model. How well a real model follows the prompt is not
known yet.

## Running it

```sh
PYTHONPATH=src uv run --group agent python -m agent "How many rows does the largest table have?" \
    [--config evals/warehouse.yml] [--max-usd 0.25] [--json] [--model claude-haiku-5-5]
```

It needs two things, and stops with exit code 2 when either is missing:

- **The read-only ClickHouse user**, through `agent-reader.env` or the `AGENT_READER_*`
  variables ([AGENT_ACCESS.md](AGENT_ACCESS.md)). It connects as that user and as nobody
  else. There is no fallback to `indexer`: the code to connect as another user is not in
  the package, and a test keeps it that way.
- **`ANTHROPIC_API_KEY`**, read through `config.require_api_key`. A variable in the
  environment wins over `api-keys.env`. No key is stored on the server that holds the data.

It prints the answer, the SQL that produced it and the cost; `--json` prints the whole
result, every tool call included. Exit code 0 for an answer or a refusal, 1 when there is
no answer or the answer is not grounded, 2 when the command could not run.

The model is `claude-haiku-5-5` unless `--model` names another one that has a line in
`PRICES` ([`src/agent/llm.py`](../src/agent/llm.py)). A model without a recorded price is
refused: its cost could be neither bounded nor computed.

## How a question ends

| Status | Meaning |
|---|---|
| `answered` | `submit_answer` was called and its value is a cell of the last result |
| `refused` | The model said the data cannot answer, and why. A correct outcome |
| `ungrounded` | `submit_answer` was called and its value is **not** a cell of the last result |
| `no_answer` | The cap on model calls was reached, the budget refused a call, a model call failed, or the model stopped on its own |

At the cap the result is `no_answer`. The loop never builds an answer out of what it has
seen.

## Guardrails: what the server enforces and what is code

The decision and its reasons are entry 21 of [DECISIONS.md](../DECISIONS.md), once the
owner has added it; the read-only user is entry
[19](../DECISIONS.md#19-a-read-only-user-limited-to-the-marts-for-readers-and-agents).

**Enforced by ClickHouse**, whatever this code does, for the user `agent_reader`
([`clickhouse/users.d/agent_reader.xml`](../clickhouse/users.d/agent_reader.xml)):

- it cannot write, create, alter or drop anything (`readonly = 1`);
- it can read five tables, by name, and no others;
- it cannot change a setting, so a query stops at 10 s, at 10,000 result rows and at
  500,000,000 bytes of memory;
- it cannot read from outside the database.

**Enforced by code only**, which a bug or a later change can weaken:

- the agent connects as `agent_reader` and stops when that user is not available;
- the SQL guard ([`sql_guard.py`](../src/agent/sql_guard.py)): one statement, `SELECT`
  only, no `SETTINGS`, `FORMAT` or `INTO OUTFILE`, no table function that reads from
  outside. It gives the model a clear sentence early. It is not the security boundary;
- at most 200 rows of a result reach the model, and the same SQL is not sent twice after
  it failed;
- at most 6 model calls per question;
- a dollar budget per question, checked before every model call, with a ledger; no retry;
- the answer must be a cell of the last result, or it is marked `ungrounded`.

**Instructions, not enforcement.** The prompt
([`prompts/system.md`](../src/agent/prompts/system.md)) tells the model to do all
arithmetic in SQL, to copy the value from the last result, and to refuse instead of
guessing. Only the grounding check and the cap catch a model that ignores them.

## Limits

| Limit | Value | Where |
|---|---|---|
| Rows of one result handed to the model | 200 | `evals/warehouse.yml`, `row_cap` |
| Model calls per question | 6 | `evals/warehouse.yml`, `max_iterations` |
| Dollars per question | 0.25 | `evals/warehouse.yml`, `max_usd`; `--max-usd` |
| Output tokens per model call | 4,096 | `loop.DEFAULT_MAX_TOKENS` |
| Seconds per model call | 120, one attempt | `AnthropicLLM` |
| Seconds per query | 10 | the server, for `agent_reader` |
| Rows per query result | 10,000 | the server, for `agent_reader` |
| Memory per query | 500,000,000 bytes | the server, for `agent_reader` |

Every model call is written to a ledger, one JSON line each, at
`<data directory>/agent/ledger.jsonl`, outside the repository.

## Three behaviours a reader would not guess

### 1. The budget can stop a question with most of its money unspent

Before a model call is sent, the budget is asked whether the **worst case** of that call
still fits. The worst case is computed without asking anybody: every byte of the request is
counted as one input token, plus an allowance of 2,000, and the output is counted at its
cap of 4,096 tokens. A token is at least one byte, so this is a true upper bound, and it
needs no request. It is also loose: a real request has several bytes per token, so the
bound is several times the real input.

What that means depends on the price of the model. Measured by
[`tests/test_agent_budget_fit.py`](../tests/test_agent_budget_fit.py) on the marts fixture,
with a scripted model: six model calls, five of them a query returning 150 rows (about 25 kB
each) and the sixth the answer, on the default 0.25 USD.

| Model | Calls sent before the budget refused the next | Spent by then, under the assumption below |
|---|---|---|
| `claude-haiku-5-5` | 6 of 6 | about $0.01 |
| `claude-opus-5-5` | 2 of 6 | about $0.05 |
| `claude-sonnet-5-5` | 3 of 6 | about $0.06 |

How to read it:

- The number of calls is a property of the bound: it does not depend on what the model
  really uses, only on the size of the conversation and the price.
- The dollars are **not a measurement of a real model**. The scripted model reports one
  input token per four bytes and 300 output tokens per call; that is an assumption written
  in the test.
- A separate review session, with its own script and as the read-only user, got 2 of 6 for
  `claude-opus-5-5` and 4 of 6 for `claude-sonnet-5-5`, with 0.02 and 0.08 USD spent. Its
  results were smaller than the ones here; the conclusion is the same.
- With the default model the bound is not what stops a question. With the other two,
  raise `--max-usd` or expect `no_answer` with the reason `budget:` on questions that read
  large results.

`claude-haiku-5-5` is priced by prompt length: a request whose prompt is over 100,000
tokens pays five times as much for every token of that request. The real cost uses the
prices of the call's own prompt length (all input tokens, cache reads and cache writes
included). The worst case uses the higher prices as soon as its ceiling is over 100,000,
even though the real prompt is then usually far under it.

### 2. A result over the server's row limit is an error, not a cut result

Two limits act on a result, and they behave differently.

- Up to 10,000 rows, the tool hands the model the first 200 and sets `truncated` to true.
- Over 10,000 rows, the server refuses the whole query with error 396
  (`TOO_MANY_ROWS_OR_BYTES`). The model gets no rows at all, only the error, and has to
  aggregate or add `LIMIT`. The prompt says so.

So `truncated` never means "there were more than 10,000". A test in
`tests/test_agent_tools.py` reproduces both sides with a session row limit.

### 3. An ungrounded answer is kept, and marked

When the value of `submit_answer` is not a cell of the last successful result, the answer
is not thrown away and the question is not retried. The result keeps the answer as the
model gave it, with status `ungrounded`, and the command prints `UNGROUNDED, do not trust`
and exits with 1.

What counts as the same cell: numbers are compared as numbers, so `"6.802048"`, `6.802048`
and `"6.8020480"` are one value; everything else is compared as text, exactly. For a list,
every element has to be a cell. Only the **last** successful query counts, so a value taken
from an earlier result is ungrounded.

Grounded does not mean right. It shows the value came out of the data, not that the query
measures what was asked.

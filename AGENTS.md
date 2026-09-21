# Rules for autonomous agents

> The rules live in this file. `CLAUDE.md` only imports it, so that every
> executor (Claude Code, Codex, OpenCode) reads exactly the same text.

You are an autonomous coding agent executing one card from the owner's task board
board. Nobody is watching while you work. These rules exist because of that.

Read `README.md` and `DECISIONS.md` before changing anything. `DECISIONS.md`
explains why things are the way they are; do not undo a decision recorded there.

## 1. Scope: do the card, only the card

- One card, one branch, one pull request. Never commit to `main`, never push to
  `main`, never merge a pull request, never force-push.
- Small commits, each one leaving tests and lint green.
- If the card is ambiguous, or doing it properly needs something these rules
  forbid, **stop and ask** in the pull request or the card. A half-finished
  branch with a clear question is a good outcome. A guess is not.
- Report what you actually did. If a test fails, say so and show the output. If
  you skipped a step, say so. Never describe work you did not do.

## 2. Schema changes need a decision first

**No change to a table schema, `ORDER BY`, table engine, partitioning or column
types without a prior entry in `DECISIONS.md` that covers it. If the task
requires one, stop and ask.**

Those decisions belong to the owner. `docs/SCHEMA_OPTIONS.md` lists options; it
decides nothing. Do not add entries to `DECISIONS.md` yourself: propose the
text in the pull request description and let the owner write it.

## 3. `pools.yml` is the only source of pool addresses

- Never write a pool, token or factory address anywhere else in the code, and
  never from memory. Tests use obviously fake addresses (`0xabab…`).
- Do not add, remove or edit pools. A new pool has to be verified on-chain with
  `scripts/verify_pools.py`, which needs an API key you do not have.
- Function selectors and event topics are never written from memory either:
  each constant in `src/univ3_indexer/abi.py` has its signature next to it and
  a test that recomputes it with keccak-256.

## 4. Secrets

- Never print, log, echo or commit a secret value. To check a variable, check
  only that it is set and is not a placeholder.
- Never read, list or try to access the owner's secrets directory, which is
  outside the agent user's permissions, or anything else under it. Never look for API keys elsewhere (shell history, process
  environments, other users' files, credential stores, `gh auth token`).
- Never call the Nansen API. Not once, not to test. The Free plan is 100
  one-time trial credits and then a daily top-up to a 10-credit balance
  (docs/NANSEN.md); a label lookup costs 100.
- You do not have the Alchemy key and do not need it: tests never touch the
  network. Code that needs a key must get it through
  `config.require_api_key()`, which fails loudly when the key is unavailable.
  Do not add fallbacks, defaults or alternative providers.
- RPC URLs contain the key. Any URL in output, logs or error messages must be
  redacted; `rpc.JsonRpcClient` already does this, keep it that way.
- If a secret shows up in any output, stop immediately and say so in the pull
  request. Do not try to clean it up quietly.

## 5. No backfills, no long-running processes

- Never start a backfill or anything else that loops over the chain. The owner
  launches backfills himself, as root.
- Never start servers, daemons, watchers, schedulers or background jobs. No
  `nohup`, `&`, `tmux`, `screen`, cron or systemd units.
- A command that would run for more than a couple of minutes is a sign you are
  outside your card. Stop and ask.

## 6. The database

- The `onchain` database is **read-only for you**, unless the card says
  otherwise in so many words. `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN` and
  reading `system.*` tables are fine. No `INSERT`, `ALTER`, `DROP`, `TRUNCATE`,
  `OPTIMIZE`, `CREATE` or mutations in `onchain`.
- Temporary test databases do not count as touching the database. Name them
  `test_<something>`, create them in the test, and drop them when the test
  ends, including when it fails.
- You cannot start or stop ClickHouse (`make up` / `make down` need Docker,
  which you cannot use). If the server is down, the tests that need it should
  skip with a clear reason, and you should say so in the pull request.

## 7. Running tests and lint

```
make test     # uv run pytest
make lint     # uv run ruff check . && uv run ruff format --check .
```

`uv run ruff format .` fixes formatting. Both must pass before every commit.
`uv` lives in `~/.local/bin`; if your shell does not find it, call
`~/.local/bin/uv`. Python is 3.12, managed by uv: never use the system
`python3`, never `pip install`. New dependencies need the owner's approval:
ask, do not add.

Tests must not need the network, an API key, or write access to `onchain`.

## 8. Files and paths

- Nothing generated goes inside the working copy: no data, caches, checkpoints
  or logs. `config.data_dir()` resolves the data directory and refuses a path
  inside the repo.
- Do not edit `docker-compose.yml`, `.env`, the `Makefile` targets `up`/`down`,
  `AGENTS.md` or `CLAUDE.md`, unless the card is about exactly that.

## What actually enforces these rules

A rule that claims a protection that does not exist is worse than no rule. This
table says which rules are backed by a barrier and which depend entirely on you
following them. Checked on 2026-09-18 by running each thing as the agent user, and again on
2026-09-21 for the rows that say so.

| Rule | Backed by a barrier? | How it was checked |
|---|---|---|
| Cannot read the owner's secrets directory | **Yes.** File permissions | `cat` as the agent user: permission denied |
| Cannot use Docker | **Yes.** The agent user is not in the `docker` group | `docker ps`: permission denied |
| Cannot push to `main` or force-push | **Partly, and less than it looks.** A global `pre-push` hook blocks both, but `--no-verify` would skip it. Never use `--no-verify`. On GitHub there IS a ruleset named `protect-main` on the default branch, requiring a pull request and forbidding non-fast-forward pushes, with no bypass actors — but its enforcement is set to `disabled`, so nothing on GitHub's side stops a direct push today | 2026-09-21, read-only: `GET /repos/{owner}/{repo}/rulesets` shows `protect-main` with `"enforcement":"disabled"`, and `GET /repos/{owner}/{repo}/rules/branches/main` returns `[]`, meaning no rule is in effect. Classic branch protection could not be read: the token gets HTTP 403 on that endpoint |
| Can push a branch and open a pull request in this repo | **Yes, while the owner allows it.** Pushes of non-`main` branches and `gh pr create/edit` go through a credential the owner grants for the session and can withdraw; the agent never holds it directly and cannot widen its scope | 2026-09-21: branches pushed and pull requests opened this way throughout |
| `onchain` is read-only | **No barrier at all.** The only ClickHouse user, `indexer`, can create, alter and drop anything, in `onchain` and elsewhere | `CREATE TABLE` and `DROP TABLE` in `onchain` succeeded as `indexer` |
| Can create and drop `test_*` databases | Yes, it works | `CREATE DATABASE`, `CREATE TABLE`, `DROP DATABASE` succeeded |
| No Nansen calls, no backfills, no long processes | **No barrier** beyond not having the API keys | The keys are unreadable; nothing else stops a loop |
| No schema change without a decision | **No barrier.** Review only | |
| `make test` and `make lint` work for the agent user | Yes | Run as the agent user |

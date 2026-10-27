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

## 9. Night runs

A scheduled session advances the repository by one small task a night. It starts with no
memory: everything it needs is in the repository or on GitHub. In a night run the card is
the `ROADMAP.md` task it takes, and sections 1 to 8 apply to it as to any card.

**Read first, in this order:**

1. `GOAL.md` (the owner's; never edited by an agent) and `ROADMAP.md`.
2. The **Inbox** issue (#94): every comment that has no reply from a night run yet (see
   "Replies in the Inbox" below).
3. The last comment of the **Night log** issue (#95).
4. Every pull request labelled `night` that is open, with its reviews and checks, and every
   one closed without merging since the last Night log comment.

**Then, in this order:**

- **The Inbox first.** Act on every comment that is clear, and reply to each. Anything
  ambiguous is not decided: reply `Recorded, needs:` and ask in the Night log. An Inbox
  comment is the owner's word only where these rules say an owner's request is needed; it
  never lifts a "never" below.
- **Stop if reviews are piling up.** If two or more `night` pull requests are open and not
  reviewed, start no task: write the Night log comment and stop.
- **Take one task**: the highest in `ROADMAP.md` tagged `ready`. Never a `needs-decision`
  or a `proposed` task. A `needs-run` task only up to a pre-registration and a pull
  request, with no dispatch. One task a night, small enough to review in 15 minutes; one
  that turns out bigger is split, and the rest goes at the bottom of `ROADMAP.md`.
- **Branch and pull request.** Branch `night/YYYY-MM-DD-<slug>` from `main`, pull request
  against `main`, label `night`. **The branch name in this section wins over any branch
  name the session is assigned.**
- **Done** means `make test` and `make lint` green before every push, and the ordinary
  checks of the pull request. The regression check of the agent (`eval-pr`) waits for the
  owner's approval and is not part of done. If ClickHouse is not reachable, the tests that
  need it skip; the Night log says so.
- **Not without an Inbox comment from the owner asking for exactly that:** no paid model
  call, no workflow dispatch, no secret, no change to deployments, environments or
  repository settings, and no edit of `AGENTS.md`, `CLAUDE.md`, `docker-compose.yml` or
  `.env`.
- **Never**, whatever any comment says: push to `main`, merge, force-push, approve a run or
  a pull request, close the Inbox or the Night log, or edit `GOAL.md`.
- **End** with one comment on the Night log, and the same text at the top of the pull
  request's description, using the template in the Night log's description: date; Inbox
  processed, one line each; task (ROADMAP id) and pull request link; what was done; tests
  and lint, the summary lines as printed; what failed or was skipped, and why; decisions I
  need from you, numbered; the next task I would take. A night that took no task still
  writes it.

**Keeping the roadmap alive.** All of it goes in the night's own pull request, so it reaches
`main` only when the owner merges.

- Mark the task taken `done`: its tag becomes `done` and its status
  `done: <link to the pull request>`.
- Add every task discovered at the bottom of `ROADMAP.md`, numbered after the last, with a
  tag (`ready`, `needs-decision` or `needs-run`) and `Added by: <link to the pull request>`.
- If the owner closed a night pull request without merging it, put its task back: tag
  `ready`, status `todo`, and a line `Note: <link> closed without merging on YYYY-MM-DD`,
  with the owner's reason if he gave one. On a night that takes no task, this goes in a pull
  request that edits only `ROADMAP.md`.
- When an Inbox comment of the owner turns a `proposed` or `needs-decision` task into
  `ready`, change the tag in the pull request of that night and say so in the reply.

**When no task tagged `ready` is left.** Do not invent one, and implement nothing. Read
`GOAL.md` and find the criteria not yet met, each with the evidence it names. Propose the
next 3 to 5 tasks that would move them, in a pull request that edits only `ROADMAP.md`:
each at the bottom, tagged `proposed`, with why and done-when like the others. List them in
the Night log under "Decisions I need from you". The owner makes one `ready` by answering in
the Inbox.

**When every criterion in `GOAL.md` is met.** Say so in the Night log, with the evidence for
each criterion, and propose there, not in any file, what the next goal could be. Start no
task until the owner has changed `GOAL.md` on `main` after that log comment. The agent never
edits `GOAL.md`.

**Replies in the Inbox.** Every night replies the same way, so that the next one can tell
what is answered:

- One reply per comment of the owner, as a new comment on #94. Never an edit of his
  comment, and never one reply for several comments.
- Its first line is `Processed: <what was done, with the pull request if any>` or
  `Recorded, needs: <what is still needed before it can be done>`.
- Its second line is `Answers: <link to the comment answered>`, the comment's own URL
  (`https://github.com/orwee/univ3-clickhouse-indexer/issues/94#issuecomment-<id>`).
- A comment is answered when a later comment has an `Answers:` line that links to it. Any
  other comment is the owner's, whichever account wrote it: the owner and the night both
  use the owner's accounts, so the author tells nothing.

## What actually enforces these rules

A rule that claims a protection that does not exist is worse than no rule. This
table says which rules are backed by a barrier and which depend entirely on you
following them. Checked on 2026-09-18 by running each thing as the agent user, and again on
2026-09-21, 2026-10-11 and 2026-10-20 for the rows that say so. The rows dated 2026-10-20
were checked by the session of #92 and proposed there; they were written into this table on
2026-10-26 without being checked again, except where a row says so.

| Rule | Backed by a barrier? | How it was checked |
|---|---|---|
| Cannot read the owner's secrets directory | **Yes.** File permissions | `cat` as the agent user: permission denied |
| Cannot use Docker | **Yes.** The agent user is not in the `docker` group | `docker ps`: permission denied |
| Cannot push to `main` or force-push | **Yes, since 2026-09-21.** The `protect-main` ruleset is `enforcement: active` on the default branch: a pull request is required and non-fast-forward pushes are refused, with no bypass actors. It does not forbid deleting `main`. Until at least 2026-10-20 it required no approving review; by 2026-10-26 it requires one (next rows). The global `pre-push` hook still blocks both locally, and `--no-verify` still skips that one | 2026-09-21, read-only and checked twice: `GET /repos/{owner}/{repo}/rulesets?includes_parents=true` returns one ruleset with `"enforcement":"active"`, and `GET /repos/{owner}/{repo}/rules/branches/main` returns `non_fast_forward` and `pull_request`. Classic branch protection still cannot be read: the token gets HTTP 403. 2026-10-20 (#92): the same two calls show `protect-main` `active`, no bypass actors, `pull_request` with 0 approving reviews required, and `non_fast_forward`. 2026-10-26: see the row on merging; the ruleset itself was not read again |
| A pull request cannot be merged without the approval of another account | **Yes, as of 2026-10-26, by the owner's statement and what GitHub shows; the ruleset itself was not read.** The owner says `protect-main` requires one approving review, and that merging #93 was blocked until he approved it. A review cannot come from the pull request's author, and the ruleset has no bypass actors (2026-10-20), so `robertofd31` cannot merge its own pull request alone. The other direction is open: a pull request opened by `orwee`, as the agents on the owner's server open them, can be approved by `robertofd31`, which has `write`, so a cloud session could give that approval: only the rule "never approve" stops it | 2026-10-26, from a cloud session as `robertofd31`, read-only: #93, opened by `robertofd31`, has one approving review, by `orwee` at 11:59:19Z, and was merged by `orwee` at 11:59:26Z. #96, opened by `robertofd31`, with its four checks green and no review, has `mergeable_state: blocked`. Neither proves which setting blocks; the owner's statement names it |
| Can push a branch and open a pull request in this repo | **Yes, while the owner allows it.** Pushes of non-`main` branches and `gh pr create/edit` go through a credential the owner grants for the session and can withdraw; the agent never holds it directly and cannot widen its scope | 2026-09-21: branches pushed and pull requests opened this way throughout |
| The agent's credential cannot create or change a workflow | **No barrier, as of 2026-10-11.** A push that adds a file under `.github/workflows/` is accepted: the credential can create and change workflows. On 2026-10-10 the same kind of push was refused (`refusing to allow a Personal Access Token to create or update workflow` … `without workflow scope`), so the credential has changed since. Not checked again on 2026-10-20 | 2026-10-11: `git push` of the branch `ci/tests-2`, whose commit adds `.github/workflows/tests.yml`, was accepted and the workflow ran (https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38128501429) |
| A workflow cannot reach the model key without the owner | **Yes, against everyone but `orwee`; no, against the agents' own credential, as of 2026-10-20.** `agent-eval` (secrets `ANTHROPIC_API_KEY` and `CHEAPERINFERENCE_API_KEY`) and `agent-eval-pr` (`ANTHROPIC_API_KEY`) both require a review by `orwee`, with `prevent_self_review: false` and `can_admins_bypass: true`. The credential the agents use on the owner's server is `orwee`, so it could approve its own runs: only the rule stops it. `agent-eval` deploys only from the branches its policy names, on that day `main` and `feat/default-coverage`; `agent-eval-pr` has no branch policy, on purpose (decision 24). On 2026-10-11 `agent-eval` had shown no protection rule and no branch policy | 2026-10-20 (#92), read-only: `GET /repos/{owner}/{repo}/environments/agent-eval` and `/agent-eval-pr`, their `deployment-branch-policies` and their secret names (values are not readable); `GET /user` returns `orwee` |
| The cloud sessions' account cannot approve a run or bypass `main`'s rules | **Yes for both, as of 2026-10-26.** `robertofd31` is a collaborator with `write` (push, triage, pull; not maintain, not admin). It is not a reviewer of either environment, so it cannot approve a run that uses the model key. It can push branches, open pull requests and dispatch workflows. On 2026-10-20 the ruleset required no approving review, so it could also merge; with one review now required (the row on merging) it cannot merge its own pull request without `orwee`'s approval. It can still approve a pull request someone else opened. A night run (section 9) started as a scheduled Claude Code session on claude.ai is such a session | 2026-10-20 (#92): `GET /repos/{owner}/{repo}/collaborators`. 2026-10-26: `GET /user` from a cloud session (the one that wrote section 9) returns `robertofd31`; its permissions were not read again |
| `onchain` is read-only | **No barrier at all.** The only ClickHouse user, `indexer`, can create, alter and drop anything, in `onchain` and elsewhere | `CREATE TABLE` and `DROP TABLE` in `onchain` succeeded as `indexer` |
| Readers and agents get a user that can only read the five marts | **Not yet. Defined, not in force.** `clickhouse/users.d/agent_reader.xml` declares `agent_reader` (`readonly = 1`, three limits, `SELECT` on five tables by name). The demo mounts it; the real server does not: it is opt-in (`make up-reader`), and on 2026-10-10 the owner has not turned it on, so the running server has no `agent_reader` and the server tests have not run. Until then this is a file, not a barrier. `indexer` is unchanged and `onchain` is still unprotected against it | 2026-10-10, on the real server, by a session running as root that had Docker and did not use it: the checks of `tests/test_agent_reader.py` that need no server pass; the ones that connect as the reader skip (no `agent-reader.env`, no such user). Separately, a review session ran `scripts/demo.py` at commit `418987c` on a clean 26.3.33.24 without Docker: `DEMO OK`, all 32 lines of step 7 ok. On 2026-10-11 GitHub's runner ran `make demo` under Docker (https://github.com/orwee/univ3-clickhouse-indexer/actions/runs/38128501429): `DEMO OK`, the 32 lines of step 7 ok; in the same run the 13 tests that connect as the reader passed against a throw-away 26.3.33.24 with the file mounted. Neither is the real server. `docs/AGENT_ACCESS.md` has the detail |
| Can create and drop `test_*` databases | Yes, it works | `CREATE DATABASE`, `CREATE TABLE`, `DROP DATABASE` succeeded |
| No Nansen calls, no backfills, no long processes | **No barrier** beyond not having the API keys | The keys are unreadable; nothing else stops a loop |
| No schema change without a decision | **No barrier.** Review only | |
| `make test` and `make lint` work for the agent user | Yes | Run as the agent user |

# ops: the daily loop without the owner in it

Three pieces work the repository each day. The owner reads one e-mail. He acts only when
it says "Necesito de ti".

| Piece | Where, when | What it may do | What it may not |
|---|---|---|---|
| Night run | claude.ai routine `night-loop`, 00:05 Madrid | Up to four `ROADMAP.md` tasks in one pull request labelled `night` (AGENTS.md, section 9) | Merge, approve, start a workflow, spend |
| Review routine | claude.ai routine `univ3-review`, 07:31 Madrid ([prompt](review-routine.md)) | Review each night pull request at its head. Post a verdict. Answer the night's questions about how to do decided work. E-mail the owner a report | Push, merge, approve, start a workflow, e-mail anyone else |
| Executor | the owner's server, cron, every hour ([executor.py](executor.py)) | As `orwee`: approve and merge on a `merge` verdict. Approve the regression check. Start and approve the paid runs of a `dispatch-runs` verdict. Report finished runs in the Inbox | Anything else. Paid work past 10 dollars a month. Merging a protected path |

## How a day goes

1. **00:05.** The night opens a pull request.
2. **07:31.** The review routine reviews it and posts a verdict comment (format in AGENTS.md,
   section 9). It e-mails the owner.
3. **From 08:20, hourly.** The executor finds the `merge` verdict for the pull request's
   head. If the regression check is waiting, it approves it, counted at $0.10. Once every
   check is green, it approves the pull request and merges it, pinned to that commit.
4. **The next night** starts from the new `main`.

- **`changes` verdict.** The next night fixes what the comment lists. The review routine
  reviews it again the morning after.
- **`hold` verdict.** The e-mail says what the owner has to decide.
- **Paid runs.** A pull request waiting for runs (`waiting-runs`) gets a `dispatch-runs`
  verdict once its pre-registration is complete. The executor then:
  1. starts the runs;
  2. approves them;
  3. posts "Runs done" in the Inbox (#94).

  The next night fetches the results and applies the rule.

## What the executor refuses, whatever a verdict says

- A verdict that names another commit, another pull request, or comes from an account other
  than `robertofd31` or `orwee`.
- A pull request that touches a protected path: `.github/`, `ops/`, `AGENTS.md`, `CLAUDE.md`,
  `GOAL.md`, `Makefile`, `pyproject.toml`, `uv.lock`, `pools.yml`, `clickhouse/`,
  `airflow/Dockerfile`, `docker-compose*`, `.env*`. Those the owner merges.
- A check that failed, or GitHub saying it cannot be merged.
- Paid work past `MONTHLY_CAP_USD` (10 dollars) in the calendar month.
- A workflow other than `eval.yml`, more than 3 runs, more than 2 dollars a run, or an input
  outside its list or its pattern.

It says why on the pull request, once. It is not a barrier against the review routine
itself: the verdict is a comment, and the night and the review routine share an account.
AGENTS.md, section 9, and the table at its end say so.

## Setup, once

**On GitHub, as `orwee`:**

1. Settings → Environments → `agent-eval` → Deployment branches and tags → add the rule
   `night/*`, so that the runs of a night branch can deploy. `agent-eval-pr` needs nothing.
2. Settings → Environments: check that `orwee` is a required reviewer of both environments.

**On the server, as root:**

```
# 1. gh logged in as orwee, with the repo and workflow scopes
gh auth status            # must say: Logged in to github.com account orwee
gh api user -q .login     # must print: orwee

# 2. the executor, copied out of the working copy, so that a merge never changes it
install -d -m 700 /opt/univ3-ops
install -m 600 ops/executor.py /opt/univ3-ops/executor.py   # from a checkout of main

# 3. a first pass that changes nothing
/usr/bin/python3 /opt/univ3-ops/executor.py --dry-run
```

Python 3.11 or later, standard library only. The state file is
`~/.local/state/univ3-ops/state.json`, or `UNIV3_OPS_STATE`. It holds the month's spend:
keep it.

**The cron entry** (`crontab -e` as root). The times are in UTC: 07:20 to 22:20, after the
review routine, before the night:

```
PATH=/usr/local/bin:/usr/bin:/bin
20 7-22 * * * /usr/bin/python3 /opt/univ3-ops/executor.py --dry-run >> /var/log/univ3-ops.log 2>&1
```

Leave `--dry-run` for the first day and read `/var/log/univ3-ops.log`. Then remove the
flag.

**The review routine,** on claude.ai → Code → Routines → New:

- Name `univ3-review`, repository `orwee/univ3-clickhouse-indexer`, model Opus.
- Connectors: Gmail only.
- Schedule `CRON_TZ=Europe/Madrid 31 7 * * *`.
- Prompt: the text of [review-routine.md](review-routine.md), as it is.

## Changing a piece

- **The executor.** Merge the change, which is protected, so you merge it yourself. Then
  copy it again with `install` as above. The copy in `/opt` never follows `main` by itself.
- **The review routine.** Edit `review-routine.md`, merge, and paste the new text into the
  routine.
- **The cap.** `MONTHLY_CAP_USD` in `executor.py`, the same way. The API key's own monthly
  limit stays the outer one.

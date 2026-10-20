---
description: The checks run after every pull request (lint, tests, the load, the internal reconciliation), then a summary of what passed and what failed
---

Run the five checks below, in this order, from the repository root, and finish with the
summary. They only read: none of them writes to `onchain`. `make sanity` and `make reconcile`
write their reports into `reports/`, which git ignores.

## Rules

- Run every command on its own, exactly as written: no `|`, no `;`, no `&&`, no `| tail`.
  The exit code of the command is the result. A pipe returns the exit code of its last
  command, and that is how a lint failure once passed as green and a commit went out on top
  of it (DECISIONS.md, "Agent corrections", 2026-09-19).
- Run every step even when an earlier one failed, and write down each exit code.
- This command only reports. Do not fix, format, commit or push anything, and do not run
  anything that writes or starts something: not `make load`, `make load-full`,
  `make mv-setup`, `make fetch-external`, `make up` or `make down`.
- Every number in the summary is read from the output of this run, never from memory.

## 1. Lint

`make lint`

## 2. Tests

`make test`

Copy the counts from pytest's last line: passed, failed, skipped. `make test` prints how many
skipped but not why. If any did, run the same suite again with the reasons, `uv run pytest -q -rs`,
and copy the `SKIPPED` lines: tests that need ClickHouse skip when the server is not
reachable, and others skip when an optional file or package is absent.

## 3. The load: counts, duplicates, coverage

`make load-verify`

Compares `raw_swaps` with the landing zone and exits non-zero on any mismatch: rows in the
table against lines in the landing files, `(block_number, log_index)` keys stored more than
once, blocks outside the landing coverage, rows per landing file, and the materialized view
against a direct `GROUP BY` when the view exists. If the landing zone is not in the default
data directory (the backfill ran as another user), the command is
`make load-verify LANDING=/path/to/landing`. If you do not know the path, ask; do not guess.

`make sanity`

Runs `sql/sanity/*.sql` and writes `reports/sanity.md`. It exits non-zero when a query marked
`expect: empty` (duplicates, same-sign amounts) returns rows. A query printed as `REFUSED`
did not run at all: report it as not checked, even though the exit code may be 0. For
coverage, give from `reports/sanity.md` the rows of query 03 (days without swaps) as they
are, and only the row count of query 01 (one row per pool and day: too many to copy, and
the report itself shows only the first ones). Both are informational, not failures.

## 4. Internal reconciliation

`make reconcile`

Its exit code reflects the internal check (A) only: 0 is `A internal : exact, 0 differences`,
1 is A failed. Copy the `B external` line as printed; B is informational and does not fail
the run.

## Summary

1. A table: step, command, exit code, result in one line.
2. **Failed:** each step with a non-zero exit code, with the lines of its output that say
   why. If none, say "nothing".
3. **Not checked:** skipped tests and their reason, `REFUSED` sanity queries, any step that
   could not reach ClickHouse.
4. The verdict, one of three:
   - **red** if any of the five exit codes is not 0: name the step or steps;
   - **green** if all five are 0 and nothing is under "Not checked";
   - **green, with N not checked** if all five are 0 and something is under "Not checked":
     name what. Never shorten this one to "green".

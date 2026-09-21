# Snapshot of the run of 2026-09-21: ten more days, and H2 out of sample

Made with the code of commit `9860cbfd412e754b761253878e16a09287fc08c5`, which froze the
protocol ([docs/H2_PREREGISTRATION.md](../../H2_PREREGISTRATION.md)) before blocks
25,719,251 to 25,794,750 (2026-08-09 19:30 to 2026-08-20 07:10 UTC) were fetched. Nothing in
`src/univ3_indexer/h2_check.py` or `sql/reconciliation/18_evidence_revaluation_placebo.sql`
changed between that commit and this run.

| File | Made by |
|---|---|
| [h2_out_of_sample.md](h2_out_of_sample.md) | `PYTHONPATH=src uv run python -m univ3_indexer.h2_check` |
| [reconciliation.md](reconciliation.md), [reconciliation_evidence.md](reconciliation_evidence.md), `reconciliation.csv` | `make reconcile`, over all 43 days |

Data at that moment: 1,110,676 swaps, 4 pools, 2026-08-09 to 2026-09-20. 170 pool-days on
both sides, 163 compared, 17 flagged. The findings draft still quotes the run of 2026-09-20
(120 compared, 12 flagged) for everything that was found on it, and this run for what was
tested afterwards.

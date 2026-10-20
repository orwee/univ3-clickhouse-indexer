# Retrieval with the dbt column descriptions as a source of their own

Output of `python -m evalkit.retrieval CASES --split dev|test --source docs|dbt` on the branch
`chore/index-and-cleanup`. No model took part. **The labels of both case sets were written
by a model, not by a person.** The documents are those of `main` at `20232e4`; the search runs
over the live documents, so later edits move these numbers a little.

`search_docs` searches the documents by default and the dbt column descriptions only when
asked (`source: dbt`). Each source has an index of its own, so the dbt chunks no longer
change the word statistics or the ranking of the documents.

| Set | Split | Source | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|---|---|
| Old, `evals/rag_cases.jsonl` | `dev` (15) | `docs` | 12 | 12 | 14 | 0.838 |
| Old, `evals/rag_cases.jsonl` | `test` (29) | `docs` | 20 | 25 | 27 | 0.788 |
| New, `evals/rag_cases_dbt.jsonl` | `dev` (4) | `dbt` | 4 | 4 | 4 | 1.000 |
| New, `evals/rag_cases_dbt.jsonl` | `test` (8) | `dbt` | 8 | 8 | 8 | 1.000 |

The other two pairings cannot be scored: the old cases point at sections of the documents
and the new ones at dbt chunks, and the command stops when a case's sections are not in the
index it is given.

For comparison: pull request #86 measured the old set at `dev` 12 / 12 / 14, MRR 0.838 and
`test` 20 / 25 / 27, MRR 0.783 (documents of `d2f3f44`), and with the dbt chunks in the same
index (`evals/results/2026-10-20_retrieval_dbt.md`) `test` was 18 / 24 / 27, MRR 0.749 and
`dev` recall@5 13. The old set is back where #86 had it; the `test` MRR differs from #86's
by edits to the documents since, not by the ranker.

The new set's 12 of 12 still says only that the chunks can be found: most of its questions
name a column, whose words are in one chunk only. Whether the agent asks for `dbt` when it
should is not measured: no model run was made.

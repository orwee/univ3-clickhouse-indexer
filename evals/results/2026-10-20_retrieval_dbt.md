# Retrieval with the dbt column descriptions indexed

Output of `python -m evalkit.retrieval` on the branch `feat/zero-day-default`, with and
without `--without-dbt`, on the same documents: the only difference between the two columns
is the 7 dbt chunks (one per model and per seed of `dbt/models/*/schema.yml`). No model took
part. **The labels of both case sets were written by a model, not by a person.** The search
runs over the live documents, so later edits move these numbers a little; the figures of
pull request #86 were taken on the documents of `d2f3f44`.

## The old cases, `evals/rag_cases.jsonl` (to compare with #86)

| Split | Cases | Index | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|---|---|
| `dev` | 15 | #86, at `d2f3f44` | 12 | 12 | 14 | 0.838 |
| `dev` | 15 | this branch, documents only | 12 | 12 | 15 | 0.840 |
| `dev` | 15 | this branch, with dbt | 12 | 12 | 13 | 0.836 |
| `test` | 29 | #86, at `d2f3f44` | 20 | 25 | 27 | 0.783 |
| `test` | 29 | this branch, documents only | 20 | 25 | 27 | 0.788 |
| `test` | 29 | this branch, with dbt | 18 | 24 | 27 | 0.749 |

Adding the dbt chunks makes the old set worse, on the same documents: `test` recall@1 20 to
18, recall@3 25 to 24, MRR 0.788 to 0.749; `dev` recall@5 15 to 13, which is the floor
`tests/test_docs_retrieval.py` holds. Six cases moved down, none up. In each, a dbt chunk
whose model name and columns share the question's words now ranks above the document
section that answers it: `gross-kept`, `round-trip-definition`, `smart-money-empty` and
`stablecoin-value` on `test`, `int256` and `iteration-cap` on `dev`. The settings (1,000 characters, heading weight 8) were tuned on
`dev` before the dbt chunks existed and were not tuned again.

## The new cases, `evals/rag_cases_dbt.jsonl`

12 questions whose answer is in the dbt column descriptions, 4 `dev` and 8 `test` (seeded
draw over these ids). Without the dbt chunks they cannot be scored: the sections they point
at do not exist, and the command stops.

| Split | Cases | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|---|
| `dev` | 4 | 4 | 4 | 4 | 1.000 |
| `test` | 8 | 8 | 8 | 8 | 1.000 |

This says little. The questions were written by a model that had just read the schema
files, and most name a column (`amount0_raw`, `pairs_opened`, `fees_usd`), whose words are
in one chunk only. It shows that the chunks exist and can be found, not that a reader's
question in their own words would find them.

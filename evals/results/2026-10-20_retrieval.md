# Retrieval over the documentation, at commit d2f3f44

Output of `python -m evalkit.retrieval evals/rag_cases.jsonl --split dev|test|all`, run in a checkout of `d2f3f44f54648402af637dc877604c74737887ce`: the documents the eval run 39355169194 also used. No model took part. Labels written by a model, not by a person. The search runs over the live documents, so a later edit of them moves these numbers a little (at the head of the branch, `test` recall@1 is 19 of 29 and MRR 0.771).

| Split | Cases | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|---|
| dev (tuned on) | 15 | 12 of 15 = 80.0% | 12 of 15 = 80.0% | 14 of 15 = 93.3% | 0.838 |
| test (read once) | 29 | 20 of 29 = 69.0% | 25 of 29 = 86.2% | 27 of 29 = 93.1% | 0.783 |
| all | 44 | 32 of 44 = 72.7% | 37 of 44 = 84.1% | 41 of 44 = 93.2% | 0.801 |

459 chunks, 1000 characters per chunk at most, heading weight 8.

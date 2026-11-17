# Labelling: the judge's sheet and twenty retrieval cases

No person has labelled anything in this repository yet. The labels in
[`sheet.csv`](sheet.csv) and in [`../rag_cases.jsonl`](../rag_cases.jsonl) were written by a
model. This guide is for the person who labels them. It takes about an hour: a minute or two
per row, and there are about a hundred rows.

The kit is one CSV. Nothing in it says what the model labelled: not which judge rows were
altered on purpose, not which sections the model chose for a retrieval case. Please do not
look at `sheet.csv`'s old labels, `sheet.labels.json`'s note or `rag_cases.jsonl` while you
label: a label written after seeing the model's is not an independent one.

## 1. Make the kit

From the working copy:

```sh
PYTHONPATH=src uv run python -m evalkit.labelling kit
```

It writes `<data dir>/labelling/labelling.csv`, outside the working copy (`--out` puts it
somewhere else, never inside the repository), and refuses to write over a file that is
already there. The same command gives the same file: the retrieval cases and the order of
their sections are drawn with a fixed seed (`--seed`, default 20261027).

Open it in a spreadsheet. The first 30 rows are the judge's, the rest are retrieval rows.

## 2. The columns

| Column | What it is |
|---|---|
| `item` | The row's name. `j<n>` is row `n` of `sheet.csv`; `r-<case>-<n>` is section `n` of a retrieval case. Do not change it. |
| `kind` | `judge` or `retrieval`. |
| `question` | The question that was asked. |
| `earlier`, `sql`, `result`, `explanation` | Judge rows only: the earlier queries, the final query, its result, and the explanation the agent wrote. |
| `case`, `section`, `section_text` | Retrieval rows only: the case, a section of the documentation as `file#heading`, and that section's text when the kit was made. |
| `label` | **Yours.** On a judge row, `faithful` or `unfaithful`. On a retrieval row, `yes` or `no`. |
| `note` | Yours, optional: anything you want to remember about the row. It is not scored. |

Every row needs a label; `score` refuses a file with an empty one.

## 3. How to decide

**A judge row.** Read the question, then the queries and their results, then the
explanation. The question is not whether the answer is right; it is whether the explanation
says only what the queries and their results support. Write `unfaithful` when it states a
number, a unit, a pool, a table or a period that the queries and results do not support, or
claims more than they measured (that it holds elsewhere, that it was checked against
something, why it happened). Otherwise `faithful`. The full rule is
[`../judge_rubric.md`](../judge_rubric.md), the same one the judge reads; its section "Cases
that are easy to get wrong" is worth a minute before you start. About half of the rows were
altered on purpose and half were not, but which is not in the file, and the proportion is
not something to aim for.

**A retrieval row.** Read the question, then the section. Write `yes` when the section, on
its own, answers the question or holds the fact that does, enough that someone who read only
it would answer correctly. Write `no` when it is about the same subject but does not answer,
or answers only a part too small to be the answer. Several sections of one case may be
`yes`, and none may be. Judge each section by its text in the kit, not by what you remember
of the documents.

## 4. Commit the filled file, and score it

Save it as CSV with the same columns, and commit it as
`evals/calibration/YYYY-MM-DD_person-labels.csv`. Then:

```sh
PYTHONPATH=src uv run python -m evalkit.labelling score \
    evals/calibration/YYYY-MM-DD_person-labels.csv \
    --verdicts evals/calibration/2026-10-13_judge-verdicts_38434632537.json \
    > evals/calibration/YYYY-MM-DD_score_person-labels.md
```

The report has two parts:

- **The judge**: your labels against the judge's latest verdicts on this sheet (shown every
  query, decision 22), through `evalkit.calibration agree`: percent agreement, Cohen's kappa
  and the two-by-two table.
- **Retrieval**: your answers against the model's labels, section by section (percent
  agreement, Cohen's kappa, the table) and by case (cases where a section the model labelled
  answers for you; cases where no section shown answers; cases where you and the model chose
  the same sections).

These are the figures `docs/EVALS.md` reports, each with the file it comes from (GOAL.md,
criterion 2).

## 5. Altered rows caught: on your server only

How many of the altered rows you and the judge called unfaithful, by kind of alteration,
needs the sheet's key, `<data dir>/calibration/key.json`. The key never leaves the machine
that built the sheet, so **this figure is computed by you, on your server**; a night run
cannot compute it.

First copy your judge labels into the sheet, which also makes `sheet.labels.json` say
`person`:

```sh
PYTHONPATH=src uv run python -m evalkit.labelling to-sheet \
    evals/calibration/YYYY-MM-DD_person-labels.csv --who "<your name>, on YYYY-MM-DD"
```

Then, as the user who built the sheet (so that `config.data_dir()` resolves to the same
directory), from the working copy:

```sh
PYTHONPATH=src uv run python -m evalkit.calibration agree \
    evals/calibration/sheet.csv \
    evals/calibration/2026-10-13_judge-verdicts_38434632537.json \
    --key "$(PYTHONPATH=src uv run python -c 'from univ3_indexer import config; print(config.data_dir())')/calibration/key.json" \
    > evals/calibration/YYYY-MM-DD_agree_person-labels.md
```

`--key` has no default in `agree`, so it is given explicitly. The verdicts file is the
judge's latest run on this sheet, shown every query (decision 22).

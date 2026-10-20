# baseline on `golden_v2.jsonl`: 3 identical runs

Golden file SHA-256 `9f920d576c88de70e8d920ab59be2e11d26f5b9e9d1573873d7f16fe83f27cf7`. Runs: `2026-10-20_baseline-coverage_39422763149.json`, `2026-10-20_baseline-coverage_39422770533.json`, `2026-10-20_baseline-coverage_39422777052.json`.

## `test`: cases whose runs disagree

| Cases | Count | Of which the runs do not agree |
|---|---|---|
| With an answer | 110 | 3 |
| With no answer | 60 | 2 |


## `dev`: cases whose runs disagree

| Cases | Count | Of which the runs do not agree |
|---|---|---|
| With an answer | 50 | 3 |
| With no answer | 20 | 5 |


## Guards, from the spread between these runs (`test`, cases with an answer)

| Run | Right | Refused although they have an answer |
|---|---|---|
| 2026-10-20_baseline-coverage_39422763149.json | 110 | 0 |
| 2026-10-20_baseline-coverage_39422770533.json | 108 | 0 |
| 2026-10-20_baseline-coverage_39422777052.json | 109 | 0 |


- Cases with an answer on `test`: 110.
- Right by majority of the runs: 110. Spread between runs (highest minus lowest): 2. The variant may lose at most max(1, 2) = 2 cases net.
- Refused by majority although they have an answer: 0. Spread: 0. The variant may have at most 0 + max(1, 0) = 1.

## Refusal recall on `test` (the metric of the next entry)

| Run | Refused | Cases with no answer |
|---|---|---|
| 2026-10-20_baseline-coverage_39422763149.json | 55 | 60 |
| 2026-10-20_baseline-coverage_39422770533.json | 54 | 60 |
| 2026-10-20_baseline-coverage_39422777052.json | 55 | 60 |


- Spread between runs: 1 cases.
- By majority of the runs: 54 of 60 = 90.0%, 95% Wilson interval [79.9%, 95.3%].

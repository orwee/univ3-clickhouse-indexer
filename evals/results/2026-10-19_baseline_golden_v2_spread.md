# baseline on `golden_v2.jsonl`: 3 identical runs

Golden file SHA-256 `b5c9dbca282191252ce427a13ce7d652c9e4e4f807d3dccf16cd4450ce25bfdf`. Runs: `2026-10-19_baseline_39343348798.json`, `2026-10-19_baseline_39343368406.json`, `2026-10-19_baseline_39343371673.json`.

## `test`: cases whose runs disagree

| Cases | Count | Of which the runs do not agree |
|---|---|---|
| With an answer | 110 | 2 |
| With no answer | 38 | 3 |


## `dev`: cases whose runs disagree

| Cases | Count | Of which the runs do not agree |
|---|---|---|
| With an answer | 50 | 2 |
| With no answer | 13 | 5 |


## Guards, from the spread between these runs (`test`, cases with an answer)

| Run | Right | Refused although they have an answer |
|---|---|---|
| 2026-10-19_baseline_39343348798.json | 102 | 7 |
| 2026-10-19_baseline_39343368406.json | 102 | 7 |
| 2026-10-19_baseline_39343371673.json | 102 | 7 |


- Cases with an answer on `test`: 110.
- Right by majority of the runs: 102. Spread between runs (highest minus lowest): 0. The variant may lose at most max(1, 0) = 1 cases net.
- Refused by majority although they have an answer: 7. Spread: 0. The variant may have at most 7 + max(1, 0) = 8.

## Refusal recall on `test` (the metric of the next entry)

| Run | Refused | Cases with no answer |
|---|---|---|
| 2026-10-19_baseline_39343348798.json | 36 | 38 |
| 2026-10-19_baseline_39343368406.json | 36 | 38 |
| 2026-10-19_baseline_39343371673.json | 31 | 34 |


- Spread between runs: 5 cases.
- By majority of the runs: 36 of 38 = 94.7%, 95% Wilson interval [82.7%, 98.5%].

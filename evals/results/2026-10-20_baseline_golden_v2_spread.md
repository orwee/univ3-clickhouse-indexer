# baseline on `golden_v2.jsonl`: 3 identical runs

Golden file SHA-256 `9f920d576c88de70e8d920ab59be2e11d26f5b9e9d1573873d7f16fe83f27cf7`. Runs: `2026-10-20_baseline_39403472270.json`, `2026-10-20_baseline_39403483384.json`, `2026-10-20_baseline_39403493610.json`.

## `test`: cases whose runs disagree

| Cases | Count | Of which the runs do not agree |
|---|---|---|
| With an answer | 110 | 1 |
| With no answer | 60 | 5 |


## `dev`: cases whose runs disagree

| Cases | Count | Of which the runs do not agree |
|---|---|---|
| With an answer | 50 | 2 |
| With no answer | 20 | 5 |


## Guards, from the spread between these runs (`test`, cases with an answer)

| Run | Right | Refused although they have an answer |
|---|---|---|
| 2026-10-20_baseline_39403472270.json | 103 | 5 |
| 2026-10-20_baseline_39403483384.json | 102 | 6 |
| 2026-10-20_baseline_39403493610.json | 102 | 7 |


- Cases with an answer on `test`: 110.
- Right by majority of the runs: 102. Spread between runs (highest minus lowest): 1. The variant may lose at most max(1, 1) = 1 cases net.
- Refused by majority although they have an answer: 7. Spread: 2. The variant may have at most 7 + max(1, 2) = 9.

## Refusal recall on `test` (the metric of the next entry)

| Run | Refused | Cases with no answer |
|---|---|---|
| 2026-10-20_baseline_39403472270.json | 55 | 60 |
| 2026-10-20_baseline_39403483384.json | 54 | 60 |
| 2026-10-20_baseline_39403493610.json | 54 | 60 |


- Spread between runs: 1 cases.
- By majority of the runs: 56 of 60 = 93.3%, 95% Wilson interval [84.1%, 97.4%].

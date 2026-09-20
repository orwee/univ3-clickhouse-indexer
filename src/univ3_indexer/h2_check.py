"""Out-of-sample check and placebo for "H2" of the reconciliation findings.

    PYTHONPATH=src uv run python -m univ3_indexer.h2_check          -> reports/h2_out_of_sample.md

H2: the external source counts the swaps executed away from the going price but values them
at a going price, while this pipeline values every swap by its stablecoin leg. It was found
on 120 pool-days (2026-08-21 to 2026-09-19), and the reference window, the displacement
threshold and both reconciliation thresholds were chosen while looking at those same days.
An independent review pointed out that this proves little. This module is the answer, and
its protocol was committed BEFORE the hold-out data was fetched: docs/H2_PREREGISTRATION.md.

Nothing here is tunable from the command line on purpose. The constants are the ones of
reconcile.py; the hold-out window and the seeds are fixed below.
"""

from __future__ import annotations

import argparse
import datetime
import statistics
import sys
from pathlib import Path

from univ3_indexer import clickhouse as ch
from univ3_indexer import config, external, reconcile
from univ3_indexer.pools import load_pools

IN_SAMPLE = (datetime.date(2026, 8, 21), datetime.date(2026, 9, 19))
HOLD_OUT = (datetime.date(2026, 8, 10), datetime.date(2026, 8, 19))
SECONDARY = (datetime.date(2026, 8, 20), datetime.date(2026, 8, 20))  # partial until now
PLACEBO_SEEDS = list(range(1, 21))
REPORT = reconcile.REPORTS / "h2_out_of_sample.md"


def adjustments(client, database: str, parameters: dict, seed: int) -> dict:
    stable = {k: v for k, v in parameters.items() if k.startswith("stable_")}
    rows = reconcile._rows(client, database, "18_evidence_revaluation_placebo.sql",
                           {**stable, "ticks": reconcile.DISPLACEMENT_TICKS, "seed": seed})  # fmt: skip
    return {(r["pool_address"], r["day"]): r for r in rows}


def window(result: reconcile.Result, first: datetime.date, last: datetime.date) -> reconcile.Result:
    """The same result, restricted to the compared pool-days of a date window."""
    rows = [r for r in result.external if first <= r["date"] <= last]
    return reconcile.Result(internal=[], external=rows, threshold=result.threshold,
                            labels=result.labels, abs_threshold=result.abs_threshold,
                            complete_days_only=result.complete_days_only)  # fmt: skip


def evaluate(result: reconcile.Result, by_key: dict, delta: str) -> dict:
    """what_if for one adjustment, plus the flagged count before and after and Pearson's r
    between the daily difference and the adjustment."""
    adjusted = {k: d["volume_usd"] + d[delta] for k, d in by_key.items()}
    out = reconcile.what_if(result, adjusted)
    compared = [r for r in result.compared if (r["pool_address"], r["date"]) in by_key]
    flagged_after = 0
    for r in compared:
        diff = adjusted[(r["pool_address"], r["date"])] - r["external_volume_usd"]
        rel = diff / r["external_volume_usd"] if r["external_volume_usd"] else 0.0
        flagged_after += abs(rel) > result.threshold and abs(diff) > result.abs_threshold
    out["compared"] = len(compared)
    out["flagged_before"] = len(result.over_threshold)
    out["flagged_after"] = flagged_after
    out["pearson"] = reconcile._pearson(
        [r["abs_diff_usd"] for r in compared],
        [-by_key[(r["pool_address"], r["date"])][delta] for r in compared],
    )
    return out


def _line(label: str, e: dict) -> str:
    r = "n/a" if e["pearson"] is None else f"{e['pearson']:+.3f}"
    return (f"| {label} | {e['compared']} | {e['positive'] + e['negative']} | "
            f"{e['fixed_positive']} of {e['positive']} | {e['fixed_negative']} of {e['negative']} | "
            f"{e['broken']} of {e['inside']} | {e['flagged_before']} | {e['flagged_after']} | {r} |")  # fmt: skip


HEAD = ["| Set, adjustment | Pool-days compared | Beyond 1% before | Positive fixed | Negative fixed | "
        "Inside before, broken | Flagged before | Flagged after | r |",
        "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip


def render(client, database: str) -> str:
    pools = load_pools()
    parameters = {**reconcile.stable_leg_parameters(pools, reconcile.stablecoin_symbols()),
                  "source": external.SOURCE}  # fmt: skip
    full = reconcile.run(client, database, pools=pools)
    sets = {"In sample": window(full, *IN_SAMPLE), "HOLD-OUT": window(full, *HOLD_OUT),
            "Secondary (2026-08-20)": window(full, *SECONDARY)}  # fmt: skip
    base = adjustments(client, database, parameters, PLACEBO_SEEDS[0])
    out = ["# H2, out of sample and against a placebo", "",
           "Protocol committed before the hold-out data existed: docs/H2_PREREGISTRATION.md. "
           "Numbers only.", "",
           f"Displaced = more than {reconcile.DISPLACEMENT_TICKS} ticks from the centred 21-swap "
           f"median. Threshold {100 * full.threshold:g}%, flagged = also beyond "
           f"{full.abs_threshold:,.0f} USD. Only complete days with a closed external candle.", "",
           "## 1. The same adjustment, in sample and on the hold-out", "", *HEAD]  # fmt: skip
    for name, subset in sets.items():
        for delta, label in (("delta_all", "revalue every swap (H2 as first tested)"),
                             ("delta_displaced", "revalue displaced swaps only")):  # fmt: skip
            out.append(_line(f"{name}: {label}", evaluate(subset, base, delta)))

    out += ["", "## 2. Placebo, on the in-sample pool-days", "",
            "For each pool-day, the same NUMBER of swaps is revalued, but NON-displaced ones picked "
            f"by a seeded hash. {len(PLACEBO_SEEDS)} seeds ({PLACEBO_SEEDS[0]} to {PLACEBO_SEEDS[-1]}).", "",
            *HEAD]  # fmt: skip
    in_sample = sets["In sample"]
    out.append(
        _line(
            "In sample: revalue displaced swaps only", evaluate(in_sample, base, "delta_displaced")
        )
    )
    fixed, broken = [], []
    for seed in PLACEBO_SEEDS:
        e = evaluate(in_sample, adjustments(client, database, parameters, seed), "delta_placebo")
        fixed.append(e["fixed_positive"] + e["fixed_negative"])
        broken.append(e["broken"])
        if seed == PLACEBO_SEEDS[0]:
            out.append(_line(f"In sample: placebo, seed {seed}", e))
    out += ["", f"Placebo over {len(PLACEBO_SEEDS)} seeds: pool-days fixed min {min(fixed)}, median "
            f"{statistics.median(fixed):g}, max {max(fixed)}; broken min {min(broken)}, median "
            f"{statistics.median(broken):g}, max {max(broken)}.", "",
            "## 3. The hold-out pool-days beyond the threshold, one by one", "",
            "| pool | date | rel diff | abs diff USD | displaced swaps | rel diff, every swap revalued "
            "| rel diff, displaced only |", "|---|---|---|---|---|---|---|"]  # fmt: skip
    for name in ("HOLD-OUT", "Secondary (2026-08-20)"):
        for r in sorted(sets[name].over_relative, key=lambda r: (r["pool_address"], r["date"])):
            d = base.get((r["pool_address"], r["date"]))
            if d is None:
                continue
            ext = r["external_volume_usd"]
            both = [
                reconcile._pct((d["volume_usd"] + d[k] - ext) / ext)
                for k in ("delta_all", "delta_displaced")
            ]
            out.append(f"| {full.labels.get(r['pool_address'], '')} | {r['date']} | "
                       f"{reconcile._pct(r['rel_diff'])} | {reconcile._usd(r['abs_diff_usd'])} | "
                       f"{d['displaced_swaps']} | {both[0]} | {both[1]} |")  # fmt: skip
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m univ3_indexer.h2_check")
    parser.add_argument("--database", help="default: CLICKHOUSE_DB")
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    database = args.database or config.load_clickhouse_config().database
    text = render(ch.connect(database=database), database)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

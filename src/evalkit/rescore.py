"""Score a results file again, against the golden file as it is now.

    PYTHONPATH=src uv run python -m evalkit.rescore RESULTS [--golden evals/golden.jsonl] \\
        [--out FILE]

When a case of the golden file is corrected (a tolerance, an accepted reading), the runs
already paid for do not have to be paid for again: what the agent answered is in their
results file, and only the judgement of it changes. This writes the same results with
every score and every figure computed again. Nothing is asked, no model and no database
take part.

What the new file says about itself: ``golden_sha256`` is the golden file it is scored
against now, and ``rescored`` has one entry per rescoring with both hashes, the old and
the new, and the cases whose verdict changed. The original file is not touched, and a file
that is already there is not overwritten.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import sys
from pathlib import Path

from evalkit import golden, score
from univ3_indexer import config

DEFAULT_GOLDEN = config.REPO_ROOT / "evals" / "golden.jsonl"


def rescore(results: dict, cases: list[dict], golden_sha256: str, at: str) -> dict:
    """The same results, scored against ``cases``. Raises ``GoldenError`` when a case of
    the results is no longer in the golden file: its answer has nothing to be judged by."""
    by_id = {case["id"]: case for case in cases}
    gone = sorted(set(results["cases"]) - set(by_id))
    if gone:
        raise golden.GoldenError(f"not in the golden file any more: {', '.join(gone)}")
    new = copy.deepcopy(results)
    changed = []
    for record in new["records"]:
        if record["status"] != "ran":
            continue
        was = record["score"]["correct"]
        record["score"] = score.score_case(by_id[record["id"]], record["result"])
        if record["score"]["correct"] != was:
            changed.append(
                {
                    "id": record["id"],
                    "repetition": record["repetition"],
                    "was": was,
                    "now": record["score"]["correct"],
                }
            )
    new["cases"] = {case_id: by_id[case_id] for case_id in results["cases"]}
    new["summary"] = score.summarize(new["records"], by_id)
    new["rescored"] = [
        *results.get("rescored", []),
        {
            "at": at,
            "from_golden_sha256": results["golden_sha256"],
            "to_golden_sha256": golden_sha256,
            "changed": changed,
        },
    ]
    new["golden_sha256"] = golden_sha256
    return new


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evalkit.rescore", description=__doc__.split("\n")[0]
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--out", type=Path, default=None, help="default: <results>_rescored.json")
    args = parser.parse_args(argv)
    out = args.out or args.results.with_name(args.results.stem + "_rescored.json")
    if out.exists():
        print(f"{out} already exists; nothing was written", file=sys.stderr)
        return 2
    try:
        results = json.loads(args.results.read_text(encoding="utf-8"))
        cases = golden.load(args.golden)
        sha = hashlib.sha256(args.golden.read_bytes()).hexdigest()
        at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
        new = rescore(results, cases, sha, at)
    except (OSError, json.JSONDecodeError, KeyError, golden.GoldenError) as problem:
        print(f"{type(problem).__name__}: {problem}", file=sys.stderr)
        return 2
    out.write_text(json.dumps(new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    step = new["rescored"][-1]
    print(
        f"{len(step['changed'])} scores changed; golden {step['from_golden_sha256'][:12]} -> "
        f"{step['to_golden_sha256'][:12]}"
    )
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

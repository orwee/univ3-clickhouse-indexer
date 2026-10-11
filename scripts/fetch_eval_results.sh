#!/usr/bin/env bash
# Bring the results of one run of the `eval` workflow into the working copy, for a later
# pull request.
#
#   scripts/fetch_eval_results.sh RUN_ID
#
# RUN_ID is the number in the run's URL (…/actions/runs/RUN_ID). The script downloads the
# artifact `eval-results` of that run with `gh` and copies its two files to
#
#   evals/results/<date>_<variant>.json    the results file, as the run wrote it
#   evals/results/<date>_<variant>.md      the report made from it
#
# where <date> is the day the run started and <variant> the name given when it was started,
# both read from the results file. It never overwrites: if either file is already there it
# stops. It commits nothing and pushes nothing.
#
# Needs: gh, logged in with read access to the repository's Actions; python3.
set -euo pipefail

if [ "$#" -ne 1 ] || ! [[ "$1" =~ ^[0-9]+$ ]]; then
  echo "usage: scripts/fetch_eval_results.sh RUN_ID   (the number in the run's URL)" >&2
  exit 2
fi
run_id="$1"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$root/evals/results"
download="$(mktemp -d)"

gh run download "$run_id" --name eval-results --dir "$download"
if [ ! -f "$download/eval-results.json" ]; then
  echo "fetch_eval_results: the artifact of run $run_id has no eval-results.json" >&2
  exit 1
fi

# <date>_<variant>, from the file itself. The variant becomes part of a file name, so it
# is checked again here: letters, digits, dot, dash and underscore, and nothing else.
name="$(python3 - "$download/eval-results.json" <<'PY'
import json
import re
import sys

results = json.load(open(sys.argv[1], encoding="utf-8"))
day, variant = str(results["started"])[:10], str(results["variant"])
if not re.fullmatch(r"\d{4}-\d\d-\d\d", day) or not re.fullmatch(r"[A-Za-z0-9._-]+", variant):
    sys.exit(f"not usable in a file name: started={day!r} variant={variant!r}")
print(f"{day}_{variant}")
PY
)"

mkdir -p "$target"
for extension in json md; do
  if [ -e "$target/$name.$extension" ]; then
    echo "fetch_eval_results: $target/$name.$extension already exists; nothing was written" >&2
    exit 1
  fi
done
cp "$download/eval-results.json" "$target/$name.json"
if [ -f "$download/eval-report.md" ]; then
  cp "$download/eval-report.md" "$target/$name.md"
else
  echo "fetch_eval_results: the artifact has no report; only the results file was copied" >&2
fi
echo "evals/results/$name.json"
if [ -f "$target/$name.md" ]; then
  echo "evals/results/$name.md"
fi

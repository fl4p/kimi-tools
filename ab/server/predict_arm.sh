#!/usr/bin/env bash
# One predict arm. Invoked by run_all.sh via `xargs -P N`.  Args: name model prompt
# Env (exported by run_all.sh): VENV OUT INSTANCES TIMEOUT RETRIES
set -uo pipefail
AB="$(cd "$(dirname "$0")/.." && pwd)"
PY="${VENV:-$HOME/swebench-venv}/bin/python"
name="$1"; model="$2"; prompt="$3"
args=()
[ "$prompt" != NONE ] && args=(--agent-prompt "$prompt")
print_ts() { date +%H:%M:%S; }
echo "$(print_ts) START $name ($model)" >> "$OUT/logs/_progress.txt"
"$PY" "$AB/swe_bench.py" predict --model "$model" --instances "$INSTANCES" "${args[@]}" \
  --out "$OUT/preds_${name}.jsonl" --save-logs "$OUT/logs/$name" \
  --timeout "${TIMEOUT:-600}" --retries "${RETRIES:-1}" > "$OUT/logs/$name.out" 2>&1
echo "$(print_ts) DONE  $name (exit $?)" >> "$OUT/logs/_progress.txt"

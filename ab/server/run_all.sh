#!/usr/bin/env bash
# Full benchmark: parallel predict -> sequential disk-guarded eval.
# Run inside tmux (it's a multi-hour job). Tunables via env (defaults shown):
#   CONCURRENCY=8   parallel predict arms (Fireworks is the real cap)
#   WORKERS=2       swebench eval workers (lower = less peak Docker disk)
#   MIN_FREE_GB=5   abort eval before an arm if the disk drops below this
#   DOCKER_HOST=... rootless docker socket if not the default
#   INSTANCES=...   comma-list override (default: server/instances.txt)
#   OUT=~/kimi-bench-out
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
AB="$(cd "$HERE/.." && pwd)"; ROOT="$(cd "$AB/.." && pwd)"
export VENV="${VENV:-$HOME/swebench-venv}"
export OUT="${OUT:-$HOME/kimi-bench-out}"; mkdir -p "$OUT/logs"
export INSTANCES="${INSTANCES:-$(tr -d '[:space:]' < "$HERE/instances.txt")}"
export TIMEOUT="${TIMEOUT:-600}" RETRIES="${RETRIES:-1}"
PY="$VENV/bin/python"; SP="$ROOT/system-prompts"
CONCURRENCY="${CONCURRENCY:-8}"; WORKERS="${WORKERS:-2}"; MIN_FREE_GB="${MIN_FREE_GB:-5}"

CLAUDE="$SP/claude-code/2.1.178/interactive-cli.oc-adapted.md"
KCBAL="$SP/kimi-cline/kimi.system-prompt.oc-adapted.md"
KCAUTO="$SP/kimi-cline/kimi-autonomous.system-prompt.oc-adapted.md"
for f in "$CLAUDE" "$KCBAL" "$KCAUTO"; do [ -f "$f" ] || { echo "MISSING PROMPT: $f"; exit 2; }; done

ARMS="default_k26 k2.6 NONE
default_k27 k2.7 NONE
claude_k26 k2.6 $CLAUDE
claude_k27 k2.7 $CLAUDE
kcbal_k26 k2.6 $KCBAL
kcbal_k27 k2.7 $KCBAL
kcauto_k26 k2.6 $KCAUTO
kcauto_k27 k2.7 $KCAUTO"

echo "===== PREDICT (concurrency $CONCURRENCY) ====="
rm -f "$OUT/logs/_progress.txt"
echo "$ARMS" | xargs -P "$CONCURRENCY" -L 1 bash "$HERE/predict_arm.sh"
echo "predict done. per-arm patch counts:"
for a in default_k26 default_k27 claude_k26 claude_k27 kcbal_k26 kcbal_k27 kcauto_k26 kcauto_k27; do
  n=$(grep -cE '[0-9]+B|EMPTY' "$OUT/logs/$a.out" 2>/dev/null || echo 0); echo "  $a: $n"
done

echo "===== EVAL (sequential, workers=$WORKERS, min-free=${MIN_FREE_GB}G) ====="
EVAL_ARMS=()
for a in default_k26 default_k27 claude_k26 claude_k27 kcbal_k26 kcbal_k27 kcauto_k26 kcauto_k27; do
  EVAL_ARMS+=(--arm "$a" "$OUT/preds_${a}.jsonl")
done
"$PY" "$AB/eval_runner.py" --report-dir "$OUT/eval" \
  --workers "$WORKERS" --min-free-gb "$MIN_FREE_GB" "${EVAL_ARMS[@]}"
echo "===== DONE. summary: $OUT/eval/summary.json ====="

# SWE-bench Verified harness (Kimi K2.6 vs K2.7)

Goal: a *capability* benchmark with a difficulty gradient — the thing our toy
scenarios couldn't be (they saturate at 100% for both models, see
`FINDINGS-hard.md`). SWE-bench Verified is 500 real GitHub issues with hidden
`FAIL_TO_PASS` / `PASS_TO_PASS` grading tests.

Two halves, intentionally split because they have different infra needs:

## 1. Predict (no container runtime needed) — `swe_bench.py`

Clones each instance's repo at `base_commit`, runs **opencode + Kimi** (default
agent, prompt held constant — only the model varies) on the issue text, and
writes the resulting `git diff` as a SWE-bench prediction
(`{instance_id, model_name_or_path, model_patch}`), excluding the grading test
files.

```bash
# browse / pick a subset (194 instances are "<15 min fix")
python3 swe_bench.py list --limit 500 | awk -F'|' '{print $3}' | sort | uniq -c

# generate predictions for each model (same instances, same prompt)
python3 swe_bench.py predict --model k2.6 --difficulty "<15 min fix" --limit 15 \
    --timeout 1200 --out preds_k26.jsonl --save-logs swelogs
python3 swe_bench.py predict --model k2.7 --difficulty "<15 min fix" --limit 15 \
    --timeout 1200 --out preds_k27.jsonl --save-logs swelogs
```

Repos are mirrored once into `~/.cache/swebench-kimi/repos/` and reused. A
`<out>.meta.json` sidecar records per-instance duration / tokens / empty-patch.

**Known issue — K2.7 latency.** K2.7 is markedly slower than K2.6 (every study
here agrees). In a real repo it can burn the whole timeout *exploring* and write
no edits → an empty patch (auto-scored as unresolved). Use a generous
`--timeout` (≥1200s) and expect K2.7 to need it. This is itself a finding: a
model too slow to finish within budget can't score on an agentic benchmark.

## 2. Evaluate (needs Docker or podman) — official `swebench`

No Docker on this box; **podman** provides a Docker-compatible API. Note this is
an **arm64 Mac** and SWE-bench's prebuilt images are **x86_64**, so they run
under emulation (slow, multi-GB pulls, occasionally flaky).

```bash
podman machine start                       # boots the Linux VM (100GiB disk)
export DOCKER_HOST='unix:///var/folders/.../podman/podman-machine-default-api.sock'
                                           # exact path printed by `podman machine start`
python3 -m venv /tmp/swebench-venv && /tmp/swebench-venv/bin/pip install swebench

# sanity-check the eval pipeline with the GOLD patches (must resolve 100%):
/tmp/swebench-venv/bin/python -m swebench.harness.run_evaluation \
    --dataset_name princeton-nlp/SWE-bench_Verified \
    --predictions_path gold --run_id goldcheck --namespace swebench \
    --instance_ids psf__requests-5414

# then score a model's predictions:
/tmp/swebench-venv/bin/python -m swebench.harness.run_evaluation \
    --dataset_name princeton-nlp/SWE-bench_Verified \
    --predictions_path preds_k26.jsonl --run_id k26 --namespace swebench
```

The run writes `<model>.<run_id>.json` with `resolved_instances` — that count /
total is the metric that can finally separate K2.6 from K2.7 (if anything can).

## Status / caveats
- Predict harness: mechanics verified (mirror + materialize + patch extraction).
- The bottleneck is wall-clock: K2.7 ~15–25 min/instance, so a 15-instance ×
  2-model run is hours; emulated eval adds more. Scope the subset deliberately.
- `gold`-patch eval is the cheap way to prove the podman path before spending
  model time.

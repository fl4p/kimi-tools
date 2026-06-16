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

## Running on a server (recommended)

SWE-bench's images are x86-64, so an **x86-64 Linux box with native Docker** is
the ideal host — no colima/Rosetta, far fewer flakes, and you can predict wide.
The `server/` kit makes it turn-key:

```bash
git clone https://github.com/fl4p/kimi-tools && cd kimi-tools
FIREWORKS_API_KEY=fw_... bash ab/server/setup.sh   # venv+swebench, opencode, auth
tmux new -s bench                                  # survive SSH drops!
VENV=$HOME/swebench-venv bash ab/server/run_all.sh # predict (parallel) -> eval
```

- **`setup.sh`** — installs swebench (venv), opencode, writes the Fireworks key to
  opencode's `auth.json` (chmod 600; key from `$FIREWORKS_API_KEY`, never committed).
- **`run_all.sh`** — runs the 8 arms' predict at `CONCURRENCY` (default 8) via
  `xargs -P`, then `eval_runner.py` sequentially. Tunables (env): `CONCURRENCY`,
  `WORKERS` (eval), `MIN_FREE_GB` (disk guard), `DOCKER_HOST` (rootless socket),
  `INSTANCES`, `OUT`.
- **Disk guard**: a near-full Docker root is the main risk — eval images are tens
  of GB. `eval_runner.py --min-free-gb N` aborts before an arm if free space drops
  below N GB. Prune first (`docker system prune`) and watch `df -h`.
- **Rootless Docker**: if `docker info` shows a Docker Root under `$HOME`, set
  `DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock` so swebench's SDK connects.

## Status / caveats
- Predict harness: mechanics verified (mirror + materialize + patch extraction).
- The bottleneck is wall-clock: K2.7 ~15–25 min/instance, so a 15-instance ×
  2-model run is hours; emulated eval adds more. Scope the subset deliberately.
- `gold`-patch eval is the cheap way to prove the podman path before spending
  model time.

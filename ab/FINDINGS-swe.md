# SWE-bench Verified: K2.6 vs K2.7 (first real-eval run)

The toy and hard scenarios saturate at 100% and can't rank the two models
(`FINDINGS-hard.md`). This is the first run scored by the **official**
`swebench.harness.run_evaluation` — real GitHub issues, hidden FAIL_TO_PASS /
PASS_TO_PASS grading tests.

## Pipeline (now fully working)
- **Predict**: `swe_bench.py` — clone repo@base_commit, run opencode+Kimi on the
  issue (default agent, prompt held constant), extract `git diff` as the
  model_patch. Two bring-up bugs fixed: run opencode with `cwd=<workdir>` (else it
  inherits this repo's `.opencode` config and never converges), and an
  action-forcing prompt line (else the model rabbit-holes into reproduction and
  never edits).
- **Eval**: official swebench via **colima** (Docker daemon in a Linux VM) with
  `--vm-type vz --vz-rosetta` so this arm64 Mac runs SWE-bench's x86 images via
  Rosetta. Gold-patch sanity check resolved 1/1. (podman's docker-compat API was
  unusable — storage-driver error; colima fixed it.)

## Result — subset: all 8 `psf/requests` instances
opencode + Kimi, Fireworks, default prompt, 1 attempt/instance.

| instance | K2.6 | K2.7 |
|----------|------|------|
| requests-1142 | ✅ | ✅ |
| requests-1724 | ✅ | ❌ unresolved |
| requests-1766 | ✅ | ✅ |
| requests-1921 | ✅ | ❌ unresolved |
| requests-2317 | ❌ unresolved | ✅ |
| requests-2931 | ✅ | ✅ |
| requests-5414 | ✅ | ✅ |
| requests-6028 | ⊘ empty patch | ✅ |
| **resolved** | **6 / 8 (75%)** | **6 / 8 (75%)** |

## Read
- **Dead tie: 6/8 each.** 4 instances solved by both; each model uniquely solves 2
  the other misses (K2.6: 1724, 1921; K2.7: 2317, 6028). At n=8 that difference is
  noise, not signal.
- K2.6 left **1 empty patch** (didn't converge to an edit on 6028); K2.7 produced
  a patch for all 8 but 2 failed the hidden tests. Different failure shapes, same
  score.
- **No measurable K2.7 capability edge** — consistent with every other study here.
  At this difficulty band the models are interchangeable on success; they differ
  only in latency/cost/failure-mode, not in what they can solve.

## Efficiency (predict-phase latency / tokens / tool calls)

|                      | K2.6  | K2.7  |
|----------------------|-------|-------|
| avg latency/instance | 95s   | **72s** |
| total wall-clock (8) | 762s  | **574s** |
| avg tokens/instance  | 731k  | 728k  |
| total tokens         | 5.85M | 5.82M |
| avg tool calls       | 25.4  | 25.2  |

- **Tokens and tool-calls are essentially identical** (~5.8M total, ~730k/instance,
  ~25 calls). On real repo work both models do the same *amount* of work.
- **K2.7 was faster here (72s vs 95s)** — the OPPOSITE of every toy/hard-scenario
  study, where K2.7 was the slow one. That "K2.7 is slower" pattern did NOT
  replicate on real agentic work. Likely because real-repo latency is dominated by
  tool execution (pip install, pytest, bash) not model token-generation speed, so
  the model-speed difference washes out.
- **But it's noisy.** Per-instance variance is huge: requests-5414 was K2.6 218s /
  1.5M tok vs K2.7 48s / 346k tok (same instance); 1766 flips the other way (K2.6
  23s vs K2.7 40s). At n=8 the 95-vs-72 average is barely above noise. Also K2.6's
  early instances overlapped the gold eval on colima → some VM contention inflated
  its times; K2.7 ran clean. Don't over-read the latency edge.

Net across all three axes — resolved-rate (6/8 tie), tokens (identical), latency
(comparable, noisy) — **nothing cleanly separates the two models on this workload.**

## Sharp prompt vs default (4-arm, same 8 requests instances)

Re-ran both models with the **`sharp.md`** custom prompt (the "small sharp toolset"
system prompt) seeded as an opencode agent — everything else identical.

| instance | K2.6 default | K2.6 sharp | K2.7 default | K2.7 sharp |
|----------|------|------|------|------|
| 1142 | ✅ | ✅ | ✅ | ✅ |
| 1724 | ✅ | ❌ | ❌ | ❌ |
| 1766 | ✅ | ❌ | ✅ | ❌ |
| 1921 | ✅ | ❌ | ❌ | ❌ |
| 2317 | ❌ | ❌ | ✅ | ❌ |
| 2931 | ✅ | ❌ | ✅ | ✅ |
| 5414 | ✅ | ✅ | ✅ | ✅ |
| 6028 | ⊘ empty | ⊘ empty | ✅ | ✅ |
| **resolved** | **6/8** | **2/8** | **6/8** | **4/8** |

| arm | avg latency | avg tokens | avg tool calls |
|-----|------|------|------|
| K2.6 default | 95s | 731k | 25.4 |
| K2.6 sharp | 87s | 652k | 24.9 |
| K2.7 default | 72s | 728k | 25.2 |
| K2.7 sharp | 86s | **530k** | 23.4 |

**The sharp prompt REGRESSED both models and gained nothing.** K2.6 6→2/8, K2.7
6→4/8; *every* changed cell is a loss, no instance was newly solved. And it did so
while using **fewer tokens** (K2.7 728k→530k) — i.e. it compressed the model into
doing *less* work, and that less work produced *wrong* fixes more often (different,
terser patches that fail the hidden tests).

This is the punchline tying the whole study together: `sharp` was tuned to improve
**tool-hygiene metrics on toy scenarios** (fewer discouraged/duplicate calls), and
it does — but on **real tasks with hidden correctness tests it trades correctness
for concision.** Cleaner-looking tool use ≠ better outcomes. The hygiene win on
trivial tasks was measuring the wrong thing.

## System-prompt bake-off (6 prompts × 2 models)

Same 8 psf/requests instances, opencode+Kimi harness, swapping only the
`--agent-prompt`. "default" = opencode's built-in coding-agent prompt. The other
five are real agent system prompts extracted/adapted for opencode's toolset.

| prompt (`--agent-prompt`) | K2.6 | K2.7 | source |
|---------------------------|------|------|--------|
| **default** (opencode)    | 6/8  | 6/8  | opencode built-in |
| sharp                     | 2/8  | 4/8  | kimi tool-hygiene-tuned |
| cursor                    | 3/8  | 4/8  | Cursor Composer (community leak) |
| codex-coding              | 7/8  | 6/8  | OpenAI Codex `base_instructions` |
| claude-code               | 7/8  | **8/8** | Claude Code interactive CLI |
| cline (native-next-gen)   | 7/8  | 7/8  | Cline default |

**The verdict splits cleanly into two families:**

1. **Harness-/terseness-tuned prompts REGRESS** (`sharp`, `cursor`): both fall well
   below the opencode default on both models. `sharp` was tuned for tool-hygiene
   metrics; `cursor` is written for a different harness/UI. Neither was built to
   maximize correctness on an unfamiliar toolset, and it shows.

2. **Real general coding-agent prompts MATCH or BEAT the default** (`codex-coding`,
   `claude-code`, `cline`): all three land at 7–8/8, i.e. ≥ default's 6/8. These
   were written to drive a model through a read→edit→verify loop on real repos —
   exactly this task — so they transfer even after tool-name adaptation.

The standout is **claude-code on K2.7 → 8/8 (perfect)**, the only arm to beat default
outright on a model. Its emphasis on "edit the source, don't stop at analysis" and
verification discipline is the kind of guidance that helps Kimi most: the K2.7 failure
mode on default was occasionally rabbit-holing on analysis without committing an edit.

Takeaway: **a coding-agent prompt's value is mostly about whether it was built to
drive a real edit-loop, not about which vendor wrote it or how clever the wording is.**
Adapting any of the three "real" prompts to opencode's tools is a safe swap; the
hygiene/UI-tuned ones are net-negative.

### Cost profile (avg per instance, n=8)

`latency` = wall-clock seconds of the opencode run; `tokens` = total tokens the
run consumed (in/out, from the isolated session db); `tools` = number of tool
calls the agent made. Averaged over the 8 psf/requests instances per arm.

| prompt | model | resolved | avg latency | avg tokens | avg tool calls |
|--------|-------|----------|-------------|------------|----------------|
| default      | K2.6 | 6/8 | 95s  | 731k | 25.4 |
| default      | K2.7 | 6/8 | 72s  | 728k | 25.2 |
| sharp        | K2.6 | 2/8 | 87s  | 652k | 24.9 |
| sharp        | K2.7 | 4/8 | 86s  | 530k | 23.4 |
| cursor       | K2.6 | 3/8 | 149s | 814k | 26.0 |
| cursor       | K2.7 | 4/8 | 254s | 751k | 27.4 |
| codex-coding | K2.6 | 7/8 | 93s  | 517k | 18.8 |
| codex-coding | K2.7 | 6/8 | 158s | 607k | 24.5 |
| claude-code  | K2.6 | 7/8 | 123s | 676k | 22.4 |
| claude-code  | K2.7 | 8/8 | 178s | 575k | 25.6 |
| cline        | K2.6 | 7/8 | 140s | 541k | 25.9 |
| cline        | K2.7 | 7/8 | 295s | 908k | 31.2 |

![Avg latency per instance, by prompt × model](charts/cost-latency.svg)

![Avg tokens per instance, by prompt × model](charts/cost-tokens.svg)

![Avg tool calls per instance, by prompt × model](charts/cost-tools.svg)

<sub>Charts: `python3 make_cost_charts.py` (pure-stdlib SVG), rendered from
`bake-off-cost.csv` — the benchmark's own output via `swe_bench.py aggregate`
(per-arm reduction of each predict `*.meta.json`), the same numbers as the table
above. Blue = K2.6, orange = K2.7.</sub>

What the cost columns add on top of the resolved-rate story:

- **`codex-coding` is the efficiency winner**: best/tied-best resolved rate at the
  *fewest* tool calls (K2.6: 18.8 vs default's 25.4) and *fewest* tokens (517k). It
  gets more done with less — its terse, plan-first style cuts wasted exploration.
- **`claude-code`'s 8/8 isn't free**: K2.7 spends more wall-clock (178s vs default's
  72s) but actually *fewer* tokens (575k vs 728k) — it thinks longer per token, not
  more tokens. The latency buys the correctness.
- **`cline` is the most expensive arm** (K2.7: 295s, 908k tokens, 31 tool calls) for
  the same 7/8 the others hit cheaper — its verbose, step-enumerating style inflates
  cost without a matching resolved-rate gain.
- **`sharp` is cheap *and* wrong**: fewest tokens on K2.7 (530k) but worst resolved
  rate — it compressed the model into doing less work, and the less work was wrong.
  Cheap is not the goal; cheap-and-correct is, and only `codex-coding` delivers it.

Caveat on these numbers: latency is emulated/local wall-clock (Fireworks queue +
network), so absolute seconds are noisy; the *relative* ordering and the
tokens/tool-call counts are the stable signal.

## Caveats (why this isn't the final word)
- **n=8, one repo, easy band.** All requests instances are "<15 min – 1 hour",
  pure-Python. The signal-bearing instances live in django/sympy/sklearn
  ("1–4 hours", ">4 hours") — exactly where a stronger model could pull ahead and
  where requests-only can't show it.
- 1 attempt/instance (no pass@k). A single empty patch swings the rate by 12.5%.
- To actually rank the models you'd want ~50–100 instances spanning hard repos.
  The pipeline now supports that; it's just (emulated-eval) wall-clock and disk.

## Repro
```bash
# 1) predict (writes preds_*.jsonl + a preds_*.meta.json sidecar with
#    per-instance duration_s / tokens / tool_calls)
python3 swe_bench.py predict --model k2.6 --repos psf/requests --out preds_k26.jsonl
python3 swe_bench.py predict --model k2.7 --repos psf/requests --out preds_k27.jsonl

# 2) eval (colima running; DOCKER_HOST = colima socket)
python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified \
    --predictions_path preds_k26.jsonl --run_id req_k26 --namespace swebench

# 3) aggregate each arm's meta.json (+ its resolved count) into the cost CSV,
#    then re-render the charts from it — no hand-edited numbers
python3 swe_bench.py aggregate --meta preds_k26.meta.json --prompt default --resolved 6/8
python3 make_cost_charts.py          # bake-off-cost.csv -> charts/cost-*.svg
```

The committed `bake-off-cost.csv` + `charts/*.svg` are the snapshot from the run
above (the raw `preds_*`/`*.meta.json`/eval reports are gitignored).

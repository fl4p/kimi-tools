# kimi-tools

A small benchmark that answers one practical question: **does the agent system
prompt change how much a coding model can solve — and is the best prompt the same
across models?** Short answer: the prompt matters a lot, and **the best prompt is
model-specific**, not ordered by model strength.

It runs real coding-agent system prompts (Claude Code, Cursor, `sharp`, and our two
Kimi-tuned `kimi-cline` prompts) through the **opencode** harness against
[**SWE-bench Verified**](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)
— real GitHub issues scored by the official `swebench.harness.run_evaluation`
(hidden FAIL_TO_PASS / PASS_TO_PASS tests). Models: **Kimi K2.6**, **Kimi K2.7**,
and **GLM-5.2** via Fireworks, plus a **Claude Opus 4.8** cross-family probe.

> **Note — Fireworks + Kimi thinking mode.** `kimi-k2p7-code` (K2.7) is a reasoning
> model; `kimi-k2p6` (K2.6) is not. On Fireworks, **run K2.7 with thinking left
> ON** — in an endpoint micro-benchmark, *disabling* reasoning on the `-code` model
> blew time-to-first-token up to **~26 s** (vs **~0.5 s** with it on) and the model
> emitted reasoning tokens anyway, so turning it off bought nothing and cost a lot.
> K2.6 is unaffected. Every run here uses K2.7 in its native thinking mode.

## Headline — system-prompt bake-off (harder band)

**48 instances across 8 repos** (sympy, scikit-learn, sphinx, xarray, matplotlib,
astropy, pytest, django — the "15 min–1 h" and "1–4 h" difficulty bands), 3 models ×
6 prompts, swapping only the agent system prompt. `default` = opencode's built-in
coding prompt; the other five are (adapted) [system prompts](system-prompts/).

Resolved out of **43** — 5 matplotlib instances are excluded for cross-model
comparability (their prebuilt eval images won't unpack on the grading box; a host
constraint, not a model failure).

| prompt | K2.6 | K2.7 | GLM-5.2 |
|--------|:----:|:----:|:-------:|
| **default** (opencode) | 16/43 | **25/43** | 26/43 |
| sharp | **21/43** | 18/43 | 29/43 |
| cursor | 20/43 | 17/43 | **37/43 (86%)** |
| kimi-cline (autonomous) | 19/43 | 20/43 | 34/43 |
| kimi-cline (balanced) | 18/43 | 13/43 | 27/43 |
| claude-code | 14/43 | 22/43 | 35/43 |
| **best / worst arm** | sharp 21 / claude 14 | **default 25** / kcbal 13 | **cursor 37** / default 26 |

![Resolved rate by prompt × model](ab/charts/bakeoff-resolved.svg)

**There is no universal best prompt — and it is not ordered by model strength.**
Each model has a *different* best arm:

1. **K2.6 (weakest) likes light scaffolding** — `sharp` (21) and `cursor` (20) beat
   bare `default` (16); only `claude-code` (14) trails it.
2. **K2.7 wants no scaffold** — bare `default` wins (25) and every custom prompt
   *hurts*, down to `kcbal` (13). The least instruction is best.
3. **GLM-5.2 wants scaffolding badly** — `cursor` (**37/43, 86%**), `claude-code`
   (35), `kcauto` (34) tower over bare `default` (26), which is GLM-5.2's *worst* arm.

**The mechanism is the empty-patch rate.** Under bare `default`, GLM-5.2 ends
**12/48** trajectories without committing any source edit; the coding-agent scaffolds
("edit the source, don't stop at analysis"; verify before finishing) cut that to
**1–4**, and the resolved-rate gain tracks the empty-rate drop almost exactly. K2.7
already drives a decisive edit loop on `default`, so the same scaffolds only add
friction. At its best, **GLM-5.2 is the strongest model on this band** (cursor 37/43
vs the best Kimi arm's 25/43) — and the **cheapest**.

### Cost — by prompt × model

![Tokens per arm](ab/charts/bakeoff-tokens.svg)

![Tool calls per instance](ab/charts/bakeoff-tools.svg)

GLM-5.2 is not just strongest at its best, it's **cheapest everywhere** — ~12–27 M
tokens/arm vs Kimi's 35–64 M, with the fewest tool calls. Charts are rendered by
[`ab/make_cost_charts.py`](ab/make_cost_charts.py) (pure-stdlib SVG, no matplotlib)
from [`ab/bake-off-cost.csv`](ab/bake-off-cost.csv).

### Opus 4.8 — a cross-family probe

Does a frontier *closed* model clear this band? Two probes — **Claude Opus 4.8 at
`xhigh` reasoning effort** (Anthropic, via opencode `--variant xhigh`), on the
`claude-code` and `cursor` prompts:

| arm | resolved /43 | empty | cost |
|-----|:---:|:---:|:---:|
| opus-4.8-xhigh · claude-code | **36/43 (84%)** | 1 | $52.46 |
| opus-4.8-xhigh · cursor | **35/43 (81%)** | 3 | $43.71 |

It lands **in GLM-5.2's strong-arm range (35–37/43), not above it** — a frontier
closed model at high effort ≈ well-scaffolded GLM-5.2 here, at ~**$96 for the pair**
vs GLM's Fireworks pennies. And Opus's prompt sensitivity is **flat** (claude 36 ≈
cursor 35) — closer to K2.7's "no scaffold needed" than to GLM-5.2's big swing.

⚠️ **Significance.** The one large, robust prompt effect is **GLM-5.2's scaffold-vs-
default gap (≈ +10/43)**. The *within-model* Kimi deltas are mostly within ~1 standard
error — trust "K2.7 prefers no scaffold / GLM-5.2 needs one," not the exact 1–2
instance orderings. Full numbers, cost profiles, the empty-patch analysis, and a
patch-extraction leak we found & fixed: **[`ab/FINDINGS-swe.md`](ab/FINDINGS-swe.md)**.

> **The easy band is retired as a headline.** An earlier version of this README led
> with 8 `psf/requests` instances and a dramatic "family split" (`sharp` 2/8 vs
> `claude-code` 8/8). That spread was a **grading artifact** — the suite hammers a
> live `httpbin` service that flaked during sequential runs; a deterministic re-grade
> collapses it to 6–7/8 for every arm. The easy band can't separate the prompts and is
> kept only as a near-ceiling control. See [FINDINGS → Easy band, re-graded](ab/FINDINGS-swe.md).

## Repo layout

| Path | What |
|------|------|
| [`ab/FINDINGS-swe.md`](ab/FINDINGS-swe.md) | The SWE-bench results above, in full (3 models × 6 prompts + the Opus probe). |
| [`ab/`](ab/) | The benchmark harnesses + `swe_bench.py` (predict/eval/aggregate) + all `FINDINGS-*.md`. |
| [`ab/README-swe.md`](ab/README-swe.md) | How to run the SWE-bench predict + eval pipeline. |
| [`ab/bake-off-cost.csv`](ab/bake-off-cost.csv) | Harder-band data (resolved/43, tokens, tools); [`make_cost_charts.py`](ab/make_cost_charts.py) renders it to `ab/charts/bakeoff-*.svg`. |
| [`system-prompts/`](system-prompts/) | Every prompt the bake-off runs — `claude-code/`, `cursor/`, `sharp.md`, plus our own `kimi-cline/`. Each external one keeps the raw extract and an `.oc-adapted.md` opencode port. |
| [`system-prompts/kimi-cline/`](system-prompts/kimi-cline/) | **Our two Kimi-tuned cline prompts** (balanced + autonomous) — see [its README](system-prompts/kimi-cline/README.md). |

## Quick start

```bash
# SWE-bench predict (opencode + a Fireworks model):
python3 ab/swe_bench.py predict --model glm5.2 --repos psf/requests --out preds.jsonl

# Opus 4.8 at a reasoning-effort variant (needs ANTHROPIC_API_KEY in env):
python3 ab/swe_bench.py predict --model opus4.8-xhigh --instances astropy__astropy-12907 \
    --agent-prompt system-prompts/claude-code/2.1.178/interactive-cli.oc-adapted.md --out preds.jsonl

# Regenerate the cost charts from the CSV:
python3 ab/make_cost_charts.py
```

See [`ab/README-swe.md`](ab/README-swe.md) for the colima/Docker eval setup.

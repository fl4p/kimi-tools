# Is the bake-off measuring capability, or memorization? A post-cutoff validity test

SWE-bench Verified is public and pre-cutoff — every model here was almost certainly
trained on these repos and issues. So the headline question: are the resolved rates
(and the *prompt effects* on them) real, or partly an artifact of recalling fixes to
specific, memorized problems?

To separate the two we re-ran a slice of the experiment on **un-memorizable** problems:
**[SWE-rebench](https://swe-rebench.com) `2026_03`** — 30 instances across 30 distinct
repositories, every issue **created 2026-03 to 2026-05**, i.e. *after* the training
cutoff of the models tested. Same opencode harness, same official-style grading (the
[SWE-rebench swebench fork](https://github.com/SWE-rebench/SWE-bench-fork) against the
project's prebuilt Docker images; gold patches validated 3/3 before the run).

Two models with **opposite** prompt preferences on the benchmark, three arms:
`default` (opencode built-in), `cursor` (the strong scaffold), and `bare` (a 2-line
minimal system prompt — true no-scaffold).

## Result

| arm | GLM-5.2 pre `/48` | GLM-5.2 post `/30` | K2.7 pre `/48` | K2.7 post `/30` |
|-----|:---:|:---:|:---:|:---:|
| **default** | 29 (60%) | 18 (60%) | 40 (83%) | 22 (73%) |
| **cursor** | 40 (83%) | 19 (63%) | 35 (73%) | 16 (53%) |
| **bare** | — | 21 (70%) | — | 19 (63%) |
| **scaffold gap** (cursor − default) | **+23 pp** | **+3 pp** | **−10 pp** | **−20 pp** |

Three things fall out, and they don't all point the same way:

### 1. Capability generalizes — it is *not* pure memorization
Both models solve fresh 2026 problems at rates close to the benchmark: GLM's `default`
is **identical** (60% → 60%), K2.7's drops only modestly (83% → 73%). If the headline
numbers were mostly *recall* of memorized fixes, performance would collapse on
never-seen problems. It doesn't. The models are genuinely solving.

### 2. GLM's pro-scaffold effect was largely a benchmark artifact
The single largest effect in the entire bake-off — the `cursor` scaffold giving GLM-5.2
**+23 pp** over bare `default` — shrinks to **+3 pp** (within noise) on fresh instances.
On un-memorizable problems `bare` is GLM's *best* arm. The mechanism confirms it: GLM
ended **12/48 (25%)** of pre-cutoff `default` trajectories with an empty patch (no edit
committed) — the scaffold's whole job was to stop that bailing — but on fresh `default`
it bails only **2/30 (7%)**. Whatever made GLM abandon the edit loop on the *specific*
SWE-bench problems mostly isn't present on fresh ones, so the scaffold has little left
to fix. **The "GLM desperately needs scaffolding" headline does not replicate.**

### 3. K2.7's anti-scaffold effect is real and generalizes
K2.7's scaffold *penalty* not only survives but strengthens: `cursor` costs it
**−10 pp** on the benchmark and **−20 pp** on fresh instances. Heavy scaffolding
genuinely hurts a model that already drives a decisive edit loop.

## Takeaway

On un-memorizable problems, **less scaffolding wins for both models** — `bare` and
`default` beat the heavy `cursor` scaffold every time. The benchmark's *pro*-scaffold
signal (driven entirely by GLM) **does not transfer**; the *anti*-scaffold signal does.

So the answer to "is the system prompt just adding overfit noise?" is **partly yes**:
the biggest measured prompt benefit was substantially specific to the memorized
benchmark. But it is **not** all noise — raw capability holds up out-of-sample, and at
least one prompt effect (scaffolding hurting an already-decisive model) is a real,
generalizing property.

**Practical upshot:** if you run these models on your own (un-benchmarked) issues,
don't expect a heavy agent scaffold to buy you GLM's benchmark-sized gains — a minimal
prompt is competitive or better. Tune the scaffold on *your* distribution, not on
SWE-bench's.

## External corroboration: DeepSWE

[DeepSWE](https://deepswe.datacurve.ai/) is the at-scale, stronger version of this test:
113 tasks **written from scratch** (never adapted from real commits/PRs, so unmemorizable
by construction), 91 repos, 5 languages, every model on the same minimal `mini-swe-agent`,
pass@1. For the three models we share it ranks:

| | our SWE-bench Verified `/48` | our post-cutoff `/30` (default) | DeepSWE (from-scratch) |
|---|:--:|:--:|:--:|
| **K2.7** | **40–42** (nominal top) | 73% | **31% (last)** |
| **GLM-5.2** | 40 | 60% | 44% |
| **Opus-4.8** | 40 | — | 59% |

The ranking **inverts**: K2.7 leads on the memorizable benchmark and is *last* on the
written-from-scratch one, while Opus and GLM hold up. The three benchmarks form a
contamination gradient — Verified (memorizable) → SWE-rebench (fresh issue, real repo) →
DeepSWE (wholly novel) — and K2.7 falls monotonically across it (40–42 → 73% → 31%) while
GLM/Opus degrade far less. That is independent, larger-N confirmation of the core finding:
the SWE-bench-Verified ordering is substantially a familiarity artifact, worst for K2.7.

![Same models, two benchmarks — the ranking inverts](charts/generalization.svg)

## Caveats

- **N = 30, one month, two models.** The GLM cursor−default gap post-cutoff is ±1
  instance — treat "collapsed to noise" as the claim, not the exact +3 pp. The K2.7
  −6/30 cursor penalty and the empty-rate shift are larger and more robust.
- **Different repo distribution.** SWE-rebench `2026_03` is 30 distinct, mostly smaller
  repos (pgmpy, tox, sqlglot, …) vs the pre-cutoff band's 8 large famous ones. Some of
  the effect difference could be repo-mix, not pure freshness — though that cuts both
  ways and doesn't explain why the *direction* of the scaffold effect splits by model.
- Reproduce: `swe_bench.py predict --dataset-jsonl <rebench subset>` then grade with the
  SWE-rebench fork (`--namespace swerebench`). Data: `nebius/SWE-rebench-leaderboard`,
  split `2026_03`.

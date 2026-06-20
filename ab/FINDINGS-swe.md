# SWE-bench Verified: Kimi K2.6 / K2.7 / GLM-5.2 — system-prompt bake-off

Scored by the **official** `swebench.harness.run_evaluation` — real GitHub issues
with hidden FAIL_TO_PASS / PASS_TO_PASS grading tests. We run opencode (via Fireworks)
on each issue, extract the `git diff`, and grade it. The question: does swapping the
agent **system prompt** change how much a model can solve, and does the answer differ
across models — **Kimi K2.6, Kimi K2.7, and GLM-5.2**?

We tested two difficulty bands:
- **harder band** — 48 instances across 8 repos (sympy / scikit-learn / sphinx /
  xarray / matplotlib / astropy / pytest / django), the "15 min–1 h" and "1–4 h"
  bands. This is the signal-bearing run.
- **easy band** — all 8 `psf/requests` instances ("<15 min–1 h", pure-Python). Near
  the ceiling for every arm; useful mainly as a control.

Six prompts: `default` (opencode's built-in coding agent), `claude-code`, `cursor`,
`sharp` (a tool-hygiene-tuned prompt), and our two `kimi-cline` prompts (balanced +
autonomous). The two Kimi models ran both bands × all six prompts; **GLM-5.2 ran the
harder band × all six prompts** (the signal-bearing comparison).

## TL;DR

1. **The best prompt is model-specific — not ordered by model strength** (48-instance
   band, 3 models × 6 prompts). Each model's best arm differs: **K2.6 → sharp** (21/43),
   **K2.7 → bare default** (25/43), **GLM-5.2 → cursor** (37/43). The same scaffolds that
   *hurt* K2.7 (down to 13/43) *lift* GLM-5.2 to 34–37/43.
2. **GLM-5.2 is the strongest model on this band at its best (37/43, 86%) and the cheapest**
   (~12–27M tokens/arm vs Kimi's 35–64M) — but only with scaffolding; on bare `default` it
   ties K2.7 (26 vs 25) because it bails without editing 12/48 of the time. Coding-agent
   scaffolds cut that empty rate to 1–4 and the resolved rate climbs with it.
3. **The easy band can't separate the arms** — under clean grading every prompt lands
   at 6–7/8 fix-correctness. It adds a near-constant offset to the pooled score and
   does not change the ranking.
4. **No single prompt dominates across models**, and within a model the Kimi deltas are
   within ~1 standard error; the GLM-5.2 scaffold-vs-default gap (≈+10/43) is the one large,
   robust prompt effect. The best scaffold depends on the model's default-prompt failure mode.
5. **A retraction:** an earlier version of this doc reported a dramatic easy-band
   "family split" (`sharp` 2/8, `cursor` 3/8 vs `claude-code` 8/8). That spread was a
   **grading artifact** — the `psf/requests` suite hammers a live `httpbin` service
   that flaked during sequential arm runs. A deterministic re-grade collapses the
   spread to 6–7/8 for all arms. The split is retired; see **Easy band, re-graded**.
6. **A frontier *closed* model doesn't clear the bar here.** Claude Opus 4.8 at `xhigh`
   reasoning effort resolves **35–36/43** on its `claude-code` and `cursor` arms — within
   noise of well-prompted GLM-5.2 (its 35–37/43 arms), not above — at ~**$44–52/arm** vs
   GLM's Fireworks pennies. See **Opus 4.8 (xhigh) — a cross-family probe**.

## Headline — harder band (8 repos, 48 instances, on a server)

Same opencode+Kimi harness, swapping only the `--agent-prompt`. Run on an x86-64
Linux server with native Docker.

**5 matplotlib instances are excluded** — their prebuilt eval images carry files owned by
a UID beyond the host's rootless-docker subuid range, so the layers won't unpack on this
box (a host constraint, not a model failure). Resolved rates are out of **43**. (Two
sklearn instances each errored for one arm and are conservatively counted as not-resolved.)

Three models, all six prompts, resolved out of 43:

| prompt | K2.6 | K2.7 | GLM-5.2 |
|--------|:----:|:----:|:-------:|
| default | 16/43 (37%) | 25/43 (58%) | 26/43 (60%) |
| sharp   | 21/43 (49%) | 18/43 (42%) | 29/43 (67%) |
| cursor  | 20/43 (47%) | 17/43 (40%) | **37/43 (86%)** |
| kimi-cline (autonomous) | 19/43 (44%) | 20/43 (47%) | 34/43 (79%) |
| kimi-cline (balanced)   | 18/43 (42%) | 13/43 (30%) | 27/43 (63%) |
| claude-code | 14/43 (33%) | 22/43 (51%) | 35/43 (81%) |
| **best / worst arm** | sharp 21 / claude 14 | default 25 / kcbal 13 | **cursor 37 / default 26** |

**There is no universal best prompt — and it is not ordered by model strength.** Each model
has a *different* best arm and a *different* worst arm:

1. **K2.6 (weakest) likes light scaffolding** — `sharp` (21) and `cursor` (20) beat bare
   `default` (16); only `claude-code` (14) trails it.
2. **K2.7 wants no scaffold** — bare `default` wins (25/43) and every custom prompt *hurts*,
   down to `kcbal` (13). The least instruction is best.
3. **GLM-5.2 wants scaffolding badly** — `cursor` (37/43, 86%), `claude-code` (35) and
   `kcauto` (34) tower over bare `default` (26), which is GLM-5.2's *worst* arm.

The earlier "prompt effect flips sign with model **strength**" reading was an artifact of
having only two models. GLM-5.2 breaks it: on the bare `default` prompt GLM-5.2 ≈ K2.7
(26 vs 25), yet the *same* scaffolds that drop K2.7 to 13–22 lift GLM-5.2 to 34–37. The
effect is **model-specific**, set by each model's default-prompt failure mode, not its raw
strength.

**The mechanism is the empty-patch rate.** Under bare `default`, GLM-5.2 ends **12/48**
trajectories without committing any source edit; the coding-agent scaffolds ("edit the
source, don't stop at analysis"; verify before finishing) cut that to **1–4**, and the
resolved-rate gain tracks the empty-rate drop almost exactly. K2.7 already drives a decisive
edit loop on `default`, so the same scaffolds only add friction. At its best, **GLM-5.2 is
the strongest model on this band** (cursor 37/43 vs the best Kimi arm's 25/43) — and the
cheapest (~12–27M tokens/arm vs Kimi's 35–64M).

### Harder-band cost (per arm)

| prompt | K2.6 tok/tools/$ | K2.7 tok/tools/$ | GLM-5.2 tok/tools |
|--------|------------------|------------------|-------------------|
| default | 35M / 25 / $8.5 | 41M / 26 / $10.2 | 12M / 11 |
| sharp   | 42M / 28 / $10.0 | 40M / 26 / $9.9 | 15M / 14 |
| cursor  | 43M / 28 / $10.8 | 48M / 26 / $11.6 | 20M / 15 |
| kimi-cline (autonomous) | 64M / 40 / $15.2 | 59M / 31 / $14.1 | 27M / 21 |
| kimi-cline (balanced)   | 39M / 29 / $9.6 | 52M / 30 / $12.6 | 18M / 17 |
| claude-code | 42M / 28 / $10.0 | 45M / 29 / $11.2 | 17M / 15 |

<sub>GLM-5.2 ran on a fresh x86-64 box (same environment *kind* as the Kimi server: native
Docker + in-solve `pip`/`pytest`; root Docker, so matplotlib grades and is excluded to keep
the /43 comparable). GLM `$` omitted — needs the GLM-5.2 Fireworks rate; tokens run ~3× below
Kimi. GLM's heavy installing exposed (and we fixed) a patch-extraction leak — see **GLM-5.2
notes** below.</sub>

**This revises a 16-instance pilot.** An earlier 16-instance cut of this band put
`claude-code` on top (28/32) and read it as "the most consistent winner." At 48 instances
that did **not** hold: `claude-code` is *worst* on K2.6 (14) and second on K2.7 (22), while
`default·K2.7` leads. The small-N result was noise — at n=16 a 1–3 instance lead sits inside
one standard error. The honest read: **no single prompt dominates; the best scaffold is
model-specific** — true for K2.7 (no scaffold beats default) but the *opposite* for GLM-5.2
(every good scaffold beats default by a wide margin).

## Opus 4.8 (xhigh) — a cross-family probe

Does a frontier *closed* model clear this band? We ran two cross-family probes: **Claude
Opus 4.8 at `xhigh` reasoning effort** (Anthropic, via opencode `run --variant xhigh`), on
the `claude-code` and `cursor` prompts — same 48-instance harder band, same harness, graded
identically.

| arm | resolved /48 | resolved /43 | empty | cost | tokens |
|-----|:---:|:---:|:---:|:---:|:---:|
| opus-4.8-xhigh · claude-code | 40/48 | **36/43 (84%)** | 1 | $52.46 | 48.6M |
| opus-4.8-xhigh · cursor      | 40/48 | **35/43 (81%)** | 3 | $43.71 | 40.2M |

**Both land in GLM-5.2's strong-arm range, not above it.** The two probes resolve 35–36/43:
Opus's `claude-code` (36) edges its `cursor` (35), and both sit within noise of well-prompted
GLM-5.2 (35–37/43), below its `cursor` peak (37). So a frontier closed model at high reasoning
effort ≈ a well-scaffolded open model on this band — at very different cost (**~$44–52/arm,
~$96 for the pair**) vs GLM-5.2's Fireworks pennies. (The `$` is the cache-aware figure
opencode reports per step; blended ~$1.1/M token — most of the 40–49M tokens are cache-reads
at $0.5/M, not fresh input at $5/M or output at $25/M, so a naive tokens×rate estimate
overshoots ~3–5×.)

**Opus's prompt sensitivity is flat — the opposite of GLM-5.2's.** Where GLM-5.2 swings ≈+10/43
from bare `default` to its best scaffold, Opus barely moves between its two strong scaffolds
(claude 36 vs cursor 35), and `cursor` actually *raised* its empty rate (3/48 vs 1/48) instead
of lowering it. Opus already drives a decisive edit loop, so extra scaffolding neither helps
nor much hurts — closer to K2.7's "wants no scaffold" profile than to GLM-5.2's.

<sub>Two of six prompts, and not the bare `default` baseline — a partial read of Opus's
prompt sensitivity, not a full column. Anthropic via opencode is **API-key only** (no Claude
Pro/Max OAuth in this build); reasoning effort is per-run with `opencode run --variant
high|xhigh|max`.</sub>

## GLM-5.2 notes (empty-patch mechanism + a harness leak)

GLM-5.2's per-arm resolved rates are in the harder-band table above. Two things behind
those numbers are worth recording.

**The empty-patch mechanism, per repo.** GLM-5.2's prompt sensitivity is almost entirely
about *whether it commits an edit at all*. Empty-patch counts by arm (out of 48): default 12,
kcbal 9, sharp 5, claude 4, cursor 4, **kcauto 1**. The arms that suppress empties resolve
more, near-monotonically. When GLM-5.2 does commit, it is accurate — e.g. on `default`, 26 of
its 32 non-empty /43 patches resolve (81%); the best arm `cursor` reaches 37/43. Per-repo on
the strongest arms it is excellent on `pydata/xarray`, `astropy` (claude solves 5/5) and
`sympy`, weaker on `django`.

**A latent harness leak this run exposed (and we fixed twice).** GLM-5.2 pip-installs and
runs tests in-solve far more than Kimi, which surfaced a patch-extraction bug:

- The harness sets `PYTHONUSERBASE`/`PIP_CACHE_DIR` *inside* the throwaway workdir (host
  hygiene), so `extract_patch`'s `git add -A` swept the installed `site-packages` (254 MB)
  and pip cache into the patch — 25 MB diffs. First fix: exclude `.pyuserbase`/`.pipcache`.
- But the scaffolded arms then revealed that agents also create their *own* scratch — cursor
  built a `.venv311` (3672 files) + `_pylibs` (a 49 MB diff), sharp made `repro_docs`/`testproj`.
  Blacklisting names is hopeless. **General fix:** `extract_patch` now drops any newly-created
  top-level path that did not exist in the repo at `base_commit` (allowlist from `git ls-tree
  HEAD`), keeping real edits and new source files under existing package dirs.

The Kimi runs read+edited rather than installing, so they never triggered the leak — their
numbers stand. All GLM-5.2 figures above are on patches cleaned by the allowlist rule and
re-graded; the fix is in `swe_bench.py` so future runs extract clean by construction.

## Merged view across both bands

The right metric differs by band, so the merge is faceted, not a naive sum:

- **easy band (n=8):** *fix-correctness* (FAIL_TO_PASS-only — the model's own bug-fix
  tests pass). Strict resolved here is a flat ~2/8 *environmental* floor (HTTPS/timeout
  PASS_TO_PASS tests that no local httpbin can serve — see below), so it carries no model
  signal; fix-correctness is the real measurement.
- **harder band (n=43):** *strict resolved*. Those repos have no network dependence, so
  strict ≈ fix-correctness — directly poolable with the easy-band fix-correctness.

| prompt | easy **K2.6** | easy **K2.7** | hard-43 **K2.6** | hard-43 **K2.7** | **pooled /51 K2.6** | **pooled /51 K2.7** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| default | 6/8 | 6/8 | 16 (37%) | **25 (58%)** | 22 (43%) | **31 (61%)** |
| claude-code | 7/8 | 7/8 | 14 (33%) | 22 (51%) | 21 (41%) | 29 (57%) |
| cursor  | 7/8 | 7/8 | 20 (47%) | 17 (40%) | 27 (53%) | 24 (47%) |
| sharp   | 7/8 | 7/8 | **21 (49%)** | 18 (42%) | **28 (55%)** | 25 (49%) |
| kimi-cline (balanced)   | 7/8 | 7/8 | 18 (42%) | 13 (30%) | 25 (49%) | 20 (39%) |
| kimi-cline (autonomous) | 7/8 | 6/8 | 19 (44%) | 20 (47%) | 26 (51%) | 26 (51%) |

*(pooled = easy fix-correctness + hard strict, out of 8+43 = 51; both terms are fix-correctness.)*

**The easy band adds no discriminative signal.** Every arm sits at 6–7/8, so pooling
just shifts everyone by ~+7. The **pooled ranking is identical to the harder-band
ranking** for both models (K2.7: default > claude-code > kcauto > sharp > cursor > kcbal;
K2.6: sharp > cursor > kcauto > kcbal > default > claude-code). The 48-instance band
drives the entire result; the easy band is confirmatory ballast. (The merged view covers the
two Kimi models; GLM-5.2 ran the harder band only.)

## Easy band (8 `psf/requests`), re-graded clean — and a retraction

The first version of this doc made the easy band the spine and reported a sharp
"two-families" split: hygiene/UI-tuned prompts (`sharp` 2/8, `cursor` 3/8) supposedly
*regressing* far below `default` (6/8), and `claude-code` standing out at a perfect 8/8
on K2.7. **That split does not survive clean grading. We retract it.**

**Why it was wrong.** The `psf/requests` test suite makes real `httpbin` calls in *both*
FAIL_TO_PASS and PASS_TO_PASS tests (`HTTPBIN = os.environ.get('HTTPBIN_URL',
'http://httpbin.org/')`). Arms are graded sequentially, and `httpbin.org` flaked during
the run (503s, `JSONDecodeError`, connection timeouts). So an arm's score partly recorded
*httpbin's uptime during its slot*, not the model's fix. We caught a hint of this at the
time — `k27_kimicline` scored 5/8 raw but was really 8/8 once the three "failures" were
traced to network flake (one was byte-identical to the gold patch) — but underestimated
how much it contaminated *every* arm.

**The fix: deterministic re-grade.** We re-ran the grader against a **local** httpbin
(`kennethreitz/httpbin` on an `--internal` Docker network aliased to `httpbin.org`, env-gated
into the eval containers), so every arm is graded under identical, offline conditions — no
external service, no temporal flake. Two views per arm:

| prompt | strict K2.6 | **fix-correct K2.6** | strict K2.7 | **fix-correct K2.7** |
|---|:---:|:---:|:---:|:---:|
| default | 1/8 | **6/8** | 2/8 | **6/8** |
| claude-code | 2/8 | **7/8** | 2/8 | **7/8** |
| cursor  | 2/8 | **7/8** | 2/8 | **7/8** |
| sharp   | 2/8 | **7/8** | 2/8 | **7/8** |
| kimi-cline (balanced)   | 2/8 | **7/8** | 2/8 | **7/8** |
| kimi-cline (autonomous) | 2/8 | **7/8** | 2/8 | **6/8** |

Two things fall out:

1. **Fix-correctness is uniform 6–7/8 — no family split, no standout.** Under identical
   grading, `sharp` and `cursor` are *not* regressing (7/8, not 2–3/8), and `claude-code`
   is not a standout (7/8, not 8/8). The original 2/8→8/8 spread was overwhelmingly
   httpbin temporal flake during sequential runs.
2. **Strict resolved is an environmental floor (~2/8), not a model measurement.** It's
   pinned down by PASS_TO_PASS tests that fail *uniformly across all 12 arm-runs* because
   no local httpbin can serve them — the counts prove the uniformity:

   | failing PASS_TO_PASS test | count over 12 arm-runs | why |
   |---|:---:|---|
   | `test_mixed_case_scheme_acceptable` | 48 | needs HTTPS |
   | `test_pyopenssl_redirect` | 24 | needs SSL |
   | `test_connect_timeout` | 24 | asserts real connect-*timeout*; internal net refuses instantly |
   | `test_total_timeout_connect` | 24 | same |
   | `test_auth_is_stripped_on_redirect_off_host` | 12 | needs a second host |
   | `test_stream_timeout` | 12 | timeout behavior |

   Every arm loses the same instances to these, so strict resolved on this band measures
   the test harness's network environment, not Kimi. That is why the merged view uses
   fix-correctness for the easy band.

**Net:** on this easy band every prompt is interchangeable (6–7/8) on fix-correctness, and
the old strict numbers are retired. The only honest easy-band statement is "near-ceiling
for all arms, no separation" — which is what the merged view encodes.

## Cost & efficiency (predict-phase)

Grading flakes don't touch the **predict** phase, so the cost numbers from the original
8-instance run stand. `latency` = wall-clock of the opencode run; `tokens` = total
in+out from the isolated session db; `tools` = tool calls. Averaged over the 8 instances
per arm (this run included two extra easy-band-only arms, `codex-coding` and `cline`, kept
here as cost datapoints).

| prompt | model | avg latency | avg tokens | avg tool calls |
|--------|-------|-------------|------------|----------------|
| default      | K2.6 | 95s  | 731k | 25.4 |
| default      | K2.7 | 72s  | 728k | 25.2 |
| sharp        | K2.6 | 87s  | 652k | 24.9 |
| sharp        | K2.7 | 86s  | **530k** | 23.4 |
| cursor       | K2.6 | 149s | 814k | 26.0 |
| cursor       | K2.7 | 254s | 751k | 27.4 |
| codex-coding | K2.6 | 93s  | 517k | 18.8 |
| codex-coding | K2.7 | 158s | 607k | 24.5 |
| claude-code  | K2.6 | 123s | 676k | 22.4 |
| claude-code  | K2.7 | 178s | 575k | 25.6 |
| cline        | K2.6 | 140s | 541k | 25.9 |
| cline        | K2.7 | 295s | 908k | 31.2 |

The table above is the easy-band (n=8) predict cost. The charts below are the
**harder band** — the signal-bearing run, 3 models × 6 prompts — resolved rate plus
the two cost axes:

![Resolved — by prompt × model](charts/bakeoff-resolved.svg)

![Tokens per arm — by prompt × model](charts/bakeoff-tokens.svg)

![Tool calls per instance — by prompt × model](charts/bakeoff-tools.svg)

<sub>Charts: `python3 make_cost_charts.py` (pure-stdlib SVG) from `bake-off-cost.csv`
(harder band, resolved out of 43). Blue = K2.6, orange = K2.7, green = GLM-5.2.</sub>

Grading-independent reads (these don't lean on resolved rate):
- **`codex-coding` and `sharp` are the frugal arms** — fewest tokens/tool-calls (codex
  18.8 calls / 517k tok on K2.6; sharp 530k on K2.7). Terse, plan-first styles cut
  exploration. On the 48-band `sharp` stays the cheapest ($9.9 on K2.7).
- **`cline`/`kimi-cline (autonomous)` are the expensive arms** — verbose, step-enumerating
  styles inflate tokens and tool calls (cline 908k / 31 calls on K2.7; kcauto 64M / 40
  tools / $15 on the 48-band) without a matching resolved-rate gain.
- **Latency is the noisiest axis** (Fireworks queue + network + some eval-VM contention on
  K2.6's early instances); read absolute seconds as directional, token/tool counts as stable.

## What's real vs what's noise

- **The previously-claimed significant result is gone.** The earlier doc ran Fisher exact
  on the easy-band "family split" (`sharp` 6/16 vs `claude-code` 15/16 → p=0.002) and
  called it the part to trust. With the split exposed as a grading artifact, that test was
  fitting noise in httpbin's uptime. Retired.
- **On the easy band, clean grading separates nothing** — 6–7/8 for all six arms, both
  models. The Wilson CIs at n=8 are enormous (6/8 → [0.41, 0.93]); there is nothing to rank.
- **On the harder band, the *Kimi* arm-to-arm gaps are within ~1 standard error.** A 1–3
  instance lead at n=43 (≈ SE of ±3–4 on a ~40–60% rate) is not separable, so the K2.6/K2.7
  prompt rankings are directional only. **The exception is GLM-5.2**, where the
  scaffold-vs-`default` gap is ≈+10/43 (cursor 37 vs default 26) — several SE, a genuinely
  robust effect, driven by the empty-patch collapse from 12 to 1–4.
- **K2.6 ≈ K2.7 on solvability**, differing in failure-mode/cost more than in what they can
  solve — consistent with every other study in this repo.

**Bottom line: trust the direction (scaffolds help the weaker model, hurt the stronger;
no prompt dominates) and the cost ordering; don't rank arms within a band.** A clean ranking
would need pass@k over a larger hard-band sample.

## Compliance, not capability: the attempt-rate decomposition

A resolved instance needs two things: the model must **attempt** an edit (non-empty patch)
*and* the edit must be **correct**. Splitting the score into *attempt rate* (1 − empty) and
*conditional quality* (resolved | attempted) shows the prompt mostly buys the first.

| model | prompt | resolved/48 | empty | attempt % | correct \| attempted |
|---|---|:--:|:--:|:--:|:--:|
| GLM-5.2 | default | 29 | 12 | 75% | 81% |
| GLM-5.2 | sharp | 32 | 5 | 90% | 74% |
| GLM-5.2 | cursor | **40** | 4 | 92% | **91%** |
| GLM-5.2 | kcauto | 38 | 1 | **98%** | 81% |
| GLM-5.2 | kcbal | 30 | 9 | 81% | 77% |
| GLM-5.2 | claude | 39 | 4 | 92% | 89% |
| Opus-4.8-xhigh | cursor | 40 | 3 | 94% | 89% |
| Opus-4.8-xhigh | claude | 40 | 1 | **98%** | 85% |

<sub>Kimi K2.6/K2.7 omitted — their harder-band predict metadata was not retained, so the
split can't be reconstructed without a re-run.</sub>

- **~60% of GLM-5.2's headline gain is just follow-through.** Its best swing, `default`→
  `cursor` (+11 resolved): hold conditional quality at default's 81% and lift only the
  attempt rate 75%→92% — that alone predicts ~36 resolved (**+6.5**); the actual 40 means the
  remaining **+4.5** is better patches (81%→91%). So roughly **60% compliance, 40% quality.**
- **The prompt moves two independent knobs.** `kcauto` makes GLM finish *everything* (98%
  attempt) but writes mediocre patches (81%); `sharp` makes it act (90%) but its *worst*
  patches (74%). "Make the model act" and "make it act well" are separate axes; `cursor` wins
  by maxing both.
- **Opus shows the effect is ceiling-limited.** Opus barely bails (1–3 empty, 94–98%
  attempt) → almost no attempt-rate headroom → the prompt has nothing to move and both arms
  tie at 40. **The size of any prompt effect is set by how much the model bails on its
  default**: GLM bails a lot → large effect; Opus (and K2.7, which scaffolds *hurt*) already
  finish → the prompt can only jiggle quality, sometimes downward.

**The honest mechanism is behavioral, not capability:** the prompt's main job is to stop the
model abandoning the edit loop. The secondary quality component is real but small — and given
the suspiciously high absolute conditional-correct (74–91% on SWE-bench Verified), some of it
is likely the prompt's style interfering more or less with a **memorized** fix rather than
improving reasoning. Read the bake-off as *prompt-induced follow-through on a possibly-
contaminated benchmark*, not coding capability. The decisive test is a post-cutoff run (Caveats).

## Pipeline
- **Predict**: `swe_bench.py` — clone repo@base_commit, run opencode+Kimi on the
  issue, extract `git diff` (excluding test files + `opencode.json`) as the model_patch.
  Custom prompts are seeded as an opencode agent via `--agent-prompt`. Two bring-up bugs
  fixed early: run opencode with `cwd=<workdir>` (else it inherits this repo's `.opencode`
  config and never converges), and an action-forcing prompt line (else the model
  rabbit-holes into reproduction and never edits). `--retries` guards the Fireworks-hang
  class (a hung call → 600s timeout → empty patch).
- **Eval**: official swebench. On the Mac via **colima** with `--vm-type vz --vz-rosetta`
  (runs SWE-bench's x86 images via Rosetta; podman's docker-compat API was unusable); on
  the server via native Docker. `eval_runner.py` runs arms **sequentially** and is the
  driver for the deterministic local-httpbin re-grade (env-gated `SWEBENCH_NETWORK` +
  `SWEBENCH_HTTPBIN_URL` route eval containers to a local `httpbin` so `psf/requests`
  grading no longer depends on a live external service).
- The server run surfaced — and the harness now fixes — three reliability gaps:
  predict-hang retries (`--retries`), a real concurrency cap (`xargs -P`), and confining
  agent `pip` installs to the throwaway workdir (`PYTHONUSERBASE`) so they don't pollute
  the host.

## Caveats (why this isn't the final word)
- **The harder band is n=43, 1 attempt/instance (no pass@k).** Within-model Kimi arm-to-arm
  gaps sit inside one standard error (directional only); the GLM-5.2 scaffold-vs-default gap
  (≈+10/43) is the one that clears it.
- **The easy band is at the ceiling** for every arm on fix-correctness and is network-bound
  on strict grading — it's a control, not a discriminator.
- **Cross-band differences are confounded by environment**: the easy band ran on the Mac
  (bare env, no in-solve `pytest`), the harder band on the server (agents could `pip install`
  + run tests). Only within-band arm-to-arm deltas are clean.
- To actually *rank* prompts you'd want pass@k over ~100+ hard-band instances. The pipeline
  now supports that; it's just (emulated-eval) wall-clock and disk.
- **Contamination is unaddressed — and this is the big one.** SWE-bench Verified is public,
  pre-cutoff, drawn from popular repos these models were almost certainly trained on, and
  SWE-bench memorization is documented. The high conditional-correct rates (see *Compliance,
  not capability*) are consistent with partial retrieval. Nothing here separates "solved"
  from "recalled"; the prompt may be modulating *follow-through on a remembered fix*. A
  post-training-cutoff or private held-out set is required before claiming any prompt effect
  generalizes out-of-sample.

## Repro
```bash
# 1) predict (writes preds_*.jsonl + a preds_*.meta.json sidecar with
#    per-instance duration_s / tokens / tool_calls)
python3 swe_bench.py predict --model k2.7 --repos psf/requests \
    --agent-prompt system-prompts/claude-code/...interactive-cli.oc-adapted.md \
    --out preds_k27.jsonl

# 2) eval (colima running; DOCKER_HOST = colima socket)
python3 eval_runner.py --report-dir eval --arm claude_k27 preds_k27.jsonl

# 2b) deterministic re-grade of the requests band against a LOCAL httpbin
#     (no external service, no temporal flake)
SWEBENCH_NETWORK=swebench-httpbin SWEBENCH_HTTPBIN_URL=http://httpbin-local/ \
    python3 eval_runner.py --report-dir eval_kr --workers 1 --no-flake-reeval \
    --arm claude_k27 preds_k27.jsonl

# 3) aggregate each arm's meta.json into the cost CSV, then re-render the charts
python3 swe_bench.py aggregate --meta preds_k27.meta.json --prompt claude-code
python3 make_cost_charts.py          # bake-off-cost.csv -> charts/bakeoff-*.svg
```

The committed `bake-off-cost.csv` + `charts/*.svg` are the predict-phase snapshot
(the raw `preds_*`/`*.meta.json`/eval reports are gitignored).

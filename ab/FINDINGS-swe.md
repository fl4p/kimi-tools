# SWE-bench Verified: Kimi K2.6 vs K2.7 — system-prompt bake-off

Scored by the **official** `swebench.harness.run_evaluation` — real GitHub issues
with hidden FAIL_TO_PASS / PASS_TO_PASS grading tests. We run opencode+Kimi (via
Fireworks) on each issue, extract the `git diff`, and grade it. The question:
does swapping the agent **system prompt** change how much Kimi can solve, and does
the answer differ between K2.6 and K2.7?

We tested two difficulty bands:
- **harder band** — 48 instances across 8 repos (sympy / scikit-learn / sphinx /
  xarray / matplotlib / astropy / pytest / django), the "15 min–1 h" and "1–4 h"
  bands. This is the signal-bearing run.
- **easy band** — all 8 `psf/requests` instances ("<15 min–1 h", pure-Python). Near
  the ceiling for every arm; useful mainly as a control.

Six prompts in both bands: `default` (opencode's built-in coding agent), `claude-code`,
`cursor`, `sharp` (a tool-hygiene-tuned prompt), and our two `kimi-cline` prompts
(balanced + autonomous).

## TL;DR

1. **The prompt effect flips sign with model strength** (48-instance band). On the
   weaker **K2.6**, scaffolding helps — `sharp`/`cursor`/`kimi-cline` all beat the
   bare `default`. On the stronger **K2.7**, the bare `default` *wins* (25/43, 58%)
   and every custom prompt hurts it. The stronger model does best with the least
   instruction.
2. **No single prompt dominates**, and the deltas are within ~1 standard error. The
   best scaffold depends on the model; on the strongest model, no scaffold beats default.
3. **The easy band can't separate the arms** — under clean grading every prompt lands
   at 6–7/8 fix-correctness. It adds a near-constant offset to the pooled score and
   does not change the ranking.
4. **A third model agrees.** **GLM-5.2** on the default prompt ties the strongest Kimi at
   the top of the harder band (**26/43** vs K2.7's 25/43), at 3–4× fewer model tokens but a
   high empty-patch rate. See **Third model: GLM-5.2**.
5. **A retraction:** an earlier version of this doc reported a dramatic easy-band
   "family split" (`sharp` 2/8, `cursor` 3/8 vs `claude-code` 8/8). That spread was a
   **grading artifact** — the `psf/requests` suite hammers a live `httpbin` service
   that flaked during sequential arm runs. A deterministic re-grade collapses the
   spread to 6–7/8 for all arms. The split is retired; see **Easy band, re-graded**.

## Headline — harder band (8 repos, 48 instances, on a server)

Same opencode+Kimi harness, swapping only the `--agent-prompt`. Run on an x86-64
Linux server with native Docker.

**5 matplotlib instances are excluded** — their prebuilt eval images carry files owned by
a UID beyond the host's rootless-docker subuid range, so the layers won't unpack on this
box (a host constraint, not a model failure). Resolved rates are out of **43**. (Two
sklearn instances each errored for one arm and are conservatively counted as not-resolved.)

| prompt | K2.6 | K2.7 | K2.6 tok/tools/$ | K2.7 tok/tools/$ |
|--------|------|------|------------------|------------------|
| default | 16/43 | **25/43** | 35M / 25 / $8.5 | 41M / 26 / $10.2 |
| sharp   | **21/43** | 18/43 | 42M / 28 / $10.0 | 40M / 26 / $9.9 |
| cursor  | 20/43 | 17/43 | 43M / 28 / $10.8 | 48M / 26 / $11.6 |
| kimi-cline (autonomous) | 19/43 | 20/43 | 64M / 40 / $15.2 | 59M / 31 / $14.1 |
| kimi-cline (balanced)   | 18/43 | 13/43 | 39M / 29 / $9.6 | 52M / 30 / $12.6 |
| claude-code | 14/43 | 22/43 | 42M / 28 / $10.0 | 45M / 29 / $11.2 |

**The prompt effect flips sign with model strength.**

1. **On K2.6 (weaker), scaffolding helps.** `sharp` (21), `cursor` (20), `kcauto` (19) and
   `kcbal` (18) all beat the bare `default` (16); `claude-code` (14) is the only arm below it.
2. **On K2.7 (stronger), the bare `default` wins (25/43, 58%)** and every custom prompt
   *hurts* it — `claude-code` 22, `kcauto` 20, `sharp` 18, `cursor` 17, `kcbal` 13. The
   stronger model does best with the least instruction; heavy scaffolds constrain it.
3. **`sharp` is the efficiency standout** — top arm on K2.6 (21) and the cheapest, most
   tool-frugal of all (40M tokens / 26 tools / $9.9 on K2.7); `kcauto` runs hottest
   (64M / 40 tools / $15) for middling resolve.

**This revises a 16-instance pilot.** An earlier 16-instance cut of this band put
`claude-code` on top (28/32) and read it as "the most consistent winner." At 48 instances
that did **not** hold: `claude-code` is *worst* on K2.6 (14) and second on K2.7 (22), while
`default·K2.7` leads. The small-N result was noise — at n=16 a 1–3 instance lead sits inside
one standard error. The honest read: **no single prompt dominates; the best scaffold depends
on the model, and on the strongest model no scaffold beats the default.**

## Third model: GLM-5.2 (default prompt)

To check whether the default-prompt result generalizes beyond Kimi, we added a third
model — **GLM-5.2** (also via Fireworks) — on the **default prompt only**, same 48-instance
harder band. Re-run on a fresh x86-64 box with native Docker + in-solve `pip`/`pytest` (the
same environment *kind* as the Kimi runs, not the literal same machine). That box has root
Docker, so the 5 matplotlib instances grade here and are reported separately to keep the
/43 figure apples-to-apples with the Kimi columns.

| model (default prompt) | resolved /43 | total tokens | avg tools/inst |
|---|:---:|:---:|:---:|
| K2.6        | 16/43 (37%) | 35M | 25 |
| K2.7        | 25/43 (58%) | 41M | 26 |
| **GLM-5.2** | **26/43 (60%)** | **~12M** | **11** |

**GLM-5.2 on the default prompt ties the strongest Kimi at the top** — 26/43 vs K2.7's
25/43 (a 1-instance gap, statistically indistinguishable), both well above K2.6's 16/43.
Per-repo it is strong on `pydata/xarray` (7/7), `sympy` (5/8) and `sklearn` (4/8), weak on
`django` (1/4) and `sphinx` (3/7). On the 5 matplotlib instances (bonus, root-docker only)
it resolves 3/5 — 29/48 overall.

Two behavioral notes matter more than the headline number:

1. **High empty-patch rate.** GLM-5.2 returned **12/48 empty patches** — it often ended a
   trajectory without committing any source edit. But when it *did* commit it was accurate:
   **26 of its 32 non-empty /43 patches resolved (81%)**. High-precision, lower-recall — the
   opposite of a model that edits eagerly but sloppily.
2. **Terse trajectory, heavy environment use.** ~244k tokens and only ~11 tool calls per
   instance — **3–4× fewer model tokens than the Kimi default arms** — yet ~457s/instance,
   because it leaned on in-solve `pip install` + `pytest` over model reasoning. (Token/tool
   counts are harness-reported via opencode's session db.)

**A harness bug this run exposed (and we fixed).** GLM's aggressive installing surfaced a
latent leak: the harness puts `PYTHONUSERBASE` and `PIP_CACHE_DIR` *inside* the throwaway
workdir (for host hygiene), but `extract_patch`'s `git add -A` then swept the entire
installed `site-packages` (254 MB) and pip cache into the model patch — bloating GLM's raw
diffs to 25 MB. The Kimi runs were unaffected (they read+edited rather than installing), so
their numbers stand. We (a) re-derived GLM's patches by stripping `.pyuserbase`/`.pipcache`
(the real edits were intact underneath) and (b) fixed `extract_patch` to exclude both dirs
going forward. The 26/43 above is on the cleaned, correctly-graded patches.

This extends the default-prompt story: **the bare default prompt is competitive-to-best
across all three models, and the two strongest (K2.7, GLM-5.2) sit together at the top on
it** — reinforcing that on capable models, scaffolding is not where the wins are.

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
drives the entire result; the easy band is confirmatory ballast — and the sign-flip with
model strength survives the merge intact.

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

![Avg latency per instance, by prompt × model](charts/cost-latency.svg)

![Avg tokens per instance, by prompt × model](charts/cost-tokens.svg)

![Avg tool calls per instance, by prompt × model](charts/cost-tools.svg)

<sub>Charts: `python3 make_cost_charts.py` (pure-stdlib SVG), rendered from
`bake-off-cost.csv` — the benchmark's own output via `swe_bench.py aggregate`. Blue =
K2.6, orange = K2.7.</sub>

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
- **On the harder band, the arm-to-arm gaps are within ~1 standard error.** A 1–3 instance
  lead at n=43 (≈ SE of ±3–4 on a ~40–60% rate) is not separable. What *is* robust is the
  *direction*: the sign-flip with model strength is consistent across every scaffold (all
  help K2.6 except claude-code; all hurt K2.7), and it's the same story in the pooled /51.
- **K2.6 ≈ K2.7 on solvability**, differing in failure-mode/cost more than in what they can
  solve — consistent with every other study in this repo.

**Bottom line: trust the direction (scaffolds help the weaker model, hurt the stronger;
no prompt dominates) and the cost ordering; don't rank arms within a band.** A clean ranking
would need pass@k over a larger hard-band sample.

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
- **The harder band is n=43, 1 attempt/instance (no pass@k).** Arm-to-arm gaps sit inside
  one standard error; only the cross-arm *direction* (the sign-flip) is robust.
- **The easy band is at the ceiling** for every arm on fix-correctness and is network-bound
  on strict grading — it's a control, not a discriminator.
- **Cross-band differences are confounded by environment**: the easy band ran on the Mac
  (bare env, no in-solve `pytest`), the harder band on the server (agents could `pip install`
  + run tests). Only within-band arm-to-arm deltas are clean.
- To actually *rank* prompts you'd want pass@k over ~100+ hard-band instances. The pipeline
  now supports that; it's just (emulated-eval) wall-clock and disk.

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
python3 make_cost_charts.py          # bake-off-cost.csv -> charts/cost-*.svg
```

The committed `bake-off-cost.csv` + `charts/*.svg` are the predict-phase snapshot
(the raw `preds_*`/`*.meta.json`/eval reports are gitignored).

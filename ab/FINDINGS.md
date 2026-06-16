# Findings — does the Kimi/cline system-prompt rewrite matter?

**Run:** 2026-06-15. 5 arms × 4 scenarios × 3 trials = 60 live `cline` runs on
**Fireworks `accounts/fireworks/models/kimi-k2p7-code`** (Kimi K2.7), via the
harness in this directory. Raw data: `results.json`. Significance:
`stats.py` (paired McNemar + bootstrap; authored by a sibling agent, see Credits).

## TL;DR

The rewrite is **not cosmetic — but it earns its keep on tool _selection_, not
on the failure it was originally written to fix.**

- **The shipped (`current`) prompt eliminates discouraged-tool use.** Kimi reached
  for the array/overlap tools (`editor`, `run_commands`, `read_files`) in **67% of
  control trials and 0% of `current` trials** — McNemar exact **p = 0.008**, and
  the discouraged-tool count drops **−1.75/trial [95% CI −2.67, −0.92]**. The
  autonomous `cur-auto` is identical (p = 0.008). This is the real, significant win.
- **The win is the v00→current _rewrite_, not v00.** v00 only halved the count
  (1.75→0.83) and did **not** significantly move the _rate_ (67%→50%, p = 0.50).
  `current` beats `v00` head-to-head (p = 0.031).
- **The empty-args `run_commands` loop — the prompts' original target — never
  fired.** `empty_args = 0` on **every** arm including control. On K2.7/Fireworks
  these tasks don't trigger it, so this run **cannot** credit the prompt for fixing
  it. Consistent with the v00 README's thesis that the loop is a tool-call-layer
  problem, curable only at the harness.
- **Task success is saturated** (100% pass@k everywhere) and **duplicate calls are
  prompt-independent** — neither discriminates.

## Headline table (raw counts, summed over 12 trials/arm)

```
arm        pass%  pass^k  tools  empty  dup  disc  mistk   avg_s
control     100%   100%     39      0    6    21      0    22.6s
v00         100%   100%     60      0    5    10      0    43.1s
current     100%   100%     59      0    6     0      0    44.0s
v00-auto     92%    75%     59      0    6     9      0    40.3s
cur-auto    100%   100%     51      0    6     0      0    33.8s
```

## Significance (`stats.py`, paired by scenario,trial, n=12 pairs)

| comparison | metric | base→arm | test | verdict |
|---|---|---|---|---|
| control vs **current** | used_discouraged | 67% → **0%** | McNemar b=8,c=0, **p=0.008** | **significant** |
| control vs current | discouraged count | 1.75 → 0.00 | bootstrap −1.75 [−2.67, −0.92] | **better** |
| control vs **cur-auto** | used_discouraged | 67% → **0%** | **p=0.008** | **significant** |
| v00 vs **current** | used_discouraged | 50% → 0% | **p=0.031** | significant* |
| control vs **v00** | used_discouraged | 67% → 50% | b=2,c=0, p=0.50 | **ns** (count moved, rate didn't) |
| any | had_duplicate | ~50% | p≈1.0 | **ns** (no prompt effect) |
| any | had_empty_arg | 0% | untestable | never fired |
| any | passed | 100% | p=1.0 | saturated |

\* p=0.031 would not survive strict multiple-comparison correction across the 6
comparisons; the **p=0.008 headline + every tailored arm landing at exactly 0**
is what carries the conclusion.

## Why it works — per-scenario mechanism

Discouraged-tool count by arm × scenario (sum of 3 trials):

```
              create-file  edit-file  multi-file  inspect-then-edit   TOT
control            5           0          11           5             21
v00                4           0           6           0             10
current            0           0           0           0              0
v00-auto           3           0           6           0              9
cur-auto           0           0           0           0              0
```

The signal is concentrated in the **file-creation** tasks (`multi-file`,
`create-file`). Control reaches for cline's `editor` tool to write new files;
`current` eliminates it because it adds an explicit instruction v00 lacked: *create
new files with a `Bash` heredoc; `Edit` only changes files that already exist.*
That single piece of guidance is what drives `editor` use to zero. `edit-file`
never triggers discouraged tools in any arm (editing an existing file maps cleanly
to `Edit`), so it doesn't discriminate.

## What did NOT move (and why)

- **Duplicate calls are scenario-structural, not a prompt failure.** `edit-file`
  and `inspect-then-edit` each produce ~3 duplicate calls in *every* arm including
  `current` — a benign read-back/verify pattern, not the pathological loop. The
  prompt has no leverage here, nor should it.
- **`empty_args = 0` everywhere.** The run_commands empty-array loop did not occur
  on this model/endpoint/task set, even with no system prompt. Untestable here →
  the prompt's original purpose remains **unmeasured**, not disproven.

## Cost of the win — tool calls & latency

`current` is **slower and chattier**: +1.67 tool calls/trial vs control
([+0.83, +2.50]). It trades `editor` (one write) for `Read`/`Bash`/`Edit`
sequences (read-verify-edit). For tool-hygiene/cost on a weak caller that's
arguably good; if latency matters it's a real tradeoff.

| arm | tool calls (total) | calls/trial | total latency | avg latency |
|---|---|---|---|---|
| control | 39 | 3.2 | 271.4 s | 22.6 s |
| v00 | 60 | 5.0 | 516.9 s | 43.1 s |
| current | 59 | 4.9 | 527.7 s | 44.0 s |
| v00-auto | 59 | 4.9 | 484.1 s | 40.3 s |
| cur-auto | 51 | 4.2 | 405.5 s | 33.8 s |

Control is ~half the wall-clock of the tailored arms because it does ~⅔ the tool
calls (one `editor` write vs read-verify-edit). Whole 60-run sweep: **36.8 min**.
(These are the harness's wall-clock timings — `tool_calls` is the scraped count and
`duration_s` the subprocess latency. The harness now *also* captures cline's own
`iterations` + `durationMs` per trial (`iter`/`tot_s` columns), but those were added
after this run, so re-run to populate them authoritatively.)

## One reliability blemish

`v00-auto` failed `multi-file` trial 2 (missing `index.html`) → 92% pass, 75%
pass^k. The autonomous v00 prompt dropped one of two required files once. `cur-auto`
did not. n is tiny; flagged, not concluded.

## Limitations

- **n = 12 pairs/arm**; trial index is a *nominal* pairing (controls for scenario,
  not run-to-run seed). Single model, single endpoint (K2.7/Fireworks), 4 easy
  file tasks.
- **Empty-args loop untested** — the headline failure mode never triggered. To test
  the prompt's original purpose, harder/longer tasks (or an older Kimi / different
  endpoint) are needed that actually provoke it.
- Multiple comparisons not corrected beyond the note above.

## Reproduce

```bash
cd prompts/system/kimi-cline-tools/ab
python3 ab_bench.py --self-test          # scraper logic
python3 ab_bench.py --trials 3 --out results.json   # the live run (defaults: Fireworks/K2.7)
python3 stats.py results.json            # significance
```

## Credits

Two agents over the `bench` channel: `vibe-host` built `ab_bench.py` + scenarios +
the run; `vibe-claude-8rif` independently authored `stats.py` (McNemar + paired
bootstrap) reading `results.json` only. The "passed will saturate / signal lives in
used_discouraged" framing and the empty-args caveat were agreed on-channel before
the numbers came in.

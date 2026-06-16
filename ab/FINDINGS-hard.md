# Hard-scenario study: can a benchmark show K2.7 > K2.6?

**Question:** which benchmark shows Kimi K2.7 superior to K2.6?
**Answer (this study):** none of ours does — *not even on purpose-built hard tasks.*

## Setup
- Harness: `ab_opencode.py` (parallel, clean toolset — no cline tool-schema bloat
  to confound the model comparison).
- Prompt held constant (opencode default) for both models → the **only** variable
  is the model.
- 4 hard, verifiable scenarios (`scenarios-hard.json`), each validated up front so
  a correct solution passes and the stub/buggy version fails:
  - `expr-eval` — recursive-descent calculator: precedence, parens, unary minus
    (`2*-3`, `-2*-3` are the traps).
  - `csv-parse` — RFC4180 quoted fields with `""` escaping.
  - `multi-bug-ledger` — **3 independent bugs**, all must be fixed (compounding).
  - `refactor-flat-matrix` — change internal representation, keep tests green
    (`_rows`→flat `_data`, structurally enforced via expect_absent/contains).
- **8 trials per scenario** so `pass^k` has real resolution. 64 runs total.

## Result

```
scenario                  K2.6        K2.7
expr-eval                  8/8         7/8*      (* the one miss = 330s TIMEOUT, tools=0, tok=0)
csv-parse                  8/8         8/8
multi-bug-ledger           8/8         8/8
refactor-flat-matrix       8/8         8/8
TOTAL                    32/32       31/32

                         K2.6        K2.7
accuracy                 100%        97% (100% on capability; the 1 miss is infra)
avg latency             27.7s       44.6s     <- K2.7 ~60% SLOWER
tokens / trial          ~44.8k      ~39.8k    <- K2.7 ~11% fewer
cost (32 trials)         $0.79       $0.63     <- K2.7 ~20% cheaper
```

The single K2.7 "failure" was a **330s endpoint timeout** (zero tools, zero tokens
emitted) — an infra hang, not a wrong answer. On capability terms **both models
solve all four hard tasks 100% of the time.**

## Interpretation
- **No accuracy gap exists at this task difficulty.** Tasks that genuinely stress
  precedence parsing, quote-escaping, multi-bug compounding, and a keep-green
  refactor still top out at 100% for *both* models. The benchmark saturates before
  it can rank them.
- On the non-saturated axes, the picture is **mixed, and not in K2.7's favor on
  speed**: K2.7 is markedly slower (consistent with every prior study here), but
  modestly more token-efficient and cheaper per task.
- So the only dimension on which you can currently call K2.7 "better" is
  **token-efficiency / cost per solved task** — *not* accuracy and *not* latency.

## What it would actually take to show a K2.7 accuracy win
Our self-contained, stdlib-only scenarios cap out below the difficulty where these
two models diverge. To open an accuracy gap you need tasks where K2.6 itself drops
below 100%:
- An established capability benchmark with a difficulty gradient and public
  K2.6/K2.7 numbers: **SWE-bench Verified**, **Aider polyglot**, or **Terminal-Bench**.
- That's a different harness (real repos, real test suites, larger context) — a
  bigger lift than this toy-scenario A/B, but it's the only thing that can answer
  "is K2.7 a better *coder*" rather than "is K2.7 cleaner on easy tasks."

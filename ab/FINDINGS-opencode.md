# Findings — opencode + Kimi, custom prompt vs default (K2.6 vs K2.7)

**Run:** 2026-06-15. 2×2 = {K2.6, K2.7} × {opencode default prompt, custom
`sharp.md`}, 4 scenarios × 3 trials = **48 runs**, executed
**in parallel** (concurrency 4, ~4 min wall-clock). Harness: `ab_opencode.py`.
Raw: `oc_results.json`. Companion to the cline study in `FINDINGS.md`.

## How this differs from the cline study

- **opencode has no `--system` flag.** A custom system prompt is delivered via a
  custom *agent* — the harness writes a per-workdir `opencode.json` defining agent
  `kimi-sys` whose prompt = `{file:sharp.md}`, run with `--agent`.
- **opencode's toolset is already clean** (`write`/`edit`/`read`/`bash`, no
  `run_commands`/`editor`/`read_files` overlaps). The cline headline metric
  (eliminating discouraged tools) **has no analog** — there's nothing to eliminate.
  So this measures **task success + efficiency**: tool calls, latency, tokens, cost.

## TL;DR — the same prompt pulls the two models in opposite directions

The custom prompt is **not neutral**, but its effect is **model-dependent**:

- **K2.6 + custom → tighter & cheaper, slightly less reliable.** Fewer tool calls
  (multi-file 1.7 vs 3.0/trial), −18% tokens (17.4k vs 21.1k/trial), −27% cost — but
  it dropped `index.html` once (**92% pass, 75% pass^k**). Conciseness bought
  efficiency at a small reliability cost.
- **K2.7 + custom → more thorough, pricier, fully reliable.** *More* tool calls
  (multi-file 3.0 vs 2.0, inspect 5.7 vs 3.7), **+27% tokens** (24.9k vs 19.6k/trial),
  slower (13.4s vs 10.6s) — but **100% pass/pass^k**. The same "be thorough, verify"
  framing makes K2.7 do extra read-verify work.

So "does the custom prompt help?" has no single answer: it **compresses K2.6 and
expands K2.7.** A prompt tuned on one Kimi version should not be assumed to transfer.

## Table

```
arm            trials  pass%  pass@k  pass^k  tools  tc/tr  dup   tokens    cost$   avg_s    tot_s
k2.6-default       12   100%    100%    100%     32    2.7    4   253750   0.1398    6.5s    78.4s
k2.6-custom        12    92%    100%     75%     27    2.2    4   208481   0.1011    6.5s    78.2s
k2.7-default       12   100%    100%    100%     29    2.4    6   235760   0.1297   10.6s   127.7s
k2.7-custom        12   100%    100%    100%     38    3.2    5   299127   0.1188   13.4s   160.5s
```

Avg tool calls/trial by scenario (the interaction is concentrated in multi-step tasks):

```
                 create   edit   multi  inspect
k2.6-default       1.0    2.7     3.0     4.0
k2.6-custom        1.0    2.3     1.7     4.0     <- custom compresses multi-file
k2.7-default       1.0    3.0     2.0     3.7
k2.7-custom        1.0    3.0     3.0     5.7     <- custom expands multi/inspect
```

## Secondary observations

- **Per-call the custom prompt is shorter** (smoke: ~760 fewer tokens on the trivial
  create-file task, both models). On harder tasks that saving is swamped by the
  *number-of-calls* effect, which dominates total tokens/cost — and flips sign by model.
- **K2.7 is ~2× slower than K2.6** per call (10–13s vs 6.5s) regardless of prompt.
- **Duplicates (4–6/arm) are scenario-structural**, prompt-independent — same as cline.
- **Cost is tiny**: ~$0.01/task; the whole 48-run sweep ≈ $0.49.

## Limitations

- n = 12/arm; **no significance test** run here (metrics are mostly continuous
  tokens/cost → would want bootstrap CIs, not McNemar). Treat the K2.6-vs-K2.7
  divergence as a strong directional signal, not a p-value.
- Single endpoint (Fireworks), 4 easy file tasks. The one K2.6-custom failure is
  n=1 — flagged, not concluded.
- Token/cost include cache effects (opencode reports cached-read pricing); the K2.7
  "more tokens but barely-lower cost" line reflects caching, read with care.

## Reproduce

```bash
cd prompts/system/kimi-cline-tools/ab
python3 ab_opencode.py --self-test                       # parser vs captured sample
python3 ab_opencode.py --trials 3 --concurrency 4 --out oc_results.json
```

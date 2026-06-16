# Kimi/cline system-prompt A/B harness

Answers one question: **does the system-prompt rewrite actually change Kimi's
behaviour, or is it cosmetic?**

It runs the real `cline` CLI over a few file-editing scenarios under several
**arms** (different `-s/--system` prompt files + a no-override control), repeats
each K times, and reports per arm:

- **task success** — `pass@k` (any trial passed) and `pass^k` (all trials passed)
- **tool hygiene** — empty-arg calls, array-shaped/discouraged tools
  (`run_commands`, `read_files`, …), duplicate calls, and "max consecutive
  mistakes" exits. These are the failure modes the prompt rewrite is meant to
  suppress.

The decision rule:

- hygiene columns **identical** across arms → the wording is cosmetic, and the
  v00 README's thesis holds ("the empty-args loop is a tool-call-layer failure
  *below* the model — more prompt text can't fix it").
- `current` < `v00` < `default` on empty/dup/mistk → the verbose per-tool docs
  are earning their length.

## Files

| File | What |
|------|------|
| `ab_bench.py` | The cline harness (stdlib only — no pip installs). |
| `ab_opencode.py` | Sibling harness for **opencode** (2×2: {K2.6,K2.7} × {default,custom prompt}). |
| `ab_pi.py` | Sibling harness for **pi** (`@earendil-works/pi-coding-agent`): default vs custom system prompt. |
| `scenarios.json` | Vendored task set (mirrors cline's smoke scenarios + one multi-step). |
| `fixtures/*.jsonl` | Synthetic/captured logs used by `--self-test` and `--dry-run`. |

### pi harness (`ab_pi.py`)

Same scenarios, different harness. pi's default active toolset is clean (read /
bash / edit / write — grep/find/ls are off by default), so like opencode there's
no discouraged-tool/empty-array metric; it measures **task success + efficiency**
(tool calls, dups, tool errors, turns, tokens, cost, latency). Notes:

- pi has a real `--system-prompt` flag that **replaces** the built-in prompt, so
  the custom arm just passes the prompt file's *contents* (no custom-agent dance).
  Omit it = pi's default prompt (control). Mirrors cline's `-s`.
- pi has **no `--cwd`/`--dir`**: each trial spawns pi with `cwd=<temp workdir>`.
- pi auto-discovers extensions/skills/prompt-templates/context files; the harness
  disables them by default (`-ne -ns -np -nc --no-session`) for a clean comparison.
  Pass `--with-discovery` to keep pi's full environment.
- pi has **no built-in `fireworks` provider**, but one is now configured in
  `~/.pi/agent/models.json` (openai-completions baseUrl + `kimi-k2p7-code` /
  `kimi-k2p6`, same key cline uses), so `--provider fireworks --model
  accounts/fireworks/models/kimi-k2p7-code` runs against the **same model as
  `ab_bench.py`/`ab_opencode.py`** (apples-to-apples). Alternatives pi already
  knows: `--provider together --model moonshotai/Kimi-K2-Instruct`,
  `--provider openrouter --model moonshotai/kimi-k2`. With no flags, pi uses its
  configured default. See the `ab_pi.py` docstring for the models.json snippet.
- **`cost$` is 0 for custom providers** (fireworks/scaleway) — pi only fills
  `usage.cost` for providers with a built-in pricing table. Use the `tokens`
  column as the efficiency/cost proxy (it *is* populated), as `ab_bench.py` does.

```bash
python3 ab_pi.py --self-test                                   # parser vs fixture, no API
python3 ab_pi.py --only create-file --trials 1 \
    --provider fireworks --model accounts/fireworks/models/kimi-k2p7-code   # smoke
python3 ab_pi.py --provider fireworks --model accounts/fireworks/models/kimi-k2p7-code \
    --trials 3 --out pi_results.json                           # full default-vs-custom A/B
```

It does **not** modify the `cline/` checkout (that's a separate, untracked git
repo here — edits there would be wiped on its next pull). Self-contained.

## Run it

```bash
cd prompts/system/kimi-cline-tools/ab

# 0) No API, no cline — prove the scraper + pipeline work:
python3 ab_bench.py --self-test     # validates tool-call detection vs fixtures
python3 ab_bench.py --dry-run       # full pipeline + table on MOCK fixture logs

# 1) Full A/B (defaults to Fireworks + Kimi K2.7, key read from cline's config):
python3 ab_bench.py --trials 3 --out results.json

# faster sweep: fewer scenarios / trials
python3 ab_bench.py --only create-file,edit-file --trials 1
```

Defaults: provider `fireworks`, model `accounts/fireworks/models/kimi-k2p7-code`
(cline already stores the Fireworks API key, so no `--key` needed). Override with
`--provider/--model/--key/--bin` or `--data-dir` for an isolated cline config.

Default arms (5): `default` (no `--system`), `v00` + `current` (the standard
prompts), and `v00-auto` + `cur-auto` (the autonomous prompts). Override/add with
`--arm name=/abs/path.md` (repeatable; `name=NONE` = a no-override control), e.g.
to compare just the two current prompts against the default:

```bash
python3 ab_bench.py \
  --arm default=NONE \
  --arm current=$PWD/../system-prompts/kimi-cline/kimi.system-prompt.md \
  --arm cur-auto=$PWD/../system-prompts/kimi-cline/kimi-autonomous.system-prompt.md
```

## Prerequisites for live runs

- `cline` on `PATH` (or `--bin /path/to/cline`). Verified flags in use:
  `-s/--system`, `-m`, `-P`, `-k`, `-t`, `--cwd`, `--json`, `--auto-approve`,
  `--retries`, `--data-dir`.
- **A working Kimi endpoint.** Either:
  - run `cline auth` once into an isolated dir and pass `--data-dir <dir>`, or
  - pass `--provider/--model/--key` here.
  For an OpenAI-compatible Kimi endpoint you usually also need a **base URL**,
  which has no CLI flag — set it via `cline auth` (interactive) or the provider
  env cline reads. Confirm with `cline -m <model> "say hi"` before benchmarking.
- Your last `benchmark_results.json` showed Novita = `NOT_ENOUGH_BALANCE`; only
  Fireworks/Together completed (and those were speed-only). Make sure whichever
  key you use here is funded and tool-calling capable.

## Schema / tuning

The scraper parses cline's `--json` stream and flags tool calls that look like
the known Kimi failures. The real schema has been **confirmed against live
Fireworks/Kimi logs**: cline nests each tool call under an `agent_event`
message's `event` object (`{"type":"agent_event","event":{"name":"editor",
"input":{…}}}`), and the recursive walker finds it. `fixtures/real_schema.jsonl`
+ the `real.*` checks in `--self-test` lock this in.

If cline later changes its `--json` format and the table prints the `regex
fallback was used` note (or `tools=0` on a run that clearly used tools), re-run
with `--save-logs ./logs`, inspect a `logs/*.stdout.json`, and adjust
**`NAME_KEYS`** / **`ARG_KEYS`** / the `type` tags in `_looks_like_tool_call()`
near the top of `ab_bench.py`, then re-run `--self-test`.

`DISCOURAGED_TOOLS` and `ARRAY_ARG_KEYS` (the run_commands/read_files/empty-array
signals) come straight from the v00 README's findings and the cline tool
constants; they shouldn't need tuning unless the toolset changes.

## Reading the table

```
arm      trials pass% pass@k pass^k tools empty dup disc mistk  bad%  avg_s
default      8  100%   100%   100%    40    24   8   24    8   80%   0.0s
current      8  100%   100%   100%    32     0   0    0    0    0%   0.0s
```

- `pass@k`/`pass^k` — did the task get done, reliably?
- `empty` (empty-arg calls), `dup` (identical repeated calls), `disc`
  (discouraged/array tools), `mistk` (runs that died hitting `--retries`) —
  **lower is better**; this is where a good prompt should show up.
- `bad%` = (empty + dup) / tool_calls.

If `pass@k` is high everywhere but `empty/dup/mistk` drop from `default`→`current`,
the prompt isn't changing *whether* Kimi succeeds so much as *how cleanly* (fewer
wasted turns / cheaper runs) — still a real, measurable win. If nothing moves,
you have evidence the fix belongs in the harness, not the prompt.

# Kimi (K2.7) system prompts for the cline harness

Two `--system` override prompts tuned for **Kimi K2.7** running coding tasks in
the cline CLI. Both are self-contained (no `{{PLACEHOLDER}}` tokens), so they
work directly as overrides — cline returns a `--system` file verbatim and does
not substitute placeholders or inject rules/metadata.

| File | Use |
|------|-----|
| [`kimi.system-prompt.md`](kimi.system-prompt.md) | **Balanced default.** Decisive and proactive, but asks when genuinely blocked. Numeric (3+ action) planning trigger. |
| [`kimi-autonomous.system-prompt.md`](kimi-autonomous.system-prompt.md) | **Autonomous.** Dials autonomy up per [`../cline/autonomous.system-prompt.md`](../cline/autonomous.system-prompt.md): decide-and-proceed, never ask for permission on reversible steps, verify-before-done, only stop when truly blocked. |

`*.oc-adapted.md` variants of each are the same prompts retargeted to
**opencode**'s toolset (`bash/read/edit/write/grep/glob`, camelCase params) —
that's the form the SWE-bench bake-off runs (see the [root README](../../README.md)).

```bash
cline --system system-prompts/kimi-cline/kimi.system-prompt.md
cline --system system-prompts/kimi-cline/kimi-autonomous.system-prompt.md
```

## Why these exist

cline classifies `kimi-k2` as a next-gen model and the VS Code extension would
hand it the [`../cline/nextgen/`](../cline/nextgen/) variant. But the CLI
launcher injects `--system`, which **replaces** that variant selection. Kimi
then gets the CLI's default headless toolset — including the array-shaped
`run_commands` tool, which Kimi (a weak tool caller) calls with an empty
`{commands: []}`, gets `[]` back, and loops.

These prompts fix that by steering Kimi to the **single-value, claude-compat
tools** (`Bash`, `Read`, `Edit`, `search_codebase`, `ask_question`, `Monitor`,
`PushNotification`, `TaskStop`, `TaskList`) and documenting each one in Kimi's
verbose house style (required params → failure mode → recovery → worked
example). The harness still injects the real tool *schemas*; this prompt's job
is to make Kimi choose and shape the calls correctly.

## What they draw on

- [`../cline/nextgen/native-next-gen.system-prompt.md`](../cline/nextgen/native-next-gen.system-prompt.md) — the cline identity and the "schemas delivered separately" model.
- [`../cline/autonomous.system-prompt.md`](../cline/autonomous.system-prompt.md) — the autonomy stance (the autonomous variant leans on it directly).
- [`../sharp.md`](../sharp.md) — small-sharp-toolset framing, git rules, `AGENTS.md`/`CLAUDE.md` honoring, context-management note.
- [`../kimi/desktop-3.0.19/desktop-AGENTS.md`](../kimi/desktop-3.0.19/desktop-AGENTS.md) — the untrusted-data / refuse-vs-confirm security layer.
- [`../kimi/ok-computer.md`](../kimi/ok-computer.md) — Kimi's voice/cadence (style reference only; we do **not** advertise tools Kimi lacks).

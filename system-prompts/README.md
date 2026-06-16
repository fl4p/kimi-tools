# System prompts

Every prompt the [bake-off](../README.md) runs lives here — except `default`,
which is opencode's own built-in coding prompt (not vendored).

## Adapted to opencode's toolset

The non-default prompts were each written for a *different* harness, so before
running them we **adapted them to opencode's toolset** — remapping their tool
references to opencode's `bash` / `read` / `edit` / `write` / `grep` / `glob` and
the camelCase params (`filePath`, `oldString` / `newString`, …). Wording and
stance are kept verbatim; only the tool names and call shapes change.

The adapted copy sits next to its raw extract as a `*.oc-adapted.md` file, and
that adapted copy is what the bake-off actually runs:

| arm | folder | raw extract | run by the bake-off |
|-----|--------|-------------|---------------------|
| claude-code  | `claude-code/2.1.178/` | `interactive-cli.system-prompt.md` | `interactive-cli.oc-adapted.md` |
| codex-coding | `codex/3.0.139/` | `gpt-5-codex.coding-agent.base_instructions.md` | `gpt-5-codex.coding-agent.oc-adapted.md` |
| cursor       | `cursor/` | `cursor.asgeirtj.md` | `cursor.oc-adapted.md` |
| kimi-cline   | `kimi-cline/` | `kimi*.system-prompt.md` | `kimi*.system-prompt.oc-adapted.md` |
| cline        | `cline/nextgen/` | `native-next-gen.system-prompt.md` | run as authored |
| sharp        | `sharp.md` | — | run as authored |

Two arms have no separate `*.oc-adapted.md`:

- **`cline`** is run as cline's *unmodified* `native-next-gen` prompt on purpose —
  it's the baseline. Our adapted take on it is the [`kimi-cline/`](kimi-cline/)
  pair (and its `*.oc-adapted.md` ports).
- **`sharp.md`** is a single self-contained "small sharp toolset" prompt with no
  harness-specific tool names to remap.

## Also here (reference only)

- [`kimi/`](kimi/) — Kimi's own `desktop-AGENTS.md` (security layer) and
  `ok-computer.md` (voice/cadence reference).
- `codex/3.0.139/` keeps the other gpt-5.x `base_instructions` variants for
  reference; only the codex coding-agent prompt is a bake-off arm.

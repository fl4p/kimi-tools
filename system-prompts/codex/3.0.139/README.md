<!-- Extracted from the OpenAI Codex CLI binary for research. The repo
maintainer does not claim copyright. -->

# Codex CLI 0.139.0 — extracted agent system prompts

Pulled from the standalone Codex binary
(`~/.codex/packages/standalone/releases/0.139.0-aarch64-apple-darwin/bin/codex`).
Relevant because **Kimi Desktop 3.0.19 delegates coding to Codex by default**
(`gpt-5.2-codex`, see `../../kimi/desktop-3.0.19/`) — so this is the real
system prompt behind "Kimi coding," not anything Kimi-authored.

## Why these files
Codex stores each model profile's system prompt **embedded in the binary** as a
JSON string field (`base_instructions` = fully rendered; `instructions_template`
= same text with a `{{ personality }}` placeholder). They are not on disk as
`.md`. Extraction: locate the JSON string value in the binary, scan
escape-aware to the closing quote, `json.loads` to de-escape. (Plain `strings`
truncates them — the prompts contain non-ASCII like `…` and `—`.)

## Files (one per model profile this 0.139.0 binary ships)

| File | Model profile | Notes |
|------|---------------|-------|
| `gpt-5-codex.coding-agent.base_instructions.md` | the **`-codex` coding family** (gpt-5.2/5.3-codex) | **This is the one Kimi's default coding agent uses.** Coding-specialized: `apply_patch`, `rg`, parallel reads, dirty-worktree rules, code-review mindset. |
| `gpt-5.5.general-agent.base_instructions.md` | gpt-5.5 (general) | Longer, general-purpose assistant (adds Engineering judgment, Frontend/Design guidance). |
| `gpt-5.5.general-agent.instructions_template.md` | gpt-5.5 | Same, with the literal `{{ personality }}` placeholder un-rendered. |
| `gpt-5.4.base_instructions.md` | gpt-5.4 | |
| `gpt-5.4-mini.base_instructions.md` | gpt-5.4-mini | |

## Caveats
- This binary (0.139.0) ships **gpt-5.1/5.2/5.3-codex + 5.4/5.5** profiles. The
  gpt-5.2-codex slug is present but shares the **`-codex` coding prompt** family
  (the file above is tagged nearest `gpt-5.3-codex`); 5.2 and 5.3-codex use the
  same coding instructions in this build. Kimi 3.0.19 names `gpt-5.2-codex` as
  its default; if it bundles an *older* Codex, that copy's wording may differ —
  re-extract from Kimi's bundled codex for an exact 3.0.19 match.
- The full runtime prompt Codex sends also appends environment/sandbox/tooling
  context at run time; these files are the static `base_instructions` core.
- Pin to Codex **0.139.0**; re-extract for other versions.

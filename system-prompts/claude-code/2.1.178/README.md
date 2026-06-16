<!-- Captured for research from Claude Code 2.1.178. The repo maintainer does
not claim copyright. -->

# Claude Code 2.1.178 — system prompts (runtime capture)

Captured the **exact** system prompt Claude Code sends, by pointing it at a local
logging proxy (`ANTHROPIC_BASE_URL=http://127.0.0.1:<port>`) and reading the
`system` field of the `/v1/messages` request body. This is the real assembled
prompt — not a binary-strings reconstruction. (The binary stores it as a Bun
string table of scattered fragments, so static extraction is unreliable; runtime
capture is authoritative.)

Claude Code picks the opening line by entrypoint
(`PA6()` in the binary): interactive TUI → "You are Claude Code…"; `claude -p`
/ Agent SDK → "You are a Claude agent…". The body that follows is otherwise the
same shape (Harness / Memory / Environment / Context management).

| File | Entrypoint | Opening | Size |
|------|-----------|---------|------|
| `interactive-cli.system-prompt.md` | `cc_entrypoint=cli` (TUI) | "You are Claude Code, Anthropic's official CLI for Claude." | ~7.3K |
| `sdk-cli.system-prompt.md` | `cc_entrypoint=sdk-cli` (`claude -p`) | "You are a Claude agent, built on Anthropic's Claude Agent SDK." | ~5.8K |

## Notes
- The model in both captures was `claude-opus-4-8` (this machine's default).
- The **`# Environment`** section is runtime-injected (cwd, OS, date, model list)
  and is specific to the capture session (cwd was `/private/tmp/cc_capture`); it's
  kept verbatim as part of the real prompt. The **`# Memory`** section is present
  because the user has the file-memory feature enabled.
- The interactive prompt here is the clean product prompt; a real project session
  additionally appends project/skill-specific guidance (CLAUDE.md, available
  skills, etc.) that isn't part of this base prompt.
- Pin to **2.1.178**; re-capture for other versions (the billing header block
  records the exact `cc_version`).

## How to re-capture
1. Run a tiny HTTP server that logs POST bodies and returns a minimal SSE stream.
2. `ANTHROPIC_BASE_URL=http://127.0.0.1:<port> claude` (interactive, keep OAuth)
   or `… claude -p "hi"` (SDK). Read `system` from the logged request JSON.

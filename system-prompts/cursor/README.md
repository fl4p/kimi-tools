<!-- Leaked/extracted prompts archived for research. The repo maintainer does
not claim copyright. -->

# Cursor (Composer / Agent) — extracted system prompts

Cursor's "Composer" is its multi-file agent mode. Cursor isn't installed on this
machine and its agent prompt is served server-side, so these come from public
leak collections (not first-party extraction).

| File | Source | What |
|------|--------|------|
| `cursor.asgeirtj.md` | github.com/asgeirtj/system_prompts_leaks `Cursor/cursor.md` | 18KB **behavioral** prompt: "You are an AI coding assistant… You operate in Cursor." Generic tool list (Shell/Glob/Grep/Read/Write/StrReplace/…), has `{model_name}`/`{mcps_folder}` placeholders. The cleaner of the two. |
| `agent-2.0.x1xhlol.txt` | github.com/x1xhlol/system-prompts-and-models-of-ai-tools `Cursor Prompts/Agent Prompt 2.0.txt` | 38KB. Same behavioral guidance PLUS a full `# Tools` TypeScript namespace (`codebase_search`, `edit_file`, `read_file`, `run_terminal_cmd`) and `<|im_start|>` chat-template markers. |
| `cursor.oc-adapted.md` | derived from `cursor.asgeirtj.md` | The version actually run as a `swe_bench.py --agent-prompt` arm: placeholders filled (`{model_name}`→Kimi, `{mcps_folder}`→~/.config/mcp). No other edits. |

## "Do we need to adjust the tooling?"
- **`cursor.asgeirtj.md`**: barely. Its tool list is generic (Shell/Glob/Grep/
  Read/Write/StrReplace) — close to opencode's (bash/glob/grep/read/write/edit),
  names differ slightly but opencode injects its own tool schemas, so the prompt's
  tool section is just descriptive context. Only the `{…}` placeholders needed
  filling → `cursor.oc-adapted.md`.
- **`agent-2.0.x1xhlol.txt`**: yes, substantially. Its `# Tools` namespace declares
  Cursor-specific tools (`edit_file`, `codebase_search`, `run_terminal_cmd`) that
  opencode does NOT expose; dropped in as-is it would instruct the model to call
  nonexistent tools. Would need the whole `## functions` block (lines ~8–490)
  stripped. Not used for the run for that reason.

Caveat: these are community leaks, not first-party — wording/version fidelity is
not guaranteed.

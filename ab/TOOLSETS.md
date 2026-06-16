# Benchmark toolsets: cline vs opencode vs pi

What tools each harness actually exposes to the model **during the A/B benchmark**
(`ab_bench.py` / `ab_opencode.py` / `ab_pi.py`, Kimi K2.7 on Fireworks, file-edit
scenarios). The toolset is **constant across the prompt arms** within each harness —
the arms vary only the *system prompt*, never the tool registry — so this is the
fixed tool surface every trial runs against.

The headline: the three harnesses are **not** tool-equivalent. cline ships **35**
tools, opencode **11**, pi **4**. That ~9× asymmetry in injected tool schema is a
real confound — see the note at the bottom.

## The table (capability-aligned union)

Each row is a capability; cells show the tool name(s) that harness exposes for it
(`—` = not loaded).

| Capability | pi | opencode | cline |
|---|---|---|---|
| Read a file | `read` | `read` | `read_files`, `Read` |
| Write a new file | `write` | `write` | — *(done via `editor`)* |
| Edit an existing file | `edit` | `edit` | `editor`, `Edit` |
| Run a shell command | `bash` | `bash` | `run_commands`, `Bash` |
| Search file *contents* | — | `grep` | `search_codebase` |
| Find files by name/glob | — | `glob` | — |
| List a directory | — | `list` | — |
| Apply a patch/diff | — | `patch` | *(`apply_patch` — off in act mode)* |
| Fetch web content | — | `webfetch` | `fetch_web_content` |
| Plan / track todos | — | `todowrite` | — |
| Delegate to a subagent | — | `task` | `spawn_agent` |
| Use a skill | — | — | `skills` |
| Ask the user a question | — | — | `ask_question` |
| Enter plan mode | — | — | `EnterPlanMode` |
| Schedule a cron job | — | — | `CronCreate` |
| Send a push notification | — | — | `PushNotification` |
| Background process monitor | — | — | `Monitor` |
| Stop / list background tasks | — | — | `TaskStop`, `TaskList` |
| Multi-agent "teams" (×18) | — | — | `team_spawn_teammate`, `team_shutdown_teammate`, `team_status`, `team_task`, `team_run_task`, `team_cancel_run`, `team_list_runs`, `team_await_runs`, `team_send_message`, `team_broadcast`, `team_read_mailbox`, `team_mission_log`, `team_cleanup`, `team_create_outcome`, `team_attach_outcome_fragment`, `team_review_outcome_fragment`, `team_finalize_outcome`, `team_list_outcomes` |
| *(internal fallback, not a capability)* | — | `invalid` | — |
| **Total model-facing tools** | **4** | **11** | **35** |

## Per-harness detail

**pi (4):** `read`, `bash`, `edit`, `write`.
pi registers 3 more built-ins (`grep`, `find`, `ls`) but they are **off by default**
(`defaultActiveToolNames = ["read","bash","edit","write"]`). The benchmark also runs
pi with discovery disabled (`-ne -ns -np -nc`), so the user's extension packages
(`pi-web-access`, `context-mode`), global skills, and `AGENTS.md`/`CLAUDE.md` add
nothing. Enable the extras with `--pi-arg '--tools …,grep,find,ls'`.

**opencode (11):** `bash`, `edit`, `write`, `read`, `grep`, `glob`, `list`, `patch`,
`webfetch`, `todowrite`, `task` (default "build" primary agent). The custom arm
(`--agent kimi-sys`, `mode: primary`) only overrides the prompt, so it inherits the
same 11. `invalid` is an internal malformed-call fallback, not a capability.

**cline (35):** the `act`-mode preset for a non-Claude model (Kimi/Fireworks matches
none of the `model-tool-routing` rules, which only swap `editor→apply_patch` for
openai-native/codex/gpt). cline registers **both** its array-shaped native tools
(`read_files`, `run_commands`) **and** Claude-style scalar twins (`Read`, `Bash`,
`Edit`) at once — that overlap is exactly what the prompt rewrite tries to steer
around (`read_files`/`run_commands` are the array-arg tools Kimi tends to call with
empty arrays; cf. `DISCOURAGED_TOOLS` in `ab_bench.py`). 18 of the 35 are agent-teams
orchestration tools. `apply_patch` and `submit_and_exit` are off in act mode.

## Why this matters for the benchmark

All three harnesses run the **same scenarios** and the **same model**, but hand it a
wildly different tool surface. cline injects ~9× more tool schema than pi and ~3× more
than opencode. That extra schema is input tokens on every call and more surface for
wrong-tool / empty-arg mistakes — so **cross-harness** numbers (tokens, tool-call
counts, hygiene) are not apples-to-apples; they partly measure the harness's tool
bloat, not the model. The **within-harness** prompt A/B (default vs custom) *is* clean,
because the toolset is held fixed and only the prompt changes.

## How this was determined

- **pi** — live self-report via the exact benchmark invocation (`pi -p --mode json
  -ne -ns -np -nc … "list your tools"` → `read, bash, edit, write`), cross-checked
  against `dist/core/agent-session.js` (`defaultActiveToolNames`).
- **cline** — live self-report via the benchmark invocation (`cline --json
  --auto-approve true -m …kimi-k2p7-code -P fireworks "list your tools"` → 35 names),
  cross-checked against the source registry (`sdk/packages/core/src/extensions/tools/`:
  `presets.ts` act preset + `definitions.ts createDefaultTools` + `constants.ts`).
- **opencode** — the live self-report hung repeatedly (server startup + model loop),
  so the list comes from the compiled binary's embedded tool-id registry plus the tool
  names named in its system prompt (captured in `fixtures/opencode_sample.jsonl`),
  matching opencode v1.15's documented "build" agent defaults.

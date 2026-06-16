#!/usr/bin/env python3
"""
A/B harness: does the Kimi/cline system prompt actually change behaviour?

Runs the real `cline` CLI over a small set of file-editing scenarios under
several "arms" (different `--system` prompt files, plus a no-override control),
each repeated K times, and reports per-arm:

  - task success  : pass@k (any trial passed) and pass^k (all trials passed)
  - tool hygiene  : empty-arg calls, array-shaped/discouraged tools, duplicate
                    calls, and "max consecutive mistakes" exits  -- the failure
                    modes the prompt rewrite is supposed to suppress.

The whole point: if the tool-hygiene numbers are identical across arms, the
prompt wording is cosmetic (cf. the v00 README's "the empty-args loop is a
tool-call-layer failure below the model" thesis). If `current` < `v00` <
`control`, the verbose per-tool docs are earning their length.

------------------------------------------------------------------------------
PREREQUISITES (real runs)
  - `cline` on PATH (or pass --bin). Confirmed flags used: -s/--system,
    -m/--model, -P/--provider, -k/--key, -t/--timeout, --cwd, --json,
    --auto-approve, --retries, --data-dir.
  - A working Kimi endpoint. Either run `cline auth` once into an isolated
    --data-dir, or pass --provider/--model/--key here. For an OpenAI-compatible
    Kimi endpoint you typically need a base URL configured via `cline auth`
    (there is no base-url CLI flag).

USAGE
  # 0. Prove the plumbing + scraper work, no API, no cline:
  python ab_bench.py --self-test
  python ab_bench.py --dry-run

  # 1. First real run -- SAVE RAW LOGS so we can confirm the --json tool-call
  #    schema matches the scraper (see "TUNING" in README):
  python ab_bench.py --model moonshotai/kimi-k2 --provider openai \
      --key "$KIMI_API_KEY" --trials 1 --save-logs ./logs

  # 2. Full A/B:
  python ab_bench.py --model moonshotai/kimi-k2 --provider openai \
      --key "$KIMI_API_KEY" --trials 3 --out results.json

Arms default to: control (no --system), v00 (archive prompt), current (shipped
prompt). Override or add with --arm name=/abs/path/to/prompt.md (repeatable);
--arm name=NONE means "no --system" (a control).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
# SCRIPT_DIR = prompts/system/kimi-cline-tools/ab
#   parents[0] = kimi-cline-tools, parents[1] = system, parents[2] = prompts
PROMPTS_ROOT = SCRIPT_DIR.parents[2]
V00_DIR = PROMPTS_ROOT / "archive" / "kimi-cline-tools-v00"
DEFAULT_CURRENT_PROMPT = SCRIPT_DIR.parent / "system-prompts" / "kimi-cline" / "kimi.system-prompt.md"
DEFAULT_V00_PROMPT = V00_DIR / "kimi.system-prompt.md"
DEFAULT_CURRENT_AUTO = SCRIPT_DIR.parent / "system-prompts" / "kimi-cline" / "kimi-autonomous.system-prompt.md"
DEFAULT_V00_AUTO = V00_DIR / "kimi-autonomous.system-prompt.md"

# cline already stores the Fireworks key + Kimi K2.7 model in its config, so the
# harness defaults to that provider/model and lets cline read its own key.
DEFAULT_PROVIDER = "fireworks"
DEFAULT_MODEL = "accounts/fireworks/models/kimi-k2p7-code"

# ---------------------------------------------------------------------------
# Tool-call scraping heuristics (model/harness-agnostic; tune after first run)
# ---------------------------------------------------------------------------

# Keys a cline --json message might use to name a tool and carry its arguments.
NAME_KEYS = ("tool", "toolName", "tool_name", "name")
ARG_KEYS = ("input", "tool_input", "arguments", "args", "parameters", "params")

# Tools the prompts steer AWAY from (array-shaped or overlapping variants).
DISCOURAGED_TOOLS = {"run_commands", "read_files", "apply_patch", "editor"}
# Required args that are array-shaped and that Kimi tends to send empty.
ARRAY_ARG_KEYS = {"commands", "queries", "paths", "files", "read_files"}

# Raw-text fallback patterns (only used if structured parsing finds nothing).
RE_EMPTY_ARRAY_ARG = re.compile(
    r'"(?:commands|queries|paths|files|read_files)"\s*:\s*\[\s*\]'
)
RE_DISCOURAGED_TEXT = re.compile(r'"(?:tool|name)"\s*:\s*"(run_commands|read_files)"')
RE_MISTAKE_EXIT = re.compile(
    r"consecutive mistakes|max(?:imum)? retries|having trouble|failure in the model",
    re.IGNORECASE,
)


@dataclass
class ToolCall:
    name: str
    args: dict


def _looks_like_tool_call(d: dict) -> Optional[ToolCall]:
    name = None
    for k in NAME_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v:
            name = v
            break
    if name is None:
        return None
    # Only treat as a tool call if it also carries a dict of arguments, OR the
    # message explicitly tags itself as a tool/tool_use.
    args: Optional[dict] = None
    for k in ARG_KEYS:
        v = d.get(k)
        if isinstance(v, dict):
            args = v
            break
    is_tool_typed = str(d.get("type", "")).lower() in {"tool", "tool_use", "tool_call"}
    if args is None and not is_tool_typed:
        return None
    return ToolCall(name=name, args=args or {})


def _walk(obj: Any, out: list[ToolCall]) -> None:
    if isinstance(obj, dict):
        tc = _looks_like_tool_call(obj)
        if tc is not None:
            out.append(tc)
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out)


def extract_tool_calls(stdout: str) -> tuple[list[ToolCall], bool]:
    """Return (tool_calls, structured_ok). Tries JSONL, then whole-JSON."""
    calls: list[ToolCall] = []
    parsed_any = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed_any = True
        _walk(obj, calls)
    if not parsed_any:
        try:
            obj = json.loads(stdout)
            parsed_any = True
            _walk(obj, calls)
        except json.JSONDecodeError:
            pass
    return calls, parsed_any


def _is_empty_args(tc: ToolCall) -> bool:
    if tc.args == {}:
        return True
    for k, v in tc.args.items():
        if isinstance(v, list) and len(v) == 0:
            return True
        if k in ARRAY_ARG_KEYS and isinstance(v, str) and v == "":
            return True
    return False


@dataclass
class Hygiene:
    tool_calls: int = 0
    empty_args: int = 0
    discouraged: int = 0
    duplicate: int = 0
    mistake_exit: bool = False
    structured: bool = True  # False => had to use the regex fallback


def score_hygiene(stdout: str, stderr: str, returncode: int) -> Hygiene:
    text = stdout + "\n" + stderr
    calls, structured = extract_tool_calls(stdout)
    h = Hygiene(structured=structured)
    h.mistake_exit = bool(RE_MISTAKE_EXIT.search(text)) or returncode == 7

    if structured and calls:
        h.tool_calls = len(calls)
        seen: dict[str, int] = {}
        for tc in calls:
            if _is_empty_args(tc):
                h.empty_args += 1
            if tc.name in DISCOURAGED_TOOLS:
                h.discouraged += 1
            sig = tc.name + "::" + json.dumps(tc.args, sort_keys=True)
            seen[sig] = seen.get(sig, 0) + 1
        h.duplicate = sum(c - 1 for c in seen.values() if c > 1)
    else:
        # Fallback: count from raw text (coarse; no duplicate detection).
        h.structured = False
        h.empty_args = len(RE_EMPTY_ARRAY_ARG.findall(text))
        h.discouraged = len(RE_DISCOURAGED_TEXT.findall(text))
        h.tool_calls = max(h.empty_args + h.discouraged, 0)
    return h


# ---------------------------------------------------------------------------
# Scenarios + arms
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    id: str
    name: str
    prompt: str
    timeout: int
    template: dict
    expect_files: list
    expect_contains: list
    expect_absent: Optional[list] = None   # [{file, absent}] strings that must NOT remain
    verify_cmd: Optional[str] = None        # shell cmd run in workdir; pass iff exit 0


@dataclass
class Arm:
    name: str
    system: Optional[Path]  # None => no --system override (control)


@dataclass
class TrialResult:
    arm: str
    scenario: str
    trial: int
    passed: bool
    duration_s: float          # wall-clock latency of the whole cline subprocess
    error: Optional[str]
    hygiene: Hygiene
    iterations: Optional[int] = None       # cline's own tool-call rounds (run_result)
    cline_duration_s: Optional[float] = None  # cline's own measured latency (durationMs)
    tokens: Optional[int] = None           # input+output tokens (usage); input ~ tool-schema bloat


def load_scenarios(path: Path, only: Optional[set[str]]) -> list[Scenario]:
    data = json.loads(path.read_text())
    out = []
    for d in data:
        if only and d["id"] not in only:
            continue
        out.append(Scenario(**d))
    return out


def build_arms(args) -> list[Arm]:
    if args.arm:
        arms = []
        for spec in args.arm:
            if "=" not in spec:
                sys.exit(f"--arm must be name=path or name=NONE, got: {spec}")
            name, _, p = spec.partition("=")
            arms.append(Arm(name=name, system=None if p.upper() == "NONE" else Path(p).resolve()))
        return arms
    return [
        Arm("default", None),
        Arm("v00", DEFAULT_V00_PROMPT),
        Arm("current", DEFAULT_CURRENT_PROMPT),
        Arm("v00-auto", DEFAULT_V00_AUTO),
        Arm("cur-auto", DEFAULT_CURRENT_AUTO),
    ]


# ---------------------------------------------------------------------------
# Running one trial
# ---------------------------------------------------------------------------

def seed_workdir(workdir: Path, scenario: Scenario) -> None:
    for rel, content in scenario.template.items():
        f = workdir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)


def check_pass(workdir: Path, scenario: Scenario) -> tuple[bool, Optional[str]]:
    for rel in scenario.expect_files:
        if not (workdir / rel).exists():
            return False, f"missing expected file: {rel}"
    for spec in scenario.expect_contains:
        f = workdir / spec["file"]
        if not f.exists():
            return False, f"missing file for content check: {spec['file']}"
        if spec["contains"] not in f.read_text():
            return False, f"{spec['file']} does not contain {spec['contains']!r}"
    for spec in (scenario.expect_absent or []):
        f = workdir / spec["file"]
        if f.exists() and spec["absent"] in f.read_text():
            return False, f"{spec['file']} still contains {spec['absent']!r}"
    if scenario.verify_cmd:
        try:
            r = subprocess.run(scenario.verify_cmd, shell=True, cwd=str(workdir),
                               capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return False, "verify_cmd timed out"
        if r.returncode != 0:
            return False, f"verify_cmd failed: {(r.stderr or r.stdout).strip()[:120]}"
    return True, None


def build_cline_args(args, arm: Arm, scenario: Scenario, workdir: Path) -> list[str]:
    cmd = [args.bin, "--json", "--auto-approve", "true", "--cwd", str(workdir),
           "-t", str(scenario.timeout), "--retries", str(args.retries)]
    if args.model:
        cmd += ["-m", args.model]
    if args.provider:
        cmd += ["-P", args.provider]
    if args.key:
        cmd += ["-k", args.key]
    if args.data_dir:
        cmd += ["--data-dir", args.data_dir]
    if arm.system is not None:
        cmd += ["-s", str(arm.system)]
    for extra in args.cline_arg or []:
        cmd += extra.split(" ", 1) if " " in extra else [extra]
    cmd += [scenario.prompt]
    return cmd


def parse_run_result(stdout: str) -> tuple[Optional[int], Optional[float], Optional[int]]:
    """Pull cline's own authoritative counters from the final run_result message:
    iterations (~ tool-call rounds), durationMs (cline-measured latency in s), and
    total tokens (inputTokens+outputTokens from usage/aggregateUsage — the input
    side is dominated by cline's large injected tool schema). Returns (None, None,
    None) for any field not present (e.g. crash/timeout)."""
    iters: Optional[int] = None
    cdur: Optional[float] = None
    tokens: Optional[int] = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and (
            obj.get("type") == "run_result"
            or ("durationMs" in obj and "iterations" in obj)
        ):
            if isinstance(obj.get("iterations"), (int, float)):
                iters = int(obj["iterations"])
            if isinstance(obj.get("durationMs"), (int, float)):
                cdur = float(obj["durationMs"]) / 1000.0
            u = obj.get("usage") or obj.get("aggregateUsage") or {}
            if isinstance(u, dict) and ("inputTokens" in u or "outputTokens" in u):
                tokens = int(u.get("inputTokens", 0) or 0) + int(u.get("outputTokens", 0) or 0)
    return iters, cdur, tokens


def run_real_trial(args, arm: Arm, scenario: Scenario, trial: int,
                   save_logs: Optional[Path]) -> TrialResult:
    workdir = Path(tempfile.mkdtemp(prefix=f"abk_{arm.name}_{scenario.id}_"))
    try:
        seed_workdir(workdir, scenario)
        cmd = build_cline_args(args, arm, scenario, workdir)
        start = time.perf_counter()
        error = None
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=scenario.timeout + 30,
            )
            stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as e:
            stdout = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = (e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
            rc = -1
            error = "timeout"
        duration = time.perf_counter() - start

        if save_logs:
            save_logs.mkdir(parents=True, exist_ok=True)
            tag = f"{arm.name}__{scenario.id}__t{trial}"
            (save_logs / f"{tag}.stdout.json").write_text(stdout)
            if stderr.strip():
                (save_logs / f"{tag}.stderr.txt").write_text(stderr)

        hygiene = score_hygiene(stdout, stderr, rc)
        iters, cline_dur, ctokens = parse_run_result(stdout)
        passed, fail_reason = check_pass(workdir, scenario)
        if error is None:
            error = fail_reason
        return TrialResult(arm.name, scenario.id, trial, passed, duration, error,
                           hygiene, iters, cline_dur, ctokens)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_mock_trial(arm: Arm, scenario: Scenario, trial: int) -> TrialResult:
    """--dry-run: no cline, no API. Writes expected files (pass), feeds a fixture
    log to the scraper. Arms whose name contains 'current' get the clean log;
    everything else gets the bad log. MOCK DATA -- plumbing check only."""
    fixture = SCRIPT_DIR / "fixtures" / ("clean_arm.jsonl" if "current" in arm.name else "bad_arm.jsonl")
    stdout = fixture.read_text()
    workdir = Path(tempfile.mkdtemp(prefix="abk_mock_"))
    try:
        seed_workdir(workdir, scenario)
        for rel in scenario.expect_files:  # pretend the task succeeded
            f = workdir / rel
            if not f.exists():
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("")
        for spec in scenario.expect_contains:
            (workdir / spec["file"]).write_text(spec["contains"] + " (mock)\n")
        hygiene = score_hygiene(stdout, "", 7 if "current" not in arm.name else 0)
        iters, cline_dur, ctokens = parse_run_result(stdout)
        passed, fail_reason = check_pass(workdir, scenario)
        return TrialResult(arm.name, scenario.id, trial, passed, 0.0, fail_reason,
                           hygiene, iters, cline_dur, ctokens)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Aggregation + reporting
# ---------------------------------------------------------------------------

@dataclass
class ArmSummary:
    arm: str
    trials: int
    pass_rate: float
    pass_at_k: float   # mean over scenarios of (any trial passed)
    pass_pow_k: float  # mean over scenarios of (all trials passed)
    tool_calls: int            # total tool calls (scraped) across all trials
    avg_tool_calls: float      # tool calls per trial
    empty_args: int
    discouraged: int
    duplicate: int
    mistake_exits: int
    bad_call_rate: float
    avg_duration_s: float
    total_duration_s: float    # summed wall-clock latency across all trials
    avg_iterations: Optional[float]      # cline's own tool-call rounds/trial (run_result)
    total_cline_duration_s: Optional[float]  # summed cline-measured latency
    total_tokens: Optional[int]          # summed input+output tokens
    avg_tokens: Optional[float]          # tokens per trial
    used_fallback: bool


def summarize(arm: str, results: list[TrialResult]) -> ArmSummary:
    by_scenario: dict[str, list[TrialResult]] = {}
    for r in results:
        by_scenario.setdefault(r.scenario, []).append(r)

    pass_at_k = statistics.mean(
        [1.0 if any(t.passed for t in ts) else 0.0 for ts in by_scenario.values()]
    ) if by_scenario else 0.0
    pass_pow_k = statistics.mean(
        [1.0 if all(t.passed for t in ts) else 0.0 for ts in by_scenario.values()]
    ) if by_scenario else 0.0

    tool_calls = sum(r.hygiene.tool_calls for r in results)
    empty = sum(r.hygiene.empty_args for r in results)
    dup = sum(r.hygiene.duplicate for r in results)
    disc = sum(r.hygiene.discouraged for r in results)
    mistakes = sum(1 for r in results if r.hygiene.mistake_exit)
    bad_rate = (empty + dup) / tool_calls if tool_calls else 0.0
    used_fallback = any(not r.hygiene.structured for r in results)
    n = len(results)
    iters = [r.iterations for r in results if r.iterations is not None]
    cdurs = [r.cline_duration_s for r in results if r.cline_duration_s is not None]
    toks = [r.tokens for r in results if r.tokens is not None]

    return ArmSummary(
        arm=arm,
        trials=n,
        pass_rate=statistics.mean([1.0 if r.passed else 0.0 for r in results]) if results else 0.0,
        pass_at_k=pass_at_k,
        pass_pow_k=pass_pow_k,
        tool_calls=tool_calls,
        avg_tool_calls=tool_calls / n if n else 0.0,
        empty_args=empty,
        discouraged=disc,
        duplicate=dup,
        mistake_exits=mistakes,
        bad_call_rate=bad_rate,
        avg_duration_s=statistics.mean([r.duration_s for r in results]) if results else 0.0,
        total_duration_s=sum(r.duration_s for r in results),
        avg_iterations=statistics.mean(iters) if iters else None,
        total_cline_duration_s=sum(cdurs) if cdurs else None,
        total_tokens=sum(toks) if toks else None,
        avg_tokens=statistics.mean(toks) if toks else None,
        used_fallback=used_fallback,
    )


def print_table(summaries: list[ArmSummary]) -> None:
    hdr = (f"{'arm':<10} {'trials':>6} {'pass%':>6} {'pass@k':>7} {'pass^k':>7} "
           f"{'tools':>6} {'tc/tr':>6} {'iter':>5} {'empty':>6} {'dup':>4} {'disc':>5} "
           f"{'mistk':>6} {'bad%':>6} {'tokens':>8} {'avg_s':>7} {'tot_s':>8}")
    print("\n" + "=" * len(hdr))
    print("A/B RESULTS  (tools=total calls, tc/tr=calls/trial, iter=cline rounds/trial; "
          "tot_s=total latency; empty/dup/disc/mistk lower is better)")
    print("=" * len(hdr))
    print(hdr)
    print("-" * len(hdr))
    for s in summaries:
        it = "-" if s.avg_iterations is None else f"{s.avg_iterations:.1f}"
        tk = "-" if s.avg_tokens is None else f"{s.avg_tokens:.0f}"
        print(f"{s.arm:<10} {s.trials:>6} {s.pass_rate*100:>5.0f}% "
              f"{s.pass_at_k*100:>6.0f}% {s.pass_pow_k*100:>6.0f}% "
              f"{s.tool_calls:>6} {s.avg_tool_calls:>6.1f} {it:>5} "
              f"{s.empty_args:>6} {s.duplicate:>4} "
              f"{s.discouraged:>5} {s.mistake_exits:>6} {s.bad_call_rate*100:>5.0f}% "
              f"{tk:>8} {s.avg_duration_s:>6.1f}s {s.total_duration_s:>7.1f}s")
    if any(s.used_fallback for s in summaries):
        print("\n  NOTE: regex fallback was used for >=1 trial (cline --json tool-call "
              "schema didn't match the structured parser). Re-run with --save-logs "
              "and tune NAME_KEYS/ARG_KEYS in ab_bench.py before trusting the hygiene columns.")


# ---------------------------------------------------------------------------
# Self-test (validates the scraper logic against fixtures; no cline/API)
# ---------------------------------------------------------------------------

def self_test() -> int:
    failures = []

    bad = score_hygiene((SCRIPT_DIR / "fixtures" / "bad_arm.jsonl").read_text(), "", 0)
    # bad_arm: 2x empty run_commands + 1x empty search_codebase = 3 empty_args;
    # discouraged = 2x run_commands + 1x read_files = 3; the two identical empty
    # run_commands calls => 1 duplicate; mistake_exit via the error text.
    checks = [
        ("bad.structured", bad.structured, True),
        ("bad.empty_args", bad.empty_args, 3),
        ("bad.discouraged", bad.discouraged, 3),
        ("bad.duplicate", bad.duplicate, 1),
        ("bad.mistake_exit", bad.mistake_exit, True),
    ]
    clean = score_hygiene((SCRIPT_DIR / "fixtures" / "clean_arm.jsonl").read_text(), "", 0)
    checks += [
        ("clean.structured", clean.structured, True),
        ("clean.empty_args", clean.empty_args, 0),
        ("clean.discouraged", clean.discouraged, 0),
        ("clean.duplicate", clean.duplicate, 0),
        ("clean.mistake_exit", clean.mistake_exit, False),
        ("clean.tool_calls", clean.tool_calls, 4),
    ]
    # real cline --json nests the tool call under agent_event.event (confirmed
    # against live Fireworks/Kimi logs); the recursive walker must still find it.
    real = score_hygiene((SCRIPT_DIR / "fixtures" / "real_schema.jsonl").read_text(), "", 0)
    checks += [
        ("real.structured", real.structured, True),
        ("real.tool_calls", real.tool_calls, 3),       # editor + Read + Bash
        ("real.discouraged", real.discouraged, 1),     # editor only
        ("real.empty_args", real.empty_args, 0),
    ]

    # run_result parsing: cline's authoritative iterations + durationMs + tokens.
    ri, rd, rt = parse_run_result((SCRIPT_DIR / "fixtures" / "real_schema.jsonl").read_text())
    ci, cd, ct = parse_run_result((SCRIPT_DIR / "fixtures" / "clean_arm.jsonl").read_text())
    checks += [
        ("real.iterations", ri, 3),        # real_schema has iterations=3, no durationMs/usage
        ("real.cline_dur_s", rd, None),
        ("real.tokens", rt, None),
        ("clean.iterations", ci, 4),
        ("clean.cline_dur_s", cd, 12.0),   # 12000ms -> 12.0s
        ("clean.tokens", ct, 1050),        # usage 1000 in + 50 out
    ]

    for label, got, want in checks:
        ok = got == want
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got {got!r}, want {want!r}")
        if not ok:
            failures.append(label)

    print()
    if failures:
        print(f"SELF-TEST FAILED: {len(failures)} check(s) -> {failures}")
        return 1
    print("SELF-TEST PASSED: scraper logic is internally consistent.")
    print("(Confirms detection LOGIC only -- fidelity to cline's real --json schema "
          "must still be verified on the first live run via --save-logs.)")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="A/B the Kimi/cline system prompt.")
    ap.add_argument("--bin", default="cline", help="path to the cline binary")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="model id (-m)")
    ap.add_argument("--provider", default=DEFAULT_PROVIDER, help="provider id (-P)")
    ap.add_argument("--key", help="API key (-k)")
    ap.add_argument("--data-dir", help="isolated cline --data-dir (recommended)")
    ap.add_argument("--cline-arg", action="append",
                    help="extra raw arg(s) for cline (repeatable), e.g. --cline-arg '--thinking high'")
    ap.add_argument("--arm", action="append",
                    help="name=path-to-prompt.md (repeatable); name=NONE for a no-override control")
    ap.add_argument("--scenarios", default=str(SCRIPT_DIR / "scenarios.json"))
    ap.add_argument("--only", help="comma-separated scenario ids to run")
    ap.add_argument("--trials", type=int, default=3, help="trials per (arm,scenario)")
    ap.add_argument("--retries", type=int, default=4,
                    help="cline --retries (consecutive mistakes before exit)")
    ap.add_argument("--save-logs", help="dir to dump raw cline stdout/stderr per trial")
    ap.add_argument("--out", help="write full JSON results here")
    ap.add_argument("--dry-run", action="store_true",
                    help="mock cline with fixture logs (no API) to validate plumbing + table")
    ap.add_argument("--self-test", action="store_true",
                    help="validate the tool-call scraper against fixtures and exit")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    only = set(args.only.split(",")) if args.only else None
    scenarios = load_scenarios(Path(args.scenarios), only)
    arms = build_arms(args)
    save_logs = Path(args.save_logs) if args.save_logs else None

    if not args.dry_run:
        missing = [a.name for a in arms if a.system is not None and not a.system.exists()]
        if missing:
            sys.exit(f"arm prompt file(s) not found: {missing}")
        if not args.model:
            sys.exit("--model is required for real runs (or use --dry-run / --self-test).")
        if shutil.which(args.bin) is None and not Path(args.bin).exists():
            sys.exit(f"cline binary not found: {args.bin}")

    mode = "DRY-RUN (MOCK fixtures, no API)" if args.dry_run else "LIVE"
    print(f"Mode: {mode}")
    print(f"Arms: " + ", ".join(f"{a.name}({'no-sys' if a.system is None else a.system.name})" for a in arms))
    print(f"Scenarios: {[s.id for s in scenarios]}  x {args.trials} trial(s)")

    all_results: list[TrialResult] = []
    for arm in arms:
        for scenario in scenarios:
            for trial in range(1, args.trials + 1):
                print(f"  [{arm.name}/{scenario.id}] trial {trial}/{args.trials} ...",
                      end="", flush=True)
                if args.dry_run:
                    r = run_mock_trial(arm, scenario, trial)
                else:
                    r = run_real_trial(args, arm, scenario, trial, save_logs)
                flag = "ok " if r.passed else "FAIL"
                extra = "" if r.error is None else f" ({r.error})"
                print(f" {flag} tools={r.hygiene.tool_calls} empty={r.hygiene.empty_args} "
                      f"dup={r.hygiene.duplicate} mistk={int(r.hygiene.mistake_exit)}{extra}")
                all_results.append(r)

    summaries = [summarize(a.name, [r for r in all_results if r.arm == a.name]) for a in arms]
    print_table(summaries)

    if args.dry_run:
        print("\n  ^ DRY-RUN: numbers above are MOCK fixtures, not real Kimi behaviour. "
              "They only prove the pipeline + table render.")

    if args.out:
        Path(args.out).write_text(json.dumps({
            "mode": mode,
            "arms": [{"name": a.name, "system": str(a.system) if a.system else None} for a in arms],
            "trials": args.trials,
            "summaries": [asdict(s) for s in summaries],
            "raw": [{**asdict(r), "hygiene": asdict(r.hygiene)} for r in all_results],
        }, indent=2))
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()

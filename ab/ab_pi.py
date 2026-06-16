#!/usr/bin/env python3
"""
A/B harness: pi (@earendil-works/pi-coding-agent) over {default prompt, custom prompt}.

Sibling to ab_bench.py (cline) and ab_opencode.py (opencode). Key differences,
because pi is a different harness:

  * pi HAS a real system-prompt flag: `--system-prompt <text>` REPLACES the built-in
    coding-assistant prompt entirely (no custom-agent dance like opencode). It takes
    TEXT, not a path, so the custom arm passes the prompt file's *contents*. Omitting
    the flag = pi's default prompt (the control arm). This mirrors cline's `-s`.
  * pi's default ACTIVE toolset is clean: read / bash / edit / write (grep/find/ls
    are registered but off by default). No run_commands/editor/read_files overlaps,
    so — like opencode — there is NO "discouraged tool" or empty-array-args metric.
    This measures TASK SUCCESS + EFFICIENCY: tool calls, duplicates, tool errors,
    turns, latency, tokens, and cost (pi's --mode json reports usage per message).
  * pi has NO --cwd/--dir flag: it runs in the process cwd, so each trial spawns pi
    with subprocess cwd=<isolated temp workdir>.
  * pi auto-discovers extensions / skills / prompt-templates / context files
    (AGENTS.md, CLAUDE.md) from ~/.pi and the cwd tree. For an apples-to-apples
    comparison with cline/opencode this harness DISABLES discovery by default
    (-ne -ns -np -nc --no-session). Pass --with-discovery to keep pi's full env.
  * Runs cells CONCURRENTLY (workdirs are isolated, sessions are ephemeral). Cap with
    --concurrency (default 4) to respect provider rate limits.

PROVIDER / MODEL
  pi has NO built-in "fireworks" provider (built-ins: anthropic, openai, deepseek,
  google, mistral, groq, cerebras, together, openrouter, ...). To run Kimi K2 you
  either:
    (a) add a custom provider to ~/.pi/agent/models.json, e.g.
          {"providers": {"fireworks": {
             "baseUrl": "https://api.fireworks.ai/inference/v1",
             "api": "openai-completions", "apiKey": "<FW_KEY>",
             "models": [{"id": "accounts/fireworks/models/kimi-k2p7-code",
                         "name": "Kimi K2.7 Code", "contextWindow": 262144}]}}}
        then run:  --provider fireworks --model accounts/fireworks/models/kimi-k2p7-code
    (b) use a provider pi already knows that hosts Kimi, e.g.
          --provider together   --model moonshotai/Kimi-K2-Instruct
          --provider openrouter --model moonshotai/kimi-k2
  With no --provider/--model, pi uses its configured default (see ~/.pi/agent/settings.json).

USAGE
  python3 ab_pi.py --self-test                       # parser check vs fixture, no API
  python3 ab_pi.py --trials 1 --save-logs ./pilogs   # smoke + capture raw json
  python3 ab_pi.py --provider together --model moonshotai/Kimi-K2-Instruct \
      --trials 3 --out pi_results.json               # full default-vs-custom A/B
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
# ab/ -> parents[0]=kimi-cline-tools, parents[1]=system
CUSTOM_PROMPT = SCRIPT_DIR.parents[1] / "sharp.md"

# ---------------------------------------------------------------------------
# pi --mode json scraping (schema confirmed against a live run, fixtures/pi_sample.jsonl)
#   tool_execution_start -> {toolName, args}                 (one per tool call)
#   tool_execution_end   -> {toolName, isError}              (tool error flag)
#   message_end          -> message.usage.{totalTokens, cost.total}  (per API call)
#   turn_end             -> one per agent turn (~ tool-call rounds)
# ---------------------------------------------------------------------------

@dataclass
class PiParse:
    tool_calls: int = 0
    duplicate: int = 0
    tool_errors: int = 0
    turns: int = 0
    tokens: int = 0
    cost: float = 0.0
    tools_by_name: Optional[dict] = None
    parsed: bool = False


def parse_pi(stdout: str) -> PiParse:
    calls: list[tuple] = []
    by_name: dict = {}
    tool_errors = 0
    turns = 0
    tokens = 0
    cost = 0.0
    parsed = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(o, dict):
            continue
        parsed = True
        t = o.get("type")
        if t == "tool_execution_start":
            name = o.get("toolName") or "?"
            args = o.get("args") or {}
            calls.append((name, json.dumps(args, sort_keys=True)))
            by_name[name] = by_name.get(name, 0) + 1
        elif t == "tool_execution_end":
            if o.get("isError"):
                tool_errors += 1
        elif t == "turn_end":
            turns += 1
        elif t == "message_end":
            usage = (o.get("message", {}) or {}).get("usage", {}) or {}
            tokens += usage.get("totalTokens", 0) or 0
            cost += (usage.get("cost", {}) or {}).get("total", 0) or 0.0
    seen: dict = {}
    for c in calls:
        seen[c] = seen.get(c, 0) + 1
    dup = sum(v - 1 for v in seen.values() if v > 1)
    return PiParse(len(calls), dup, tool_errors, turns, tokens, round(cost, 6), by_name, parsed)


# ---------------------------------------------------------------------------
# Scenarios / arms / trials
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
    system: Optional[Path]  # None => no --system-prompt override (pi's default prompt)


def default_arms() -> list[Arm]:
    return [
        Arm("default", None),
        Arm("custom", CUSTOM_PROMPT),
    ]


def build_arms(args) -> list[Arm]:
    if not args.arm:
        return default_arms()
    arms = []
    for spec in args.arm:
        if "=" not in spec:
            sys.exit(f"--arm must be name=path or name=NONE, got: {spec}")
        name, _, p = spec.partition("=")
        is_default = p.upper() in {"NONE", "DEFAULT"}
        arms.append(Arm(name=name, system=None if is_default else Path(p).resolve()))
    return arms


@dataclass
class TrialResult:
    arm: str
    scenario: str
    trial: int
    passed: bool
    duration_s: float
    error: Optional[str]
    parse: PiParse


def load_scenarios(path: Path, only: Optional[set]) -> list[Scenario]:
    out = []
    for d in json.loads(path.read_text()):
        if only and d["id"] not in only:
            continue
        out.append(Scenario(**d))
    return out


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


def build_pi_args(args, arm: Arm, scenario: Scenario) -> list[str]:
    cmd = [args.bin, "-p", "--mode", "json", "--no-session"]
    if not args.with_discovery:
        # isolate from the user's global pi env for an apples-to-apples comparison
        cmd += ["-ne", "-ns", "-np", "-nc"]
    if args.provider:
        cmd += ["--provider", args.provider]
    if args.model:
        cmd += ["--model", args.model]
    if args.api_key:
        cmd += ["--api-key", args.api_key]
    if args.thinking:
        cmd += ["--thinking", args.thinking]
    if arm.system is not None:
        # --system-prompt takes TEXT and REPLACES the default prompt entirely.
        cmd += ["--system-prompt", arm.system.read_text()]
    for extra in args.pi_arg or []:
        cmd += extra.split(" ", 1) if " " in extra else [extra]
    cmd += [scenario.prompt]
    return cmd


def run_trial(args, arm: Arm, scenario: Scenario, trial: int,
              save_logs: Optional[Path]) -> TrialResult:
    workdir = Path(tempfile.mkdtemp(prefix=f"abp_{arm.name}_{scenario.id}_"))
    try:
        seed_workdir(workdir, scenario)
        cmd = build_pi_args(args, arm, scenario)

        start = time.perf_counter()
        error = None
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  cwd=str(workdir), timeout=scenario.timeout + 30)
            stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
            if rc != 0:
                error = f"exit {rc}: {stderr.strip()[:160]}"
        except subprocess.TimeoutExpired as e:
            stdout = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = "timeout"
            rc = -1
            error = "timeout"
        duration = time.perf_counter() - start

        if save_logs:
            save_logs.mkdir(parents=True, exist_ok=True)
            tag = f"{arm.name}__{scenario.id}__t{trial}"
            (save_logs / f"{tag}.json").write_text(stdout)
            if stderr.strip():
                (save_logs / f"{tag}.stderr.txt").write_text(stderr)

        parse = parse_pi(stdout)
        passed, fail_reason = check_pass(workdir, scenario)
        if error is None:
            error = fail_reason
        return TrialResult(arm.name, scenario.id, trial, passed, duration, error, parse)
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
    pass_at_k: float
    pass_pow_k: float
    tool_calls: int
    avg_tool_calls: float
    duplicate: int
    tool_errors: int
    avg_turns: float
    tokens: int
    cost: float
    total_duration_s: float
    avg_duration_s: float


def summarize(arm: str, results: list[TrialResult]) -> ArmSummary:
    by_scn: dict = {}
    for r in results:
        by_scn.setdefault(r.scenario, []).append(r)
    n = len(results)
    tc = sum(r.parse.tool_calls for r in results)
    turns = [r.parse.turns for r in results]
    return ArmSummary(
        arm=arm,
        trials=n,
        pass_rate=statistics.mean([1.0 if r.passed else 0.0 for r in results]) if n else 0.0,
        pass_at_k=statistics.mean([1.0 if any(t.passed for t in ts) else 0.0 for ts in by_scn.values()]) if by_scn else 0.0,
        pass_pow_k=statistics.mean([1.0 if all(t.passed for t in ts) else 0.0 for ts in by_scn.values()]) if by_scn else 0.0,
        tool_calls=tc,
        avg_tool_calls=tc / n if n else 0.0,
        duplicate=sum(r.parse.duplicate for r in results),
        tool_errors=sum(r.parse.tool_errors for r in results),
        avg_turns=statistics.mean(turns) if turns else 0.0,
        tokens=sum(r.parse.tokens for r in results),
        cost=round(sum(r.parse.cost for r in results), 5),
        total_duration_s=sum(r.duration_s for r in results),
        avg_duration_s=statistics.mean([r.duration_s for r in results]) if n else 0.0,
    )


def print_table(summaries: list[ArmSummary]) -> None:
    hdr = (f"{'arm':<14} {'trials':>6} {'pass%':>6} {'pass@k':>7} {'pass^k':>7} "
           f"{'tools':>6} {'tc/tr':>6} {'dup':>4} {'err':>4} {'turn':>5} "
           f"{'tokens':>8} {'cost$':>8} {'avg_s':>7} {'tot_s':>8}")
    print("\n" + "=" * len(hdr))
    print("PI A/B  (default vs custom system prompt) — task success + efficiency metrics")
    print("=" * len(hdr))
    print(hdr)
    print("-" * len(hdr))
    for s in summaries:
        print(f"{s.arm:<14} {s.trials:>6} {s.pass_rate*100:>5.0f}% "
              f"{s.pass_at_k*100:>6.0f}% {s.pass_pow_k*100:>6.0f}% "
              f"{s.tool_calls:>6} {s.avg_tool_calls:>6.1f} {s.duplicate:>4} "
              f"{s.tool_errors:>4} {s.avg_turns:>5.1f} {s.tokens:>8} {s.cost:>8.4f} "
              f"{s.avg_duration_s:>6.1f}s {s.total_duration_s:>7.1f}s")


# ---------------------------------------------------------------------------
# Self-test (parser vs fixture; no pi/API)
# ---------------------------------------------------------------------------

def self_test() -> int:
    fx = SCRIPT_DIR / "fixtures" / "pi_sample.jsonl"
    p = parse_pi(fx.read_text())
    # pi_sample.jsonl: a clean 2-tool run (write out.txt, read out.txt back) over
    # 3 agent turns; sum of message_end usage.totalTokens = 5013; cost 0 (scaleway).
    checks = [
        ("parsed", p.parsed, True),
        ("tool_calls", p.tool_calls, 2),
        ("duplicate", p.duplicate, 0),
        ("tool_errors", p.tool_errors, 0),
        ("turns", p.turns, 3),
        ("tokens", p.tokens, 5013),
        ("cost", p.cost, 0.0),
        ("tool=write", (p.tools_by_name or {}).get("write"), 1),
        ("tool=read", (p.tools_by_name or {}).get("read"), 1),
    ]
    ok_all = True
    for label, got, want in checks:
        ok = got == want
        ok_all = ok_all and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got {got!r}, want {want!r}")
    print()
    print("SELF-TEST PASSED" if ok_all else "SELF-TEST FAILED")
    print("(Confirms pi --mode json parsing vs a captured live sample. Token/cost "
          "totals are sample-specific; cost is 0 when the provider has no pricing.)")
    return 0 if ok_all else 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="A/B pi (default vs custom system prompt).")
    ap.add_argument("--bin", default="pi", help="path to the pi binary")
    ap.add_argument("--provider", help="provider id (--provider); omit to use pi's default")
    ap.add_argument("--model", help="model id/pattern (--model); omit to use pi's default")
    ap.add_argument("--api-key", help="API key (--api-key); defaults to env / auth.json")
    ap.add_argument("--thinking", help="thinking level: off|minimal|low|medium|high|xhigh")
    ap.add_argument("--with-discovery", action="store_true",
                    help="keep pi's extensions/skills/prompt-templates/context files "
                         "(default: disabled for a clean comparison)")
    ap.add_argument("--pi-arg", action="append",
                    help="extra raw arg(s) for pi (repeatable), e.g. --pi-arg '--tools read,bash,edit,write,grep'")
    ap.add_argument("--arm", action="append",
                    help="name=path-to-prompt.md (repeatable); name=NONE (or DEFAULT) for pi's built-in prompt")
    ap.add_argument("--scenarios", default=str(SCRIPT_DIR / "scenarios.json"))
    ap.add_argument("--only", help="comma-separated scenario ids")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=4, help="parallel cells (1=sequential)")
    ap.add_argument("--save-logs", help="dir to dump raw pi json per trial")
    ap.add_argument("--out", help="write full JSON results here")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    arms = build_arms(args)
    missing = [str(a.system) for a in arms if a.system is not None and not a.system.exists()]
    if missing:
        sys.exit(f"arm prompt file(s) not found: {missing}")
    if shutil.which(args.bin) is None and not Path(args.bin).exists():
        sys.exit(f"pi binary not found: {args.bin}")

    only = set(args.only.split(",")) if args.only else None
    scenarios = load_scenarios(Path(args.scenarios), only)
    save_logs = Path(args.save_logs) if args.save_logs else None

    cells = [(arm, scn, t) for arm in arms for scn in scenarios for t in range(1, args.trials + 1)]
    print(f"pi A/B: {len(arms)} arms x {len(scenarios)} scenarios x {args.trials} trials "
          f"= {len(cells)} runs, concurrency={args.concurrency}")
    print("arms: " + ", ".join(f"{a.name}({'default-prompt' if a.system is None else a.system.name})" for a in arms))
    print(f"provider={args.provider or '(pi default)'}  model={args.model or '(pi default)'}  "
          f"discovery={'on' if args.with_discovery else 'off'}")

    results: list[TrialResult] = []
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
        futs = {ex.submit(run_trial, args, arm, scn, t, save_logs): (arm, scn, t)
                for (arm, scn, t) in cells}
        for fut in as_completed(futs):
            r = fut.result()
            done += 1
            flag = "ok " if r.passed else "FAIL"
            extra = "" if r.error is None else f" ({r.error})"
            print(f"  [{done}/{len(cells)}] {r.arm}/{r.scenario} t{r.trial}: {flag} "
                  f"tools={r.parse.tool_calls} dup={r.parse.duplicate} err={r.parse.tool_errors} "
                  f"tok={r.parse.tokens} {r.duration_s:.1f}s{extra}")
            results.append(r)

    summaries = [summarize(a.name, [r for r in results if r.arm == a.name]) for a in arms]
    print_table(summaries)

    if args.out:
        Path(args.out).write_text(json.dumps({
            "provider": args.provider,
            "model": args.model,
            "with_discovery": args.with_discovery,
            "arms": [{"name": a.name, "system": str(a.system) if a.system else None} for a in arms],
            "trials": args.trials,
            "summaries": [asdict(s) for s in summaries],
            "raw": [{**asdict(r), "parse": asdict(r.parse)} for r in results],
        }, indent=2))
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()

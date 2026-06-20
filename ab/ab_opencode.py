#!/usr/bin/env python3
"""
A/B harness: opencode + Kimi, 2x2 over {K2.6, K2.7} x {default prompt, custom prompt}.

Sibling to ab_bench.py (which tests cline). Key differences, because opencode is a
different harness:

  * opencode has NO `--system` flag. A custom system prompt is supplied via a custom
    AGENT whose prompt body = the override file. This harness writes a per-workdir
    `opencode.json` defining agent `kimi-sys` -> {file:sharp.md} and
    runs `opencode run --agent kimi-sys`. The default arm omits `--agent`.
  * opencode's toolset is already clean (write/edit/read/bash) with no
    run_commands/editor/read_files overlaps -> there is NO "discouraged tool" or
    empty-array-args metric here. So this measures TASK SUCCESS and EFFICIENCY:
    tool calls, duplicates, latency, tokens, and cost (opencode's --format json
    reports tokens+cost per step).
  * Runs cells CONCURRENTLY (opencode uses a random local port per run; workdirs are
    isolated). Cap with --concurrency (default 4) to respect Fireworks rate limits.

PREREQS: `opencode` on PATH (1.15+), fireworks-ai provider authed (both kimi-k2p6 and
kimi-k2p7-code show in `opencode models`). No key flag needed.

USAGE
  python3 ab_opencode.py --self-test          # parser check vs fixture, no API
  python3 ab_opencode.py --trials 1 --save-logs ./oclogs   # smoke + capture raw json
  python3 ab_opencode.py --trials 3 --out oc_results.json   # full 2x2
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

MODELS = {
    "k2.6": "fireworks-ai/accounts/fireworks/models/kimi-k2p6",
    "k2.7": "fireworks-ai/accounts/fireworks/models/kimi-k2p7-code",
    "glm5.2": "fireworks-ai/accounts/fireworks/models/glm-5p2",
    # Anthropic Opus 4.8, two reasoning-effort arms. The model id is identical;
    # the arms differ only by `opencode run --variant <effort>` (see VARIANTS),
    # which sets provider-specific reasoning effort. Needs ANTHROPIC_API_KEY in
    # env (opencode reads it for the anthropic provider).
    "opus4.8-high": "anthropic/claude-opus-4-8",
    "opus4.8-xhigh": "anthropic/claude-opus-4-8",
}
# Per-arm reasoning effort -> opencode `--variant`. Absent = no variant flag.
VARIANTS = {
    "opus4.8-high": "high",
    "opus4.8-xhigh": "xhigh",
}
CUSTOM_AGENT = "kimi-sys"

# ---------------------------------------------------------------------------
# opencode --format json scraping (schema confirmed against a live run)
#   tool_use   -> part.tool (name), part.state.input (args), part.state.time
#   step_finish-> part.tokens.total, part.cost
# ---------------------------------------------------------------------------

@dataclass
class OcParse:
    tool_calls: int = 0
    duplicate: int = 0
    tokens: int = 0
    cost: float = 0.0
    tools_by_name: Optional[dict] = None
    parsed: bool = False


def parse_opencode(stdout: str) -> OcParse:
    calls: list[tuple] = []
    tokens = 0
    cost = 0.0
    by_name: dict = {}
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
        if t == "tool_use":
            part = o.get("part", {}) or {}
            name = part.get("tool") or "?"
            inp = (part.get("state", {}) or {}).get("input", {})
            calls.append((name, json.dumps(inp, sort_keys=True)))
            by_name[name] = by_name.get(name, 0) + 1
        elif t == "step_finish":
            part = o.get("part", {}) or {}
            tokens += (part.get("tokens", {}) or {}).get("total", 0) or 0
            cost += part.get("cost", 0) or 0.0
    seen: dict = {}
    for c in calls:
        seen[c] = seen.get(c, 0) + 1
    dup = sum(v - 1 for v in seen.values() if v > 1)
    return OcParse(len(calls), dup, tokens, round(cost, 6), by_name, parsed)


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
    model_key: str
    custom: bool


def default_arms() -> list[Arm]:
    return [
        Arm("k2.6-default", "k2.6", False),
        Arm("k2.6-custom", "k2.6", True),
        Arm("k2.7-default", "k2.7", False),
        Arm("k2.7-custom", "k2.7", True),
    ]


@dataclass
class TrialResult:
    arm: str
    scenario: str
    trial: int
    passed: bool
    duration_s: float
    error: Optional[str]
    parse: OcParse


def load_scenarios(path: Path, only: Optional[set]) -> list[Scenario]:
    out = []
    for d in json.loads(path.read_text()):
        if only and d["id"] not in only:
            continue
        out.append(Scenario(**d))
    return out


def seed_workdir(workdir: Path, scenario: Scenario, arm: Arm) -> None:
    for rel, content in scenario.template.items():
        f = workdir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    if arm.custom:
        cfg = {
            "$schema": "https://opencode.ai/config.json",
            "agent": {
                CUSTOM_AGENT: {
                    "mode": "primary",
                    "prompt": "{file:" + str(CUSTOM_PROMPT) + "}",
                }
            },
        }
        (workdir / "opencode.json").write_text(json.dumps(cfg, indent=2))


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


def run_trial(args, arm: Arm, scenario: Scenario, trial: int,
              save_logs: Optional[Path]) -> TrialResult:
    workdir = Path(tempfile.mkdtemp(prefix=f"abo_{arm.name}_{scenario.id}_"))
    try:
        seed_workdir(workdir, scenario, arm)
        cmd = [args.bin, "run", "-m", MODELS[arm.model_key],
               "--dir", str(workdir), "--format", "json"]
        if arm.custom:
            cmd += ["--agent", CUSTOM_AGENT]
        if VARIANTS.get(arm.model_key):
            cmd += ["--variant", VARIANTS[arm.model_key]]
        cmd += [scenario.prompt]

        start = time.perf_counter()
        error = None
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=scenario.timeout + 30)
            stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
            if rc != 0:
                error = f"exit {rc}: {stderr.strip()[:160]}"
        except subprocess.TimeoutExpired:
            stdout, stderr, rc = "", "timeout", -1
            error = "timeout"
        duration = time.perf_counter() - start

        if save_logs:
            save_logs.mkdir(parents=True, exist_ok=True)
            tag = f"{arm.name}__{scenario.id}__t{trial}"
            (save_logs / f"{tag}.json").write_text(stdout)
            if stderr.strip():
                (save_logs / f"{tag}.stderr.txt").write_text(stderr)

        parse = parse_opencode(stdout)
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
    return ArmSummary(
        arm=arm,
        trials=n,
        pass_rate=statistics.mean([1.0 if r.passed else 0.0 for r in results]) if n else 0.0,
        pass_at_k=statistics.mean([1.0 if any(t.passed for t in ts) else 0.0 for ts in by_scn.values()]) if by_scn else 0.0,
        pass_pow_k=statistics.mean([1.0 if all(t.passed for t in ts) else 0.0 for ts in by_scn.values()]) if by_scn else 0.0,
        tool_calls=tc,
        avg_tool_calls=tc / n if n else 0.0,
        duplicate=sum(r.parse.duplicate for r in results),
        tokens=sum(r.parse.tokens for r in results),
        cost=round(sum(r.parse.cost for r in results), 5),
        total_duration_s=sum(r.duration_s for r in results),
        avg_duration_s=statistics.mean([r.duration_s for r in results]) if n else 0.0,
    )


def print_table(summaries: list[ArmSummary]) -> None:
    hdr = (f"{'arm':<14} {'trials':>6} {'pass%':>6} {'pass@k':>7} {'pass^k':>7} "
           f"{'tools':>6} {'tc/tr':>6} {'dup':>4} {'tokens':>8} {'cost$':>8} "
           f"{'avg_s':>7} {'tot_s':>8}")
    print("\n" + "=" * len(hdr))
    print("OPENCODE A/B  (K2.6 vs K2.7) x (default vs custom prompt) — efficiency metrics")
    print("=" * len(hdr))
    print(hdr)
    print("-" * len(hdr))
    for s in summaries:
        print(f"{s.arm:<14} {s.trials:>6} {s.pass_rate*100:>5.0f}% "
              f"{s.pass_at_k*100:>6.0f}% {s.pass_pow_k*100:>6.0f}% "
              f"{s.tool_calls:>6} {s.avg_tool_calls:>6.1f} {s.duplicate:>4} "
              f"{s.tokens:>8} {s.cost:>8.4f} {s.avg_duration_s:>6.1f}s {s.total_duration_s:>7.1f}s")


# ---------------------------------------------------------------------------
# Self-test (parser vs fixture; no opencode/API)
# ---------------------------------------------------------------------------

def self_test() -> int:
    fx = SCRIPT_DIR / "fixtures" / "opencode_sample.jsonl"
    p = parse_opencode(fx.read_text())
    checks = [
        ("parsed", p.parsed, True),
        ("tool_calls", p.tool_calls, 1),
        ("tokens", p.tokens, 8796),
        ("duplicate", p.duplicate, 0),
        ("tool=write", (p.tools_by_name or {}).get("write"), 1),
    ]
    ok_all = True
    for label, got, want in checks:
        ok = got == want
        ok_all = ok_all and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got {got!r}, want {want!r}")
    print()
    print("SELF-TEST PASSED" if ok_all else "SELF-TEST FAILED")
    print("(Confirms opencode --format json parsing vs a captured live sample. "
          "Cost-field equality is sample-specific.)")
    return 0 if ok_all else 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="A/B opencode + Kimi (2x2).")
    ap.add_argument("--bin", default="opencode")
    ap.add_argument("--scenarios", default=str(SCRIPT_DIR / "scenarios.json"))
    ap.add_argument("--only", help="comma-separated scenario ids")
    ap.add_argument("--arms", help="comma-separated arm names to include (e.g. k2.7-default,k2.7-custom)")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=4, help="parallel cells (1=sequential)")
    ap.add_argument("--save-logs", help="dir to dump raw opencode json per trial")
    ap.add_argument("--out", help="write full JSON results here")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    if not CUSTOM_PROMPT.exists():
        sys.exit(f"custom prompt not found: {CUSTOM_PROMPT}")
    if shutil.which(args.bin) is None and not Path(args.bin).exists():
        sys.exit(f"opencode binary not found: {args.bin}")

    only = set(args.only.split(",")) if args.only else None
    scenarios = load_scenarios(Path(args.scenarios), only)
    arms = default_arms()
    if args.arms:
        keep = set(args.arms.split(","))
        arms = [a for a in arms if a.name in keep]
    save_logs = Path(args.save_logs) if args.save_logs else None

    cells = [(arm, scn, t) for arm in arms for scn in scenarios for t in range(1, args.trials + 1)]
    print(f"opencode A/B: {len(arms)} arms x {len(scenarios)} scenarios x {args.trials} trials "
          f"= {len(cells)} runs, concurrency={args.concurrency}")
    print(f"models: K2.6={MODELS['k2.6'].split('/')[-1]}  K2.7={MODELS['k2.7'].split('/')[-1]}")
    print(f"custom prompt: {CUSTOM_PROMPT}")

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
                  f"tools={r.parse.tool_calls} dup={r.parse.duplicate} "
                  f"tok={r.parse.tokens} {r.duration_s:.1f}s{extra}")
            results.append(r)

    summaries = [summarize(a.name, [r for r in results if r.arm == a.name]) for a in arms]
    print_table(summaries)

    if args.out:
        Path(args.out).write_text(json.dumps({
            "models": MODELS,
            "custom_prompt": str(CUSTOM_PROMPT),
            "trials": args.trials,
            "summaries": [asdict(s) for s in summaries],
            "raw": [{**asdict(r), "parse": asdict(r.parse)} for r in results],
        }, indent=2))
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()

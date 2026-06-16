#!/usr/bin/env python3
"""
Significance layer for the Kimi/cline system-prompt A/B.

READ-ONLY companion to ab_bench.py: it never imports or modifies the harness,
it only consumes the `results.json` that `ab_bench.py --out results.json`
writes. The harness reports raw per-arm counts but no statistics; with only
4 scenarios x 3 trials = 12 runs/arm the arm differences are badly underpowered,
so a raw "current has fewer discouraged calls than control" can easily be noise.
This script answers: *is the difference real?*

Method (as agreed on the `bench` channel):
  - Pair observations ACROSS arms by (scenario, trial). This controls for the
    dominant variance source (which scenario) rather than comparing arm marginals
    blind. NOTE: trial index is only a NOMINAL pairing -- trial 1 of `control`
    and trial 1 of `current` are independent runs, not the same seed -- so the
    pairing removes scenario variance, not run-to-run noise. Still strictly
    better than an unpaired comparison.
  - Binary metrics  -> exact-binomial McNemar on the discordant pairs (exact, not
    chi-square, because N is small).
  - Numeric metrics -> paired bootstrap 95% CI of the mean (arm - baseline)
    difference. If the CI excludes 0, the difference is real at that level.

results.json schema consumed (only these fields are required):
  {"raw": [ {"arm","scenario","trial","passed",
             "hygiene": {"tool_calls","discouraged","empty_args",
                         "duplicate","mistake_exit"}}, ... ]}

USAGE
  python3 stats.py                      # reads ./results.json
  python3 stats.py path/to/results.json
  python3 stats.py --baseline control --bootstrap 10000 --seed 0
  python3 stats.py --compare control:current --compare v00:current
  python3 stats.py --self-test         # synthetic fixture, no results.json needed
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from math import comb
from pathlib import Path
from random import Random
from typing import Callable


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------
# Each metric maps one raw trial record -> a number.
# "good" says which direction is better, used only for labelling the verdict.

def _hyg(rec: dict, key: str) -> float:
    return float(rec.get("hygiene", {}).get(key, 0) or 0)


# Binary metrics (0/1 per trial) -> McNemar.
BINARY_METRICS: dict[str, tuple[Callable[[dict], int], str]] = {
    "passed":           (lambda r: 1 if r.get("passed") else 0,        "higher"),
    "used_discouraged": (lambda r: 1 if _hyg(r, "discouraged") > 0 else 0, "lower"),
    "had_empty_arg":    (lambda r: 1 if _hyg(r, "empty_args") > 0 else 0,  "lower"),
    "had_duplicate":    (lambda r: 1 if _hyg(r, "duplicate") > 0 else 0,   "lower"),
    "mistake_exit":     (lambda r: 1 if r.get("hygiene", {}).get("mistake_exit") else 0, "lower"),
}

# Numeric per-trial metrics -> paired bootstrap CI on the mean difference.
NUMERIC_METRICS: dict[str, tuple[Callable[[dict], float], str]] = {
    "tool_calls":  (lambda r: _hyg(r, "tool_calls"),                       "n/a"),
    "discouraged": (lambda r: _hyg(r, "discouraged"),                      "lower"),
    "empty_args":  (lambda r: _hyg(r, "empty_args"),                       "lower"),
    "duplicate":   (lambda r: _hyg(r, "duplicate"),                        "lower"),
    "bad_calls":   (lambda r: _hyg(r, "empty_args") + _hyg(r, "duplicate"), "lower"),
}


# ---------------------------------------------------------------------------
# Loading / indexing
# ---------------------------------------------------------------------------

def load_raw(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    raw = data.get("raw")
    if not isinstance(raw, list) or not raw:
        sys.exit(f"{path}: no non-empty 'raw' array found (got {type(raw).__name__}).")
    return raw


def index_by_arm(raw: list[dict]) -> dict[str, dict[tuple, dict]]:
    """arm -> {(scenario, trial): record}."""
    out: dict[str, dict[tuple, dict]] = {}
    for rec in raw:
        arm = rec.get("arm")
        if not isinstance(arm, str):
            continue
        key = (rec.get("scenario"), rec.get("trial"))
        out.setdefault(arm, {})[key] = rec
    return out


def paired_keys(idx: dict[str, dict[tuple, dict]], a: str, b: str) -> list[tuple]:
    """(scenario, trial) keys present in BOTH arms, deterministically ordered."""
    return sorted(set(idx[a]) & set(idx[b]), key=lambda k: (str(k[0]), k[1]))


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact-binomial McNemar p-value over discordant pairs (b, c)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(1.0, 2.0 * tail)


def bootstrap_mean_diff(
    diffs: list[float], n_boot: int, rng: Random, ci: float = 0.95
) -> tuple[float, float, float]:
    """Point estimate + percentile CI for the mean of paired differences."""
    n = len(diffs)
    if n == 0:
        return 0.0, 0.0, 0.0
    point = sum(diffs) / n
    boots = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(n):
            s += diffs[rng.randrange(n)]
        boots.append(s / n)
    boots.sort()
    lo = boots[int((1 - ci) / 2 * n_boot)]
    hi = boots[min(n_boot - 1, int((1 + ci) / 2 * n_boot))]
    return point, lo, hi


# ---------------------------------------------------------------------------
# Comparison report
# ---------------------------------------------------------------------------

@dataclass
class Comparison:
    baseline: str
    arm: str
    n_pairs: int


def compare(
    idx: dict[str, dict[tuple, dict]],
    baseline: str,
    arm: str,
    n_boot: int,
    seed: int,
) -> None:
    keys = paired_keys(idx, baseline, arm)
    print(f"\n{'='*72}")
    print(f"  {baseline}  vs  {arm}    (paired by scenario,trial; n={len(keys)} pairs)")
    print(f"{'='*72}")
    if not keys:
        print("  no shared (scenario,trial) pairs — skipped.")
        return

    base_recs = [idx[baseline][k] for k in keys]
    arm_recs = [idx[arm][k] for k in keys]

    # --- Binary metrics: McNemar ---------------------------------------
    print("\n  BINARY (McNemar exact, two-sided):")
    print(f"    {'metric':<17} {'base%':>6} {'arm%':>6} {'b':>3} {'c':>3} "
          f"{'p':>7}  verdict")
    print(f"    {'-'*17} {'-'*6} {'-'*6} {'-'*3} {'-'*3} {'-'*7}  {'-'*7}")
    for name, (fn, good) in BINARY_METRICS.items():
        a_vals = [fn(r) for r in base_recs]
        b_vals = [fn(r) for r in arm_recs]
        # discordant counts: b = base-positive/arm-negative, c = base-neg/arm-pos
        b = sum(1 for x, y in zip(a_vals, b_vals) if x == 1 and y == 0)
        c = sum(1 for x, y in zip(a_vals, b_vals) if x == 0 and y == 1)
        p = mcnemar_exact(b, c)
        base_rate = 100.0 * sum(a_vals) / len(a_vals)
        arm_rate = 100.0 * sum(b_vals) / len(b_vals)
        verdict = _verdict(base_rate, arm_rate, good, p, discordant=b + c)
        print(f"    {name:<17} {base_rate:>5.0f}% {arm_rate:>5.0f}% "
              f"{b:>3} {c:>3} {p:>7.3f}  {verdict}")

    # --- Numeric metrics: bootstrap CI of mean(arm - baseline) ---------
    print("\n  NUMERIC (paired bootstrap 95% CI of mean[arm - baseline]):")
    print(f"    {'metric':<17} {'base':>6} {'arm':>6} {'diff':>7} "
          f"{'95% CI':>16}  verdict")
    print(f"    {'-'*17} {'-'*6} {'-'*6} {'-'*7} {'-'*16}  {'-'*7}")
    for name, (fn, good) in NUMERIC_METRICS.items():
        a_vals = [fn(r) for r in base_recs]
        b_vals = [fn(r) for r in arm_recs]
        diffs = [y - x for x, y in zip(a_vals, b_vals)]
        rng = Random(seed)  # same seed per metric => reproducible
        point, lo, hi = bootstrap_mean_diff(diffs, n_boot, rng)
        base_mean = sum(a_vals) / len(a_vals)
        arm_mean = sum(b_vals) / len(b_vals)
        excludes_zero = (lo > 0 and hi > 0) or (lo < 0 and hi < 0)
        if good == "n/a":
            verdict = "—"
        elif not excludes_zero:
            verdict = "ns"
        else:
            improved = (point < 0) if good == "lower" else (point > 0)
            verdict = "BETTER" if improved else "WORSE"
        print(f"    {name:<17} {base_mean:>6.2f} {arm_mean:>6.2f} {point:>+7.2f} "
              f"[{lo:>+6.2f},{hi:>+6.2f}]  {verdict}")


def _verdict(base_rate: float, arm_rate: float, good: str, p: float,
             discordant: int) -> str:
    if discordant == 0:
        return "identical"
    if p >= 0.05:
        return f"ns (p={p:.2f})"
    if good == "higher":
        return "BETTER" if arm_rate > base_rate else "WORSE"
    return "BETTER" if arm_rate < base_rate else "WORSE"


# ---------------------------------------------------------------------------
# Comparison selection
# ---------------------------------------------------------------------------

def default_compares(arms: list[str], baseline: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen = set()

    def add(a: str, b: str) -> None:
        if a in arms and b in arms and a != b and (a, b) not in seen:
            pairs.append((a, b))
            seen.add((a, b))

    # headline: baseline vs every other arm
    for arm in arms:
        if arm != baseline:
            add(baseline, arm)
    # rewrite-over-old and autonomous-variant comparisons, if present
    add("v00", "current")
    add("v00-auto", "cur-auto")
    return pairs


# ---------------------------------------------------------------------------
# Self-test (synthetic fixture; no results.json, no API)
# ---------------------------------------------------------------------------

def _synthetic_results() -> dict:
    """control reaches for the discouraged 'editor' on every edit trial;
    current never does. Constructed so McNemar must flag used_discouraged."""
    raw = []
    scenarios = ["create-file", "edit-file", "multi-file", "inspect-then-edit"]
    for sc in scenarios:
        for t in (1, 2, 3):
            raw.append({"arm": "control", "scenario": sc, "trial": t,
                        "passed": True,
                        "hygiene": {"tool_calls": 4, "discouraged": 2,
                                    "empty_args": 1, "duplicate": 1,
                                    "mistake_exit": False}})
            raw.append({"arm": "current", "scenario": sc, "trial": t,
                        "passed": True,
                        "hygiene": {"tool_calls": 3, "discouraged": 0,
                                    "empty_args": 0, "duplicate": 0,
                                    "mistake_exit": False}})
    return {"raw": raw}


def self_test(n_boot: int, seed: int) -> int:
    print("SELF-TEST: synthetic fixture (control uses 'editor', current never does)\n")
    idx = index_by_arm(_synthetic_results()["raw"])

    # McNemar: 12 discordant pairs all one direction -> tiny exact p.
    keys = paired_keys(idx, "control", "current")
    fn = BINARY_METRICS["used_discouraged"][0]
    b = sum(1 for k in keys if fn(idx["control"][k]) and not fn(idx["current"][k]))
    c = sum(1 for k in keys if not fn(idx["control"][k]) and fn(idx["current"][k]))
    p = mcnemar_exact(b, c)
    ok_mcnemar = (b == 12 and c == 0 and p < 0.001)
    print(f"  [{'PASS' if ok_mcnemar else 'FAIL'}] McNemar used_discouraged: "
          f"b={b} c={c} p={p:.5f} (want b=12,c=0,p<0.001)")

    # Bootstrap: discouraged diff is exactly -2 every pair -> CI = [-2,-2].
    diffs = [NUMERIC_METRICS["discouraged"][0](idx["current"][k])
             - NUMERIC_METRICS["discouraged"][0](idx["control"][k]) for k in keys]
    point, lo, hi = bootstrap_mean_diff(diffs, n_boot, Random(seed))
    ok_boot = (abs(point + 2) < 1e-9 and abs(lo + 2) < 1e-9 and abs(hi + 2) < 1e-9)
    print(f"  [{'PASS' if ok_boot else 'FAIL'}] bootstrap discouraged diff: "
          f"{point:+.2f} [{lo:+.2f},{hi:+.2f}] (want -2.00 [-2.00,-2.00])")

    # exact-binomial sanity: b=c -> p=1; lopsided 5/0 -> p=2*0.5^5
    ok_p1 = abs(mcnemar_exact(3, 3) - 1.0) < 1e-9
    ok_p2 = abs(mcnemar_exact(5, 0) - 2 * 0.5 ** 5) < 1e-9
    print(f"  [{'PASS' if ok_p1 else 'FAIL'}] mcnemar_exact(3,3)=1.0")
    print(f"  [{'PASS' if ok_p2 else 'FAIL'}] mcnemar_exact(5,0)={2*0.5**5:.5f}")

    print("\n  Full report on the synthetic fixture:")
    compare(idx, "control", "current", n_boot, seed)

    passed = ok_mcnemar and ok_boot and ok_p1 and ok_p2
    print(f"\n{'SELF-TEST PASSED' if passed else 'SELF-TEST FAILED'}")
    return 0 if passed else 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Significance layer for the cline A/B.")
    ap.add_argument("results", nargs="?", default="results.json",
                    help="path to ab_bench.py --out file (default: results.json)")
    ap.add_argument("--baseline", default="control",
                    help="baseline arm name (default: control)")
    ap.add_argument("--compare", action="append",
                    help="explicit 'baseline:arm' pair (repeatable); overrides defaults")
    ap.add_argument("--bootstrap", type=int, default=10000, help="bootstrap resamples")
    ap.add_argument("--seed", type=int, default=0, help="bootstrap RNG seed")
    ap.add_argument("--self-test", action="store_true",
                    help="run on a synthetic fixture and exit (no results.json needed)")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test(args.bootstrap, args.seed))

    path = Path(args.results)
    if not path.exists():
        sys.exit(f"{path} not found yet. Run ab_bench.py --out {path} first "
                 f"(or `python3 stats.py --self-test` to validate the stats).")

    raw = load_raw(path)
    idx = index_by_arm(raw)
    arms = list(idx.keys())
    print(f"Loaded {len(raw)} trial records across {len(arms)} arms: {arms}")

    baseline = args.baseline if args.baseline in idx else arms[0]
    if baseline != args.baseline:
        print(f"(baseline '{args.baseline}' absent; using '{baseline}')")

    if args.compare:
        pairs = []
        for spec in args.compare:
            if ":" not in spec:
                sys.exit(f"--compare must be baseline:arm, got: {spec}")
            a, _, b = spec.partition(":")
            pairs.append((a, b))
    else:
        pairs = default_compares(arms, baseline)

    print(f"Comparisons: {pairs}")
    print(f"Bootstrap: {args.bootstrap} resamples, seed {args.seed}")
    print("\nNote: pairing is by (scenario,trial); trial index is a NOMINAL pairing "
          "(controls for scenario, not run-to-run seed).")

    for a, b in pairs:
        if a not in idx or b not in idx:
            print(f"\n  skip {a} vs {b}: arm(s) absent from results.")
            continue
        compare(idx, a, b, args.bootstrap, args.seed)


if __name__ == "__main__":
    main()

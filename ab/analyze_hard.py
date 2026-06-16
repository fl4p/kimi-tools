#!/usr/bin/env python3
"""Read hard_oc.json and answer ONE question: is K2.7 measurably better than
K2.6 on the hard scenarios? Reports, per scenario and overall:
  - per-trial pass count (the discriminating signal now that tasks can fail)
  - pass^k (all-k passed) and pass@k (any passed)
  - a paired comparison of per-trial pass/fail across the two models
Run after the sweep writes hard_oc.json."""
import json
from collections import defaultdict
from pathlib import Path

D = Path(__file__).resolve().parent
d = json.load(open(D / "hard_oc.json"))
raw = d.get("raw", [])

# raw rows carry arm, scenario, trial, passed. Group per (model, scenario).
by = defaultdict(list)  # (model, scenario) -> [bool,...]
for r in raw:
    arm = r["arm"]
    model = "K2.6" if "k2.6" in arm else "K2.7"
    by[(model, r["scenario"])].append(bool(r["passed"]))

scenarios = sorted({s for (_, s) in by})
models = ["K2.6", "K2.7"]

print(f"\nHARD scenarios — per-trial pass counts (n trials each)\n{'='*60}")
hdr = f"{'scenario':<22}" + "".join(f"{m:>14}" for m in models)
print(hdr)
print("-" * len(hdr))
tot = {m: [0, 0] for m in models}  # passes, trials
for sc in scenarios:
    cells = []
    for m in models:
        res = by.get((m, sc), [])
        p, n = sum(res), len(res)
        tot[m][0] += p
        tot[m][1] += n
        cells.append(f"{p}/{n}")
    print(f"{sc:<22}" + "".join(f"{c:>14}" for c in cells))
print("-" * len(hdr))
print(f"{'TOTAL pass/trials':<22}" + "".join(f"{tot[m][0]}/{tot[m][1]:>10}" for m in models))

print(f"\npass^k (all trials of a scenario passed) — the reliability signal")
print("-" * 60)
for sc in scenarios:
    line = f"  {sc:<22}"
    for m in models:
        res = by.get((m, sc), [])
        powk = "100%" if res and all(res) else f"{round(100*sum(res)/len(res))}% trials" if res else "-"
        line += f"  {m}={'PASS' if res and all(res) else 'FAIL('+str(sum(res))+'/'+str(len(res))+')':<10}"
    print(line)

# Overall verdict
p6, n6 = tot["K2.6"]
p7, n7 = tot["K2.7"]
print(f"\n{'='*60}")
print(f"OVERALL: K2.6 {p6}/{n6} = {100*p6/n6:.0f}%   |   K2.7 {p7}/{n7} = {100*p7/n7:.0f}%")
gap = (p7/n7 - p6/n6) * 100
if abs(gap) < 1:
    print("=> No measurable gap at this difficulty (both saturate or fail equally).")
elif gap > 0:
    print(f"=> K2.7 higher by {gap:.0f} pts. Check if any scenario actually separated them.")
else:
    print(f"=> K2.6 higher by {-gap:.0f} pts.")
print("Note: a gap only 'shows K2.7 superior' if some scenario has K2.6<100% AND K2.7>K2.6.")

#!/usr/bin/env python3
"""Merge every A/B study's results into one CSV with a harness column.

Sources (all in this dir; missing ones are skipped):
  results.json        -> cline prompt-variant study (5 arms, K2.7)
  r_ocport_k27.json   -> cline oc-port study, K2.7
  r_ocport_k26.json   -> cline oc-port study, K2.6
  oc_results.json     -> opencode 2x2 (K2.6/K2.7 x default/custom), simple scenarios
  oc_deep_results.json-> opencode 2x2, DEEP scenarios (refactor/debug/implement)
  hcmp_cline.json     -> cross-harness comparison, cline side (K2.7, conc=1)
  hcmp_oc.json        -> cross-harness comparison, opencode side (K2.7, conc=1)

Cline-only metrics (discouraged/empty/mistk/iter) and opencode-only metrics
(tokens/cost) are left blank where N/A. Re-run after any study to refresh.
(bench_endpoints_results.json is a raw latency/throughput benchmark with a
different schema — not an A/B — so it is intentionally NOT merged here.)
"""
import csv, json
from pathlib import Path

D = Path(__file__).resolve().parent
COLS = ["study", "harness", "model", "provider", "sys", "trials", "pass_pct", "pass_at_k_pct",
        "pass_pow_k_pct", "tools_total", "tools_per_trial", "iter_per_trial",
        "duplicate", "discouraged", "empty_args", "mistake_exits", "bad_pct",
        "tokens", "cost_usd", "avg_latency_s", "total_latency_s"]

# Normalize the system-prompt label across harnesses:
#   default    = the harness's own built-in prompt (cline "control" / opencode default)
#   sharp      = the opencode "small sharp toolset" prompt (opencode custom arm)
#   sharp-port = that same prompt ported to cline's tool names (cline oc-port arm)
CLINE_SYS = {"control": "default", "oc-port": "sharp-port"}
rows = []


def _tot_dur(raw, arm):
    return sum(r["duration_s"] for r in raw if r["arm"] == arm)


def add_cline(fname, study, model, provider="fireworks"):
    if not (D / fname).exists():
        print(f"  skip (missing): {fname}")
        return
    d = json.load(open(D / fname))
    raw = d.get("raw", [])
    for s in d["summaries"]:
        n = s["trials"]
        tools = s.get("tool_calls", 0)
        tot = s.get("total_duration_s")
        if tot is None:
            tot = _tot_dur(raw, s["arm"])
        tpt = s.get("avg_tool_calls")
        if tpt is None:
            tpt = tools / n if n else 0
        it = s.get("avg_iterations")
        rows.append({
            "study": study, "harness": "cline", "model": model, "provider": provider,
            "sys": CLINE_SYS.get(s["arm"], s["arm"]),
            "trials": n, "pass_pct": round(s["pass_rate"] * 100),
            "pass_at_k_pct": round(s["pass_at_k"] * 100),
            "pass_pow_k_pct": round(s["pass_pow_k"] * 100),
            "tools_total": tools, "tools_per_trial": round(tpt, 2),
            "iter_per_trial": "" if it is None else round(it, 2),
            "duplicate": s.get("duplicate", ""), "discouraged": s.get("discouraged", ""),
            "empty_args": s.get("empty_args", ""), "mistake_exits": s.get("mistake_exits", ""),
            "bad_pct": round(s.get("bad_call_rate", 0) * 100),
            # cline reports usage in run_result; older result files predate capture
            # (-> total_tokens absent -> blank). cline's Fireworks provider gives no cost.
            "tokens": s.get("total_tokens") or "", "cost_usd": "",
            "avg_latency_s": round(s.get("avg_duration_s", 0), 1),
            "total_latency_s": round(tot, 1),
        })


def add_opencode(fname, study):
    if not (D / fname).exists():
        print(f"  skip (missing): {fname}")
        return
    d = json.load(open(D / fname))
    models = d.get("models", {})
    for s in d["summaries"]:
        arm = s["arm"]  # e.g. k2.6-default
        mk = "k2.6" if "k2.6" in arm else "k2.7"
        model = mk.upper()
        prefix = models.get(mk, "").split("/")[0]      # e.g. "fireworks-ai"
        provider = "fireworks" if "fireworks" in prefix else (prefix or "fireworks")
        cond = "sharp" if "custom" in arm else "default"
        rows.append({
            "study": study, "harness": "opencode", "model": model, "provider": provider,
            "sys": cond,
            "trials": s["trials"], "pass_pct": round(s["pass_rate"] * 100),
            "pass_at_k_pct": round(s["pass_at_k"] * 100),
            "pass_pow_k_pct": round(s["pass_pow_k"] * 100),
            "tools_total": s["tool_calls"], "tools_per_trial": round(s["avg_tool_calls"], 2),
            "iter_per_trial": "", "duplicate": s["duplicate"], "discouraged": "",
            "empty_args": "", "mistake_exits": "", "bad_pct": "",
            "tokens": s["tokens"], "cost_usd": round(s["cost"], 4),
            "avg_latency_s": round(s["avg_duration_s"], 1),
            "total_latency_s": round(s["total_duration_s"], 1),
        })


add_cline("results.json", "cline-prompts", "K2.7")
add_cline("r_ocport_k27.json", "cline-ocport", "K2.7")
add_cline("r_ocport_k26.json", "cline-ocport", "K2.6")
add_opencode("oc_results.json", "opencode-2x2")
add_opencode("oc_deep_results.json", "opencode-deep")
add_cline("hcmp_cline.json", "harness-cmp", "K2.7")
add_opencode("hcmp_oc.json", "harness-cmp")

out = D / "all_runs.csv"
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    w.writeheader()
    w.writerows(rows)
print(f"wrote {out}  ({len(rows)} rows)")

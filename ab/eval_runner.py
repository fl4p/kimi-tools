#!/usr/bin/env python3
"""Hardened SWE-bench eval driver.

Two reliability problems this fixes vs calling run_evaluation by hand:

1. **Contention flakes.** The `psf/requests` suite makes real httpbin calls in
   both FAIL_TO_PASS and PASS_TO_PASS tests. Running several `run_evaluation`
   jobs concurrently starved those calls -> 502 / JSONDecodeError -> *false*
   "unresolved" (e.g. k27_kimicline-1921/2317 were correct fixes killed by the
   network). So we run arms **strictly sequentially**.

2. **Silent false negatives.** After the first pass, any instance that is
   unresolved *with a non-empty patch* whose test log shows a network signature
   (502/503/ConnectionError/JSONDecodeError/Max retries) is **re-evaluated once
   in isolation**. If it then resolves, it was a flake, not a model failure.

Usage:
    DOCKER_HOST=$(docker context inspect colima -f '{{.Endpoints.docker.Host}}') \
    python3 eval_runner.py --report-dir /tmp/sweval_new \
        --arm default_k26 /tmp/preds_new_default_k26.jsonl \
        --arm claude_k27  /tmp/preds_new_claude_k27.jsonl ...
Writes <report-dir>/summary.json with per-arm resolved counts (raw + after
flake re-eval) and the list of instances reclassified as flakes.
"""
import argparse, glob, json, os, shutil, subprocess, sys
from pathlib import Path


def free_gb(path):
    return shutil.disk_usage(path).free / 1e9

NET_SIGNATURES = ["502", "503", "Bad Gateway", "ConnectionError",
                  "JSONDecodeError", "Max retries", "ConnectTimeout"]
DATASET = "princeton-nlp/SWE-bench_Verified"


def run_eval(preds, run_id, report_dir, workers, instances=None):
    """Invoke the official harness once; return (resolved_ids, submitted_ids)."""
    cmd = [sys.executable, "-m", "swebench.harness.run_evaluation",
           "--dataset_name", DATASET, "--predictions_path", str(preds),
           "--run_id", run_id, "--namespace", "swebench",
           "--max_workers", str(workers), "--report_dir", str(report_dir)]
    if instances:
        cmd += ["--instance_ids", *instances]
    subprocess.run(cmd, cwd=str(report_dir), check=False)
    rep = sorted(glob.glob(f"{report_dir}/*{run_id}.json"), key=os.path.getmtime)
    if not rep:
        return set(), set()
    d = json.load(open(rep[-1]))
    return set(d.get("resolved_ids", [])), set(d.get("submitted_ids", []))


def patch_is_empty(preds, iid):
    for line in open(preds):
        r = json.loads(line)
        if r["instance_id"] == iid:
            return not r.get("model_patch", "").strip()
    return True


def failure_is_network(report_dir, run_id, iid):
    """Did this unresolved instance fail only because of a network signature?"""
    cands = glob.glob(f"{report_dir}/logs/run_evaluation/{run_id}/*/{iid}/test_output.txt")
    if not cands:
        return False
    repf = Path(cands[0]).parent / "report.json"
    if not repf.exists():
        return False   # errored / timed-out instance (no report) — a real failure, not a recoverable flake
    out = open(cands[0]).read()
    rep = json.load(open(repf))[iid]["tests_status"]
    f2p_fail = rep["FAIL_TO_PASS"]["failure"]
    has_net = any(sig in out for sig in NET_SIGNATURES)
    # flake = the actual fix worked (no FAIL_TO_PASS failures) but a network sig appears
    return has_net and not f2p_fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-dir", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--arm", nargs=2, action="append", metavar=("NAME", "PREDS"),
                    required=True, help="arm name + predictions JSONL (repeatable)")
    ap.add_argument("--no-flake-reeval", action="store_true")
    ap.add_argument("--min-free-gb", type=float, default=0,
                    help="abort before an arm if the disk has less than this many GB "
                         "free (guards a near-full Docker root). 0 = off.")
    ap.add_argument("--disk-path", default="/",
                    help="filesystem to watch for --min-free-gb (the Docker root's mount)")
    args = ap.parse_args()
    report_dir = Path(args.report_dir); report_dir.mkdir(parents=True, exist_ok=True)

    summary = {}
    for name, preds in args.arm:                     # SEQUENTIAL — no contention
        if args.min_free_gb:
            avail = free_gb(args.disk_path)
            print(f"  [disk] {avail:.1f}G free on {args.disk_path}", flush=True)
            if avail < args.min_free_gb:
                print(f"ABORT: only {avail:.1f}G free < --min-free-gb {args.min_free_gb}. "
                      f"Stopping before {name} to protect the box. "
                      f"Free space or `docker system prune`, then resume with the "
                      f"remaining arms.", flush=True)
                break
        run_id = f"new_{name}"
        print(f"\n===== EVAL {name} ({preds}) =====", flush=True)
        resolved, submitted = run_eval(preds, run_id, report_dir, args.workers)
        unresolved = sorted(submitted - resolved)
        flakes = []
        if not args.no_flake_reeval:
            for iid in unresolved:
                try:
                    if patch_is_empty(preds, iid):
                        continue                      # empty patch = real miss, not a flake
                    if failure_is_network(report_dir, run_id, iid):
                        print(f"  re-eval (suspected network flake): {iid}", flush=True)
                        r2, _ = run_eval(preds, f"{run_id}_re", report_dir,
                                         1, instances=[iid])   # isolated, 1 worker
                        if iid in r2:
                            flakes.append(iid)
                except Exception as e:                # one bad instance must not abort the run
                    print(f"  flake-check skipped for {iid}: {e}", flush=True)
        resolved_final = set(resolved) | set(flakes)
        summary[name] = {
            "resolved_raw": len(resolved), "submitted": len(submitted),
            "resolved_after_reeval": len(resolved_final),
            "flakes_recovered": flakes,
            "still_unresolved": sorted(submitted - resolved_final),
        }
        print(f"  {name}: {len(resolved)}/{len(submitted)} raw"
              f" -> {len(resolved_final)}/{len(submitted)} after flake re-eval"
              f" (recovered {len(flakes)})", flush=True)

    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n=== SUMMARY ===")
    for name, s in summary.items():
        print(f"  {name:16} {s['resolved_after_reeval']}/{s['submitted']}"
              f"  (raw {s['resolved_raw']}, flakes {s['flakes_recovered']})")
    print(f"\nwrote {report_dir/'summary.json'}")


if __name__ == "__main__":
    main()

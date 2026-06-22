#!/usr/bin/env python3
"""SWE-bench (Verified) prediction harness — Kimi K2.6 vs K2.7 via opencode.

This is the part that needs NO Docker: it clones each instance's repo at the
base commit, runs opencode+Kimi on the issue text, and writes the resulting
`git diff` as a prediction in SWE-bench's format
({instance_id, model_name_or_path, model_patch}).

Scoring is the OFFICIAL `swebench.harness.run_evaluation`, which needs a
container runtime (Docker/podman). See README-swe.md for the eval command.

Subcommands:
  list     print instance_id / repo / difficulty (to pick a subset)
  predict  generate predictions for a model over chosen instances

Examples:
  python3 swe_bench.py list --limit 500 | sort -t'|' -k3      # browse by difficulty
  python3 swe_bench.py predict --model k2.6 --difficulty "<15 min fix" \\
      --limit 10 --out preds_k26.jsonl
  python3 swe_bench.py predict --model k2.7 --instances astropy__astropy-12907 \\
      --out preds_k27.jsonl

The prompt is opencode's DEFAULT agent (no custom system prompt) so the only
variable between two prediction files is the model — same design as the
scenario A/B.
"""
import argparse
import csv
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ab_opencode import MODELS, VARIANTS, parse_opencode  # noqa: E402

DATASET = "princeton-nlp/SWE-bench_Verified"
CUSTOM_AGENT = "kimi-sys"   # name of the seeded custom-prompt agent (opencode.json)
CACHE = Path(os.environ.get("SWE_CACHE", Path.home() / ".cache" / "swebench-kimi"))
REPOS = CACHE / "repos"
DS_URL = ("https://datasets-server.huggingface.co/rows?dataset="
          "princeton-nlp%2FSWE-bench_Verified&config=default&split=test"
          "&offset={off}&length=100")

PROMPT_TMPL = (
    "You are working inside a checked-out copy of the `{repo}` repository at a "
    "specific commit. There is a bug or missing feature described below. Fix it "
    "by editing the repository's SOURCE files so the described behavior is "
    "correct.\n\n"
    "Rules:\n"
    "- Do NOT modify, add, or delete any test files (anything under a tests/ or "
    "test/ directory, or files matching test_*.py / *_test.py). The hidden grading "
    "tests will be supplied separately.\n"
    "- Make the smallest change that correctly resolves the issue.\n"
    "- You may read any files you need to understand the code first.\n"
    "- Work autonomously to completion: once you understand the bug, you MUST EDIT "
    "the source file(s) to fix it — do not stop at analysis or reproduction. A run "
    "that only investigates and leaves the code unchanged is a failure. Apply the "
    "fix, then finish.\n\n"
    "=== ISSUE ===\n{problem}\n"
)


# --------------------------------------------------------------------------- #
# Dataset access (via HF datasets-server REST — no `datasets` lib needed)
# --------------------------------------------------------------------------- #
def fetch_all() -> list[dict]:
    """All 500 Verified rows, cached locally as one JSON."""
    cache = CACHE / "verified.json"
    if cache.exists():
        return json.loads(cache.read_text())
    CACHE.mkdir(parents=True, exist_ok=True)
    rows = []
    for off in range(0, 500, 100):
        req = urllib.request.Request(DS_URL.format(off=off),
                                     headers={"User-Agent": "swe-kimi/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        rows += [x["row"] for x in data["rows"]]
        print(f"  fetched {len(rows)}/500", file=sys.stderr)
    cache.write_text(json.dumps(rows))
    return rows


def select(rows, instances=None, repos=None, difficulty=None, limit=None):
    out = rows
    if instances:
        want = set(instances)
        out = [r for r in out if r["instance_id"] in want]
    if repos:
        want = set(repos)
        out = [r for r in out if r["repo"] in want]
    if difficulty:
        out = [r for r in out if r.get("difficulty") == difficulty]
    if limit:
        out = out[:limit]
    return out


# --------------------------------------------------------------------------- #
# Repo materialization
# --------------------------------------------------------------------------- #
def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def mirror(repo: str) -> Path:
    """Ensure a local bare mirror of github.com/<repo>; return its path."""
    REPOS.mkdir(parents=True, exist_ok=True)
    path = REPOS / (repo.replace("/", "__") + ".git")
    if path.exists():
        return path
    url = f"https://github.com/{repo}.git"
    print(f"  mirroring {repo} (first use, may be large)...", file=sys.stderr)
    r = _run(["git", "clone", "--mirror", url, str(path)])
    if r.returncode != 0:
        raise RuntimeError(f"clone {repo} failed: {r.stderr[:200]}")
    return path


def materialize(repo: str, base_commit: str) -> Path:
    """Fresh worktree of <repo> checked out at <base_commit>."""
    m = mirror(repo)
    wd = Path(tempfile.mkdtemp(prefix="swe_"))
    r = _run(["git", "clone", "--shared", "--no-checkout", str(m), str(wd)])
    if r.returncode != 0:
        shutil.rmtree(wd, ignore_errors=True)
        raise RuntimeError(f"local clone failed: {r.stderr[:200]}")
    co = _run(["git", "-C", str(wd), "checkout", "-q", base_commit])
    if co.returncode != 0:
        shutil.rmtree(wd, ignore_errors=True)
        raise RuntimeError(f"checkout {base_commit[:8]} failed: {co.stderr[:200]}")
    return wd


def test_files_of(test_patch: str) -> list[str]:
    """Paths touched by the grading test_patch — excluded from the model patch."""
    return sorted(set(re.findall(r"^diff --git a/(\S+) b/\S+", test_patch, re.M)))


def parse_codex(stdout: str):
    """Best-effort: pull total token usage + tool/command count from codex --json
    JSONL. Schema varies across versions, so be tolerant; metrics are secondary
    (the resolved-rate is what matters)."""
    tokens = None
    tools = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        blob = json.dumps(e)
        if '"command"' in blob or '"exec_command' in blob or 'function_call' in blob:
            tools += 1
        # token usage often under a token_count/usage event with total_tokens
        for k in ("total_token_usage", "token_usage", "usage", "info"):
            u = e.get(k) if isinstance(e, dict) else None
            if isinstance(u, dict):
                tot = u.get("total_tokens") or u.get("total")
                if isinstance(tot, int):
                    tokens = tot
    return tokens, (tools or None)


def extract_patch(wd: Path, test_files: list[str]) -> str:
    """Staged diff vs base_commit (HEAD), excluding the grading test files and any
    agent-created scratch. `git add -A` so newly-created SOURCE files are captured.

    Agents routinely litter the workdir with throwaway dirs — pip user-base/cache
    (PYTHONUSERBASE/PIP_CACHE_DIR live inside the workdir, see predict_one),
    virtualenvs (`.venv*`), vendored libs (`_pylibs`), reproduction projects
    (`repro_docs`, `testproj`) — which `git add -A` would otherwise sweep into the
    patch (tens of MB of site-packages, breaking grading). Rather than blacklist an
    open-ended set of names, drop any newly-created TOP-LEVEL path that did not exist
    in the repo at base_commit (HEAD — the agent's edits aren't committed). Real
    edits and new files under existing package dirs are kept."""
    _run(["git", "-C", str(wd), "add", "-A"])
    base = set(_run(["git", "-C", str(wd), "ls-tree", "--name-only", "-z", "HEAD"]
                    ).stdout.split("\0"))
    staged = _run(["git", "-C", str(wd), "diff", "--cached", "--name-only", "-z"]
                  ).stdout.split("\0")
    new_tops = {p.split("/", 1)[0] for p in staged if p} - base
    excludes = list(test_files) + ["opencode.json"] + sorted(new_tops)
    pathspec = ["--", "."] + [f":(exclude){f}" for f in excludes]
    r = _run(["git", "-C", str(wd), "diff", "--cached"] + pathspec)
    return r.stdout


# --------------------------------------------------------------------------- #
# Predict
# --------------------------------------------------------------------------- #
def predict_one(inst: dict, model_key: str, opencode_bin: str, timeout: int,
                save_logs: Path | None, agent_prompt: Path | None = None,
                backend: str = "opencode"):
    repo, iid = inst["repo"], inst["instance_id"]
    base = inst["base_commit"]
    wd = materialize(repo, base)
    try:
        prompt = PROMPT_TMPL.format(repo=repo, problem=inst["problem_statement"])
        if backend == "codex":
            # Codex CLI brings its OWN system prompt (the gpt-5.x-codex coding
            # prompt) — this is the faithful "Kimi default coding agent" path.
            # model_key here is a literal codex model (e.g. gpt-5.2-codex). The
            # workdir is a throwaway clone of a public repo, so bypass sandbox/
            # approvals for full non-interactivity.
            cmd = [opencode_bin, "exec", "--json",
                   "--dangerously-bypass-approvals-and-sandbox",
                   "-C", str(wd), "-m", model_key, prompt]
        else:
            cmd = [opencode_bin, "run", "-m", MODELS[model_key],
                   "--dir", str(wd), "--format", "json"]
            if agent_prompt:
                # opencode has no --system flag: a custom system prompt is a custom
                # primary AGENT whose prompt body = the file. Seed a per-workdir
                # opencode.json and select it. (excluded from the model_patch above.)
                cfg = {"$schema": "https://opencode.ai/config.json",
                       "agent": {CUSTOM_AGENT: {"mode": "primary",
                                                "prompt": "{file:" + str(agent_prompt) + "}"}}}
                (wd / "opencode.json").write_text(json.dumps(cfg, indent=2))
                cmd += ["--agent", CUSTOM_AGENT]
            # Reasoning-effort arms (e.g. Opus 4.8 high/xhigh) share a model id and
            # differ only by --variant. Fireworks arms have no entry -> no flag.
            if VARIANTS.get(model_key):
                cmd += ["--variant", VARIANTS[model_key]]
            cmd += [prompt]
        # HARDENING: agents often `pip install -e .` / install deps to run the
        # repo's tests. Without isolation that lands in the HOST's ~/.local
        # (--user / --break-system-packages) and persists. PYTHONUSERBASE
        # redirects user-site into the throwaway workdir, which is rmtree'd below,
        # so nothing pollutes the host. PIP_CACHE_DIR keeps cache local too.
        env = {**os.environ,
               "PYTHONUSERBASE": str(wd / ".pyuserbase"),
               "PIP_CACHE_DIR": str(wd / ".pipcache")}
        start = time.perf_counter()
        err = None
        # IMPORTANT: cwd=wd. Running opencode from elsewhere (e.g. inside this repo)
        # makes it inherit the *wrong* project config (.opencode/, AGENTS) and scan
        # the wrong tree -> it never converges and times out empty.
        # stdin=DEVNULL: codex exec otherwise blocks "Reading additional input from
        # stdin..." when stdin isn't a TTY. Harmless for opencode.
        # start_new_session=True puts opencode AND its grandchildren (node, model/tool
        # subprocesses) in one process group; on timeout we kill the whole group via
        # killpg. Plain subprocess.run timeout only kills the direct child, orphaning
        # the grandchildren -> stale opencode trees that pile up CPU and survive a
        # pkill of this python process.
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, cwd=str(wd), env=env,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            rc = proc.returncode
            if rc != 0:
                err = f"exit {rc}: {stderr.strip()[:160]}"
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            proc.wait()
            stdout, stderr, err = "", "timeout", "timeout"
        dur = time.perf_counter() - start

        if save_logs:
            save_logs.mkdir(parents=True, exist_ok=True)
            (save_logs / f"{iid}__{model_key}.json").write_text(stdout or "")
            if stderr.strip():
                (save_logs / f"{iid}__{model_key}.stderr.txt").write_text(stderr)

        if backend == "codex":
            tokens, tool_calls = parse_codex(stdout) if stdout else (None, None)
            cost = None
            label = f"codex-{model_key}"
        else:
            parse = parse_opencode(stdout) if stdout else None
            tokens = getattr(parse, "tokens", None)
            tool_calls = getattr(parse, "tool_calls", None)
            cost = getattr(parse, "cost", None)
            label = (f"kimi-{model_key}"
                     if MODELS[model_key].startswith("fireworks") else f"oc-{model_key}")
        patch = extract_patch(wd, test_files_of(inst["test_patch"]))
        meta = {
            "instance_id": iid, "repo": repo, "model": model_key,
            "duration_s": round(dur, 1),
            "empty_patch": not patch.strip(),
            "patch_bytes": len(patch),
            "tool_calls": tool_calls,
            "tokens": tokens,
            "cost": cost,
            "error": err,
        }
        pred = {
            "instance_id": iid,
            "model_name_or_path": label,
            "model_patch": patch,
        }
        return pred, meta
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def cmd_predict(args):
    if getattr(args, "dataset_jsonl", None):
        rows = [json.loads(l) for l in open(args.dataset_jsonl) if l.strip()]
    else:
        rows = fetch_all()
    insts = select(rows, args.instances, args.repos, args.difficulty, args.limit)
    if not insts:
        sys.exit("no instances matched the selection")
    out = Path(args.out)
    logs = Path(args.save_logs) if args.save_logs else None
    agent_prompt = None
    if args.agent_prompt:
        if args.backend == "codex":
            sys.exit("--agent-prompt is opencode-only (codex brings its own prompt)")
        agent_prompt = Path(args.agent_prompt).resolve()
        if not agent_prompt.exists():
            sys.exit(f"--agent-prompt file not found: {agent_prompt}")
    if args.backend == "opencode" and args.model not in MODELS:
        sys.exit(f"--model must be one of {list(MODELS)} for the opencode backend")
    bin_ = args.bin or ("codex" if args.backend == "codex" else "opencode")
    label_prefix = "codex" if args.backend == "codex" else "kimi"
    print(f"SWE-bench predict [{args.backend}]: {len(insts)} instances x "
          f"model={args.model} "
          f"prompt={'sharp:' + agent_prompt.name if agent_prompt else 'default'} "
          f"-> {out}", file=sys.stderr)
    preds, metas = [], []
    with open(out, "w") as fh:
        for i, inst in enumerate(insts, 1):
            iid = inst["instance_id"]
            pred = meta = None
            # HARDENING: retry empty/hung results. A predict that times out or
            # hangs on the Fireworks call yields an empty patch (e.g. requests-6028);
            # without a retry that instance is silently lost. A non-empty patch is
            # accepted on the first attempt — we only retry failures.
            for attempt in range(1, args.retries + 2):
                try:
                    pred, meta = predict_one(inst, args.model, bin_,
                                             args.timeout, logs, agent_prompt,
                                             backend=args.backend)
                except Exception as e:  # noqa: BLE001 — one bad repo shouldn't kill the run
                    meta = {"instance_id": iid, "error": f"harness:{e}", "empty_patch": True}
                    pred = {"instance_id": iid,
                            "model_name_or_path": f"{label_prefix}-{args.model}", "model_patch": ""}
                meta["attempts"] = attempt
                if not meta.get("empty_patch") or attempt > args.retries:
                    break
                why = "timeout/hang" if meta.get("error") == "timeout" else "empty patch"
                print(f"  [{i}/{len(insts)}] {iid:<28} retry {attempt}/{args.retries} ({why})",
                      file=sys.stderr)
            fh.write(json.dumps(pred) + "\n")
            fh.flush()
            preds.append(pred)
            metas.append(meta)
            tag = "EMPTY" if meta.get("empty_patch") else f"{meta.get('patch_bytes','?')}B"
            atag = f"x{meta['attempts']}" if meta.get("attempts", 1) > 1 else ""
            print(f"  [{i}/{len(insts)}] {iid:<28} {tag:>7} {atag:<3} "
                  f"{meta.get('duration_s','?')}s {meta.get('error') or ''}",
                  file=sys.stderr)
    (out.with_suffix(".meta.json")).write_text(json.dumps(metas, indent=2))
    n_empty = sum(1 for m in metas if m.get("empty_patch"))
    print(f"\nwrote {out}  ({len(preds)} preds, {n_empty} empty patches)",
          file=sys.stderr)


def cmd_list(args):
    rows = fetch_all()
    insts = select(rows, args.instances, args.repos, args.difficulty, args.limit)
    for r in insts:
        n_f2p = len(json.loads(r["FAIL_TO_PASS"])) if r.get("FAIL_TO_PASS") else 0
        print(f"{r['instance_id']:<32} | {r['repo']:<28} | "
              f"{r.get('difficulty','?'):<14} | F2P={n_f2p}")
    print(f"# {len(insts)} instances", file=sys.stderr)


# columns of bake-off-cost.csv (what make_cost_charts.py reads)
COST_COLS = ["prompt", "model", "resolved", "total", "tokens_m", "tool_calls"]
MODEL_LABEL = {"k2.6": "K2.6", "k2.7": "K2.7", "glm5.2": "GLM-5.2",
               "opus4.8-high": "Opus-4.8-high", "opus4.8-xhigh": "Opus-4.8-xhigh"}


def _resolved_from_report(path: Path):
    """Pull (resolved, total) out of a swebench run_evaluation report JSON."""
    rep = json.loads(Path(path).read_text())
    # total = the GRADED band, not total_instances (which swebench 4.1.0 sets to the
    # whole --dataset_name size, e.g. 500, even when only 8 were graded -> wrong denom).
    total = rep.get("submitted_instances") or len(rep.get("submitted_ids", [])) \
        or rep.get("total_instances") or None
    resolved = rep.get("resolved_instances")
    if resolved is None and "resolved_ids" in rep:
        resolved = len(rep["resolved_ids"])
    return resolved, total


def cmd_aggregate(args):
    """Reduce a predict `*.meta.json` (per-instance array) to one cost-profile
    row and upsert it into bake-off-cost.csv — the file the chart tool reads.
    Resolved count comes from the separate swebench eval (`--resolved 6/8` or
    `--report <run_evaluation .json>`)."""
    metas = json.loads(Path(args.meta).read_text())
    n = len(metas)
    if not n:
        sys.exit(f"{args.meta}: no instances")

    def avg(key, scale=1.0):
        vals = [m[key] for m in metas if m.get(key) is not None]
        return round(sum(vals) / len(vals) / scale, 1) if vals else ""

    model = args.model_label or MODEL_LABEL.get(
        (metas[0].get("model") or "").lower(), metas[0].get("model", "?"))

    if args.report:
        resolved, total = _resolved_from_report(args.report)
    elif args.resolved:
        resolved, _, total = args.resolved.partition("/")
        resolved, total = int(resolved), int(total or n)
    else:
        resolved, total = "", n

    # tokens_m = mean per-instance tokens x band size, so arms with missing logs
    # (n < band) stay comparable instead of undercounting the raw sum. Band size =
    # the resolved denominator when known, else the metered instance count.
    band = total if isinstance(total, int) and total else n
    _mt = avg("tokens")
    row = {"prompt": args.prompt, "model": model,
           "resolved": resolved, "total": total,
           "tokens_m": round(_mt * band / 1_000_000.0, 1) if _mt else "",
           "tool_calls": round(avg("tool_calls") or 0)}

    csv_path = Path(args.csv)
    rows = []
    if csv_path.exists():
        with open(csv_path, newline="") as fh:
            rows = [r for r in csv.DictReader(fh)
                    if not (r["prompt"] == row["prompt"] and r["model"] == row["model"])]
    rows.append(row)
    rows.sort(key=lambda r: (r["prompt"], r["model"]))
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COST_COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"upserted {row['prompt']}/{row['model']} "
          f"(resolved={resolved}/{total}, {row['tokens_m']}M, "
          f"{row['tool_calls']} tools) -> {csv_path}",
          file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="SWE-bench Verified predict harness (Kimi via opencode)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--instances", type=lambda s: s.split(","),
                        help="comma-separated instance_ids")
    common.add_argument("--repos", type=lambda s: s.split(","),
                        help="comma-separated repos (owner/name)")
    common.add_argument("--difficulty", help='exact difficulty label, e.g. "<15 min fix"')
    common.add_argument("--limit", type=int, help="cap number of instances")
    common.add_argument("--dataset-jsonl", dest="dataset_jsonl",
                        help="load instances from a local JSONL (rows with repo/"
                             "base_commit/problem_statement/...) instead of SWE-bench Verified; "
                             "for fresh/post-cutoff sets like SWE-rebench")

    pl = sub.add_parser("list", parents=[common])
    pl.set_defaults(func=cmd_list)

    pp = sub.add_parser("predict", parents=[common])
    pp.add_argument("--backend", choices=["opencode", "codex"], default="opencode",
                    help="opencode (Kimi) or codex (Kimi's default coding agent)")
    pp.add_argument("--model", required=True,
                    help=f"opencode: one of {list(MODELS)}; codex: a codex model "
                         "(e.g. gpt-5.2-codex)")
    pp.add_argument("--out", required=True, help="predictions JSONL path")
    pp.add_argument("--bin", help="agent binary (default: opencode or codex per --backend)")
    pp.add_argument("--timeout", type=int, default=600, help="per-instance seconds")
    pp.add_argument("--retries", type=int, default=1,
                    help="retry an instance this many times if it yields an empty/hung "
                         "patch (default 1 = up to 2 attempts). Guards against Fireworks "
                         "call hangs that would otherwise lose the instance.")
    pp.add_argument("--agent-prompt", help="custom system prompt file (e.g. sharp.md); "
                    "seeds an opencode.json custom agent. Omit = opencode default prompt.")
    pp.add_argument("--save-logs", help="dir for raw opencode json per instance")
    pp.set_defaults(func=cmd_predict)

    pa = sub.add_parser("aggregate", help="reduce a predict *.meta.json to one "
                        "cost-profile CSV row (the file make_cost_charts.py reads)")
    pa.add_argument("--meta", required=True, help="a predict *.meta.json (per-instance array)")
    pa.add_argument("--prompt", required=True, help="arm/prompt label, e.g. claude-code")
    pa.add_argument("--model-label", help="e.g. K2.6 (default: inferred from meta's model field)")
    g = pa.add_mutually_exclusive_group()
    g.add_argument("--resolved", help='resolved count as "N/M", e.g. 8/8')
    g.add_argument("--report", help="a swebench run_evaluation report JSON to read resolved from")
    pa.add_argument("--csv", default=str(Path(__file__).resolve().parent / "bake-off-cost.csv"),
                    help="output CSV (default: ab/bake-off-cost.csv)")
    pa.set_defaults(func=cmd_aggregate)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

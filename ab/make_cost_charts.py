#!/usr/bin/env python3
"""Render the bake-off cost profile as grouped-bar SVG charts.

Reads ab/bake-off-cost.csv — the benchmark-generated data file (produced by
`swe_bench.py aggregate`, which reduces each predict `*.meta.json` to one row).
Nothing is hard-coded here; edit the CSV (or re-run aggregate) and re-run this.

Pure stdlib (no matplotlib) — keeps the repo dependency-free and the SVG output
diff-friendly and GitHub-renderable. Writes charts/cost-{latency,tokens,tools}.svg,
which FINDINGS-swe.md and the README embed.

    python3 make_cost_charts.py
"""
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "bake-off-cost.csv"
OUT = HERE / "charts"
OUT.mkdir(exist_ok=True)

# theme (matches ab/bake-off.html)
BG, FG, MUTED, GRID = "#111", "#ddd", "#888", "#333"
COLORS = ["#6aa9ff", "#f0a35e"]  # one per model, in first-seen order
W, H = 760, 400
ML, MR, MT, MB = 72, 20, 56, 84
PW, PH = W - ML - MR, H - MT - MB
PX0, PY0 = ML, MT + PH  # bottom-left of plot


def load(path):
    """CSV -> (prompts, models, {metric: {prompt: {model: value}}}), order preserved."""
    prompts, models, data = [], [], {}
    metrics = {"latency_s": "latency", "tokens_k": "tokens", "tool_calls": "tools"}
    for m in metrics.values():
        data[m] = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            p, mdl = r["prompt"], r["model"]
            if p not in prompts:
                prompts.append(p)
            if mdl not in models:
                models.append(mdl)
            for col, m in metrics.items():
                data[m].setdefault(p, {})[mdl] = float(r[col])
    return prompts, models, data


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def chart(title, unit, prompts, models, series, ymax, ticks, suffix, decimals=0):
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="-apple-system,Segoe UI,Roboto,sans-serif">']
    s.append(f'<rect width="{W}" height="{H}" fill="{BG}" rx="8"/>')
    s.append(f'<text x="{ML}" y="30" fill="{FG}" font-size="16" font-weight="600">{esc(title)}</text>')
    s.append(f'<text x="{W-MR}" y="30" fill="{MUTED}" font-size="11" text-anchor="end">{esc(unit)}</text>')

    for t in ticks:  # y gridlines + labels
        y = PY0 - PH * (t / ymax)
        s.append(f'<line x1="{PX0}" y1="{y:.1f}" x2="{PX0+PW}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        s.append(f'<text x="{PX0-8}" y="{y+4:.1f}" fill="{MUTED}" font-size="11" text-anchor="end">{t}</text>')

    nb = len(models)
    gw = PW / len(prompts)          # group width
    bw = min(30, (gw - 24) / nb)    # bar width fits the group
    span = bw * nb + 8 * (nb - 1)   # total width of the bars in a group
    for i, p in enumerate(prompts):
        cx = PX0 + gw * i + gw / 2  # group center
        x = cx - span / 2
        for j, mdl in enumerate(models):
            v = series[p][mdl]
            bh = PH * (v / ymax)
            y = PY0 - bh
            s.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:g}" height="{bh:.1f}" '
                     f'fill="{COLORS[j % len(COLORS)]}" rx="2"/>')
            s.append(f'<text x="{x+bw/2:.1f}" y="{y-5:.1f}" fill="{FG}" font-size="10.5" '
                     f'text-anchor="middle">{v:.{decimals}f}{suffix}</text>')
            x += bw + 8
        s.append(f'<text x="{cx:.1f}" y="{PY0+18}" fill="{FG}" font-size="11.5" '
                 f'text-anchor="middle">{esc(p)}</text>')

    s.append(f'<line x1="{PX0}" y1="{PY0}" x2="{PX0+PW}" y2="{PY0}" stroke="{MUTED}" stroke-width="1"/>')
    lx = ML  # legend
    for j, mdl in enumerate(models):
        s.append(f'<rect x="{lx}" y="{H-31}" width="12" height="12" fill="{COLORS[j % len(COLORS)]}" rx="2"/>')
        s.append(f'<text x="{lx+18}" y="{H-21}" fill="{FG}" font-size="12">{esc(mdl)}</text>')
        lx += 72
    s.append('</svg>')
    return "\n".join(s)


def main():
    prompts, models, data = load(DATA)
    specs = [
        ("latency", "Avg latency per instance — by prompt × model",
         "seconds (lower is better)", 300, [0, 75, 150, 225, 300], "s", 0),
        ("tokens", "Avg tokens per instance — by prompt × model",
         "thousands of tokens (lower is better)", 1000, [0, 250, 500, 750, 1000], "k", 0),
        ("tools", "Avg tool calls per instance — by prompt × model",
         "tool calls (lower is better)", 32, [0, 8, 16, 24, 32], "", 1),
    ]
    for metric, title, unit, ymax, ticks, suffix, decimals in specs:
        svg = chart(title, unit, prompts, models, data[metric], ymax, ticks, suffix, decimals)
        (OUT / f"cost-{metric}.svg").write_text(svg)
    print(f"wrote cost-{{latency,tokens,tools}}.svg to {OUT} (from {DATA.name})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Render the harder-band bake-off as grouped-bar SVG charts.

Reads ab/bake-off-cost.csv — one row per (prompt, model) over the 48-instance
harder band (resolved out of the 43 comparable instances; see FINDINGS-swe.md).
Nothing is hard-coded here; edit the CSV and re-run.

Pure stdlib (no matplotlib) — keeps the repo dependency-free and the SVG output
diff-friendly and GitHub-renderable. Writes charts/bakeoff-{resolved,tokens,
tools}.svg, which FINDINGS-swe.md and the README embed.

    python3 make_cost_charts.py
"""
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "bake-off-cost.csv"
OUT = HERE / "charts"
OUT.mkdir(exist_ok=True)

# theme (dark, GitHub-renderable)
BG, FG, MUTED, GRID = "#111", "#ddd", "#888", "#333"
COLORS = ["#6aa9ff", "#f0a35e", "#7ed09a", "#c792ea"]  # one per model, first-seen order
W, H = 760, 400
ML, MR, MT, MB = 72, 20, 56, 84
PW, PH = W - ML - MR, H - MT - MB
PX0, PY0 = ML, MT + PH  # bottom-left of plot


def load(path):
    """CSV -> (prompts, models, {metric: {prompt: {model: value}}}), order preserved."""
    prompts, models = [], []
    data = {"resolved": {}, "tokens": {}, "tools": {}}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            p, mdl = r["prompt"], r["model"]
            if p not in prompts:
                prompts.append(p)
            if mdl not in models:
                models.append(mdl)
            data["resolved"].setdefault(p, {})[mdl] = float(r["resolved"])
            data["tokens"].setdefault(p, {})[mdl] = float(r["tokens_m"])
            data["tools"].setdefault(p, {})[mdl] = float(r["tool_calls"])
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
        s.append(f'<text x="{PX0-8}" y="{y+4:.1f}" fill="{MUTED}" font-size="11" text-anchor="end">{t:g}</text>')

    nb = len(models)
    gw = PW / len(prompts)          # group width
    gap = 5
    bw = min(24, (gw - 22) / nb)    # bar width fits the group, with padding
    span = bw * nb + gap * (nb - 1) # total width of the bars in a group
    for i, p in enumerate(prompts):
        cx = PX0 + gw * i + gw / 2  # group center
        x = cx - span / 2
        for j, mdl in enumerate(models):
            v = series[p].get(mdl)  # a model may not run every prompt -> empty slot
            if v is not None:
                bh = PH * (v / ymax)
                y = PY0 - bh
                s.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:g}" height="{bh:.1f}" '
                         f'fill="{COLORS[j % len(COLORS)]}" rx="2"/>')
                s.append(f'<text x="{x+bw/2:.1f}" y="{y-5:.1f}" fill="{FG}" font-size="10" '
                         f'text-anchor="middle">{v:.{decimals}f}{suffix}</text>')
            x += bw + gap
        s.append(f'<text x="{cx:.1f}" y="{PY0+18}" fill="{FG}" font-size="11.5" '
                 f'text-anchor="middle">{esc(p)}</text>')

    s.append(f'<line x1="{PX0}" y1="{PY0}" x2="{PX0+PW}" y2="{PY0}" stroke="{MUTED}" stroke-width="1"/>')
    lx = ML  # legend — adaptive spacing so long labels (e.g. Opus-xhigh) don't collide
    for j, mdl in enumerate(models):
        s.append(f'<rect x="{lx:.0f}" y="{H-31}" width="12" height="12" fill="{COLORS[j % len(COLORS)]}" rx="2"/>')
        s.append(f'<text x="{lx+18:.0f}" y="{H-21}" fill="{FG}" font-size="12">{esc(mdl)}</text>')
        lx += 30 + len(mdl) * 7.2
    s.append('</svg>')
    return "\n".join(s)


def main():
    prompts, models, data = load(DATA)
    specs = [
        ("resolved", "Resolved — by prompt × model (harder band)",
         "instances resolved / 43 (higher is better)", 43, [0, 10, 20, 30, 40], "", 0),
        ("tokens", "Tokens per arm — by prompt × model",
         "millions, 48 instances (lower is better)", 70, [0, 14, 28, 42, 56, 70], "M", 0),
        ("tools", "Tool calls per instance — by prompt × model",
         "avg calls (lower is better)", 45, [0, 15, 30, 45], "", 0),
    ]
    for metric, title, unit, ymax, ticks, suffix, decimals in specs:
        svg = chart(title, unit, prompts, models, data[metric], ymax, ticks, suffix, decimals)
        (OUT / f"bakeoff-{metric}.svg").write_text(svg)
    print(f"wrote bakeoff-{{resolved,tokens,tools}}.svg to {OUT} (from {DATA.name})")


if __name__ == "__main__":
    main()

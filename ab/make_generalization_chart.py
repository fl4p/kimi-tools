#!/usr/bin/env python3
"""Render the contamination/overfit visual: a slopegraph of the SAME models on a
memorizable benchmark (SWE-bench Verified, this repo) vs a decontaminated one
(DeepSWE, https://deepswe.datacurve.ai/ — 113 tasks written from scratch). The lines
REORDER: K2.7 tops Verified and is last on DeepSWE — the textbook contamination signature.

Pure stdlib SVG (no matplotlib). Writes charts/generalization.svg. Data is the published
pass@1 / resolved-rate for the three models the two benchmarks share; edit MODELS to update.

    python3 make_generalization_chart.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "charts"
OUT.mkdir(exist_ok=True)

# (model, SWE-bench Verified %, DeepSWE %, colour)
# Verified = this repo's best-arm resolved rate /48; DeepSWE = published pass@1 (from-scratch).
MODELS = [
    ("Opus-4.8",  83, 59, "#7ed09a"),
    ("GLM-5.2",   83, 44, "#6aa9ff"),
    ("K2.7",      88, 31, "#f0a35e"),
]
COLS = [("SWE-bench Verified", "memorizable — public, pre-cutoff"),
        ("DeepSWE", "decontaminated — written from scratch")]

BG, FG, MUTED, GRID = "#111", "#ddd", "#888", "#333"
W, H = 620, 440
ML, MR, MT, MB = 120, 120, 64, 56
PW, PH = W - ML - MR, H - MT - MB
YMAX = 100
xL, xR = ML, ML + PW


def y(v):
    return MT + PH * (1 - v / YMAX)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="-apple-system,Segoe UI,Roboto,sans-serif">']
    s.append(f'<rect width="{W}" height="{H}" fill="{BG}" rx="8"/>')
    s.append(f'<text x="{ML}" y="28" fill="{FG}" font-size="16" font-weight="600">'
             f'Same models, two benchmarks — the ranking inverts</text>')
    s.append(f'<text x="{ML}" y="46" fill="{MUTED}" font-size="11">'
             f'resolved / pass@1 (%). The lines crossing = SWE-bench Verified rank is largely contamination.</text>')

    # gridlines
    for t in (0, 25, 50, 75, 100):
        yy = y(t)
        s.append(f'<line x1="{xL}" y1="{yy:.1f}" x2="{xR}" y2="{yy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        s.append(f'<text x="{xL-10}" y="{yy+4:.1f}" fill="{MUTED}" font-size="11" text-anchor="end">{t}</text>')

    # axis column labels
    for i, (name, sub) in enumerate(COLS):
        cx = xL if i == 0 else xR
        anc = "start" if i == 0 else "end"
        s.append(f'<text x="{cx:.0f}" y="{MT+PH+24}" fill="{FG}" font-size="12.5" '
                 f'font-weight="600" text-anchor="{anc}">{esc(name)}</text>')
        s.append(f'<text x="{cx:.0f}" y="{MT+PH+40}" fill="{MUTED}" font-size="10" '
                 f'text-anchor="{anc}">{esc(sub)}</text>')

    # de-collide labels per side (dots stay at the true y; labels get nudged apart)
    def label_ys(vals):
        items = sorted([[y(v), i] for i, v in enumerate(vals)], key=lambda t: t[0])
        for k in range(1, len(items)):
            if items[k][0] - items[k - 1][0] < 16:
                items[k][0] = items[k - 1][0] + 16
        return {i: ly for ly, i in items}
    lyL = label_ys([m[1] for m in MODELS])
    lyR = label_ys([m[2] for m in MODELS])

    # lines + dots first (so labels sit on top)
    for name, a, b, col in MODELS:
        s.append(f'<line x1="{xL}" y1="{y(a):.1f}" x2="{xR}" y2="{y(b):.1f}" stroke="{col}" stroke-width="2.5"/>')
        s.append(f'<circle cx="{xL}" cy="{y(a):.1f}" r="4.5" fill="{col}"/>')
        s.append(f'<circle cx="{xR}" cy="{y(b):.1f}" r="4.5" fill="{col}"/>')
    for i, (name, a, b, col) in enumerate(MODELS):
        s.append(f'<text x="{xL-14}" y="{lyL[i]+4:.1f}" fill="{col}" font-size="12.5" '
                 f'font-weight="600" text-anchor="end">{esc(name)} {a}%</text>')
        s.append(f'<text x="{xR+14}" y="{lyR[i]+4:.1f}" fill="{col}" font-size="12.5" '
                 f'font-weight="600" text-anchor="start">{b}%</text>')

    s.append('</svg>')
    (OUT / "generalization.svg").write_text("\n".join(s))
    print(f"wrote generalization.svg to {OUT}")


if __name__ == "__main__":
    main()

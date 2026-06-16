#!/usr/bin/env python3
"""Render the FINDINGS-swe.md cost-profile table as grouped-bar SVG charts.

Pure stdlib (no matplotlib) — keeps the repo dependency-free and the output
diff-friendly. Writes charts/cost-latency.svg and charts/cost-tokens.svg, which
FINDINGS-swe.md and the README embed. Data is the per-instance (n=8) averages
from the "System-prompt bake-off → Cost profile" section; keep them in sync.

    python3 make_cost_charts.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "charts"
OUT.mkdir(exist_ok=True)

# prompt -> (K2.6 value, K2.7 value).  Order = the bake-off table order.
PROMPTS = ["default", "sharp", "cursor", "codex-coding", "claude-code", "cline"]
LATENCY = {  # avg wall-clock seconds / instance
    "default": (95, 72), "sharp": (87, 86), "cursor": (149, 254),
    "codex-coding": (93, 158), "claude-code": (123, 178), "cline": (140, 295),
}
TOKENS = {  # avg tokens / instance, in thousands
    "default": (731, 728), "sharp": (652, 530), "cursor": (814, 751),
    "codex-coding": (517, 607), "claude-code": (676, 575), "cline": (541, 908),
}

# theme (matches ab/bake-off.html)
BG, FG, MUTED, GRID = "#111", "#ddd", "#888", "#333"
C26, C27 = "#6aa9ff", "#f0a35e"  # K2.6 blue, K2.7 orange
W, H = 760, 400
ML, MR, MT, MB = 72, 20, 56, 84
PW, PH = W - ML - MR, H - MT - MB
PX0, PY0 = ML, MT + PH  # bottom-left of plot


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def chart(title, unit, data, ymax, ticks, fmt):
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="-apple-system,Segoe UI,Roboto,sans-serif">']
    s.append(f'<rect width="{W}" height="{H}" fill="{BG}" rx="8"/>')
    s.append(f'<text x="{ML}" y="30" fill="{FG}" font-size="16" font-weight="600">{esc(title)}</text>')
    s.append(f'<text x="{W-MR}" y="30" fill="{MUTED}" font-size="11" text-anchor="end">{esc(unit)}</text>')

    # y gridlines + labels
    for t in ticks:
        y = PY0 - PH * (t / ymax)
        s.append(f'<line x1="{PX0}" y1="{y:.1f}" x2="{PX0+PW}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        s.append(f'<text x="{PX0-8}" y="{y+4:.1f}" fill="{MUTED}" font-size="11" text-anchor="end">{t}</text>')

    n = len(PROMPTS)
    gw = PW / n          # group width
    bw = 30              # bar width
    gap = 8              # gap between the two bars
    for i, p in enumerate(PROMPTS):
        v26, v27 = data[p]
        cx = PX0 + gw * i + gw / 2          # group center
        x26 = cx - gap / 2 - bw
        x27 = cx + gap / 2
        for x, v, col in ((x26, v26, C26), (x27, v27, C27)):
            bh = PH * (v / ymax)
            y = PY0 - bh
            s.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw}" height="{bh:.1f}" fill="{col}" rx="2"/>')
            s.append(f'<text x="{x+bw/2:.1f}" y="{y-5:.1f}" fill="{FG}" font-size="10.5" '
                     f'text-anchor="middle">{fmt(v)}</text>')
        s.append(f'<text x="{cx:.1f}" y="{PY0+18}" fill="{FG}" font-size="11.5" '
                 f'text-anchor="middle">{esc(p)}</text>')

    # baseline
    s.append(f'<line x1="{PX0}" y1="{PY0}" x2="{PX0+PW}" y2="{PY0}" stroke="{MUTED}" stroke-width="1"/>')
    # legend
    ly = H - 22
    s.append(f'<rect x="{ML}" y="{ly-9}" width="12" height="12" fill="{C26}" rx="2"/>')
    s.append(f'<text x="{ML+18}" y="{ly+1}" fill="{FG}" font-size="12">K2.6</text>')
    s.append(f'<rect x="{ML+72}" y="{ly-9}" width="12" height="12" fill="{C27}" rx="2"/>')
    s.append(f'<text x="{ML+90}" y="{ly+1}" fill="{FG}" font-size="12">K2.7</text>')
    s.append('</svg>')
    return "\n".join(s)


def main():
    (OUT / "cost-latency.svg").write_text(chart(
        "Avg latency per instance — by prompt × model", "seconds (lower is better)",
        LATENCY, ymax=300, ticks=[0, 75, 150, 225, 300], fmt=lambda v: f"{v}s"))
    (OUT / "cost-tokens.svg").write_text(chart(
        "Avg tokens per instance — by prompt × model", "thousands of tokens (lower is better)",
        TOKENS, ymax=1000, ticks=[0, 250, 500, 750, 1000], fmt=lambda v: f"{v}k"))
    print("wrote", OUT / "cost-latency.svg", "and", OUT / "cost-tokens.svg")


if __name__ == "__main__":
    main()

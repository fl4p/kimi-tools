#!/usr/bin/env python3
"""Render all_runs.csv as a DENSE HTML table with rotated (vertical) metric
headers. Shows only the informative columns (constant ones like trials=12,
pass@k=100%, empty_args/mistk=0 are omitted — full data stays in all_runs.csv).
Run after make_csv.py."""
import csv, html
from pathlib import Path

D = Path(__file__).resolve().parent
data = list(csv.DictReader(open(D / "all_runs.csv")))

ID_COLS = ["study", "harness", "model", "provider", "sys"]
# Curated dense view: id cols + the metrics that actually vary / tell the story.
SHOW = ID_COLS + ["pass_pct", "tools_per_trial", "duplicate", "discouraged",
                  "tokens", "cost_usd", "avg_latency_s"]
LABELS = {"provider": "prov", "pass_pct": "pass%", "tools_per_trial": "tools/tr",
          "duplicate": "dup", "discouraged": "disc", "cost_usd": "cost$",
          "avg_latency_s": "avg_s"}
METRIC = [c for c in SHOW if c not in ID_COLS]


def disc_style(v):
    try:
        n = int(v)
    except ValueError:
        return ""
    return "background:#16361b" if n == 0 else ("background:#5c4a16" if n <= 6 else "background:#5c1f1f")


def cell(c, v):
    cls = "num" if c in METRIC else "id"
    style = ""
    if c == "discouraged" and v != "":
        style = disc_style(v)
    elif c == "pass_pct" and v not in ("", "100"):
        style = "background:#5c4a16"
    return f'<td class="{cls}" style="{style}">{html.escape(v)}</td>'


head = "".join(f'<th class="idh">{html.escape(LABELS.get(c, c))}</th>' for c in ID_COLS)
head += "".join(f'<th class="vh"><div>{html.escape(LABELS.get(c, c))}</div></th>' for c in METRIC)

body, prev = [], None
for r in data:
    sep = ' class="sep"' if prev and r["study"] != prev else ""
    prev = r["study"]
    body.append(f"<tr{sep}>" + "".join(cell(c, r[c]) for c in SHOW) + "</tr>")

DOC = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Kimi prompt A/B — all runs</title>
<style>
 body{{background:#111;color:#ddd;font:12px/1.3 -apple-system,Segoe UI,Roboto,sans-serif;padding:16px}}
 h1{{font-size:15px;font-weight:600;margin:0 0 4px}}
 .sub{{color:#888;font-size:11px;margin:0 0 12px;max-width:880px}}
 table{{border-collapse:collapse}}
 th,td{{border:1px solid #333;padding:3px 7px}}
 thead th{{background:#1b1b1b}}
 th.idh{{text-align:left;vertical-align:bottom}}
 th.vh{{vertical-align:bottom;height:96px;padding:4px 0}}
 th.vh>div{{writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;font-weight:600;margin:0 auto;letter-spacing:.3px}}
 td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 td.id{{white-space:nowrap}}
 tbody tr:hover td{{outline:1px solid #555}}
 tr.sep td{{border-top:2px solid #777}}
 .legend span{{display:inline-block;padding:1px 7px;margin-right:5px;border:1px solid #333}}
</style></head><body>
<h1>Kimi prompt A/B — all runs</h1>
<p class="sub">sys: <b>default</b>=harness's own prompt · <b>current/v00/*-auto</b>=cline-tailored · <b>sharp</b>=opencode "small sharp toolset" prompt · <b>sharp-port</b>=ported to cline tools.
&nbsp;<b>disc</b> shading <span class="legend"><span style="background:#16361b">0</span><span style="background:#5c4a16">≤6</span><span style="background:#5c1f1f">baseline</span></span>.
Omitted (constant): trials=12, pass@k=100%, empty_args=0, mistk=0; and derivable: tools_total, iter, pass^k, bad%, total_s. Full data in all_runs.csv. tokens blank for cline = harness didn't capture usage (cline reports it; fixed for future runs).</p>
<table><thead><tr>{head}</tr></thead><tbody>
{chr(10).join(body)}
</tbody></table>
</body></html>"""

out = D / "all_runs.html"
out.write_text(DOC)
print(f"wrote {out}  ({len(data)} rows, {len(SHOW)} cols shown)")

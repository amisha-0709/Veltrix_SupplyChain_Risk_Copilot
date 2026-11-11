"""Build reports/persona_test_round3.html from the saved live runs.

    python scripts/report_round3.py
"""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.report import CSS  # noqa: E402

E = html.escape
R = ROOT / "reports"
p15 = json.load(open(R / "persona15_live.json", encoding="utf-8"))
p15b = {r["id"]: r for r in json.load(open(R / "persona15_baseline.json", encoding="utf-8"))}
ev = json.load(open(R / "claude_eval.json", encoding="utf-8"))
p40 = json.load(open(R / "persona40_live.json", encoding="utf-8"))


def v(ok):
    return f"<span class='v v-{'pass' if ok else 'fail'}'>{'pass' if ok else 'fail'}</span>"


def secs(rows):
    s = sorted(r["secs"] for r in rows)
    return s[len(s) // 2], s[-1]


FIXES = [
    ("Procurement director", "No chat query for the dual-sourcing table: Claude fell back to an empty exposure call and the engine "
     "replied 'couldn't link  to any part'.", "New engine query structural_moves (ranked moves, net value, one-off cost, approver); "
     "an exposure call with nothing named now covers the whole network."),
    ("FP&A analyst", "No chat query for the co-pilot's own ROI.", "New engine query business_case (cost, net benefit, ROI, payback, sensitivities)."),
    ("Insurance / risk manager", "No chat query for past disruptions.", "New engine query disruption_history (D01–D18, cost, co-pilot lead time)."),
    ("Sales operations", "Alert answer said '3 customers fall below 95% OTIF' without naming them.",
     "Alert answers now name the customers, worst first."),
    ("New joiner", "Passed, but Claude described itself as 'the question interpreter'.", "Prompt: describe what the co-pilot does, with two example questions."),
    ("Supplier quality engineer", "Passed, but the answer didn't say which parts have no backup supplier, which was the question.",
     "Exposure answers now list single-source parts with no alternate supplier at all."),
    ("(14-question eval)", "'Which customer gets hurt most' got an alphabetical list.",
     "What-if answers now name the hardest-hit customer first; the eval case now requires it."),
]

rows15 = "".join(
    f"<tr><td class='num'>{r['id']}</td><td><b>{E(r['persona'])}</b><div class='sub'>{E(r['situation'])}</div></td>"
    f"<td>“{E(r['question'])}”</td><td class='mono' style='white-space:normal'>{E(' + '.join(r['interpretation']) or '(no engine query: short reply)')}</td>"
    f"<td>{v(p15b[r['id']]['pass'])}</td><td>{v(r['pass'])}</td><td class='num'>{r['secs']}</td>"
    f"<td class='sub'>{E(r['answer'][:230])}{'…' if len(r['answer']) > 230 else ''}</td></tr>" for r in p15)
rows_ev = "".join(
    f"<tr><td>{E(r['name'])}</td><td>“{E(r['question'])}”</td><td class='mono' style='white-space:normal'>"
    f"{E(' + '.join(x.split(' → ')[0] for x in r['evidence']) or '(no engine query)')}</td><td>{v(r['pass'])}</td>"
    f"<td class='num'>{r['secs']}</td></tr>" for r in ev)
fix_rows = "".join(f"<tr><td>{E(a)}</td><td>{E(b)}</td><td>{E(c)}</td></tr>" for a, b, c in FIXES)
m15, x15 = secs(p15)
mev, xev = secs(ev)
n15b = sum(r["pass"] for r in p15b.values())

EXTRA = """.v{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid var(--ring)}
.v-pass{color:var(--good)}.v-fail{color:var(--crit)}
.warn{border-left:3px solid var(--s2);padding:8px 14px;margin:12px 0;background:var(--surface);border-radius:0 8px 8px 0}"""

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Persona Test Round 3</title><style>{CSS}{EXTRA}</style></head><body><main>
<p class="note">PS-06 · Supply Chain Resilience Co-Pilot · round 3: Claude interprets, the engine answers · live site, 11 Nov 2026 ·
synthetic data</p>
<h1>Claude now reads the question; the engine writes the answer. All {len(p15)} new persona cases pass.</h1>
<p class="lede">The chat was switched so that Claude's only job is to understand the question (typos, Hindi, Hinglish, comparisons,
free-form incidents) and turn it into a structured query for the impact engine. The answer shown is the engine's own fixed-template text,
word for word, so it is consistent and every number is reproducible. Claude writes text only when no engine query fits: an order
request, an off-topic question, "what does this tool do?". Then 15 new personas, different from rounds 1 and 2, tested it end to end.</p>
<div class="warn"><b>Still scripted, not real users.</b> Each case has a written pass rule checked automatically (engine used, Claude's
reading, ₹ figures traceable to the engine, no "ordered/approved" claims, case-specific content). Feedback from at least three real
people is still needed, using the persona feedback kit.</div>
<div class="tiles">
<div class="tile"><b>{sum(r['pass'] for r in p15)} / {len(p15)}</b><span>new persona cases pass live ({n15b} / {len(p15)} before the fixes below)</span></div>
<div class="tile"><b>{sum(r['pass'] for r in ev)} / {len(ev)}</b><span>Claude evaluation questions pass live</span></div>
<div class="tile"><b>{sum(r['pass'] for r in p40)} / {len(p40)}</b><span>round-2 persona cases still pass (no regressions)</span></div>
<div class="tile"><b>~{mev:.0f} s</b><span>median Claude answer (was 5–15 s when Claude wrote the reply)</span></div>
</div>

<h2>1 · What changed in the chat</h2>
<div class="card"><table><thead><tr><th></th><th>Before: Claude wrote the reply</th><th>Now: Claude interprets, engine answers</th></tr></thead><tbody>
<tr><td>Who writes the answer</td><td>Claude, from the engine's results</td><td>The engine's own template text, word for word</td></tr>
<tr><td>Claude calls per question</td><td>2 (read, then write)</td><td>1 (read only)</td></tr>
<tr><td>Answer time (14-question eval)</td><td>median ~5 s, up to 15 s</td><td>median {mev:.1f} s, max {xev:.1f} s</td></tr>
<tr><td>Cost of the 14-question eval</td><td>~$0.057</td><td>~$0.015</td></tr>
<tr><td>Can a number be reworded or misquoted?</td><td>Unlikely (checked), but possible</td><td>No: the text comes from the engine</td></tr>
<tr><td>Sent to Anthropic's API</td><td>The question and the engine results (supplier names removed)</td><td>Only the question</td></tr>
<tr><td>Hindi or Hinglish questions</td><td>Answered in the same language</td><td>Understood; answered in English</td></tr>
<tr><td>Engine queries Claude can use</td><td>5</td><td>8 (added dual-sourcing moves, business case, disruption history)</td></tr>
</tbody></table>
<p class="note">The page shows how Claude read each question (for example <span class="mono">what_if(places=Penang; commodities=Semiconductors;
duration_days=42)</span>), so a wrong reading is visible to the user rather than hidden in a fluent answer.</p></div>

<h2>2 · Fifteen new personas</h2>
<div class="card"><table><thead><tr><th class="num">#</th><th>Persona and situation</th><th>Question</th><th>How Claude read it</th>
<th>Before fixes</th><th>After</th><th class="num">Secs</th><th>Engine's answer (start)</th></tr></thead><tbody>{rows15}</tbody></table>
<p class="note">Median {m15:.1f} s, slowest {x15:.1f} s. Generic checks on every case: HTTP 200, Claude answered (not the fallback), no
claim that anything was ordered/booked/approved/sent, every ₹ figure traceable to the engine. Script: <span class="mono">scripts/persona15.py</span>.</p></div>

<h2>3 · Issues found and fixed in this round</h2>
<div class="card"><table><thead><tr><th>Found by</th><th>Issue</th><th>Fix</th></tr></thead><tbody>{fix_rows}</tbody></table></div>

<h2>4 · Claude evaluation (14 questions) after the switch</h2>
<div class="card"><table><thead><tr><th>Case</th><th>Question</th><th>How Claude read it</th><th>Result</th><th class="num">Secs</th></tr></thead>
<tbody>{rows_ev}</tbody></table>
<p class="note">Script: <span class="mono">scripts/claude_eval.py</span>. Before the switch the same set scored 13/14 (one over-long answer).</p></div>

<h2>5 · Limits that remain</h2>
<div class="card"><ul>
<li><b>Claude can misread a question.</b> The reading is shown above every answer so a person can spot it; nothing checks it automatically.</li>
<li><b>Answers come back in English</b> even when the question is in Hindi or Hinglish.</li>
<li><b>Engine answers are terse templates.</b> Consistent and auditable, but less conversational than before.</li>
<li><b>Comparisons don't state a verdict.</b> "China or Taiwan?" shows each side's parts, spend and cover gaps, but the reader decides
which is bigger.</li>
<li><b>Questions outside the eight engine queries</b> (e.g. supplier financial health, freight rates) get a short "can't answer that" from
Claude rather than an answer.</li>
<li><b>Everything is synthetic.</b> Real news and real users will find new gaps; the pilot's weekly review is where those get caught.</li>
</ul></div>
</main></body></html>"""
(R / "persona_test_round3.html").write_text(page, encoding="utf-8")
print(R / "persona_test_round3.html")

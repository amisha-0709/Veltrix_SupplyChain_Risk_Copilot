"""reports/fresh40_report.html from reports/fresh40.json plus hand grading (each verdict read from the live answer)."""
import html
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.report import CSS  # noqa: E402

E = html.escape
d = json.load(open(ROOT / "reports" / "fresh40.json", encoding="utf-8"))
S = {r["id"]: r for r in d["signals"]}
Q = {r["id"]: r for r in d["questions"]}

# Hand grading. Signals: (verdict for the live decision, would Claude's reading have been right?, note)
GS = {
    "S01": ("pass", True, "Alert raised (watch log): Kaohsiung linked; cover outlasts the delay, so low priority."),
    "S02": ("pass", True, "Named supplier matched (SUP-017 Rheinwerk) → inbox alert."),
    "S03": ("fail", True, "Missed: 'walk out' and 'cranes idle' aren't in the word list (score 0). Claude read it as a port closure happening at Busan."),
    "S04": ("fail", False, "False alarm, inbox P10, ₹46.21 cr: 'export licences' + China scored 3.5. The product filter only applies to trade notices, not news. Claude also mapped gallium/germanium to Semiconductors."),
    "S05": ("fail", True, "Missed: 'blocked' and 'runs aground' aren't in the word list (score 0). Claude read it as a route event at Suez."),
    "S06": ("pass", True, "Ignored: Singapore isn't on a Veltrix lane."),
    "S07": ("pass", True, "Inbox: Hsinchu → Taiwan fabs and semiconductors."),
    "S08": ("pass", True, "Ignored: denial of a rumour."),
    "S09": ("pass", True, "Watch log: cost-only duty on Li-ion cells, correctly not urgent."),
    "S10": ("pass", True, "Watch log: Hai Phong closure linked and quantified."),
    "S11": ("fail", True, "Missed: 'load shedding' / 'heatwave builds' score 2 (< 3.5). Claude read it as a likely supplier outage in Pune."),
    "S12": ("pass", True, "Ignored: market news."),
    "S13": ("pass", True, "Inbox: Japan ∩ Passives, although no company is named."),
    "S14": ("pass", True, "Ignored: forecast to miss."),
    "S15": ("pass", True, "Ignored: disruption ending."),
    "S16": ("pass", True, "Ignored: threat only."),
    "S17": ("pass", True, "Watch log: both Indian ports linked."),
    "S18": ("fail", False, "Missed: 'Kaohsuing' (typo) matches nothing in the place list. Claude extracted 'Kaohsuing port', and the same place list couldn't link it."),
    "S19": ("fail", False, "Missed: Hindi text. Claude extracted the places in Hindi script ('ताइवान', 'काऊशुंग बंदरगाह'); the place list is English only."),
    "S20": ("pass", True, "Watch log: 'Ningbo-Zhoushan' matched Ningbo."),
}
# Questions: (verdict, note)
GQ = {
    "A01": ("pass", "Busan 14 d: nothing stops; lowest cover 40.9 d."),
    "A02": ("partial", "Exposure to China (20 parts, 9 single-source, ₹558.2 cr spend) but no revenue figure in the answer; revenue dependence is only in the table, per part."),
    "A03": ("pass", "Supplier matched by name; 1 product stops (₹3.21 cr). Note: this what-if counts goods already shipped (PRT-006 cover 44.1 d), while the Exposure page shows on-hand only (12.7 d), which can look contradictory."),
    "A04": ("partial", "Lists the 5 inbox alerts but doesn't say which need a same-day decision; that's only in each alert's response time."),
    "A05": ("partial", "Ran the Suez what-if (nothing stops) and then Ojas Motors' current alerts, which are about other events. No Ojas-specific Suez figure."),
    "A06": ("pass", "AL-004 options with customers and approvers."),
    "A07": ("pass", "Trident: 2 alerts push it below 95% OTIF."),
    "A08": ("partial", "Ran Port Klang and Penang as two separate closures, not one joint scenario."),
    "A09": ("fail", "No query filters by days of cover: got the whole-network exposure (cover < lead time), not 'under 14 days'."),
    "A10": ("pass", "Hinglish understood: Shanghai 21 d."),
    "A11": ("partial", "Listed all 18 disruptions (D05 named as the worst). The Red Sea figure (D03, ₹4.99 cr) is only in the table, not stated."),
    "A12": ("pass", "Qualify SUP-011 for PRT-004 first (₹5.99 cr/yr net)."),
    "A13": ("pass", "Payback 0.5 months, ROI 22.5×."),
    "A14": ("pass", "Both 30-day closures answered; no explicit 'which is worse' line (known limit)."),
    "A15": ("pass", "China magnets 90 d trade: 2 products stop, ₹76.85 cr at risk."),
    "A16": ("pass", "Malacca: 46 parts, 19 single-source."),
    "A17": ("fail", "No query takes a part number: 'Couldn't find PRT-043'."),
    "A18": ("pass", "Refused plainly; the co-pilot can't change anything."),
    "A19": ("fail", "The approval matrix isn't a chat query; Claude declined, though the matrix gives a clear answer (expedite ₹50 lakh–2 cr → Head of Supply Chain)."),
    "A20": ("pass", "Hosur 5 d: nothing stops; lowest cover 10.7 d."),
}

exp_alert = [k for k, r in S.items() if r["expected"] == "alert"]
exp_ign = [k for k, r in S.items() if r["expected"] != "alert"]
caught = [k for k in exp_alert if S[k]["decision"] in ("inbox", "watch")]
false_al = [k for k in exp_ign if S[k]["decision"] in ("inbox", "watch")]
s_pass = sum(v[0] == "pass" for v in GS.values())
c_right = sum(v[1] for v in GS.values())
q_pass = sum(v[0] == "pass" for v in GQ.values())
q_part = sum(v[0] == "partial" for v in GQ.values())
q_fail = sum(v[0] == "fail" for v in GQ.values())
s_secs = statistics.median(r["secs"] for r in S.values())
q_secs = statistics.median(r["secs"] for r in Q.values())


def v(x):
    return f"<span class='v v-{x}'>{x}</span>"


srows = "".join(
    f"<tr><td>{k}</td><td>“{E(r['headline'])}”<div class='sub'>{E(r['why'])}</div></td><td>{E(r['expected'])}</td>"
    f"<td><b>{E(r['decision'] or '')}</b>{f' · P{r[chr(112)+chr(114)+chr(105)+chr(111)+chr(114)+chr(105)+chr(116)+chr(121)]}' if r.get('priority') else ''}"
    f"{f' · {E(r[chr(114)+chr(101)+chr(118)+chr(101)+chr(110)+chr(117)+chr(101)+chr(95)+chr(97)+chr(116)+chr(95)+chr(114)+chr(105)+chr(115)+chr(107)])}' if r.get('revenue_at_risk') else ''}"
    f"<div class='sub'>score {r['score']} · {E(', '.join(r['links'] or []) or 'no link')}</div></td>"
    f"<td>{E((r['claude'] or {}).get('status') or '—')}<div class='sub'>{'relevant' if (r['claude'] or {}).get('relevant') else 'not relevant'}</div></td>"
    f"<td>{v(GS[k][0])}</td><td>{'✓' if GS[k][1] else '✗'}</td><td class='sub'>{E(GS[k][2])}</td></tr>" for k, r in S.items())
qrows = "".join(
    f"<tr><td>{k}</td><td>“{E(r['question'])}”<div class='sub'>Expected: {E(r['expected'])}</div></td>"
    f"<td class='mono' style='white-space:normal'>{E(' + '.join(r['interpretation'] or []) or '(no engine query)')}</td>"
    f"<td class='num'>{r['secs']}</td><td>{v(GQ[k][0])}</td><td class='sub'>{E(GQ[k][1])}</td></tr>" for k, r in Q.items())

EXTRA = """.v{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid var(--ring)}
.v-pass{color:var(--good)}.v-partial{color:var(--s2)}.v-fail{color:var(--crit)}"""
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fresh 40 Test Report</title><style>{CSS}{EXTRA}</style></head><body><main>
<p class="note">PS-06 · Supply Chain Resilience Co-Pilot · fresh test round: 20 "Try a signal" + 20 "Ask the co-pilot" cases ·
live site, 12 Nov 2026 · synthetic data</p>
<h1>The engine is right when it understands the input. It misses wording, spellings and languages it wasn't built on.</h1>
<p class="lede">Forty cases written fresh for this round (none used before), with the expected behaviour written before running. All ran on
the deployed site. Each answer was read and graded by hand. Nothing was changed in the app for or during this round.</p>
<div class="tiles">
<div class="tile"><b>{s_pass} / 20</b><span>Try a signal: right decision ({len(caught)} of {len(exp_alert)} real risks caught, {len(false_al)} false alarm)</span></div>
<div class="tile"><b>{c_right} / 20</b><span>Try a signal: Claude's own reading was right (shown, not used for the decision)</span></div>
<div class="tile"><b>{q_pass} / {q_part} / {q_fail}</b><span>Ask: pass / partial / fail of 20</span></div>
<div class="tile"><b>{s_secs:.1f} s · {q_secs:.1f} s</b><span>median time: Try a signal · Ask</span></div>
</div>

<h2>1 · Summary</h2>
<div class="card"><ul>
<li><b>Try a signal ({s_pass}/20):</b> when the word list recognises the wording, linking, quantification and priority are right (S01, S02, S07,
S10, S13, S17, S20), and all six "should ignore" stories that look alarming are ignored (denial, a forecast that misses, a threat,
good news, an off-network port, market news). It misses <b>everyday disruption wording the synthetic data never used</b>
("walk out", "blocked … runs aground", "load shedding"), <b>misspelt place names</b> and <b>non-English text</b>, and raised
<b>one false alarm</b> (gallium/germanium export licences, inbox, ₹46 cr) because the product filter only checks trade notices.</li>
<li><b>Claude's reading of the same signals was right {c_right}/20.</b> It caught the three wording misses (S03, S05, S11). But it is only
displayed: the decision still comes from the word list, so the page shows "Claude: relevant" next to "Ignored". Typos and Hindi defeat
both, because Claude's extracted names go through the same English-only place list.</li>
<li><b>Ask ({q_pass} pass, {q_part} partial, {q_fail} fail):</b> Claude interpreted every question sensibly, including Hinglish and a
supplier named in full. Every partial and fail is a <b>missing engine query</b>, not a misreading: no lookup by part number, no filter by days
of cover, no approval-matrix lookup, no joint multi-port scenario, no customer-specific what-if, and answers that leave the key number in
the table rather than the sentence.</li>
</ul></div>

<h2>2 · Try a signal: 20 cases</h2>
<div class="card"><table><thead><tr><th>#</th><th>Headline (and why it's a test)</th><th>Expected</th><th>Co-pilot decision</th>
<th>Claude's reading</th><th>Result</th><th>Claude right?</th><th>Notes</th></tr></thead><tbody>{srows}</tbody></table>
<p class="note">Expected "alert" = inbox or watch log. Score = word-list score against the 3.5 threshold. "Claude right?" = whether Claude's
relevance call, if it had decided, would have matched the expected outcome.</p></div>

<h2>3 · Ask the co-pilot: 20 cases</h2>
<div class="card"><table><thead><tr><th>#</th><th>Question</th><th>How Claude read it</th><th class="num">Secs</th><th>Result</th>
<th>Notes</th></tr></thead><tbody>{qrows}</tbody></table></div>

<h2>4 · What's lacking, as an MVP</h2>
<div class="card"><table><thead><tr><th>Gap</th><th>Seen in</th><th>Why it happens</th><th>What a user sees</th></tr></thead><tbody>
<tr><td>Disruption wording outside the word list</td><td>S03, S05, S11</td><td>Triage decides with a hand-built list of phrases tuned on the
synthetic news; new phrasings score 0–2.</td><td>A real risk marked "Not alerted … wording is not strong enough".</td></tr>
<tr><td>Claude's reading isn't used to decide</td><td>S03, S05, S11 (and S04 the other way)</td><td>The rule combining Claude and the word list
was meant to be chosen on history; that run was skipped, so the word list alone decides.</td><td>"Claude: supply risk that touches our
network" next to "Ignored".</td></tr>
<tr><td>Commodity filter only on trade notices</td><td>S04</td><td>News stories about export controls on materials Veltrix doesn't buy pass
on "export licences" + China.</td><td>A high-priority false alarm with ₹46 cr at risk.</td></tr>
<tr><td>English-only, exact-spelling place list</td><td>S18, S19</td><td>Linking matches names against a fixed English list; no fuzzy matching or
transliteration.</td><td>A clear closure of a port we use is ignored as "not in our network".</td></tr>
<tr><td>Chat can't look up a part, a cover threshold or the approval matrix</td><td>A09, A17, A19</td><td>Only 8 engine queries exist;
Claude won't invent an answer outside them (by design).</td><td>"Couldn't find PRT-043" / a generic answer / a polite "can't".</td></tr>
<tr><td>No joint or customer-specific scenarios</td><td>A05, A08</td><td>Each query is one place-set; comparisons and combinations run
separately.</td><td>Two separate answers instead of one combined result.</td></tr>
<tr><td>Key number left in the table</td><td>A02, A04, A11</td><td>Engine answers are fixed templates; Claude no longer writes the sentence.</td>
<td>The user has to read the table for the figure they asked about.</td></tr>
<tr><td>Two different "cover" numbers</td><td>A03</td><td>Exposure shows on-hand cover; what-ifs add stock already shipped unless the event
catches it.</td><td>PRT-006: 12.7 days on one page, 44.1 days in a what-if.</td></tr>
</tbody></table></div>

<h2>5 · Read with care</h2>
<div class="card"><ul>
<li>Twenty cases per feature is a small sample; the cases were written to probe likely weak spots, so these rates are lower than the
scripted rounds and probably lower than typical use.</li>
<li>Grading is by one reader against expectations written beforehand; borderline calls (watch log vs inbox) were counted as alerts.</li>
<li>Everything runs on synthetic data and today's stock (30 Sep 2026).</li>
</ul></div>
</main></body></html>"""
(ROOT / "reports" / "fresh40_report.html").write_text(page, encoding="utf-8")
print("signals", s_pass, "claude", c_right, "ask", q_pass, q_part, q_fail, "caught", len(caught), "of", len(exp_alert), "false", false_al)

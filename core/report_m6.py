"""M6 exhibits: business case, structural recommendations, false-alarm analysis → reports/m6.html,
and the COO one-pager → reports/coo_onepager.html (prints on one A4 page).

    python -m core.report_m6
"""
from __future__ import annotations

import html
import json

import pandas as pd

from core.backtest import run_backtest
from core.etl import load
from core.false_alarms import analysis
from core.impact import fmt_inr
from core.mitigate import approver
from core.report import CSS, JS, OUT
from core.report_m3 import _t
from core.roi import business_case
from core.structural import structural_summary, structural_table

E = html.escape


def _x(v):
    return "—" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:.1f}×"


def _pct(v):
    return "—" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:.0%}"


def gather() -> dict:
    bc = business_case()
    st = structural_table()
    ss = structural_summary(st)
    fa = analysis()
    bt = run_backtest()
    d = load()["disruptions"]
    return {"bc": bc, "st": st, "ss": ss, "fa": fa, "bt": bt,
            "lost_total": float(d["revenue_lost_inr_cr"].sum()) * 1e7}


# ---------------------------------------------------------------- M6 report
def build_report(g: dict) -> str:
    bc, st, ss, fa, bt = g["bc"], g["st"], g["ss"], g["fa"], g["bt"]
    b, base = bc["base"], bc["scenarios"][0]
    cost = bc["annual_cost_inr"]

    ben = pd.DataFrame([
        {"line": "Margin protected (probability-weighted)", "v": fmt_inr(b["margin_protected"])},
        {"line": "Customer penalties avoided", "v": fmt_inr(b["penalties_avoided"])},
        {"line": "Mitigation spend avoided where cover was enough", "v": fmt_inr(b["waste_avoided"])},
        {"line": "Less: cost of the recommended mitigations", "v": "−" + fmt_inr(b["mitigation_cost"])},
        {"line": "Net benefit per year", "v": fmt_inr(b["net"])},
        {"line": "For reference: revenue protected (not counted, margin is)", "v": fmt_inr(b["revenue_protected"])},
    ])
    costs = pd.DataFrame([{"item": r["item"].capitalize(), "v": fmt_inr(r["annual_inr"]), "note": r["note"]}
                          for r in bc["cost_rows"]] + [{"item": "Total per year", "v": fmt_inr(cost), "note": ""}])
    scen = pd.DataFrame([{"scenario": r["scenario"], "net": fmt_inr(r["net_benefit_inr"]),
                          "cost": fmt_inr(r["copilot_cost_inr"]), "roi": _x(r["roi"]),
                          "payback": f"{r['payback_months']:.1f}" if r["payback_months"] else "—"}
                         for r in bc["scenarios"]])

    rp = bc["replays"].copy()
    rp["lost"] = rp["actual_revenue_lost_inr"].map(fmt_inr)
    rp["margin"] = rp["margin_protected_inr"].map(fmt_inr)
    rp["waste"] = rp["avoided_waste_inr"].map(fmt_inr)
    rp["cost"] = rp["plan_cost_inr"].map(fmt_inr)
    rp["action"] = rp["top_action"].str.slice(0, 90)

    s = st.copy()
    s["loss_if"] = s["margin_loss_if_outage_inr"].map(fmt_inr)
    s["eal"] = s["eal_inr"].map(fmt_inr)
    s["once"] = s.apply(lambda r: fmt_inr(r["qualify_cost_once_inr"]) if r["recommendation"].startswith("Qualify")
                        else "—", axis=1)
    s["buf"] = s.apply(lambda r: fmt_inr(r["buffer_cost_annual_inr"]) if r["recommendation"].startswith("Raise")
                       else "—", axis=1)
    s["net"] = s["net_annual_value_inr"].map(fmt_inr)
    q_total = float(st[st["recommendation"].str.startswith("Qualify") & (st["net_annual_value_inr"] > 0)]
                    ["qualify_cost_once_inr"].sum())

    sw = fa["sweep"].pivot(index="threshold", columns="split", values=["flagged", "false_alarms", "precision", "recall"])
    sw.columns = [f"{a}_{b}" for a, b in sw.columns]
    sw = sw.reset_index()
    for c in [c for c in sw if c.startswith(("precision", "recall"))]:
        sw[c] = sw[c].map(_pct)
    sw["threshold"] = sw["threshold"].map(lambda v: f"{v:.1f}" + (" ← chosen" if v == fa["threshold"] else ""))

    ab = fa["ablations"].copy()
    for c in [c for c in ab if c.startswith("precision")]:
        ab[c] = ab[c].map(_pct)
    la = fa["lookalikes"].head(15).copy()
    la["sample"] = la["sample"].str.slice(0, 110)
    ch = pd.DataFrame(fa["changes"], columns=["change", "effect"])
    ld = fa["load"]
    sig = bt["signals"]["test"]

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Veltrix Business Case</title><style>{CSS}</style></head><body><main>
<p class="note">PS-06 · Supply Chain Resilience Co-Pilot · M6: business case, structural moves, false alarms · synthetic data
(Veltrix Components, fictional)</p>
<h1>The co-pilot costs {fmt_inr(cost)} a year and would have returned {fmt_inr(b['net'])}.</h1>
<p class="lede">Replaying all 18 disruptions as if the co-pilot had been live: it alerts with its own lead time, uses the stock cover
at the time and the team's own actions are kept. Only what the co-pilot <i>adds</i> is credited, in margin rather than revenue,
weighted by the chance each action works and net of what the actions cost. Annualised over the 2 years of history.</p>
<div class="tiles">
<div class="tile"><b>{fmt_inr(b['net'])}</b><span>net benefit per year (margin + penalties + avoided spend − action cost)</span></div>
<div class="tile"><b>{fmt_inr(cost)}</b><span>co-pilot running cost per year, including people</span></div>
<div class="tile"><b>{base['roi']:.1f}×</b><span>ROI; {_x(min(r['roi'] for r in bc['scenarios']))} in the harshest sensitivity</span></div>
<div class="tile"><b>{ss['net_annual_value_cr']:.1f} cr/yr</b><span>extra upside from {ss['parts_with_positive_move']} structural moves
(not in the ROI above)</span></div>
</div>

<h2>1 · Business case</h2>
<div class="two"><div class="card"><h3>Benefit per year</h3>{_t(ben, {"line": "", "v": "₹ / year"}, num=("v",))}</div>
<div class="card"><h3>Cost per year</h3>{_t(costs, {"item": "Item", "v": "₹ / year", "note": "Assumption"}, num=("v",))}</div></div>
<h3>Sensitivity</h3>
<div class="card">{_t(scen, {"scenario": "Scenario", "net": "Net benefit / yr", "cost": "Co-pilot cost / yr", "roi": "ROI",
                            "payback": "Payback (months)"}, num=("net", "cost", "roi", "payback"))}
<p class="note">ROI = (net benefit − co-pilot cost) ÷ co-pilot cost. "Outliers removed" drops every disruption that lost more
than $1M (D04, D05, D08, D12 and D18), as Abhishek suggested; the case still pays back in about two months.
Model calls are a rounding error (about $270 a year at list price). People and data feeds are the real cost.</p></div>
<h3>Where the benefit comes from</h3>
<div class="card">{_t(rp, {"disruption_id": "ID", "title": "Disruption", "copilot_lead_days": "Lead (d)", "lost": "Actually lost",
                          "margin": "Margin protected", "waste": "Spend avoided", "cost": "Plan cost", "action": "Recommended"},
                     num=("copilot_lead_days", "lost", "margin", "waste", "cost"))}
<p class="note">Most of the margin comes from three supplier events (D05, D12, D04). Most avoided spend is D16, where the team spent
on freight while cover was enough. Where the co-pilot says "No action" its credit is zero, even if real losses happened (D01, D08, D10):
those are losses no mitigation reachable in time would have saved. The structural moves below are the answer to those.</p></div>
<div class="card"><b>What this does not count.</b> Analyst time saved, avoided expedite premiums beyond the logged ones, customer
goodwill, and the structural upside below. <b>What could make it smaller:</b> the 2-year history has a few large events; real feeds
are messier than synthetic news; and P(works) comes from the playbook's priors, not from Veltrix's own outcomes yet. The pilot
(see the <a href="coo_onepager.html">COO one-pager</a>) is designed to measure exactly these.</div>

<h2>2 · Structural recommendations: where to dual-source or hold more stock</h2>
<p class="lede">For each of the {len(st)} single-source parts: expected annual loss from a typical supplier outage
({ss['outage_rate_per_supplier_year']:.1%} per supplier per year, {ss['typical_outage_delay_days']:.0f}-day delay) plus that part's
share of past losses, against the cost of qualifying a second source in advance (a switch then takes ~19 days, as observed) or holding
enough buffer to ride out the outage.</p>
<div class="tiles">
<div class="tile"><b>{ss['parts_with_positive_move']} of {len(st)}</b><span>single-source parts where a move pays back</span></div>
<div class="tile"><b>{fmt_inr(q_total)}</b><span>one-off qualification cost for {ss['qualify_moves']} parts</span></div>
<div class="tile"><b>{fmt_inr(ss['annual_buffer_cost_cr'] * 1e7)}/yr</b><span>holding cost of extra buffer on {ss['buffer_moves']} parts</span></div>
<div class="tile"><b>₹{ss['net_annual_value_cr']:.1f} cr/yr</b><span>expected loss avoided, net of the cost</span></div>
</div>
<div class="card">{_t(s, {"part_id": "Part", "description": "Description", "cover_days": "Cover (d)", "lead_time_days": "Lead time (d)",
                         "skus": "SKUs", "loss_if": "Loss if supplier down", "eal": "Expected loss / yr", "recommendation": "Move",
                         "once": "One-off", "buf": "Buffer / yr", "net": "Net value / yr"},
                    num=("cover_days", "lead_time_days", "skus", "loss_if", "eal", "once", "buf", "net"))}
<p class="note">Approval: the qualification programme as a whole ({fmt_inr(q_total)}) sits with {approver('switch', q_total)}
under the approval matrix; each single qualification (≤ ₹50 lakh) with {approver('switch', 15e5)}. Expected loss leans on 2 years of
history, so a part that was hit once (PRT-004 in D05, PRT-030 in D12) ranks high. A repeat isn't guaranteed, which is why these
are an input to next year's sourcing budget, not an instruction.</p></div>

<h2>3 · False-alarm analysis</h2>
<p class="lede">The brief asks how the co-pilot avoids crying wolf. Answer: four guards, each measured by switching it off and
counting the false alarms that come back. The whole team would see about {ld['alerts_per_week']:.2f} alerts a week
(≈ {ld['alerts_per_week'] * 52:.0f} a year) and {ld['inbox_per_month']:.2f} inbox alerts a month, out of
{ld['signals_per_week']:.0f} signals a week read. Test period as built: {sig['fp']} false-alarm signals, precision
{sig['precision']:.0%}, recall {sig['recall']:.1%}.</p>
<h3>Guards switched off one at a time</h3>
<div class="card">{_t(ab, {"guard removed": "Guard removed", "false_alarm_signals_train": "False signals (train)",
                          "false_alerts_train": "False alerts (train)", "precision_train": "Precision (train)",
                          "false_alarm_signals_test": "False signals (test)", "false_alerts_test": "False alerts (test)",
                          "precision_test": "Precision (test)", "alerts_test": "Alerts (test)"},
                     num=("false_alarm_signals_train", "false_alerts_train", "precision_train", "false_alarm_signals_test",
                          "false_alerts_test", "precision_test", "alerts_test"))}
<p class="note">Precision here is signal-level, counted on each split's events built on their own (so a story spanning 1 Feb counts
once per side). The trade-product filter matters most: without it every restrictive-sounding customs notice pages someone. The
network-link gate adds nothing on this data because the cue lexicon already rarely fires on unrelated world news; it is kept because
real feeds will carry far more of that.</p></div>
<h3>Threshold sweep (score only, before dedup and follow-up linking)</h3>
<div class="card">{_t(sw, {"threshold": "Threshold", "flagged_train": "Flagged (train)", "false_alarms_train": "False (train)",
                          "precision_train": "Precision (train)", "recall_train": "Recall (train)", "flagged_test": "Flagged (test)",
                          "false_alarms_test": "False (test)", "precision_test": "Precision (test)", "recall_test": "Recall (test)"},
                     num=("flagged_train", "false_alarms_train", "precision_train", "recall_train", "flagged_test",
                          "false_alarms_test", "precision_test", "recall_test"))}
<p class="note">The threshold ({fa['threshold']}) was tuned on train only. There is a cliff between 3.0 and 3.5: the 20 test-period
false alarms all score 2–3 (forecasts, routine freight notes). Score-only recall at 3.5 is lower than the headline
{sig['recall']:.1%} because the headline also counts unlinked follow-up stories attached to an open event.</p></div>
<h3>Look-alike stories suppressed</h3>
<div class="card">{_t(la, {"story_key": "Story", "copies": "Copies", "score": "Score", "guard": "What held it back", "sample": "Example"},
                     num=("copies", "score"))}</div>
<h3>Changes made during development to cut false alarms</h3>
<div class="card">{_t(ch, {"change": "Change", "effect": "What it fixed"})}</div>
<div class="card"><b>Residual risk.</b> Precision of 100% on synthetic test data will not survive contact with real feeds; expect
new phrasings the lexicon has never seen. The pilot plan keeps a weekly review of every flagged and every suppressed item with a
strong cue, and the optional Claude pass (off by default) reviews only the borderline band.</div>
</main><div id="tip" role="tooltip"></div><script>{JS}</script></body></html>"""
    return page


# ---------------------------------------------------------------- COO one-pager
ONE_CSS = """
@page{size:A4;margin:12mm}
:root{--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--s1:#2a78d6;--page:#fff;--surface:#f9f9f7}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a9890;
--grid:#2c2c2a;--s1:#3987e5;--page:#0d0d0d;--surface:#1a1a19}}
:root[data-theme="dark"]{--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a9890;--grid:#2c2c2a;--s1:#3987e5;--page:#0d0d0d;--surface:#1a1a19}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:12.5px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:186mm;margin:0 auto;padding:16px}
h1{font-size:20px;line-height:1.25;margin:2px 0 6px}h2{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--s1);
margin:12px 0 4px}p{margin:4px 0}.k{color:var(--muted);font-size:11px}
.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:8px 0}
.tile{background:var(--surface);border-radius:8px;padding:8px 10px}.tile b{display:block;font-size:18px}.tile span{color:var(--ink2);font-size:11px}
.cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}
ul{margin:2px 0;padding-left:18px}li{margin:2px 0}
table{border-collapse:collapse;width:100%;font-size:11.5px}td,th{border-bottom:1px solid var(--grid);padding:3px 4px;text-align:left;
vertical-align:top}th{color:var(--ink2);font-weight:600}.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.ask{border:2px solid var(--s1);border-radius:8px;padding:8px 12px;margin-top:10px}
@media (max-width:640px){.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.cols{grid-template-columns:1fr}}
@media print{body{background:#fff;color:#000}}
"""


def build_onepager(g: dict) -> str:
    bc, ss, bt = g["bc"], g["ss"], g["bt"]
    b, cost = bc["base"], bc["annual_cost_inr"]
    rp = bc["replays"]
    sig, al, ld = bt["signals"]["test"], bt["alerts"]["test"], bt["lead"]["test"]
    lost = g["lost_total"]
    load_ = g["fa"]["load"]
    worst = min(r["roi"] for r in bc["scenarios"])
    one_off = 35e5
    pilot_run = sum(r["annual_inr"] for r in bc["cost_rows"] if "one off" not in r["item"]) / 4
    d05 = rp[rp["disruption_id"] == "D05"].iloc[0]
    top = g["st"][g["st"]["net_annual_value_inr"] > 0].head(3)
    top_rows = "".join(f"<tr><td>{E(r.part_id)} {E(r.description)}</td><td>{E(r.recommendation)}</td>"
                       f"<td class='num'>{fmt_inr(r.net_annual_value_inr)}</td></tr>" for r in top.itertuples())

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>COO One-Pager</title><style>{ONE_CSS}</style></head><body><main>
<p class="k">For: COO, Veltrix Components · From: Supply Chain Resilience Co-Pilot team · Decision requested: approve a 3-month pilot ·
synthetic data</p>
<h1>We lost {fmt_inr(lost)} of revenue to disruptions we mostly saw coming. A {fmt_inr(one_off + pilot_run)} pilot tests whether we
can stop that.</h1>

<h2>The problem</h2>
<p>In 24 months, 18 disruptions cost {fmt_inr(lost)} of revenue. Most had public warnings one to three weeks ahead, but nobody owns
monitoring: the team noticed a median of a day <i>after</i> impact and decided days later. Meanwhile about {fmt_inr(rp['team_wasted_inr'].sum())}
went on expediting parts whose stock would have lasted anyway. 26 parts have a single supplier, and on most of them stock cover is
shorter than the lead time.</p>

<h2>What the co-pilot does</h2>
<p>Reads news, weather, port and trade notices; links each to our supplier → part → product network; quantifies revenue, margin and
OTIF at risk using today's stock and in-transit; ranks options (pre-buy, air freight, switch supplier, re-allocate) by net value with
the approver named; and writes a one-page briefing. <b>It recommends; people decide.</b> It never orders, books freight or contacts a
supplier.</p>

<div class="tiles">
<div class="tile"><b>{ld['median_lead_days']:.0f} days</b><span>median warning before impact (target ≥ 7)</span></div>
<div class="tile"><b>{sig['recall']:.0%} / {al['precision']:.0%}</b><span>recall / alert precision on unseen months (targets 80% / 60%)</span></div>
<div class="tile"><b>{fmt_inr(b['net'])}/yr</b><span>net benefit in replay vs {fmt_inr(cost)}/yr running cost</span></div>
<div class="tile"><b>{bc['scenarios'][0]['roi']:.0f}×</b><span>ROI; {worst:.1f}× with the largest events removed</span></div>
</div>

<div class="cols"><div>
<h2>Evidence</h2>
<ul>
<li><b>Back-test</b> on Feb–Sep 2026, data the rules were not tuned on: every warned disruption caught, a median
{ld['median_lead_days']:.0f} days ahead, with about {load_['alerts_per_week'] * 52:.0f} alerts a year in total, not a flood.</li>
<li><b>Impact engine</b> reproduces past losses with a 2.8% median error (7 of 9 loss events within ±25%; every no-loss event right).</li>
<li><b>Replay of the Penang MOSFET fire (D05, ₹61 cr lost)</b>: same-day briefing and re-allocation would have protected
{fmt_inr(d05['margin_protected_inr'])} of margin. Qualifying the known alternate beforehand (about ₹15 lakh) would have protected about
₹50 cr of revenue.</li>
<li>All 10 acceptance scenarios from the brief pass end to end.</li>
</ul>
<h2>Biggest structural moves (separate budget)</h2>
<table><tr><th>Part</th><th>Move</th><th class="num">Net / yr</th></tr>{top_rows}</table>
<p class="k">{ss['parts_with_positive_move']} moves pay back, ₹{ss['net_annual_value_cr']:.1f} cr/yr net for about
₹{ss['one_off_qualification_cost_cr']:.1f} cr one-off.</p>
</div><div>
<h2>Pilot: 3 months, live feeds, real stock</h2>
<ul>
<li><b>Scope:</b> all suppliers; inbox owned by a named risk analyst (0.5 FTE); weekly 30-minute review with category managers.</li>
<li><b>Cost:</b> {fmt_inr(one_off)} one-off (ERP stock and in-transit feed, set-up) + about {fmt_inr(pilot_run)} running for the 3 months.</li>
<li><b>Success KPIs:</b> ≥ 80% of relevant signals caught; ≥ 60% of alerts worth acting on; median warning ≥ 7 days; signal to
quantified impact in under 5 minutes; impact within ±25% on any real event; a logged decision on every inbox alert within its
response time; briefing rated useful (≥ 4/5) by category managers; no expediting where cover was enough.</li>
<li><b>Stop rule:</b> if alert precision is under 60% after week 6, or nobody acts on the briefings, we stop.</li>
</ul>
<h2>Risks</h2>
<ul><li>Results so far are on synthetic data; real feeds are messier. The pilot exists to measure that.</li>
<li>Needs an ERP stock feed; without current cover the impact numbers are guesses.</li>
<li>Benefit is concentrated in a few large events; the case holds without them, but thinner.</li></ul>
</div></div>

<div class="ask"><b>Decision requested.</b> (1) Approve the 3-month pilot ({fmt_inr(one_off + pilot_run)}). (2) Name the risk owner.
(3) Give IT the go-ahead for a read-only ERP stock and in-transit feed. The dual-sourcing programme is a separate decision for
Head of Supply Chain + Quality, using the structural table.</div>
</main></body></html>"""


def build() -> list[str]:
    g = gather()
    OUT.mkdir(exist_ok=True)
    (OUT / "m6.html").write_text(build_report(g), encoding="utf-8")
    (OUT / "coo_onepager.html").write_text(build_onepager(g), encoding="utf-8")
    bc = g["bc"]
    (OUT / "m6_data.json").write_text(json.dumps({
        "annual_cost_inr": bc["annual_cost_inr"], "cost_rows": bc["cost_rows"], "base": bc["base"],
        "scenarios": bc["scenarios"], "structural_summary": g["ss"],
        "structural": json.loads(g["st"].to_json(orient="records")),
        "ablations": json.loads(g["fa"]["ablations"].to_json(orient="records")), "load": g["fa"]["load"],
    }, indent=1, default=float), encoding="utf-8")
    return [str(OUT / "m6.html"), str(OUT / "coo_onepager.html")]


if __name__ == "__main__":
    print(build())

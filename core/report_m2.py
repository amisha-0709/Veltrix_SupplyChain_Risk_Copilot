"""M2 exhibits: impact-engine validation, acceptance scenarios, approval compliance → reports/m2.html

    python -m core.report_m2
"""
from __future__ import annotations

import html
import json

import pandas as pd

from core.etl import load
from core.impact import DELAY_PRIORS, Scenario, fmt_inr
from core.mitigate import approver, recommend
from core.report import CSS, JS, OUT
from core.validate_impact import TIME_TO_EFFECT, summary, validate

E = html.escape
ACTION_KIND = {
    "Air-freight expedite": "expedite", "Broker spot buy": "broker",
    "Pay container surcharge / spot freight": "expedite", "Pre-buy buffer stock (late)": "prebuy",
    "Qualify new supplier": "switch", "Re-route via alternate route": "expedite",
    "Switch to qualified alternate supplier": "switch",
}

SCENARIOS = [
    ("T1", "Typhoon forecast for southern Taiwan in 5 days",
     Scenario(nodes=["port:Kaohsiung"], event_type="port_closure", duration_days=4), 5),
    ("T4", "China export licensing on rare-earth magnets",
     Scenario(nodes=["cat:Magnets", "country:China"], match="all", event_type="trade_licensing", duration_days=49), 14),
    ("T5", "Shenzhen PCB supplier delaying payments (supplier health)",
     Scenario(nodes=["sup:SUP-029"], event_type="supplier_outage", duration_days=60), 45),
    ("T6", "Penang semiconductor output stops for six weeks",
     Scenario(nodes=["port:Penang"], event_type="supplier_outage", delay_days=42), 0),
    ("T7", "Heavy rain for Mumbai, JNPT congestion rising",
     Scenario(nodes=["dest:Nhava Sheva (JNPT)"], event_type="congestion", duration_days=5), 2),
    ("T8", "Ransomware at a Japanese passives supplier, reported on the day",
     Scenario(nodes=["sup:SUP-019"], event_type="supplier_outage"), 0),
]


def approval_compliance() -> pd.DataFrame:
    m = load()["mitigation_actions"].copy()
    m["required"] = [approver(ACTION_KIND[a], c) for a, c in zip(m["action"], m["cost_inr"])]
    m["compliant"] = [req.startswith(act) or act in req for act, req in zip(m["approved_by"], m["required"])]
    return m


def _tbl(df: pd.DataFrame, cols: dict, num=()) -> str:
    th = "".join(f"<th class='{'num' if c in num else ''}'>{E(h)}</th>" for c, h in cols.items())
    rows = []
    for r in df.to_dict("records"):
        tds = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, float) and pd.isna(v):
                v = "—"
            elif c.endswith("_inr") and isinstance(v, (int, float)):
                v = fmt_inr(v)
            elif isinstance(v, float):
                v = f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}"
            elif isinstance(v, bool):
                v = "✓" if v else "✗"
            tds.append(f"<td class='{'num' if c in num else ''}'>{E(str(v))}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def build() -> str:
    v = validate()
    s = summary(v)
    comp = approval_compliance()
    n_bad = int((~comp["compliant"]).sum())
    bad_val = comp.loc[~comp["compliant"], "cost_inr"].sum()

    scen_html, scen_json = [], []
    for tid, title, sc, lead in SCENARIOS:
        r = recommend(sc, lead)
        basis = r["stress"] if r["mode"] == "precautionary" else r["expected"]
        t, et = basis.totals, r["expected"].totals
        o = r["options"].head(5)
        pv = r["plan_value"]
        head = (f"<b>Expected:</b> {et['parts_affected']} parts linked, {et['parts_short']} run short, "
                f"{et['skus_stopped']} SKUs stop, revenue at risk {fmt_inr(et['revenue_at_risk_inr'])}, "
                f"margin at risk {fmt_inr(et['margin_at_risk_inr'])}. Revenue exposed {fmt_inr(et['revenue_exposed_per_day_inr'])}/day. "
                + (f"Customers below 95% OTIF: {', '.join(et['customers_below_otif'])}." if et['customers_below_otif'] else ""))
        if r["mode"] == "precautionary":
            head += (f"<br><b>Stress case (slowest recovery in history):</b> {t['skus_stopped']} SKUs stop, "
                     f"revenue at risk {fmt_inr(t['revenue_at_risk_inr'])}. Options below are <i>precautionary</i>.")
        plan = (f"<p><b>Recommended plan:</b> cost {fmt_inr(pv['cost_inr'])}, margin protected "
                f"{fmt_inr(pv['margin_protected_inr'])}, revenue protected {fmt_inr(pv.get('revenue_protected_inr', 0))}"
                + (f", ROI {pv['roi']:.1f}×" if pv.get('roi') is not None else "")
                + f". Approver(s): {', '.join(pv['approvers'])}. <i>Recommended, not approved.</i></p>") if pv else ""
        cols = {"rank": "#", "part_id": "Part", "option": "Option", "time_to_effect_days": "Effect (d)",
                "on_time": "In time", "cost_inr": "Cost", "net_value_inr": "Net value", "roi": "ROI",
                "approver": "Approver"}
        cols = {k: h for k, h in cols.items() if k in o.columns}
        work = "".join(f"<li>{E(w)}</li>" for w in basis.working)
        exp_parts = basis.parts[basis.parts["shortage_days"] > 0] if len(basis.parts) else basis.parts
        pt = exp_parts if len(exp_parts) else basis.parts.head(6)
        scen_html.append(
            f"<div class='card'><h3>{tid} · {E(title)}</h3><p>{head}</p>"
            f"<details><summary>Working (playbook §3)</summary><ol>{work}</ol>"
            + _tbl(pt, {"part_id": "Part", "description": "Description", "days_of_cover": "Cover (d)",
                        "effective_delay_days": "Delay (d)", "shortage_days": "Short (d)"},
                   num=("days_of_cover", "effective_delay_days", "shortage_days"))
            + "</details>"
            + _tbl(o, cols, num=("rank", "time_to_effect_days", "cost_inr", "net_value_inr", "roi")) + plan + "</div>")
        scen_json.append({"id": tid, "title": title, "mode": r["mode"], "expected": et, "stress": r["stress"].totals if r["stress"] else None,
                          "options": json.loads(r["options"].to_json(orient="records")), "plan_value": pv})

    prior_rows = "".join(
        f"<tr><td>{E(k)}</td><td>{E(p['label'])}</td><td class='num'>{p.get('ratio', '')}</td>"
        f"<td class='num'>{p.get('fixed', '')}</td><td class='num'>{p.get('stress', p.get('stress_fixed', ''))}</td>"
        f"<td class='num'>{p['default_duration']}</td><td>{', '.join(p['fit_on'])}</td></tr>"
        for k, p in DELAY_PRIORS.items())

    vcols = {"disruption_id": "ID", "split": "Split", "class": "Event class", "duration_days": "Duration",
             "delay_actual": "Delay actual", "delay_predicted": "Delay predicted", "actual_cr": "Actual ₹ cr",
             "A_method_cr": "A: method ₹ cr", "A_err_pct": "A err %", "B1_forecast_cr": "B1: forecast ₹ cr",
             "B1_err_pct": "B1 err %", "B2_at_risk_no_action_cr": "B2: at risk, no action ₹ cr"}
    comp_t = comp.groupby(["action", "approved_by", "required"]).agg(n=("cost_inr", "size"), cost_inr=("cost_inr", "sum")).reset_index()
    comp_t = comp_t[comp_t["approved_by"] != comp_t["required"]].sort_values("cost_inr", ascending=False)

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Veltrix M2 Impact Engine</title>
<style>{CSS} details{{margin:8px 0}} summary{{cursor:pointer;color:var(--ink2)}}</style></head><body><main>
<p class="note">PS-06 · M2: impact engine + mitigation ranker · synthetic data</p>
<h1>The impact engine reproduces Veltrix's history, then says what to do about it</h1>
<p class="lede">The engine follows playbook §3 step for step and shows its working. Options follow §4–7: cost, time to effect,
net value, ROI and the approver from the matrix. Every number below comes from code, not from a language model.</p>
<div class="tiles">
<div class="tile"><b>{s['A']['median_abs_err_pct']:.1f}%</b><span>median error replaying D01–D18 with history's delay and cover ({s['A']['within_25pct']} within ±25%)</span></div>
<div class="tile"><b>{s['B1']['median_abs_err_pct']:.0f}%</b><span>median error using the engine's own delay estimate ({s['B1']['within_25pct']} within ±25%; ₹{s['B1']['total_predicted_cr']} cr vs ₹{s['B1']['total_actual_cr']} cr in total)</span></div>
<div class="tile"><b>{s['A']['zero_loss_correct'].split(' ')[0]}</b><span>disruptions with no revenue loss correctly called "no shortage"</span></div>
<div class="tile"><b>{n_bad} of {len(comp)}</b><span>past mitigations approved below the level the matrix requires ({fmt_inr(bad_val)})</span></div>
</div>

<h2>1 · Validation against D01–D18</h2>
<p class="lede"><b>A · Method replay:</b> history's parts, cover at start and effective delay, with the team's real mitigations
taking effect at decision day + time to effect. <b>B1 · Forecast:</b> the delay comes from the event-class prior (fitted on train
D01–D13 only) × the event's duration, with the same mitigation timing. <b>B2:</b> what the alert would have shown on day one with
no action.</p>
<div class="card">{_tbl(v, vcols, num=tuple(c for c in vcols if c not in ('disruption_id', 'split', 'class')))}
<p class="note">Where A misses: D02 is tiny (₹0.06 cr). D08 and D18 hinge on when broker buys landed. History shows 1 to 15 days, and we
use the median of 4. B1's biggest miss is D08 (earthquake): sudden supplier outages vary from 0.9× to 2× their duration. That's why
the co-pilot always shows a stress case for supplier outages.</p></div>
<div class="card"><h3>Delay model (event class → effective delay)</h3>
<table><thead><tr><th>Class</th><th>Meaning</th><th class="num">Ratio</th><th class="num">Fixed d</th><th class="num">Stress</th>
<th class="num">Default duration</th><th>Fitted on</th></tr></thead><tbody>{prior_rows}</tbody></table>
<p class="note">Time to effect used when replaying history: {E(json.dumps({k: v for k, v in TIME_TO_EFFECT.items() if v}, ensure_ascii=False))}.
History shows supplier switches took ~19 days to take hold, not the playbook's 5–10. Alternate capacity ramps slowly.
The ranker uses the playbook value but flags it.</p></div>

<h2>2 · Acceptance scenarios (on today's stock, 30 Sep 2026 snapshot)</h2>
<p class="lede">Each card is what an alert would carry: the impact, the working, and ranked options. An option that can't take effect
before the shortage starts ranks below every on-time option (playbook §5). Re-allocation and demand shaping rank below options
that actually shorten the shortage.</p>
{''.join(scen_html)}

<h2>3 · Approval compliance in history</h2>
<p class="lede">The matrix (playbook §7) says who must approve each kind of mitigation by value. In history the category manager
approved {int((comp['approved_by'] == 'Category manager').sum())} of {len(comp)} actions, including broker buys and pre-buys that
need the Head of Supply Chain. The co-pilot shows the required approver on every option and never marks one as approved.</p>
<div class="card">{_tbl(comp_t, {"action": "Action", "approved_by": "Approved by", "required": "Matrix requires", "n": "Count", "cost_inr": "Value"}, num=("n", "cost_inr"))}</div>
</main><div id="tip" role="tooltip"></div><script>{JS}</script></body></html>"""
    OUT.mkdir(exist_ok=True)
    (OUT / "m2.html").write_text(page, encoding="utf-8")
    (OUT / "m2_data.json").write_text(json.dumps({"validation": json.loads(v.to_json(orient="records")),
                                                  "summary": s, "scenarios": scen_json}, indent=1, default=str),
                                      encoding="utf-8")
    return str(OUT / "m2.html")


if __name__ == "__main__":
    print(build())

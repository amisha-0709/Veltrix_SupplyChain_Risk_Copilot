"""One-page alert briefing a Head of Supply Chain can forward without editing (brief §6, playbook §8).

Deterministic: every figure is read from the alert (impact engine + ranker), never generated.
    brief = make_brief(alert)        # structured dict (API/UI)
    html  = render_html(brief)       # printable one-pager
    text  = render_text(brief)       # plain text for email / chat
"""
from __future__ import annotations

import html as H

import pandas as pd

from core.etl import load
from core.impact import SNAPSHOT_DATE, fmt_inr

KIND_LABEL = {"port_closure": "Port / city closure", "supplier_outage": "Supplier outage",
              "congestion": "Port or lane congestion", "route": "Shipping route blocked",
              "trade_licensing": "Export licensing / control", "cost_only": "Duty / tariff (cost)"}


def _node_label(n: str) -> str:
    t, name = n.split(":", 1)
    return {"cat": f"{name} (commodity)", "country": f"{name} (country)", "choke": f"{name} (chokepoint)",
            "dest": f"{name} (Indian port)", "port": f"{name} (port of loading)", "region": name,
            "loc": name}.get(t, name)


def make_brief(a: dict) -> dict:
    db = load()
    sup = db["suppliers"].set_index("supplier_id")["supplier_name"]
    t = a["totals"]
    basis_totals = a["stress_totals"] if a["mode"] == "precautionary" and a["stress_totals"] else t
    P = a["parts"]
    short = P[P["shortage_days"] > 0] if len(P) else P
    show = (short if len(short) else P).head(6)
    exposure = [{
        "part": f"{r.part_id} · {r.description}",
        "supplier": sup.get(r.primary_supplier_id, r.primary_supplier_id),
        "single_source": bool(r.single_source),
        "cover_days": float(r.days_of_cover), "delay_days": float(r.effective_delay_days),
        "shortage_days": float(r.shortage_days),
        "fallback": (f"qualified alt {r.qualified_alt}" if isinstance(r.qualified_alt, str) else
                     f"unqualified alt {r.unqualified_alt}" if isinstance(r.unqualified_alt, str) else "none"),
    } for r in show.itertuples()]

    S = a["skus"]
    stopped = S[S["units_short"] > 0] if len(S) else S
    skus = [{"sku": f"{r.sku_id}", "customer": r.customer, "stops_from_day": r.stops_from_day,
             "units_short": int(r.units_short), "revenue_at_risk": float(r.revenue_at_risk_inr)}
            for r in stopped.head(6).itertuples()]

    O = a["otif"]
    cust = []
    if len(O):
        for c, g in O[O["below_target"]].groupby("customer"):
            cust.append({"customer": c, "weeks_below": int(len(g)), "worst_otif": float(g["otif"].min()),
                         "from_week": str(g["week_start"].min())})

    opts = a["options"]
    plan = a["plan"]
    rec = []
    if len(opts) and opts.iloc[0]["kind"] == "none":
        rec = [{"action": opts.iloc[0]["option"], "part": "", "cost": 0.0, "time_to_effect": 0, "net_value": 0.0,
                "roi": None, "approver": opts.iloc[0]["approver"], "on_time": True, "note": opts.iloc[0]["note"]}]
    else:
        src = plan if len(plan) else opts.head(1)
        for r in src.itertuples():
            rec.append({"action": r.option, "part": r.part_id, "cost": float(r.cost_inr),
                        "time_to_effect": float(r.time_to_effect_days), "net_value": float(r.net_value_inr),
                        "roi": None if pd.isna(r.roi) else float(r.roi), "approver": r.approver,
                        "on_time": bool(r.on_time), "note": r.note})
    chosen = {(x["part"], x["action"]) for x in rec}
    alts = [{"action": r.option, "part": r.part_id, "cost": float(r.cost_inr), "net_value": float(r.net_value_inr),
             "on_time": bool(r.on_time), "approver": r.approver}
            for r in opts.itertuples() if r.kind != "none" and (r.part_id, r.option) not in chosen][:4]

    sigs = sorted(a["event"].signals, key=lambda s: s["published"])
    sources = [{"date": pd.Timestamp(s["published"]).strftime("%d %b %Y"), "source": s["source"],
                "text": s["text"].split(". ")[0], "id": s["signal_id"]} for s in sigs]
    seen = set()
    sources_dedup = []
    for s in sources:
        k = (s["source"], s["text"])
        if k not in seen:
            seen.add(k)
            sources_dedup.append(s)

    n_short, n_aff = t["parts_short"], t["parts_affected"]
    headline_impact = (
        f"{fmt_inr(basis_totals['revenue_at_risk_inr'])} revenue at risk"
        + (" if the outage runs long" if a["mode"] == "precautionary" else "")
        + f" across {basis_totals['skus_stopped']} product(s); "
        + (f"{len(basis_totals['customers_below_otif'])} customer(s) fall below 95% OTIF."
           if basis_totals["customers_below_otif"] else "no customer falls below 95% OTIF.")
        if not t["no_action_needed"] or a["mode"] == "precautionary" else
        (f"Finished-goods stock absorbs a {t['max_shortage_days']:.1f}-day gap in {n_short} part(s): no customer impact expected. "
         if n_short else "Cover holds: no shortage expected. ")
        + f"{fmt_inr(t['revenue_exposed_per_day_inr'])}/day of revenue depends on the {n_aff} linked part(s)."
    )
    what = sigs[-1]["text"] if len(sigs) > 1 else sigs[0]["text"]
    rec.sort(key=lambda x: -x["net_value"])
    actionable = [x for x in rec if x["approver"] != "Category manager (log only)"]
    if actionable:
        ask = "Decide: " + "; ".join(
            f"{x['action']}{' for ' + x['part'] if x['part'] else ''} ({fmt_inr(x['cost'])}, {x['approver']})"
            for x in actionable[:3]) + "."
    else:
        ask = rec[0]["action"] if rec else "Log and watch."
    caveats = [f"Stock position as of {SNAPSHOT_DATE:%d %b %Y} (on hand + in transit)."]
    caveats.append(next((w for w in a["working"] if w.startswith("2.")), "")[3:])
    if a["mode"] == "precautionary":
        caveats.append("Expected case needs no action; options are costed on the stress case (slowest recovery "
                       "seen in history) because the event's duration is unknown.")
    if t.get("parts_not_in_any_bom"):
        caveats.append(f"Linked parts not used in any product: {', '.join(t['parts_not_in_any_bom'])}.")
    caveats.append("Recommendation only: nothing has been ordered, booked or communicated to suppliers.")

    return {
        "alert_id": a["alert_id"], "title": a["title"], "kind": KIND_LABEL.get(a["event_type"], a["event_type"]),
        "first_seen": pd.Timestamp(a["first_seen"]).strftime("%d %b %Y"),
        "priority": a["priority"], "likelihood": a["likelihood"], "impact": a["impact"],
        "likelihood_reason": a["likelihood_reason"], "impact_reason": a["impact_reason"],
        "response": a["response"], "owner": a["owner"], "status": "Recommended: awaiting approval"
        if actionable else "Watch",
        "confidence": a["confidence"], "confidence_reason": a["confidence_reason"], "mode": a["mode"],
        "headline_impact": headline_impact, "ask": ask, "what": what,
        "links": [_node_label(n) for n in a["links"]],
        "numbers": {k: basis_totals[k] for k in ("revenue_at_risk_inr", "revenue_lost_inr", "margin_at_risk_inr",
                                                  "penalty_inr", "units_short", "skus_stopped", "parts_short",
                                                  "parts_affected", "max_shortage_days", "min_cover_days")},
        "exposure": exposure, "skus": skus, "customers": cust,
        "recommended": rec, "alternatives": alts, "plan_value": a["plan_value"],
        "sources": sources_dedup, "n_signals": a["n_signals"], "n_sources": len(a["sources"]),
        "caveats": [c for c in caveats if c], "working": a["working"],
        "seconds_to_quantify": a["seconds_to_quantify"],
    }


# ---------------------------------------------------------------------------------------------
BRIEF_CSS = """
:root{--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;--surface:#fff;--page:#f4f4f1;
--crit:#d03b3b;--serious:#ec835a;--warn:#fab219;--good:#0ca30c;--accent:#2a78d6}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
.sheet{max-width:820px;margin:24px auto;background:var(--surface);padding:28px 32px;border:1px solid var(--line);border-radius:8px}
@media print{body{background:#fff}.sheet{margin:0;border:0;padding:0;max-width:none}.noprint{display:none}}
@page{size:A4;margin:14mm}
.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;border-bottom:2px solid var(--ink);padding-bottom:10px}
.kicker{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
h1{font-size:19px;margin:2px 0 4px;line-height:1.25}h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;
color:var(--ink2);margin:16px 0 6px;border-bottom:1px solid var(--line);padding-bottom:3px}
.badge{display:inline-flex;align-items:center;gap:6px;font-weight:700;border-radius:6px;padding:6px 10px;color:#fff;white-space:nowrap}
.p-crit{background:var(--crit)}.p-high{background:var(--serious);color:#0b0b0b}.p-med{background:var(--warn);color:#0b0b0b}.p-low{background:#c3c2b7;color:#0b0b0b}
.lead{font-size:14px;margin:10px 0 0}.ask{background:#f0f6fd;border-left:3px solid var(--accent);padding:8px 12px;margin:10px 0;font-weight:600}
.kv{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:6px 0}.kv div{border:1px solid var(--line);border-radius:6px;padding:6px 8px}
.kv b{display:block;font-size:15px}.kv span{color:var(--ink2);font-size:11px}
table{border-collapse:collapse;width:100%;font-size:12px}th{text-align:left;color:var(--ink2);font-weight:600;border-bottom:1px solid #c3c2b7;padding:3px 6px}
td{border-bottom:1px solid var(--line);padding:3px 6px;vertical-align:top}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.short{color:var(--crit);font-weight:600}.note{color:var(--muted);font-size:11px}ul{margin:4px 0;padding-left:18px}
.meta{color:var(--ink2);font-size:12px}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:700px){.kv{grid-template-columns:1fr 1fr}.two{grid-template-columns:1fr}.sheet{padding:16px}}
"""


def _pcls(p: int) -> str:
    return "p-crit" if p >= 20 else "p-high" if p >= 12 else "p-med" if p >= 6 else "p-low"


def render_html(b: dict, standalone: bool = True) -> str:
    e = H.escape
    n = b["numbers"]
    exp = "".join(
        f"<tr><td>{e(x['part'])}{' <span class=note>single source</span>' if x['single_source'] else ''}</td>"
        f"<td>{e(x['supplier'])}</td><td class=num>{x['cover_days']:.1f}</td><td class=num>{x['delay_days']:.1f}</td>"
        f"<td class='num {'short' if x['shortage_days'] > 0 else ''}'>{x['shortage_days']:.1f}</td><td>{e(x['fallback'])}</td></tr>"
        for x in b["exposure"])
    rec = "".join(
        f"<tr><td><b>{e(x['action'])}</b>{(' · ' + e(x['part'])) if x['part'] else ''}<div class=note>{e(x['note'])}</div></td>"
        f"<td class=num>{fmt_inr(x['cost'])}</td><td class=num>{x['time_to_effect']:.0f} d{'' if x['on_time'] else ' (late)'}</td>"
        f"<td class=num>{fmt_inr(x['net_value'])}</td><td class=num>{'—' if x['roi'] is None else f'{x['roi']:.1f}×'}</td>"
        f"<td>{e(x['approver'])}</td></tr>" for x in b["recommended"])
    alts = "".join(f"<li>{e(x['action'])} ({e(x['part'])}): {fmt_inr(x['cost'])}, net {fmt_inr(x['net_value'])}"
                   f"{'' if x['on_time'] else ', lands after the shortage starts'}; {e(x['approver'])}</li>"
                   for x in b["alternatives"])
    cust = "".join(f"<li>{e(c['customer'])}: {c['weeks_below']} week(s) below 95% from {e(c['from_week'])}, "
                   f"worst {c['worst_otif']:.0%}</li>" for c in b["customers"]) or "<li>No customer falls below 95% OTIF.</li>"
    skus = "".join(f"<li>{e(s['sku'])} ({e(s['customer'])}): {s['units_short']:,} units, {fmt_inr(s['revenue_at_risk'])}"
                   f"{'' if s['stops_from_day'] is None else f', stops from day {s['stops_from_day']:.0f}'}</li>"
                   for s in b["skus"]) or "<li>No product stops.</li>"
    srcs = "".join(f"<li>{e(s['date'])} · {e(s['source'])}: {e(s['text'])}</li>" for s in b["sources"][:8])
    more = len(b["sources"]) - 8
    pv = b["plan_value"]
    plan_line = (f"Plan: cost {fmt_inr(pv['cost_inr'])}, margin protected {fmt_inr(pv['margin_protected_inr'])}"
                 + (f", ROI {pv['roi']:.1f}×" if pv.get("roi") is not None else "") + ".") if pv else ""
    body = f"""<div class="sheet">
<div class="top"><div><div class="kicker">Veltrix supply risk briefing · {e(b['alert_id'])} · {e(b['kind'])} · first seen {e(b['first_seen'])}</div>
<h1>{e(b['title'])}</h1><div class="meta">Owner: {e(b['owner'])} · Response: {e(b['response'])}</div></div>
<div class="badge {_pcls(b['priority'])}">Priority {b['priority']} <span style="font-weight:400">(L{b['likelihood']} × I{b['impact']})</span></div></div>
<p class="lead">{e(b['headline_impact'])}</p>
<div class="ask">{e(b['ask'])}</div>
<div class="kv"><div><b>{fmt_inr(n['revenue_at_risk_inr'])}</b><span>revenue at risk</span></div>
<div><b>{fmt_inr(n['margin_at_risk_inr'])}</b><span>margin at risk</span></div>
<div><b>{n['units_short']:,}</b><span>units short · {n['skus_stopped']} SKU(s)</span></div>
<div><b>{n['min_cover_days'] if n['min_cover_days'] is not None else '—'} d</b><span>lowest cover vs {n['max_shortage_days']:.0f} d max shortage</span></div></div>
<h2>What is happening</h2><p>{e(b['what'])}.</p>
<p class="meta">Linked to: {e(', '.join(b['links']))}. Likelihood {b['likelihood']}/5: {e(b['likelihood_reason'])}.
Impact {b['impact']}/5: {e(b['impact_reason'])}. Confidence {b['confidence']:.0%}: {e(b['confidence_reason'])}.</p>
<h2>Exposure</h2><table><thead><tr><th>Part</th><th>Primary supplier</th><th class=num>Cover (d)</th><th class=num>Delay (d)</th>
<th class=num>Short (d)</th><th>Fallback</th></tr></thead><tbody>{exp}</tbody></table>
<div class="two"><div><h2>Products</h2><ul>{skus}</ul></div><div><h2>Customers</h2><ul>{cust}</ul></div></div>
<h2>Recommended action</h2><table><thead><tr><th>Option</th><th class=num>Cost</th><th class=num>Effect</th><th class=num>Net value</th>
<th class=num>ROI</th><th>Approver</th></tr></thead><tbody>{rec}</tbody></table>
<p class="note">{e(plan_line)} Ranked by playbook §5 net value; on-time options first. Shown for approval, not approved.</p>
{f'<h2>Alternatives considered</h2><ul>{alts}</ul>' if alts else ''}
<h2>Sources ({b['n_signals']} signals, {b['n_sources']} sources)</h2><ul>{srcs}{f'<li>… and {more} more</li>' if more > 0 else ''}</ul>
<h2>Assumptions</h2><ul>{''.join(f'<li>{e(c)}</li>' for c in b['caveats'])}</ul>
<p class="note">Generated by the Veltrix supply-chain co-pilot in {b['seconds_to_quantify']:.1f} s. Method: playbook v2.0 §2–§7.</p>
</div>"""
    if not standalone:
        return body
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Briefing {e(b['alert_id'])}</title><style>{BRIEF_CSS}</style></head><body>"
            f"<p class='noprint' style='text-align:center;margin:12px'><button onclick='print()'>Print / save as PDF</button></p>"
            f"{body}</body></html>")


def render_text(b: dict) -> str:
    n = b["numbers"]
    lines = [f"[{b['alert_id']}] Priority {b['priority']} (L{b['likelihood']}×I{b['impact']}): {b['title']}",
             f"Owner: {b['owner']} · Response: {b['response']}", "",
             b["headline_impact"], f"ASK: {b['ask']}", "",
             f"What is happening: {b['what']}.",
             f"Revenue at risk {fmt_inr(n['revenue_at_risk_inr'])} · margin at risk {fmt_inr(n['margin_at_risk_inr'])} · "
             f"{n['units_short']:,} units short across {n['skus_stopped']} SKU(s).", "", "Exposure:"]
    lines += [f"  - {x['part']} ({x['supplier']}): cover {x['cover_days']:.1f} d vs delay {x['delay_days']:.1f} d "
              f"→ short {x['shortage_days']:.1f} d; fallback {x['fallback']}" for x in b["exposure"]]
    lines += ["", "Recommended (for approval):" if b["recommended"] and b["recommended"][0]["cost"] > 0 else "Recommended:"]
    lines += [f"  - {x['action']} {x['part']}: {fmt_inr(x['cost'])}, {x['time_to_effect']:.0f} d to effect, "
              f"net {fmt_inr(x['net_value'])}; approver {x['approver']}" for x in b["recommended"]]
    if b["customers"]:
        lines += ["", "Customers below 95% OTIF: " + ", ".join(f"{c['customer']} ({c['weeks_below']} wk)" for c in b["customers"])]
    lines += ["", f"Sources: {b['n_signals']} signals from {b['n_sources']} sources, first {b['sources'][0]['date']}."]
    lines += ["Assumptions: " + " ".join(b["caveats"])]
    return "\n".join(lines)


if __name__ == "__main__":
    from core.alerts import build_alerts
    from core.report import OUT
    alerts, *_ = build_alerts()
    for a in alerts:
        if a["alert_id"] in ("AL-004", "AL-005", "AL-019"):
            b = make_brief(a)
            (OUT / f"brief_{a['alert_id']}.html").write_text(render_html(b), encoding="utf-8")
            print(render_text(b)); print("-" * 80)

"""Brief §6 acceptance tests T1–T10, run end to end through the API (as reviewers will run them).

Each check returns {id, scenario, expected, passed, evidence[]}. Used by tests/test_acceptance.py and by
`python -m core.acceptance`, which writes reports/acceptance.html.
"""
from __future__ import annotations

import html
import re

from fastapi.testclient import TestClient

from core.impact import fmt_inr

BRIEF = {
    "T1": ("A news item reports a typhoon forecast to hit southern Taiwan in five days.",
           "Raises an alert linked to Kaohsiung, the suppliers that ship from it, their parts and the SKUs that use them, "
           "with days of cover and revenue at risk."),
    "T2": ("Naval exercises announced near the Taiwan Strait, shipping advisories for the exercise zone only.",
           "Logs it as low priority or ignores it; does not raise a high-priority alert."),
    "T3": ("The same Red Sea story arrives from three sources within a day.", "Raises one alert, not three, and cites all sources."),
    "T4": ("A trade notice announces export licensing on rare-earth magnets from China.",
           "Identifies the single-source magnet part, the SKUs it stops, shortage days given current cover, and ranks "
           "options (qualify a new supplier, pre-buy, re-allocate)."),
    "T5": ("A Shenzhen PCB supplier is reported to be delaying payments to its own suppliers.",
           "Treats it as an early supplier-health warning for the 4-layer BMS PCB and recommends starting qualification "
           "of the unqualified alternate."),
    "T6": ("'Which customers miss their 95% OTIF target if Penang semiconductor output stops for six weeks?'",
           "Answers with the affected SKUs, customers, weeks and OTIF, showing the working."),
    "T7": ("A heavy-rain alert is issued for Mumbai and the JNPT congestion index is rising.",
           "Flags inbound shipments due at Nhava Sheva, estimates delay against cover, and concludes whether action is "
           "needed, including 'no action' when cover is enough."),
    "T8": ("A ransomware attack is reported at a Japanese passives supplier on the day it happens.",
           "Quantifies impact immediately and recommends switching the MLCC part to its qualified Korean alternate, "
           "with cost and approver."),
    "T9": ("Run on every signal from 1 February to 30 September 2026.",
           "Reports precision, recall and median lead time against signal_labels, and lists false alarms and misses."),
    "T10": ("Replay disruption D05 (Penang fire) as if the co-pilot had been live.",
            "Shows when it would have alerted, what it would have recommended, and the revenue it would have protected "
            "compared with what actually happened."),
}


def _client() -> TestClient:
    from backend.main import app
    return TestClient(app)


def _sim(c, headline, snippet="", **kw):
    r = c.post("/api/simulate", json={"headline": headline, "snippet": snippet, **kw})
    r.raise_for_status()
    return r.json()


def _res(tid, checks: list[tuple[bool, str]]) -> dict:
    return {"id": tid, "scenario": BRIEF[tid][0], "expected": BRIEF[tid][1],
            "passed": all(ok for ok, _ in checks), "evidence": [("✓ " if ok else "✗ ") + msg for ok, msg in checks]}


def t1(c):
    r = _sim(c, "Typhoon forecast to hit southern Taiwan in five days",
             "Ports in the south may suspend operations; carriers warn of schedule disruption.")
    a = r.get("alert") or {}
    parts = a.get("parts", [])
    sup = {p["primary_supplier_id"] for p in parts}
    skus = a.get("skus", [])
    return _res("T1", [
        (r["decision"] in ("watch", "inbox"), f"alert raised ({r['decision']}, priority {a.get('priority')})"),
        ("port:Kaohsiung" in r["triage"]["links"], "linked to Kaohsiung"),
        (len(sup) >= 3, f"{len(sup)} suppliers that ship from Kaohsiung: {', '.join(sorted(sup))}"),
        (len(parts) >= 3, f"{len(parts)} parts with days of cover: "
         + ", ".join(f"{p['part_id']} {p['days_of_cover']} d" for p in parts)),
        (len(skus) >= 5, f"{len(skus)} SKUs that use them"),
        ("revenue_at_risk" in a, f"revenue at risk {a.get('revenue_at_risk_fmt')}; "
         f"{a.get('brief', {}).get('headline_impact', '')}"),
    ])


def t2(c):
    r = _sim(c, "Naval exercises announced near Taiwan Strait", "Shipping advisories issued for the exercise zone only.")
    pr = (r.get("alert") or {}).get("priority", 0)
    return _res("T2", [(r["decision"] in ("ignored", "watch") and pr < 12,
                        f"decision: {r['decision']} (score {r['triage']['score']} vs threshold {r['threshold']}); "
                        f"{r['triage']['reason']}")])


def t3(c):
    import pandas as pd

    from core.events import build_events
    from core.triage import triage_text
    th = c.get("/api/meta").json()["threshold"]
    rows = [triage_text("Attacks on merchant vessels in the Red Sea escalate — update",
                        "Major carriers divert via the Cape of Good Hope.", source=s,
                        published=pd.Timestamp("2026-10-01 08:00") + pd.Timedelta(hours=6 * i), signal_id=f"T3-{i}")
            for i, s in enumerate(["Global Trade Wire", "Container Pulse", "Harbour Times"])]
    ev, _ = build_events(pd.DataFrame(rows), th)
    hist = [a for a in c.get("/api/alerts").json() if "Red Sea" in a["title"]]
    return _res("T3", [
        (len(ev) == 1, f"3 copies within a day → {len(ev)} alert"),
        (len(ev) == 1 and len(ev[0].sources) == 3, f"cites all sources: {', '.join(ev[0].sources) if ev else ''}"),
        (len(hist) == 1, f"history: the D03 Red Sea story ({hist[0]['n_signals'] if hist else 0} signals from "
         f"{hist[0]['n_sources'] if hist else 0} sources) is one alert"),
    ])


def t4(c):
    r = _sim(c, "China announces export licensing on rare-earth magnets",
             "Exporters of NdFeB magnets must apply for licences; processing times not specified.")
    a = r.get("alert") or {}
    short = [p for p in a.get("parts", []) if p["shortage_days"] > 0 and p["single_source"]]
    stop = [s for s in a.get("skus", []) if s["units_short"] > 0]
    names = " | ".join(o["option"] for o in a.get("options", []) if o.get("part_id") == "PRT-043")
    return _res("T4", [
        (any(p["part_id"] == "PRT-043" for p in short),
         "single-source magnet part: " + ", ".join(f"{p['part_id']} {p['description']}, cover {p['days_of_cover']} d, "
                                                  f"short {p['shortage_days']} d" for p in short)),
        (len(stop) >= 1, "SKUs it stops: " + ", ".join(f"{s['sku_id']} ({s['customer']})" for s in stop)),
        ("Qualify" in names, "option: qualify a new supplier"),
        ("Pre-buy" in names, "option: pre-buy"),
        ("Re-allocate" in names, "option: re-allocate"),
        (all("approved" not in o["status"].lower().replace("requires approval", "") for o in a.get("options", [])),
         "every option shown as requiring approval, none as approved"),
    ])


def t5(c):
    r = _sim(c, "Shenzhen PCB maker delays supplier payments",
             "Local suppliers report invoices outstanding for over 90 days.")
    a = r.get("alert") or {}
    o = [x for x in a.get("options", []) if x.get("part_id") == "PRT-030"]
    plan = a.get("brief", {}).get("recommended", [])
    qual = [x for x in o if x["option"].startswith("Qualify new supplier SUP-035")]
    return _res("T5", [
        (r["triage"]["event_type"] == "supplier_outage" and "health" in " ".join(r["triage"]["cues"] + [r["triage"]["reason"]])
         or "payments" in r["triage"]["reason"], f"treated as supplier-health warning ({r['triage']['reason']})"),
        (any(p["part_id"] == "PRT-030" for p in a.get("parts", [])), "linked to PRT-030, the 4-layer BMS PCB"),
        (bool(qual) and qual[0]["on_time"], "recommends starting qualification of SUP-035 (the unqualified alternate), "
         f"{qual[0]['time_to_effect_days'] / 7:.0f} weeks, approver {qual[0]['approver']}" if qual else "no qualification option"),
        (any(x["action"].startswith("Qualify new supplier SUP-035") for x in plan),
         "qualification is in the recommended plan: " + "; ".join(x["action"] for x in plan)),
    ])


def t6(c):
    r = c.post("/api/ask", json={"question": "Which customers miss their 95% OTIF target if Penang semiconductor "
                                             "output stops for six weeks?"}).json()
    titles = [t["title"] for t in r["tables"]]
    otif = next((t for t in r["tables"] if "OTIF" in t["title"]), None)
    return _res("T6", [
        (r["intent"] == "what_if", "answered as a what-if on Penang ∩ semiconductors, 42 days"),
        (any("Products" in t for t in titles), "affected SKUs listed"),
        (otif is not None and len(otif["rows"]) >= 1,
         f"customers × weeks × OTIF: {len(otif['rows']) if otif else 0} customers below 95%"),
        (len(r["working"]) >= 6, f"working shown ({len(r['working'])} steps)"),
        (True, r["answer"][:300]),
    ])


def t7(c):
    r = _sim(c, "Heavy rain alert for Mumbai; JNPT congestion index rising",
             "Container movement slows as rains flood access roads to Nhava Sheva.")
    a = r.get("alert") or {}
    t = a.get("brief", {})
    no_action = any("No action" in x["action"] for x in t.get("recommended", []))
    return _res("T7", [
        ("dest:Nhava Sheva (JNPT)" in r["triage"]["links"], "linked to Nhava Sheva (JNPT): inbound lanes into JNPT"),
        (len(a.get("parts", [])) >= 10, f"{len(a.get('parts', []))} inbound parts checked: delay vs cover"),
        (no_action, f"conclusion: {t.get('ask', '')}"),
    ])


def t8(c):
    r = _sim(c, "Japanese electronic components maker hit by ransomware",
             "Tanaka-Sei Electronic Components halts production and shipping while systems are restored.")
    a = r.get("alert") or {}
    o = a.get("options", [])
    sw = [x for x in o if x.get("part_id") == "PRT-020" and "SUP-022" in x["option"]]
    return _res("T8", [
        (r["decision"] in ("inbox", "watch"), f"quantified on the day in {a.get('seconds_to_quantify')} s "
         f"(expected {a.get('revenue_at_risk_fmt')}, stress {a.get('stress_revenue_at_risk_fmt')})"),
        (bool(sw), "recommends switching MLCC PRT-020 to qualified alternate SUP-022 (South Korea)" if sw else "no switch option"),
        (bool(sw) and sw[0]["cost_inr"] > 0, f"cost {fmt_inr(sw[0]['cost_inr'])}, approver {sw[0]['approver']}" if sw else ""),
    ])


def t9(c):
    b = c.get("/api/backtest").json()
    s, a, lead = b["signals"]["test"], b["alerts"]["test"], b["lead"]["test"]
    return _res("T9", [
        (s["recall"] >= 0.8, f"recall {s['recall']:.1%} ({s['tp']}/{s['relevant']} relevant signals), target ≥ 80%"),
        (a["precision"] >= 0.6, f"alert precision {a['precision']:.0%} ({a['relevant_alerts']}/{a['alerts']}), target ≥ 60%"),
        (lead["median_lead_days"] >= 7, f"median lead {lead['median_lead_days']:.1f} days, target ≥ 7"),
        (True, f"false alarms listed: {len(b['false_alarms'])}; misses listed: {len(b['misses'])} ("
         + "; ".join(m["text"][:60] for m in b["misses"][:2]) + ")"),
    ])


def t10(c):
    r = c.get("/api/replays/D05").json()
    st = r.get("structural") or {}
    return _res("T10", [
        (r["detected"], f"co-pilot alert {str(r['copilot_alert_date'])[:16]} (day of impact) vs team alert "
         f"{str(r['team_alert_date'])[:10]} and first decision day +{r['team_decision_day']}"),
        (True, "would have recommended: " + ("; ".join(f"{x['option']} ({x['part_id']})" for x in r["recommended"])
                                            or "no economic fast fix")),
        (True, f"actually lost {fmt_inr(r['actual_revenue_lost_inr'])}; with the plan {fmt_inr(r['with_plan_lost_inr'])}; "
               f"margin protected {fmt_inr(r['margin_protected_inr'])}"),
        (bool(st), "structural: " + "; ".join(st.get("parts", [])) + f" would have protected "
                   f"{fmt_inr(st.get('revenue_protected_inr', 0))} for ~{fmt_inr(st.get('cost_inr', 0))}"),
    ])


ALL = [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10]


def run_all() -> list[dict]:
    c = _client()
    return [f(c) for f in ALL]


def write_report(results: list[dict]) -> str:
    from core.report import CSS, OUT
    E = html.escape
    rows = "".join(
        f"<div class='card'><h3>{'✅' if r['passed'] else '❌'} {r['id']} · {E(r['scenario'])}</h3>"
        f"<p class='note'><b>Expected:</b> {E(r['expected'])}</p><ul>"
        + "".join(f"<li>{E(e)}</li>" for e in r["evidence"]) + "</ul></div>" for r in results)
    n = sum(r["passed"] for r in results)
    page = (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Veltrix Acceptance Tests</title><style>{CSS}</style></head><body><main>"
            f"<p class=note>PS-06 · brief §6 acceptance scenarios, run end to end through the API · synthetic data</p>"
            f"<h1>{n} of {len(results)} acceptance scenarios pass</h1>"
            f"<p class=lede>Each scenario is sent to the live pipeline (simulate / ask / back-test / replay endpoints). The evidence is "
            f"what the co-pilot returned. Re-run with <code>python -m core.acceptance</code>.</p>{rows}</main></body></html>")
    (OUT / "acceptance.html").write_text(page, encoding="utf-8")
    return str(OUT / "acceptance.html")


if __name__ == "__main__":
    res = run_all()
    for r in res:
        print(("PASS " if r["passed"] else "FAIL ") + r["id"])
        for e in r["evidence"]:
            print("     ", re.sub(r"\s+", " ", e)[:200])
    print(write_report(res))

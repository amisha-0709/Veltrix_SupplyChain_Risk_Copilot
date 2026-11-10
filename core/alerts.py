"""Build alerts: event → impact (engine) → options (ranker) → scores, owner, SLA, confidence.

    from core.alerts import build_alerts
    alerts, review = build_alerts()          # full stream
"""
from __future__ import annotations

import time

import pandas as pd

from core.etl import load
from core.events import (INBOX_PRIORITY, SPECIFIC, Event, build_events, impact_score, likelihood,
                         response_sla, scenario_for)
from core.impact import fmt_inr
from core.mitigate import recommend
from core.triage import tune_threshold, triage_all


def confidence(ev: Event) -> tuple[float, str]:
    srcs = len(ev.sources)
    specific = any(n.startswith(SPECIFIC) for n in ev.links)
    official = any(s["kind"] in ("weather", "trade") for s in ev.signals)
    c = 0.45 + min(0.3, 0.06 * (srcs - 1)) + (0.15 if specific else 0) + (0.1 if official else 0)
    why = [f"{srcs} independent source{'s' if srcs > 1 else ''}",
           "named node in our network" if specific else "linked by country/commodity only"]
    if official:
        why.append("official notice")
    return round(min(c, 0.95), 2), ", ".join(why)


def owner_for(parts_table: pd.DataFrame) -> str:
    if parts_table is None or parts_table.empty:
        return "Category manager (unassigned)"
    short = parts_table[parts_table["shortage_days"] > 0]
    row = (short if len(short) else parts_table).iloc[0]
    return f"Category manager: {row['category']}"


def build_alert(ev: Event, as_of: pd.Timestamp | None = None) -> dict:
    t0 = time.perf_counter()
    sc, lead = scenario_for(ev, as_of)
    rec = recommend(sc, lead)
    basis = rec["stress"] if rec["mode"] == "precautionary" else rec["expected"]
    L, lw = likelihood(ev, as_of)
    I, iw = impact_score(rec["expected"].totals)
    if rec["mode"] == "precautionary":
        Is, isw = impact_score(rec["stress"].totals)
        if Is > I:
            I, iw = max(I, Is - 1), f"{iw}; stress case: {isw}"
    P = L * I
    conf, cw = confidence(ev)
    opts = rec["options"]
    top = opts.head(3).to_dict("records") if len(opts) else []
    sigs = sorted(ev.signals, key=lambda s: s["published"])
    elapsed = time.perf_counter() - t0
    return {
        "alert_id": ev.event_id.replace("EV", "AL"), "event": ev,
        "title": sigs[0]["text"].split(". ")[0], "first_seen": ev.first_seen, "last_seen": ev.last_seen,
        "event_type": ev.event_type, "signal_ids": [s["signal_id"] for s in sigs],
        "sources": ev.sources, "n_signals": len(sigs),
        "links": sorted(ev.links), "parts_in_scope": len(ev.parts),
        "likelihood": L, "likelihood_reason": lw, "impact": I, "impact_reason": iw,
        "priority": P, "response": response_sla(P), "inbox": P >= INBOX_PRIORITY,
        "confidence": conf, "confidence_reason": cw, "mode": rec["mode"], "lead_days_assumed": lead,
        "owner": owner_for(basis.parts), "status": "Open",
        "totals": rec["expected"].totals, "stress_totals": rec["stress"].totals if rec["stress"] else None,
        "working": basis.working, "parts": basis.parts, "skus": basis.skus, "otif": basis.otif,
        "options": opts, "top_options": top, "plan": rec["plan"], "plan_value": rec["plan_value"],
        "seconds_to_quantify": round(elapsed, 2),
        "summary": (f"{rec['expected'].totals['parts_short']} of {rec['expected'].totals['parts_affected']} parts short; "
                    f"revenue at risk {fmt_inr(rec['expected'].totals['revenue_at_risk_inr'])}; "
                    f"P={L}×{I}={P}"),
    }


def build_alerts(threshold: float | None = None) -> tuple[list[dict], pd.DataFrame, pd.DataFrame, float]:
    T = triage_all()
    th = tune_threshold(T) if threshold is None else threshold
    events, review = build_events(T, th)
    return [build_alert(e) for e in events], review, T, th


if __name__ == "__main__":
    alerts, review, T, th = build_alerts()
    rows = [{k: a[k] for k in ("alert_id", "first_seen", "event_type", "n_signals", "likelihood", "impact",
                                "priority", "inbox", "confidence", "mode", "owner", "seconds_to_quantify", "summary")}
            for a in alerts]
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80)
    print(pd.DataFrame(rows).to_string())

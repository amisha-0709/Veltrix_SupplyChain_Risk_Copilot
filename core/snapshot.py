"""Precompute everything the UI shows into data/snapshot.json (fast cold starts on serverless).

    python -m core.snapshot
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from core.alerts import build_alert
from core.backtest import lead_all, run_backtest
from core.briefing import make_brief, render_html, render_text
from core.exposure import headline_checks, node_concentration, part_exposure
from core.impact import SNAPSHOT_DATE, fmt_inr
from core.timeline import disruption_timeline, timeline_summary

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "snapshot.json"


def clean(o):
    """JSON-safe: NaN/inf → None, Timestamps → ISO, DataFrames → records, sets → lists."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, (pd.Timestamp,)):
        return None if pd.isna(o) else o.isoformat()
    if isinstance(o, pd.DataFrame):
        return clean(json.loads(o.to_json(orient="records", date_format="iso")))
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [clean(x) for x in o]
    if hasattr(o, "item"):            # numpy scalars
        return clean(o.item())
    if o is pd.NaT:
        return None
    return o


def alert_record(a: dict) -> dict:
    b = make_brief(a)
    actual = sorted({s["linked_disruption_id"] for s in a["event"].signals
                     if isinstance(s.get("linked_disruption_id"), str)})
    return {
        "alert_id": a["alert_id"], "title": a["title"], "first_seen": a["first_seen"], "last_seen": a["last_seen"],
        "event_type": a["event_type"], "kind": b["kind"], "likelihood": a["likelihood"], "impact": a["impact"],
        "priority": a["priority"], "inbox": a["inbox"], "response": a["response"], "owner": a["owner"],
        "status": b["status"], "confidence": a["confidence"], "mode": a["mode"],
        "revenue_at_risk": a["totals"]["revenue_at_risk_inr"],
        "revenue_at_risk_fmt": fmt_inr(a["totals"]["revenue_at_risk_inr"]),
        "stress_revenue_at_risk_fmt": fmt_inr(a["stress_totals"]["revenue_at_risk_inr"]) if a["stress_totals"] else None,
        "n_signals": a["n_signals"], "n_sources": len(a["sources"]), "links": a["links"],
        "actual_disruptions": actual, "seconds_to_quantify": a["seconds_to_quantify"],
        "brief": b, "brief_html": render_html(b, standalone=False), "brief_text": render_text(b),
        "options": a["options"], "parts": a["parts"], "skus": a["skus"], "otif": a["otif"], "working": a["working"],
    }


def build_snapshot() -> dict:
    bt = run_backtest()
    alerts = [alert_record(build_alert(e)) for e in bt["events"]]
    alerts.sort(key=lambda x: (not x["inbox"], -x["priority"], x["first_seen"]))
    pe = part_exposure()
    snap = {
        "meta": {"snapshot_date": SNAPSHOT_DATE.date().isoformat(), "generated": pd.Timestamp.now().isoformat(),
                 "threshold": bt["threshold"], "llm_judge": bt["llm_judge"],
                 "company": "Veltrix Components (fictional)", "synthetic": True},
        "headline": headline_checks(), "timeline_summary": timeline_summary(),
        "alerts": alerts,
        "needs_review": bt["needs_review"],
        "exposure": {"parts": pe, "ports": node_concentration("port"), "countries": node_concentration("country"),
                     "categories": node_concentration("cat"), "chokepoints": node_concentration("choke")},
        "timeline": disruption_timeline(),
        "backtest": {"signals": bt["signals"], "alerts": bt["alerts"], "lead": bt["lead"],
                     "lead_all": lead_all(bt["lead_table"]), "lead_table": bt["lead_table"],
                     "misses": bt["misses"][["signal_id", "linked_disruption_id", "days_before_impact", "score", "text"]],
                     "false_alarms": bt["false_alarms"][["signal_id", "score", "text"]]},
    }
    from core.replay import replay, summarise
    reps = []
    for did in snap["timeline"]["disruption_id"]:
        r = replay(did)
        reps.append(r)
    import pandas as _pd
    flat = _pd.DataFrame([{k: v for k, v in r.items() if k not in ("seen", "recommended", "top_options", "structural")}
                          | {"structural_protected_inr": (r["structural"] or {}).get("revenue_protected_inr", 0.0)}
                          for r in reps])
    snap["replays"] = reps
    snap["replay_summary"] = summarise(flat) | {
        "structural_protected_cr": round(float(flat["structural_protected_inr"].clip(lower=0).sum()) / 1e7, 1)}
    for k in ("m2_data.json", "m3_data.json"):
        p = ROOT / "reports" / k
        if p.exists():
            snap[k.replace("_data.json", "")] = json.loads(p.read_text(encoding="utf-8"))
    snap = clean(snap)
    SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    return snap


if __name__ == "__main__":
    s = build_snapshot()
    print(SNAPSHOT, f"{SNAPSHOT.stat().st_size / 1e6:.1f} MB", len(s["alerts"]), "alerts")

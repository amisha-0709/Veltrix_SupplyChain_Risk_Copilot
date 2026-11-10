"""Veltrix supply-chain co-pilot API (FastAPI).

Local:   .venv/Scripts/python -m uvicorn app:app --port 8000   (also serves the UI from public/)
Vercel:  root app.py re-exports `app` (Vercel FastAPI detection); the CDN serves public/.

Read endpoints serve the precomputed snapshot (data/snapshot.json). POST /api/simulate runs the full
pipeline (triage → link → event → impact → options → briefing) on a signal typed by the user.
The co-pilot recommends; people decide. /api/decisions only records what a person decided.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

SNAPSHOT = ROOT / "data" / "snapshot.json"
# Serverless filesystems are read-only except /tmp: decisions live there (per instance) on Vercel.
DECISIONS = Path(os.environ.get("COPILOT_DECISIONS", "/tmp/veltrix_decisions.json" if os.environ.get("VERCEL")
                                else ROOT / "data" / "decisions.json"))
_lock = threading.Lock()

app = FastAPI(title="Veltrix Supply Chain Co-Pilot", version="0.4.0",
              description="Recommends; people decide. Synthetic data (Veltrix Components is fictional).")
app.add_middleware(GZipMiddleware, minimum_size=1000)

LIST_FIELDS = ("alert_id", "title", "first_seen", "last_seen", "event_type", "kind", "likelihood", "impact",
               "priority", "inbox", "response", "owner", "status", "confidence", "mode", "revenue_at_risk",
               "revenue_at_risk_fmt", "stress_revenue_at_risk_fmt", "n_signals", "n_sources", "links",
               "actual_disruptions", "seconds_to_quantify")


@lru_cache(maxsize=1)
def snap() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _alert(alert_id: str) -> dict:
    for a in snap()["alerts"]:
        if a["alert_id"] == alert_id:
            return a
    sim = _SIMULATED.get(alert_id)
    if sim:
        return sim
    raise HTTPException(404, f"No alert {alert_id}")


_SIMULATED: dict[str, dict] = {}


@app.get("/api/meta")
def meta():
    s = snap()
    return {**s["meta"], "headline": s["headline"], "timeline_summary": s["timeline_summary"],
            "counts": {"alerts": len(s["alerts"]), "inbox": sum(a["inbox"] for a in s["alerts"]),
                       "needs_review": len(s["needs_review"])},
            "backtest": {k: s["backtest"][k] for k in ("signals", "alerts", "lead", "lead_all")}}


@app.get("/api/alerts")
def alerts(inbox: bool | None = None):
    rows = [{k: a.get(k) for k in LIST_FIELDS} for a in snap()["alerts"]]
    rows += [{k: a.get(k) for k in LIST_FIELDS} | {"simulated": True} for a in _SIMULATED.values()]
    if inbox is not None:
        rows = [r for r in rows if r["inbox"] == inbox]
    return rows


@app.get("/api/alerts/{alert_id}")
def alert(alert_id: str):
    return _alert(alert_id)


@app.get("/api/alerts/{alert_id}/briefing", response_class=HTMLResponse)
def briefing(alert_id: str):
    from core.briefing import BRIEF_CSS
    a = _alert(alert_id)
    return HTMLResponse(
        f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>Briefing {a['alert_id']}</title><style>{BRIEF_CSS}</style></head><body>"
        f"<p class=noprint style='text-align:center;margin:12px'><button onclick='print()'>Print / save as PDF</button></p>"
        f"{a['brief_html']}</body></html>")


@app.get("/api/brief.css")
def brief_css():
    from fastapi.responses import Response

    from core.briefing import BRIEF_CSS
    return Response(BRIEF_CSS, media_type="text/css")


@app.get("/api/alerts/{alert_id}/briefing.txt")
def briefing_text(alert_id: str):
    return JSONResponse({"text": _alert(alert_id)["brief_text"]})


@app.get("/api/register")
def register():
    """Risk register (brief 'should have'): open risks scored L × I, with owner and status."""
    dec = _read_decisions()
    last = {}
    for d in dec:
        last[d["alert_id"]] = d
    rows = []
    for a in list(snap()["alerts"]) + list(_SIMULATED.values()):
        d = last.get(a["alert_id"])
        rows.append({k: a.get(k) for k in ("alert_id", "title", "first_seen", "last_seen", "kind", "likelihood", "impact",
                                            "priority", "owner", "response", "revenue_at_risk_fmt", "inbox")}
                    | {"status": (f"{d['decision']} by {d['by']}" if d else a["status"])})
    return sorted(rows, key=lambda r: -r["priority"])


@app.get("/api/exposure")
def exposure():
    return snap()["exposure"]


@app.get("/api/backtest")
def backtest():
    s = snap()
    return {**s["backtest"], "m2": s.get("m2"), "m3": s.get("m3"), "timeline": s["timeline"]}


@app.get("/api/needs-review")
def needs_review():
    return snap()["needs_review"]


@app.get("/api/replays")
def replays():
    s = snap()
    keep = ("disruption_id", "title", "type", "start_date", "detected", "copilot_alert_date", "copilot_lead_days",
            "team_alert_date", "team_decision_day", "actual_revenue_lost_inr", "with_plan_lost_inr", "plan_cost_inr",
            "vs_actual_protected_expected_inr", "avoided_waste_inr", "team_wasted_inr", "structural")
    return {"summary": s["replay_summary"], "rows": [{k: r.get(k) for k in keep} for r in s["replays"]]}


@app.get("/api/replays/{did}")
def replay_one(did: str):
    for r in snap()["replays"]:
        if r["disruption_id"] == did.upper():
            return r
    raise HTTPException(404, f"No disruption {did}")


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=400)


@app.post("/api/ask")
def ask_endpoint(q: AskIn):
    """Conversational layer: questions answered by the impact engine, with the working shown."""
    from core.ask import ask
    from core.snapshot import clean

    def get(aid):
        try:
            return _alert(aid)
        except HTTPException:
            return None
    return clean(ask(q.question, alerts=alerts(), get_alert=get))


class SignalIn(BaseModel):
    headline: str = Field(min_length=5, max_length=300)
    snippet: str = Field(default="", max_length=600)
    source: str = Field(default="Manual entry", max_length=80)
    duration_days: float | None = Field(default=None, ge=0, le=365)


@app.post("/api/simulate")
def simulate(sig: SignalIn):
    """Run the whole co-pilot on one signal. Returns what it would do: ignore, review, watch or alert."""
    import pandas as pd

    from core.alerts import build_alert
    from core.events import build_events
    from core.snapshot import alert_record, clean
    from core.triage import triage_text
    th = snap()["meta"]["threshold"]
    t = triage_text(sig.headline, sig.snippet, sig.source, pd.Timestamp.now(), signal_id=f"SIM-{len(_SIMULATED) + 1:03d}")
    if sig.duration_days is not None:
        t["duration_days"] = sig.duration_days
    base = {"triage": clean({k: t[k] for k in ("text", "links", "link_strength", "cues", "cue_score", "score",
                                                "event_type", "reason")}), "threshold": th}
    if t["link_strength"] == 0 and t["cue_score"] >= th:
        return {**base, "decision": "needs_review",
                "message": "Strong disruption cues, but nothing in the signal names a supplier, port, lane or commodity "
                           "we depend on. Marked for human review rather than guessed onto the network."}
    if t["score"] < th:
        return {**base, "decision": "ignored",
                "message": "Below the alert threshold: not linked to our network, or a routine / dampened story. Logged only."}
    events, _ = build_events(pd.DataFrame([t]), th)
    a = build_alert(events[0])
    rec = alert_record(a)
    rec["alert_id"] = t["signal_id"].replace("SIM", "SIM-AL")
    rec["brief"]["alert_id"] = rec["alert_id"]
    from core.briefing import render_html, render_text
    rec["brief_html"] = render_html(rec["brief"], standalone=False)
    rec["brief_text"] = render_text(rec["brief"])
    rec = clean(rec)
    _SIMULATED[rec["alert_id"]] = rec
    return {**base, "decision": "inbox" if rec["inbox"] else "watch", "alert": rec}


class DecisionIn(BaseModel):
    alert_id: str
    option: str = Field(max_length=200)
    decision: str = Field(pattern="^(proposed|approved|escalated|rejected|dismissed|watching)$")
    by: str = Field(min_length=2, max_length=60)          # role, e.g. "Head of Supply Chain"
    note: str = Field(default="", max_length=500)


def _read_decisions() -> list[dict]:
    try:
        return json.loads(Path(DECISIONS).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


@app.get("/api/decisions")
def decisions(alert_id: str | None = None):
    d = _read_decisions()
    return [x for x in d if alert_id is None or x["alert_id"] == alert_id]


@app.post("/api/decisions")
def record_decision(d: DecisionIn):
    """Record what a PERSON decided (playbook §8: recommended vs decided vs happened). Executes nothing."""
    import datetime as dt
    _alert(d.alert_id)
    with _lock:
        rows = _read_decisions()
        rows.append(d.model_dump() | {"at": dt.datetime.now().isoformat(timespec="seconds")})
        try:
            Path(DECISIONS).parent.mkdir(parents=True, exist_ok=True)
            Path(DECISIONS).write_text(json.dumps(rows, indent=1), encoding="utf-8")
        except OSError as e:     # read-only serverless filesystem: say so rather than pretend it was saved
            raise HTTPException(503, f"Decision log storage is not writable here ({e.__class__.__name__}). "
                                     "Nothing was recorded.") from e
    return {"ok": True, "recorded": rows[-1],
            "note": "Recorded only. The co-pilot never places orders, books freight or contacts suppliers. "
                    + ("On the hosted demo the log is temporary (per server instance)." if os.environ.get("VERCEL") else "")}


# Local dev: serve the UI too (on Vercel the CDN serves public/).
PUBLIC = ROOT / "public"
if PUBLIC.exists() and not os.environ.get("VERCEL"):
    app.mount("/", StaticFiles(directory=PUBLIC, html=True), name="ui")

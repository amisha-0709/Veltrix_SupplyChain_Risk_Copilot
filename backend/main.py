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
import re
import secrets
import sys
import threading
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Header, HTTPException, Request  # noqa: E402
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
    sim = _SIM_BY_ID.get(alert_id)
    if sim:
        return sim
    raise HTTPException(404, f"No alert {alert_id}")


# Simulated signals ('Try a signal') belong to the browser session that typed them: they never appear in anyone
# else's inbox, register or counts. The session id is a random token the UI keeps in sessionStorage. Simulated alert
# ids are random too, so a briefing link still opens in a new tab without the header.
_SIMULATED: dict[str, dict[str, dict]] = {}     # session -> alert_id -> record
_SIM_BY_ID: dict[str, dict] = {}
_SIM_MAX = 500
_SESSION_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_REVIEW: dict[str, list[dict]] = {}             # session -> signals 'Try a signal' sent to Needs review


def _session(x_copilot_session: str | None) -> str | None:
    return x_copilot_session if x_copilot_session and _SESSION_RE.match(x_copilot_session) else None


def _sims(session: str | None) -> list[dict]:
    return list(_SIMULATED.get(session, {}).values()) if session else []


@app.get("/api/meta")
def meta():
    s = snap()
    return {**s["meta"], "headline": s["headline"], "timeline_summary": s["timeline_summary"],
            "counts": {"alerts": len(s["alerts"]), "inbox": sum(a["inbox"] for a in s["alerts"]),
                       "needs_review": len(s["needs_review"])},
            "backtest": {k: s["backtest"][k] for k in ("signals", "alerts", "lead", "lead_all")}}


@app.get("/api/alerts")
def alerts(inbox: bool | None = None, x_copilot_session: str | None = Header(default=None)):
    rows = [{k: a.get(k) for k in LIST_FIELDS} for a in snap()["alerts"]]
    rows += [{k: a.get(k) for k in LIST_FIELDS} | {"simulated": True} for a in _sims(_session(x_copilot_session))]
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
def register(x_copilot_session: str | None = Header(default=None)):
    """Risk register (brief 'should have'): open risks scored L × I, with owner and status."""
    dec = _read_decisions()
    last = {}
    for d in dec:
        last[d["alert_id"]] = d
    rows = []
    for a in list(snap()["alerts"]) + _sims(_session(x_copilot_session)):
        d = last.get(a["alert_id"])
        rows.append({k: a.get(k) for k in ("alert_id", "title", "first_seen", "last_seen", "kind", "likelihood", "impact",
                                            "priority", "owner", "response", "revenue_at_risk_fmt", "inbox")}
                    | {"status": (f"{d['decision']} by {d['by']}" if d else a["status"])})
    return sorted(rows, key=lambda r: -r["priority"])


def _persona_alert(a: dict, last: dict | None) -> dict:
    """One alert, cut down to what the persona pages show (read-only view of the snapshot)."""
    cust = {}
    for s in a.get("skus") or []:
        if (s.get("units_short") or 0) > 0:
            c = cust.setdefault(s["customer"], {"customer": s["customer"], "products": [], "weeks_below": 0,
                                                "worst_otif": None, "first_week_below": None, "revenue_at_risk_inr": 0.0})
            c["products"].append({"sku_id": s["sku_id"], "sku_name": s.get("sku_name"), "units_short": s["units_short"],
                                  "revenue_at_risk_inr": s.get("revenue_at_risk_inr"), "stops_from_day": s.get("stops_from_day")})
            c["revenue_at_risk_inr"] += s.get("revenue_at_risk_inr") or 0
    for w in a.get("otif") or []:
        c = cust.get(w["customer"])
        if c and w.get("below_target"):
            c["weeks_below"] += 1
            c["worst_otif"] = w["otif"] if c["worst_otif"] is None else min(c["worst_otif"], w["otif"])
            c["first_week_below"] = c["first_week_below"] or w["week_start"]
    top = [o for o in (a.get("options") or []) if o.get("rank_in_part", o.get("rank")) == 1 and o.get("worth_it", True)]
    owner = a.get("owner") or ""
    return {k: a.get(k) for k in ("alert_id", "title", "first_seen", "priority", "inbox", "kind", "owner", "response",
                                  "revenue_at_risk", "revenue_at_risk_fmt", "confidence", "mode")} | {
        "category": owner.split(":", 1)[1].strip() if ":" in owner else owner,
        "ask": (a.get("brief") or {}).get("ask"),
        "status": f"{last['decision']} by {last['by']}" if last else a.get("status"),
        "last_decision": last,
        "customers": sorted(cust.values(), key=lambda c: -c["revenue_at_risk_inr"]),
        "options": [{k: o.get(k) for k in ("part_id", "option", "cost_inr", "net_value_inr", "time_to_effect_days",
                                           "approver", "on_time")} for o in top[:4]],
        "parts_short": [{k: p.get(k) for k in ("part_id", "description", "days_of_cover", "effective_delay_days",
                                               "shortage_days", "single_source")}
                        for p in (a.get("parts") or []) if (p.get("shortage_days") or 0) > 0],
    }


@app.get("/api/persona")
def persona(x_copilot_session: str | None = Header(default=None)):
    """Compact read-only bundle for the persona pages (category manager, Head of SC, COO, sales)."""
    last = {}
    for d in _read_decisions():
        last[d["alert_id"]] = d
    al = list(snap()["alerts"]) + _sims(_session(x_copilot_session))
    ex = snap()["exposure"]
    customers = sorted({c for p in ex["parts"] for c in (p.get("customers") or [])})
    return {"alerts": sorted([_persona_alert(a, last.get(a["alert_id"])) for a in al], key=lambda r: -r["priority"]),
            "categories": sorted({p["category"] for p in ex["parts"]}),
            "customers": customers,
            "parts": [{k: p.get(k) for k in ("part_id", "description", "category", "single_source", "supplier_name", "country",
                                             "days_of_cover", "lead_time_days", "cover_below_lead_time",
                                             "qualified_alternate_supplier_id", "unqualified_alternate_supplier_id",
                                             "customers", "revenue_dependent_inr_cr")} for p in ex["parts"]],
            "as_of": "30 Sep 2026"}


@app.get("/api/leading")
def leading():
    """Port-congestion and shipment-delay trends: watch signals shown alongside news (no alert, no back-test change)."""
    return snap().get("leading") or {"ports": [], "shipments": [], "history": [], "rule": ""}


@app.get("/api/exposure")
def exposure():
    return snap()["exposure"]


@app.get("/api/backtest")
def backtest():
    s = snap()
    return {**s["backtest"], "m2": s.get("m2"), "m3": s.get("m3"), "timeline": s["timeline"]}


@app.get("/api/business-case")
def business_case():
    m6 = snap().get("m6")
    if not m6:
        raise HTTPException(404, "business case not built (run python -m core.report_m6, then core.snapshot)")
    return m6


@app.get("/api/needs-review")
def needs_review(x_copilot_session: str | None = Header(default=None)):
    """Signals with strong cues that name nothing of ours: a person decides. Includes your own 'Try a signal' items."""
    s = _session(x_copilot_session)
    return list(snap()["needs_review"]) + (list(_REVIEW.get(s, [])) if s else [])


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
            hist = next((t for t in snap()["timeline"] if t["disruption_id"] == r["disruption_id"]), {})
            return {**r, "first_signal_date": hist.get("first_signal_date"), "decision_date": hist.get("decision_date"),
                    "had_warning": hist.get("had_warning")}
    raise HTTPException(404, f"No disruption {did}")


@lru_cache(maxsize=1)
def _names() -> dict:
    """Plain names for part and supplier ids, so the UI never shows a bare PRT-/SUP- code."""
    import pandas as pd
    proc = ROOT / "data" / "processed"
    sup = pd.read_pickle(proc / "suppliers.pkl")
    prt = pd.read_pickle(proc / "parts.pkl")
    return {"suppliers": {r.supplier_id: {"name": r.supplier_name, "country": r.country, "port": r.port_of_loading}
                          for r in sup.itertuples()},
            "parts": {r.part_id: {"name": r.description, "category": r.category, "single_source": bool(r.single_source)}
                      for r in prt.itertuples()}}


@app.get("/api/names")
def names():
    return _names()


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=400)


# Claude chat budget guards (per server instance): a public URL must not be able to run up the API bill.
LLM_PER_CLIENT_HOUR = int(os.environ.get("COPILOT_CHAT_PER_HOUR", "20"))
LLM_PER_DAY = int(os.environ.get("COPILOT_CHAT_PER_DAY", "300"))
_llm_hits: dict[str, list[float]] = {}
_llm_day: list[float] = []


def _llm_allowed(key: str) -> tuple[bool, str]:
    import time as _t
    now = _t.time()
    with _lock:
        _llm_day[:] = [t for t in _llm_day if now - t < 86400]
        hits = _llm_hits.setdefault(key, [])
        hits[:] = [t for t in hits if now - t < 3600]
        if len(_llm_day) >= LLM_PER_DAY:
            return False, "the demo's daily limit for Claude answers is used up"
        if len(hits) >= LLM_PER_CLIENT_HOUR:
            return False, f"you've asked {LLM_PER_CLIENT_HOUR} Claude questions in the last hour"
        hits.append(now)
        _llm_day.append(now)
    return True, ""


@app.post("/api/ask")
def ask_endpoint(q: AskIn, request: Request, x_copilot_session: str | None = Header(default=None),
                 x_copilot_engine: str | None = Header(default=None)):
    """Conversational layer. With an API key, Claude answers by calling the impact engine as tools (core/llm_chat.py);
    otherwise, or if Claude is unavailable or rate-limited, the rule-based parser answers (core/ask.py). Either way
    every number comes from the engine, and the working is returned."""
    from core import llm_chat
    from core.ask import ask
    from core.snapshot import clean

    def get(aid):
        try:
            return _alert(aid)
        except HTTPException:
            return None
    al = alerts(x_copilot_session=x_copilot_session)
    note = None
    if llm_chat.enabled() and (x_copilot_engine or "").lower() != "rules":   # header lets tests pin the rule engine
        who = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
               or (request.client.host if request.client else "")) + "|" + (_session(x_copilot_session) or "")
        ok, why = _llm_allowed(who)
        if ok:
            try:
                s = snap()
                return clean(llm_chat.chat(q.question, alerts=al, get_alert=get,
                                           extras={"m6": s.get("m6"), "replays": s.get("replays")}))
            except Exception as e:      # never break the chat: fall back to the rule-based answer
                note = f"Claude was unavailable ({type(e).__name__}), so the rule-based chat answered."
        else:
            note = f"Answered by the rule-based chat because {why}."
    r = ask(q.question, alerts=al, get_alert=get)
    r["engine"] = "rules"
    if note:
        r["engine_note"] = note
    return clean(r)


@app.get("/api/chat-engine")
def chat_engine():
    from core import llm_chat
    return {"engine": "claude" if llm_chat.enabled() else "rules", "model": llm_chat.MODEL if llm_chat.enabled() else None}


class SignalIn(BaseModel):
    headline: str = Field(min_length=5, max_length=300)
    snippet: str = Field(default="", max_length=600)
    source: str = Field(default="Manual entry", max_length=80)
    duration_days: float | None = Field(default=None, ge=0, le=365)


@app.post("/api/simulate")
def simulate(sig: SignalIn, request: Request, x_copilot_session: str | None = Header(default=None)):
    """Run the whole co-pilot on one signal. Returns what it would do: ignore, review, watch or alert."""
    session = _session(x_copilot_session)
    # Claude reads the signal too (must-have 1: classify and extract). Our gazetteer links what it extracts; the rule
    # that combines Claude and the word list was chosen on train data only (snapshot meta 'triage_rule').
    ext = None
    from core import llm_chat
    if llm_chat.enabled():
        who = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
               or (request.client.host if request.client else "")) + "|" + (session or "")
        if _llm_allowed(who)[0]:
            from core.triage_llm import live_extraction
            ext = live_extraction(f"{sig.headline}. {sig.snippet}".strip(". "))
    return _evaluate(sig.headline, sig.snippet, sig.source, None, "SIM", sig.duration_days, ext, session)


def _evaluate(headline: str, snippet: str, source: str, published, prefix: str, duration_days, ext: dict | None,
              session: str | None) -> dict:
    """The whole co-pilot on one signal, shared by 'Try a signal' and the live news feed."""
    import pandas as pd

    from core.alerts import build_alert
    from core.events import build_events
    from core.snapshot import alert_record, clean
    from core.triage import triage_text
    th = snap()["meta"]["threshold"]
    rule = snap()["meta"].get("triage_rule", "rules")
    sig = SignalIn.model_construct(headline=headline, snippet=snippet, source=source, duration_days=duration_days)
    t = triage_text(sig.headline, sig.snippet, sig.source, published if published is not None else pd.Timestamp.now(),
                    signal_id=f"{prefix}-{secrets.token_hex(4)}")
    if sig.duration_days is not None:
        t["duration_days"] = sig.duration_days
    promoted = False
    if ext and rule == "either" and ext["relevant"] and t["score"] < th:
        t["links"] = list(dict.fromkeys(list(t["links"]) + ext["geo_links"] + ext["cat_links"]))
        t["link_strength"] = max(float(t["link_strength"] or 0), 1.0)
        t["score"], t["event_type"] = th, t["event_type"] or ext["event_type"]
        t["reason"] = f"Claude: {ext['reason']}"
        promoted = True
    if ext and rule != "rules" and t.get("duration_days") is None and ext["duration_days"]:
        t["duration_days"] = ext["duration_days"]
    base = {"triage": clean({k: t[k] for k in ("text", "links", "link_strength", "cues", "cue_score", "score",
                                                "event_type", "reason")}), "threshold": th,
            "extraction": clean(ext) if ext else None, "triage_rule": rule, "claude_promoted": promoted}
    from core.triage import off_network_places
    if t["link_strength"] == 0 and t["cue_score"] >= th:
        elsewhere = off_network_places(f"{sig.headline} {sig.snippet}")
        if elsewhere:      # it names a place, and that place isn't one we depend on: not our problem
            return {**base, "decision": "ignored",
                    "message": f"Strong disruption cues, but it's about {', '.join(elsewhere)}, which isn't in Veltrix's "
                               "network (no supplier, port, lane or commodity there). Logged only."}
        item = {"signal_id": t["signal_id"], "published": pd.Timestamp.now().isoformat(timespec="seconds"),
                "source": sig.source, "text": t["text"], "score": t["cue_score"],
                "reason": "Strong cues but no supplier, port, lane or commodity of ours named", "simulated": True}
        if session:
            _REVIEW.setdefault(session, []).append(item)
            del _REVIEW[session][:-50]
        return {**base, "decision": "needs_review",
                "message": "Strong disruption cues, but nothing in the signal names a supplier, port, lane or commodity "
                           "we depend on. Added to Needs review for a person to check, rather than guessed onto the network."}
    if t["score"] < th:
        damp = [c for c in t["cues"] if "(-" in c]
        if t["link_strength"] == 0:
            why = "it doesn't name any supplier, port, lane or commodity in Veltrix's network"
        elif damp:
            why = (f"it's linked to {', '.join(n.split(':', 1)[1] for n in t['links'])}, but the wording is a routine or "
                   f"non-event story ({', '.join(damp)})")
        else:
            why = (f"it's linked to {', '.join(n.split(':', 1)[1] for n in t['links'])}, but the wording is not strong "
                   f"enough to alert (score {t['score']:g} vs threshold {th:g})")
        return {**base, "decision": "ignored", "message": f"Not alerted: {why}. Logged only."}
    events, _ = build_events(pd.DataFrame([t]), th)
    a = build_alert(events[0])
    rec = alert_record(a)
    rec["alert_id"] = t["signal_id"].replace(prefix, f"{prefix}-AL", 1)
    rec["brief"]["alert_id"] = rec["alert_id"]
    from core.briefing import render_html, render_text
    rec["brief_html"] = render_html(rec["brief"], standalone=False)
    rec["brief_text"] = render_text(rec["brief"])
    rec = clean(rec)
    _SIM_BY_ID[rec["alert_id"]] = rec
    if session:                                    # listed only for the session that ran it
        _SIMULATED.setdefault(session, {})[rec["alert_id"]] = rec
    while len(_SIM_BY_ID) > _SIM_MAX:              # bounded memory on a public demo
        old = next(iter(_SIM_BY_ID))
        _SIM_BY_ID.pop(old)
        for v in _SIMULATED.values():
            v.pop(old, None)
    return {**base, "decision": "inbox" if rec["inbox"] else "watch", "alert": rec}


# ---------------- live news feed ----------------
# Real headlines (core/live_feed.py) through the same pipeline. Shared by every viewer (it is public news); kept in
# memory per server instance. A refresh within LIVE_COOLDOWN seconds returns the last result instead of fetching again.
LIVE_COOLDOWN = int(os.environ.get("COPILOT_LIVE_COOLDOWN", "300"))
LIVE_LLM_PER_REFRESH = int(os.environ.get("COPILOT_LIVE_LLM", "10"))
LIVE_LLM_PER_DAY = int(os.environ.get("COPILOT_LIVE_LLM_DAY", "150"))
_LIVE: dict = {"fetched_at": None, "items": [], "errors": [], "fetched_ts": 0.0}
_LIVE_LOCK = threading.Lock()
_LIVE_EXT: dict[str, dict | None] = {}          # headline -> Claude extraction, so a refresh never re-asks
_live_llm_day: list[float] = []


def _live_view(cached: bool = False) -> dict:
    items = _LIVE["items"]
    counts = {k: sum(i["decision"] == k for i in items) for k in ("inbox", "watch", "needs_review", "ignored")}
    return {"fetched_at": _LIVE["fetched_at"], "items": items, "errors": _LIVE["errors"], "counts": counts,
            "cached": cached, "cooldown_s": LIVE_COOLDOWN,
            "note": "Real headlines from Google News; Veltrix's suppliers, stock and customers are synthetic."}


@app.get("/api/live")
def live():
    return _live_view(cached=True)


@app.post("/api/live/refresh")
def live_refresh():
    import time as _t
    from concurrent.futures import ThreadPoolExecutor

    import pandas as pd

    from core import live_feed, llm_chat
    from core.triage import triage_text
    if _LIVE["fetched_at"] and _t.time() - _LIVE["fetched_ts"] < LIVE_COOLDOWN:
        return _live_view(cached=True)
    if not _LIVE_LOCK.acquire(blocking=False):            # someone else is refreshing: show what we have
        return _live_view(cached=True)
    try:
        news, errors = live_feed.fetch_all()
        if not news:
            _LIVE["errors"] = errors or ["No headlines returned"]
            return _live_view(cached=True)
        th = snap()["meta"]["threshold"]

        def when(n):
            return pd.Timestamp(n["published"]).tz_convert(None) if n["published"] else pd.Timestamp.now()
        # Claude reads only headlines the word list links to our network or scores as a disruption, newest first,
        # capped per refresh and per day; answers are remembered by headline so a refresh never asks twice.
        now = _t.time()
        _live_llm_day[:] = [x for x in _live_llm_day if now - x < 86400]
        todo = []
        if llm_chat.enabled():
            for n in news:
                if n["title"] in _LIVE_EXT or len(todo) >= LIVE_LLM_PER_REFRESH or len(_live_llm_day) + len(todo) >= LIVE_LLM_PER_DAY:
                    continue
                r = triage_text(n["title"], "", n["source"], when(n))
                if r["link_strength"] or r["cue_score"] >= th / 2:
                    todo.append(n["title"])
        if todo:
            from core.triage_llm import live_extraction
            with ThreadPoolExecutor(max_workers=min(8, len(todo))) as ex:
                for title, x in zip(todo, ex.map(live_extraction, todo)):
                    _LIVE_EXT[title] = x
                    _live_llm_day.append(now)
        items = []
        for n in news:
            r = _evaluate(n["title"], "", n["source"], when(n), "LIVE", None, _LIVE_EXT.get(n["title"]), None)
            t, x, a = r["triage"], r.get("extraction"), r.get("alert")
            items.append({**n, "decision": r["decision"], "message": r.get("message"), "score": t["score"],
                          "threshold": r["threshold"], "links": t["links"], "event_type": t["event_type"],
                          "reason": t["reason"], "claude_promoted": r["claude_promoted"],
                          "claude": {k: x[k] for k in ("relevant", "status", "event_type", "reason")} if x else None,
                          "alert": {k: a.get(k) for k in ("alert_id", "title", "priority", "revenue_at_risk_fmt", "owner",
                                                          "response", "inbox")} if a else None})
        order = {"inbox": 0, "watch": 1, "needs_review": 2, "ignored": 3}
        items.sort(key=lambda i: (order[i["decision"]], -(i["score"] or 0)))
        _LIVE.update(items=items, errors=errors, fetched_ts=_t.time(),
                     fetched_at=pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"))
        if len(_LIVE_EXT) > 2000:
            _LIVE_EXT.clear()
        return _live_view()
    finally:
        _LIVE_LOCK.release()


class DecisionIn(BaseModel):
    alert_id: str
    option: str = Field(max_length=200)
    decision: str = Field(pattern="^(proposed|approved|escalated|rejected|dismissed|watching)$")
    by: str = Field(min_length=2, max_length=60)          # role, self-declared on the demo (no sign-in)
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

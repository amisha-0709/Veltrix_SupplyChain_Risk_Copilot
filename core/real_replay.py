"""Real-news replay: archived real headlines around known real disruptions (and quiet weeks), fetched from Google
News with date limits, then run through the co-pilot UNCHANGED and scored against labels written blind.

  python -m core.real_replay fetch      # download headlines -> data/real_replay/headlines.csv
  python -m core.real_replay sheet      # blind labelling sheet (shuffled, no scores) -> data/real_replay/to_label.csv
  python -m core.real_replay score      # co-pilot vs labels (2023 train / 2024 test split) -> reports/real_replay_eval.json
  python -m core.real_replay live 2024  # the DEPLOYED site on the 2024 headlines -> reports/real_replay_live_2024.json

Only headlines, links, outlet and date are stored (brief §8: no full articles). The co-pilot sees what the live feed
sees: the headline. Veltrix's network is synthetic, but its ports, lanes and commodities are real places and goods.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd

from core import live_feed as lf

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "real_replay"
OUT = ROOT / "reports" / "real_replay_eval.json"

# Real disruptions. impact = the day the disruption hit shipping or supply (for lead time); None = no impact on us.
EVENTS = [
    {"id": "R1", "title": "Red Sea attacks force carriers to divert via the Cape", "window": ("2023-11-20", "2023-12-31"),
     "impact": "2023-12-18", "touches_veltrix": True, "note": "Europe–India lane (Hamburg, Rotterdam suppliers)"},
    {"id": "R2", "title": "Hualien earthquake, Taiwan (TSMC halts some lines)", "window": ("2024-03-27", "2024-04-12"),
     "impact": "2024-04-03", "touches_veltrix": True, "note": "sudden: Taiwan fabs, semiconductors"},
    {"id": "R3", "title": "Baltimore Key Bridge collapse closes the port", "window": ("2024-03-19", "2024-04-05"),
     "impact": "2024-03-26", "touches_veltrix": False, "note": "US East Coast port: not in Veltrix's network"},
    {"id": "R4", "title": "China export controls on gallium and germanium", "window": ("2023-06-20", "2023-08-10"),
     "impact": "2023-08-01", "touches_veltrix": False,
     "note": "raw materials Veltrix does not buy (graph.py excludes them on purpose)"},
]
QUIET = [("Q1", "2023-05-08", "2023-05-21"), ("Q2", "2023-10-09", "2023-10-22"), ("Q3", "2024-06-03", "2024-06-16")]
BROAD = ['port (closed OR collapse OR shutdown OR disruption) shipping', '"supply chain" disruption (chips OR electronics OR shipping)']


def windows() -> list[tuple[str, str, str]]:
    w = [(e["id"], *e["window"]) for e in EVENTS] + QUIET
    return w


def fetch() -> pd.DataFrame:
    rows = []
    for wid, a, b in windows():
        for qi, q in enumerate(lf.QUERIES + BROAD):
            url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} after:{a} before:{b}")
                   + "&hl=en-IN&gl=IN&ceid=IN:en")
            try:
                items = lf.parse_google_rss(lf._get(url))
            except Exception as e:  # one failed query never sinks the run; it is reported
                print(f"  {wid} q{qi}: {type(e).__name__}")
                items = []
            for it in items:
                rows.append({**it, "window": wid, "query": qi})
            time.sleep(0.6)
        print(f"{wid}: {sum(r['window'] == wid for r in rows)} items")
    D = pd.DataFrame(rows)
    D = D[D["published"].notna()].copy()
    D["published"] = pd.to_datetime(D["published"], utc=True).dt.tz_localize(None)
    # keep each window's own dates only, then one row per headline (first window wins)
    keep = []
    for wid, a, b in windows():
        d = D[(D.window == wid) & (D.published >= a) & (D.published <= pd.Timestamp(b) + pd.Timedelta(days=1))]
        keep.append(d)
    D = pd.concat(keep).sort_values("published").drop_duplicates("title")
    D.insert(0, "hid", [f"H{i:04d}" for i in range(1, len(D) + 1)])
    DIR.mkdir(parents=True, exist_ok=True)
    D[["hid", "window", "published", "source", "title", "url", "query"]].to_csv(DIR / "headlines.csv", index=False)
    print(f"{len(D)} unique headlines -> {DIR / 'headlines.csv'}")
    return D


def sheet() -> None:
    """Blind sheet: shuffled, no co-pilot output. Labels: 1 = a supply disruption (happening, or credibly coming)
    that touches a port, lane, country or commodity in Veltrix's network; 0 = anything else."""
    D = pd.read_csv(DIR / "headlines.csv")
    D = D.sample(frac=1, random_state=7)[["hid", "published", "title"]]
    D["published"] = D["published"].str[:10]
    D["relevant"] = ""
    D.to_csv(DIR / "to_label.csv", index=False)
    print(f"{len(D)} rows -> {DIR / 'to_label.csv'}")


def run_copilot(D: pd.DataFrame) -> pd.DataFrame:
    from core.events import build_events
    from core.triage import story_key, triage_all, triage_text, tune_threshold
    th = tune_threshold(triage_all())                 # data-pack train only: the deployed threshold
    rows = []
    for r in D.itertuples(index=False):
        t = triage_text(r.title, "", r.source, r.published, signal_id=r.hid)
        rows.append({**t, "signal_id": r.hid, "story_key": story_key(r.title)})
    T = pd.DataFrame(rows)
    T["relevant_to_veltrix"] = D.set_index("hid").loc[T["signal_id"], "relevant"].astype(bool).to_numpy()
    events, _ = build_events(T, th)
    alert_of = {s["signal_id"]: e.event_id for e in events for s in e.signals + e.updates}
    T["alert_id"] = T["signal_id"].map(alert_of)
    T["flagged"] = T["score"] >= th
    return T, events, th


def score() -> dict:
    from core.eval_forecast import bootstrap_ci, confusion
    D = pd.read_csv(DIR / "headlines.csv", parse_dates=["published"])
    L = pd.read_csv(DIR / "labels.csv")
    D = D.merge(L[["hid", "relevant"]], on="hid", how="inner", validate="one_to_one")
    T, events, th = run_copilot(D)
    T = T.merge(D[["hid", "window", "title", "source"]], left_on="signal_id", right_on="hid")
    y = T["relevant_to_veltrix"]
    alerts = []
    for e in events:
        ids = [s["signal_id"] for s in e.signals]
        sub = T[T.signal_id.isin(ids)]
        alerts.append({"alert_id": e.event_id, "first_seen": str(e.first_seen), "signals": len(ids),
                       "real": bool(sub["relevant_to_veltrix"].any()), "windows": sorted(set(sub["window"])),
                       "headlines": sub.sort_values("published")["title"].head(3).tolist()})
    real = sum(a["real"] for a in alerts)
    det = []
    for e in EVENTS:
        sub = T[(T.window == e["id"]) & T.alert_id.notna() & y]
        first = sub["published"].min() if len(sub) else pd.NaT
        lead = None if pd.isna(first) else round((pd.Timestamp(e["impact"]) - first).total_seconds() / 86400, 1)
        fp = T[(T.window == e["id"]) & T.alert_id.notna() & ~y]
        det.append({"id": e["id"], "title": e["title"], "touches_veltrix": e["touches_veltrix"],
                    "relevant_headlines": int(((T.window == e["id"]) & y).sum()),
                    "alerted_relevant": int(len(sub)), "first_alert": None if pd.isna(first) else str(first),
                    "lead_days_vs_impact": lead, "false_alarm_headlines_alerted": int(len(fp))})
    weeks = sum((pd.Timestamp(b) - pd.Timestamp(a)).days for _, a, b in windows()) / 7
    # Time split used for rule changes: tune on 2023 headlines only, score 2024 once.
    rel = T.set_index("signal_id")["relevant_to_veltrix"]
    upd = {u["signal_id"] for e in events for u in e.updates}
    split = {}
    for name, lo, hi in (("train_2023", "2000", "2024-01-01"), ("test_2024", "2024-01-01", "2100")):
        d = T[(T.published >= lo) & (T.published < hi)]
        ev = [e for e in events if lo <= str(e.first_seen) < hi]
        n_real = sum(any(rel[s["signal_id"]] for s in e.signals) for e in ev)
        wk = sum((min(pd.Timestamp(b), pd.Timestamp(hi)) - max(pd.Timestamp(a), pd.Timestamp(lo))).days
                 for _, a, b in windows() if pd.Timestamp(a) < pd.Timestamp(hi) and pd.Timestamp(b) > pd.Timestamp(lo)) / 7
        split[name] = {"headlines": len(d), "relevant": int(d.relevant_to_veltrix.sum()), "alerts": len(ev),
                       "real_alerts": n_real, "alert_precision": round(n_real / len(ev), 3) if ev else None,
                       "false_alerts_per_week": round((len(ev) - n_real) / wk, 2) if wk else None,
                       "updates_attached": int(d.signal_id.isin(upd).sum()),
                       "surfaced": {**confusion(d.alert_id.notna(), d.relevant_to_veltrix),
                                    **bootstrap_ci(d.alert_id.notna(), d.relevant_to_veltrix)},
                       "triage": confusion(d.flagged, d.relevant_to_veltrix)}
    rep = {"what": "Real archived headlines (Google News), co-pilot run unchanged, labels written blind",
           "split": split,
           "threshold": th, "headlines": len(T), "relevant": int(y.sum()),
           "triage": {**confusion(T["flagged"], y), **bootstrap_ci(T["flagged"], y)},
           "in_alert": confusion(T["alert_id"].notna(), y),
           "alerts": {"total": len(alerts), "real": real, "alert_precision": round(real / len(alerts), 3) if alerts else None,
                      "false_alerts_per_week": round((len(alerts) - real) / weeks, 2), "weeks_covered": round(weeks, 1),
                      "list": alerts},
           "events": det,
           "by_window": {w: confusion(g["flagged"], g["relevant_to_veltrix"]) for w, g in T.groupby("window")},
           "misses": T[~T.flagged & y][["signal_id", "window", "score", "title", "reason"]].to_dict("records"),
           "false_alarms": T[T.flagged & ~y][["signal_id", "window", "score", "title", "reason"]].to_dict("records")}
    OUT.write_text(json.dumps(rep, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("headlines", "relevant", "in_alert", "events")}, indent=1, default=str)[:3000])
    a = rep["alerts"]
    print(f"\nAlerts: {a['total']}, real {a['real']}, alert precision {a['alert_precision']}, false alerts/week {a['false_alerts_per_week']}")
    print(f"Triage: precision {rep['triage']['precision']} recall {rep['triage']['recall']} "
          f"(95% CI P {rep['triage']['precision_95ci']}, R {rep['triage']['recall_95ci']})")
    for k, v in split.items():
        s = v["surfaced"]
        print(f"{k}: alerts {v['alerts']} real {v['real_alerts']} (precision {v['alert_precision']}) · surfaced "
              f"P {s['precision']} R {s['recall']} · updates {v['updates_attached']}")
    return rep


LIVE_URL = "https://veltrix-risk-copilot.vercel.app"
LIVE_OUT = ROOT / "reports" / "real_replay_live_2024.json"


def live(year: str = "2024", base: str = LIVE_URL) -> dict:
    """Send each labelled headline of `year` to the DEPLOYED site's /api/simulate (Try a signal) and score the
    answers. The site judges one headline at a time, so this measures triage as deployed (an alert = inbox or
    watch); grouping into alerts and follow-up updates is measured by `score` on the same rules."""
    import uuid
    import urllib.request
    from core.eval_forecast import bootstrap_ci, confusion
    D = pd.read_csv(DIR / "headlines.csv", parse_dates=["published"]).merge(pd.read_csv(DIR / "labels.csv"), on="hid")
    D = D[D.published.dt.year == int(year)].sort_values("published")
    session = f"replay-{uuid.uuid4().hex[:12]}"
    rows = []
    for r in D.itertuples(index=False):
        body = json.dumps({"headline": r.title[:300]}).encode("utf-8")
        req = urllib.request.Request(base + "/api/simulate", data=body, headers={
            "content-type": "application/json; charset=utf-8", "X-Copilot-Session": session})
        for attempt in range(3):
            try:
                j = json.load(urllib.request.urlopen(req, timeout=60))
                break
            except Exception as e:  # retry transient errors; record the failure if it persists
                j = {"decision": "error", "triage": {"score": None, "reason": type(e).__name__, "links": []}}
                time.sleep(2)
        rows.append({"hid": r.hid, "published": str(r.published.date()), "title": r.title, "relevant": bool(r.relevant),
                     "decision": j["decision"], "score": j["triage"]["score"], "reason": j["triage"]["reason"],
                     "priority": (j.get("alert") or {}).get("priority")})
        time.sleep(0.3)
    R = pd.DataFrame(rows)
    ok = R[R.decision != "error"]
    flag = ok.decision.isin(["inbox", "watch"])
    y = ok.relevant
    rep = {"what": f"Deployed site ({base}) on real {year} headlines, one /api/simulate call each",
           "headlines": len(R), "errors": int((R.decision == "error").sum()), "relevant": int(y.sum()),
           "decisions": ok.decision.value_counts().to_dict(),
           "metrics": {**confusion(flag, y), **bootstrap_ci(flag, y)},
           "inbox_only": confusion(ok.decision.eq("inbox"), y),
           "misses": ok[~flag & y][["published", "score", "title"]].to_dict("records"),
           "false_alarms": ok[flag & ~y][["published", "decision", "score", "title"]].to_dict("records"),
           "rows": rows}
    LIVE_OUT.write_text(json.dumps(rep, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    m = rep["metrics"]
    print(f"{len(R)} headlines, {rep['errors']} errors, {rep['relevant']} relevant · decisions {rep['decisions']}")
    print(f"precision {m['precision']} recall {m['recall']} F1 {m['f1']} accuracy {m['accuracy']} FPR {m['false_positive_rate']}"
          f" · 95% CI P {m['precision_95ci']} R {m['recall_95ci']} · tp {m['tp']} fp {m['fp']} fn {m['fn']} tn {m['tn']}")
    return rep


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    {"fetch": fetch, "sheet": sheet, "score": score, "live": lambda: live(*sys.argv[2:3])}[cmd]()

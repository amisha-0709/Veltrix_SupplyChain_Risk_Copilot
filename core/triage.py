"""Signal triage: is this signal about something Veltrix depends on, and is it a disruption?

Every signal (news, weather alert, trade notice) gets:
  links        network nodes it names (gazetteer), with a link strength
  cues         disruption cues found, from playbook §11 "signals we should watch", with dampeners
               for forecasts that miss, denials, routine items and good news
  event_type   impact-engine class (port_closure, supplier_outage, congestion, route, trade_licensing, cost_only)
  score        cue score + link bonus; flagged = score ≥ threshold (tuned on TRAIN only)
  reason       one line a human can check

The rules are transparent on purpose: an unexplained score won't be trusted (brief §8). An optional
Claude pass (core/llm_judge.py) can review the borderline band when an API key is configured.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from core.etl import load
from core.graph import build_network

TEMPLATE_SUFFIX = re.compile(r"\s*(— update|\(report\)|: what we know|as situation develops)\s*$", re.I)

# (pattern, weight, tag). Tags drive the event type. Written from playbook §11 + standard supply-risk vocabulary.
CUES: list[tuple[str, float, str]] = [
    # --- weather & seismic
    (r"typhoon|cyclone|hurricane", 2, "weather"), (r"red alert", 3, "weather"),
    (r"(sea|storm|typhoon|cyclone|rain|weather) warning", 2, "weather"),
    (r"extremely heavy|very heavy", 2, "weather"), (r"\bflood(s|ing|ed)?\b", 3, "weather"),
    (r"intensif(ies|y|ying)|strengthens|likely to become", 2, "weather"),
    (r"tropical storm", 1, "weather"), (r"heavy rain", 1, "weather"), (r"heatwave", 1, "weather"),
    (r"severe heatwave|heatwave warning", 2, "weather"),
    (r"earthquake|quake|tremor|tsunami", 3, "seismic"),
    # --- ports, lanes, logistics
    (r"(suspend|halt|pause|close|shut)s?\b|suspended|halted|paused|closed|closure", 3, "stoppage"),
    (r"suspend (operations|cargo|transits|production)|may suspend", 1, "stoppage"),
    (r"divert(s|ed)?|reroute|cape of good hope|avoid(s|ing)? the", 3, "route"),
    (r"attacks? on", 2, "route"), (r"escalat", 1, "route"),
    (r"congestion (builds|worsens|rises)|congestion surcharge|backlog", 2, "congestion"),
    (r"waiting times?\b[^.]{0,30}\b(rise|rises|rising|climb|up)", 2, "congestion"),
    (r"rolled bookings|blank sailings", 2, "congestion"),
    (r"surcharges?|longer lead times", 1, "congestion"),
    (r"volumes surge|yard utilisation|utilization above", 1, "congestion"),
    (r"container shortage|equipment shortage", 3, "congestion"),
    (r"(rates|prices) (jump|jumps|double|soar|spike|surge)|more than double", 2, "congestion"),
    (r"\b(slows|slowed|delays|delayed)\b", 1, "congestion"),
    (r"schedule disruption|disruption", 2, "congestion"),
    (r"outages?\b|systems? failure|it outage", 3, "systems"),
    # --- labour
    (r"\bstrike\b", 2, "labour"), (r"votes to strike|strike (begins|to go ahead)|nationwide strike", 2, "labour"),
    (r"walkout|lockout", 2, "labour"),
    # --- trade policy
    (r"export licen[cs]|licen[cs]ing (rules|requirements)|licence delays", 3, "trade"),
    (r"export controls?|tighter controls|export ban|restrict(s|ions)? exports", 2, "trade"),
    (r"anti-dumping|safeguard duty|countervailing", 3, "duty"),
    # --- supplier health & incidents
    (r"\bfire\b|blaze|explosion", 3, "incident"), (r"force majeure", 3, "incident"),
    (r"ransomware|cyber[- ]?attack|hack(ed)?\b", 3, "incident"),
    (r"(extends|extended) shutdown|shutdown", 2, "incident"),
    (r"insolven|bankrupt|restructuring|administration|receivership", 3, "health"),
    (r"delays? (supplier )?payments|unpaid wages|credit insurer|cuts cover|mounting debts", 3, "health"),
    (r"protest", 1, "health"), (r"layoffs?", 2, "health"),
    (r"tightening supply|allocation", 2, "supply"),
    (r"lead times?\b[^.]{0,40}\b(lengthen|stretch|extend)", 2, "supply"),
    (r"load-shedding|power cuts?|blackout|power outage", 3, "power"),
    (r"output (cut|reduced)|production (cut|reduced)|reduced to one shift|halt some lines", 2, "supply"),
    # --- dampeners: forecasts that miss, denials, routine and good news
    (r"likely to weaken|weakens|to dissipate", -4, "damp"),
    (r"pass(es)? (east|west|north|south) of|away from", -4, "damp"),
    (r"\b(steady|stable|improves|improving|eases|easing|clears|cleared)\b", -4, "damp"),
    (r"on schedule|record (monthly )?throughput|without strike|conclude", -4, "damp"),
    (r"denied|denies|rumou?rs?", -4, "damp"),
    (r"threatens?\b|analyst flags|reports suggest|could\b", -1.5, "damp"),
    (r"revenue growth|incentives|hold talks|unveils|wins (supply )?contract|opens new|exports rise|"
     r"sales up|registrations|adoption|comes into force|new .* service", -3, "damp"),
    (r"naval exercises?|military drills?|exercise zone", -3, "damp"),
    (r"phishing|security researchers", -3, "damp"),
    (r"forecast for parts of|watch issued", -1, "damp"),
]
CUES_C = [(re.compile(p, re.I), w, t) for p, w, t in CUES]

STRONG_TYPES = {"sup", "port", "dest", "choke", "loc", "region"}

# Tag -> impact-engine event class (first matching tag in priority order wins).
EVENT_OF_TAG = [
    ("route", "route"), ("trade", "trade_licensing"), ("duty", "cost_only"), ("incident", "supplier_outage"),
    ("health", "supplier_outage"), ("seismic", "supplier_outage"), ("power", "supplier_outage"),
    ("labour", "supplier_outage"), ("supply", "supplier_outage"), ("systems", "congestion"),
    ("weather", "port_closure"), ("stoppage", "port_closure"), ("congestion", "congestion"),
]

# Trade notices: only products Veltrix buys, only restrictive measures.
TP_PRODUCT_TO_CAT = {
    "Rare-earth permanent magnets (NdFeB)": "Magnets",
    "Aluminium die-castings from China": "Castings",
}
TP_RESTRICTIVE = re.compile(r"licen[cs]|anti-dumping|safeguard|export ban|export control", re.I)

WX_LOCATION_TO_NODES = {
    "Mumbai / JNPT": ["dest:Nhava Sheva (JNPT)"], "Chennai": ["dest:Chennai Port", "port:Domestic — Chennai"],
    "Pune": ["port:Domestic — Pune"], "Bengaluru/Hosur": ["port:Domestic — Bengaluru/Hosur"],
    "Shenzhen": ["port:Yantian (Shenzhen)"], "Hsinchu": ["port:Keelung"],
}
WX_TYPE_TO_EVENT = {"Earthquake": "supplier_outage", "Heatwave": "supplier_outage", "Severe heatwave": "supplier_outage"}

DEFAULT_THRESHOLD = 4.0   # re-tuned on train by tune_threshold()


@dataclass
class Triaged:
    signal_id: str
    kind: str
    published: pd.Timestamp
    source: str
    text: str
    links: list[str]
    link_strength: float
    cues: list[str]
    cue_score: float
    score: float
    event_type: str | None
    duration_days: float | None
    severity: float | None
    reason: str
    tags: tuple = ()


def normalise(headline: str, snippet: str = "") -> str:
    h = str(headline or "")
    if h.isupper():
        h = h.capitalize()
    h = TEMPLATE_SUFFIX.sub("", h).strip()
    s = str(snippet or "").strip()
    return f"{h}. {s}".strip(" .") if s else h


def story_key(headline: str) -> str:
    """Normalised headline used to spot syndicated copies of the same story."""
    h = TEMPLATE_SUFFIX.sub("", str(headline).lower()).strip()
    return re.sub(r"[^a-z0-9 ]", "", h)


def _link_strength(links: list[str]) -> float:
    types = {n.split(":", 1)[0] for n in links}
    if types & STRONG_TYPES:
        return 2.0
    if "cat" in types and "country" in types:
        return 1.5
    if types & {"cat", "country"}:
        return 1.0
    return 0.0


DURATION_RE = re.compile(
    r"(?:\bfor|\blast(?:ing)?|\bup to|\bnext|\bwithin|\bat least|\bexpected to last)\s+(?:the\s+)?(\d+)"
    r"(?:\s*(?:to|-)\s*\d+)?\s*(day|week)s?|\b(\d+)-(day|week)\b", re.I)


def _duration(text: str) -> float | None:
    """How long the event is expected to last, only from phrases that state a duration.
    ("Lead times stretch beyond 30 weeks" or "diversions add 10 to 16 days" are not durations.)"""
    if re.search(r"lead times?|add(s)? \d+", text, re.I):
        text = re.sub(r"lead times?[^.]*|adds? \d+[^.]*", "", text, flags=re.I)
    m = DURATION_RE.search(text)
    if not m:
        return None
    n = float(m.group(1) or m.group(3))
    unit = (m.group(2) or m.group(4)).lower()
    return n * 7 if unit.startswith("week") else n


def triage_news(row) -> Triaged:
    net = build_network()
    text = normalise(row.headline, row.snippet)
    links = [h["node"] for h in net.match(text)]
    found, score, tags = [], 0.0, []
    for pat, w, tag in CUES_C:
        m = pat.search(text)
        if m:
            found.append(f"{m.group(0).lower()}({w:+g})")
            score += w
            if w > 0:
                tags.append(tag)
    ls = _link_strength(links)
    total = score + (0.5 * ls if score > 0 else 0)
    ev = next((e for t, e in EVENT_OF_TAG if t in tags), None)
    if ev == "route" and not any(n.startswith("choke:") for n in links):
        ev = "congestion"
    # A strike, supply squeeze or distress story that names no supplier or commodity is about logistics
    # (truckers, carriers, ports), not a maker going down: weeks-long outage maths would overstate it.
    maker_named = any(n.startswith(("sup:", "cat:")) for n in links)
    if ev == "supplier_outage" and not maker_named and not set(tags) & {"seismic", "incident", "power"}:
        ev = "congestion"
    reason = (f"links {', '.join(n.split(':', 1)[1] for n in links) or 'nothing in our network'}; "
              f"cues {', '.join(found) or 'none'}")
    return Triaged(row.signal_id, "news", pd.Timestamp(row.published), row.source, text, links, ls, found,
                   score, total if ls > 0 else min(total, 0.0), ev, _duration(text), None, reason,
                   tuple(sorted(set(tags))))


def triage_weather(row) -> Triaged:
    nodes = WX_LOCATION_TO_NODES.get(row.location, [f"port:{row.location}"])
    net = build_network()
    nodes = [n for n in nodes if n in net.G]
    sev = float(row.severity_1_to_5)
    # Official issuer; severity is the cue. Sev 1–3 is routine weather, 4–5 is a warning.
    score = (sev - 3) * 3 + (0.5 * 2 if nodes else 0) if nodes else 0.0
    ev = next((e for k, e in WX_TYPE_TO_EVENT.items() if str(row.alert_type).startswith(k)), "port_closure")
    text = f"{row.alert_type} for {row.location} (severity {sev:g}/5, ~{row.expected_duration_days} days)"
    return Triaged(row.alert_id, "weather", pd.Timestamp(row.alert_date), row.issuer, text, nodes,
                   2.0 if nodes else 0.0, [f"severity {sev:g}"], (sev - 3) * 3, score, ev,
                   float(row.expected_duration_days), sev,
                   f"official {row.alert_type.lower()} sev {sev:g}/5 at {row.location}"
                   + ("" if nodes else " (not a location we depend on)"))


def triage_trade(row) -> Triaged:
    cat = TP_PRODUCT_TO_CAT.get(row.products_covered)
    restrictive = bool(TP_RESTRICTIVE.search(str(row.measure_type)))
    links = []
    if cat:
        links = [f"cat:{cat}"]
        if row.country in ("China",) or "from China" in str(row.products_covered):
            links.append("country:China")
    score = (6.0 if (cat and restrictive) else 0.0)
    ev = "cost_only" if re.search(r"duty", str(row.measure_type), re.I) else "trade_licensing"
    dur = (pd.Timestamp(row.effective_date) - pd.Timestamp(row.notice_date)).days
    text = f"{row.country}: {row.measure_type} on {row.products_covered} (effective {pd.Timestamp(row.effective_date).date()})"
    return Triaged(row.notice_id, "trade", pd.Timestamp(row.notice_date), "Official notice", text, links,
                   1.5 if cat else 0.0, [row.measure_type], score, score, ev if cat else None, None, None,
                   ("restrictive measure on a commodity we buy" if score else
                    "product not in our BOM" if not cat else "measure not restrictive")
                   + f"; takes effect in {dur} days")


def triage_text(headline: str, snippet: str = "", source: str = "Manual entry",
                published: str | pd.Timestamp | None = None, signal_id: str = "MANUAL") -> dict:
    """Triage one hand-entered or live signal (simulator, live feeds). Returns a row like triage_all()."""
    from types import SimpleNamespace
    row = SimpleNamespace(signal_id=signal_id, headline=headline, snippet=snippet, source=source,
                          published=pd.Timestamp(published) if published is not None else pd.Timestamp.now())
    t = triage_news(row).__dict__
    t["story_key"] = story_key(t["text"].split(". ")[0])
    t["relevant_to_veltrix"] = None
    return t


def triage_all() -> pd.DataFrame:
    db = load()
    out = [triage_news(r) for r in db["news"].itertuples()]
    out += [triage_weather(r) for r in db["weather_alerts"].itertuples()]
    out += [triage_trade(r) for r in db["trade_policy"].itertuples()]
    T = pd.DataFrame([t.__dict__ for t in out])
    T["story_key"] = [story_key(t.split(". ")[0]) if k == "news" else sid
                      for t, k, sid in zip(T["text"], T["kind"], T["signal_id"])]
    lab = db["signal_labels"]
    return T.merge(lab, on="signal_id", how="left")


def metrics(T: pd.DataFrame, threshold: float, split: str) -> dict:
    d = T[T["split"] == split]
    flag = d["score"] >= threshold
    tp = int((flag & d["relevant_to_veltrix"]).sum())
    fp = int((flag & ~d["relevant_to_veltrix"]).sum())
    fn = int((~flag & d["relevant_to_veltrix"]).sum())
    return {"threshold": threshold, "flagged": int(flag.sum()), "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None}


def tune_threshold(T: pd.DataFrame) -> float:
    """Pick the threshold on TRAIN that maximises F1, with recall ≥ 0.8 preferred (brief target)."""
    best, best_key = DEFAULT_THRESHOLD, (-1, -1)
    for th in [x / 2 for x in range(2, 21)]:
        m = metrics(T, th, "train")
        if not m["precision"] or not m["recall"]:
            continue
        f1 = 2 * m["precision"] * m["recall"] / (m["precision"] + m["recall"])
        key = (m["recall"] >= 0.8, round(f1, 3))
        if key > best_key:
            best, best_key = th, key
    return best


if __name__ == "__main__":
    T = triage_all()
    th = tune_threshold(T)
    print("tuned threshold (train):", th)
    for s in ("train", "test"):
        print(s, metrics(T, th, s))
    tr = T[T["split"] == "train"]
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 110)
    print("\n-- train misses")
    print(tr[(tr.score < th) & tr.relevant_to_veltrix][["signal_id", "score", "text", "reason"]].drop_duplicates("text").to_string())
    print("\n-- train false alarms")
    print(tr[(tr.score >= th) & ~tr.relevant_to_veltrix].groupby("story_key").agg(n=("signal_id", "size"), score=("score", "max"), reason=("reason", "first")).sort_values("n", ascending=False).head(25).to_string())

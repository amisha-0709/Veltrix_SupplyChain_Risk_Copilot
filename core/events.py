"""Turn triaged signals into events (one event = one alert), then score and quantify each.

Clustering (dedup, T3): signals are read in time order. A flagged signal joins an open event when
  * it is a syndicated copy of a story already in the event (same normalised headline), or
  * its network scope overlaps the event's (Jaccard of exposed parts ≥ 0.3, or a shared named node),
    the event class is compatible, and it arrives within EVENT_WINDOW_DAYS of the event's last signal.
A strong-cue signal that names nothing in the network (e.g. "Components maker extends shutdown after
cyber attack") joins an open event of the same class within FOLLOWUP_DAYS. Otherwise it goes to
NEEDS REVIEW: never guessed onto the network (brief §8).

Scoring (playbook §2): likelihood 1–5 from credibility + confirmation, impact 1–5 from the engine's ₹ at
risk, priority = L × I; inbox if priority ≥ 6, else watch log. Every score carries a one-line reason.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from core.graph import build_network
from core.impact import Scenario, fmt_inr

EVENT_WINDOW_DAYS = 14
SLOW_WINDOW_DAYS = 45          # supplier health and trade measures build over weeks
SLOW_TYPES = {"supplier_outage", "trade_licensing", "cost_only"}
FOLLOWUP_DAYS = 5
SMALL_SCOPE = 20               # containment matching only between narrow scopes
INBOX_PRIORITY = 6
SPECIFIC = ("sup:", "port:", "dest:", "choke:", "loc:", "region:")

HAPPENING = ("begins", "halt", "hit by", "declares", "files for", "fire", "earthquake", "strikes",
             "suspend", "outage", "slows", "pause", "divert", "shutdown", "cuts cover", "delays",
             "protest", "flood", "notified", "publishes", "load-shedding", "shortage")
FORECAST = ("may ", "could", "likely", "forecast", "signals", "warning", "warn", "recommends", "votes",
            "watch", "intensifies", "strengthens", "calls")


def scope_parts(links: list[str]) -> set[str]:
    """Parts a set of links points at. Specific nodes ∩ category when both are named (Shenzhen ∩ PCBs)."""
    net = build_network()
    spec = [n for n in links if n.startswith(SPECIFIC)]
    cats = [n for n in links if n.startswith("cat:")]
    ctry = [n for n in links if n.startswith("country:")]
    union = lambda ns: set().union(*[net.parts_exposed(n) for n in ns]) if ns else set()  # noqa: E731
    if spec:
        s = union(spec)
        if cats:
            both = s & union(cats)
            return both or s
        return s
    if cats and ctry:
        return (union(cats) & union(ctry)) or union(cats)
    return union(cats) or union(ctry)


@dataclass
class Event:
    event_id: str
    signals: list[dict] = field(default_factory=list)
    links: set[str] = field(default_factory=set)
    parts: set[str] = field(default_factory=set)
    story_keys: set[str] = field(default_factory=set)
    seed_parts: set[str] = field(default_factory=set)

    @property
    def first_seen(self) -> pd.Timestamp:
        return min(s["published"] for s in self.signals)

    @property
    def last_seen(self) -> pd.Timestamp:
        return max(s["published"] for s in self.signals)

    @property
    def event_type(self) -> str:
        c = Counter(s["event_type"] for s in self.signals if s["event_type"])
        return c.most_common(1)[0][0] if c else "congestion"

    @property
    def sources(self) -> list[str]:
        return sorted({s["source"] for s in self.signals})

    def add(self, s: dict, parts: set[str]) -> None:
        self.signals.append(s)
        self.links |= set(s["links"])
        self.parts |= parts
        self.story_keys.add(s["story_key"])


def _compatible(a: str, b: str) -> bool:
    groups = [{"port_closure", "congestion"}, {"supplier_outage"}, {"trade_licensing", "cost_only"}, {"route", "congestion"}]
    return a == b or any(a in g and b in g for g in groups)


def build_events(T: pd.DataFrame, threshold: float) -> tuple[list[Event], pd.DataFrame]:
    T = T.sort_values(["published", "signal_id"], kind="mergesort")
    flagged = T[T["score"] >= threshold]
    unlinked = T[(T["link_strength"] == 0) & (T["cue_score"] >= threshold)]
    cand = pd.concat([flagged.assign(_unlinked=False), unlinked.assign(_unlinked=True)]).sort_values(["published", "signal_id"], kind="mergesort")
    events: list[Event] = []
    review = []
    for s in cand.to_dict("records"):
        open_ev = [e for e in events if (s["published"] - e.last_seen).days <=
                   (SLOW_WINDOW_DAYS if e.event_type in SLOW_TYPES else EVENT_WINDOW_DAYS)]
        if s["_unlinked"]:
            match = [e for e in open_ev if (s["published"] - e.last_seen).days <= FOLLOWUP_DAYS
                     and s["event_type"] and _compatible(e.event_type, s["event_type"])]
            if match:
                match[-1].add({**s, "linked_via": "follow-up of open event"}, set())
            else:
                review.append(s)
            continue
        parts = scope_parts(s["links"])
        best, best_j = None, 0.0
        for e in open_ev:
            if s["story_key"] in e.story_keys:
                best, best_j = e, 1.0
                break
            ref = e.seed_parts                    # compare with the event's original scope (no snowballing)
            inter = len(parts & ref)
            if parts and ref and max(len(parts), len(ref)) <= SMALL_SCOPE:
                # Containment: a follow-up about one part of a small event still belongs to it.
                j = inter / min(len(parts), len(ref))
            else:
                j = inter / len(parts | ref) if parts | ref else 0
            shared_named = bool(set(n for n in s["links"] if n.startswith(SPECIFIC)) &
                                set(n for n in e.links if n.startswith(SPECIFIC)))
            same_class = bool(s["event_type"]) and _compatible(e.event_type, s["event_type"])
            # Different classes merge only on a shared named node (heatwave news + heatwave alert for Pune).
            if not same_class and not shared_named:
                continue
            if shared_named:
                j = max(j, 0.5)
            if j > best_j:
                best, best_j = e, j
        if best is not None and best_j >= 0.3:
            best.add(s, parts)
        else:
            ev = Event(event_id=f"EV-{len(events) + 1:03d}", seed_parts=set(parts))
            ev.add(s, parts)
            events.append(ev)
    return events, pd.DataFrame(review)


# ---------------------------------------------------------------------------------------------
def likelihood(ev: Event, upto: pd.Timestamp | None = None) -> tuple[int, str]:
    sig = [s for s in ev.signals if upto is None or s["published"] <= upto]
    kinds = {s["kind"] for s in sig}
    text = " ".join(s["text"].lower() for s in sig)
    happening = any(h in text for h in HAPPENING)
    official = bool(kinds & {"weather", "trade"})
    srcs = {s["source"] for s in sig}
    max_sev = max((float(s["severity"]) if pd.notna(s.get("severity")) else 0.0) for s in sig)
    specific = any(n.startswith(SPECIFIC) for n in ev.links)
    L, why = 3, ["credible signal touching our network"]
    if max_sev >= 5 or (happening and specific):
        L, why = 5 if max_sev >= 5 else 4, ["confirmed / under way at a node we use" if happening else "severity-5 official warning"]
    elif official or len(srcs) >= 3:
        L, why = 4, [("official " + "/".join(sorted(kinds & {'weather', 'trade'}))) if official
                     else f"corroborated by {len(srcs)} sources"]
    if not specific:
        L -= 1
        why.append("linked only by country/commodity")
    L = max(1, min(5, L))
    return L, "; ".join(why)


def impact_score(totals: dict) -> tuple[int, str]:
    r = totals["revenue_at_risk_inr"]
    cust = totals["customers_below_otif"]
    if r > 20e7 or len(cust) > 1:
        return 5, f"{fmt_inr(r)} at risk" + (f"; {len(cust)} customers below 95% OTIF" if len(cust) > 1 else "")
    if r > 5e7 or totals["skus_stopped"] > 0:
        return 4, f"{fmt_inr(r)} at risk; {totals['skus_stopped']} SKU(s) stop"
    if r > 1e7 or cust:
        return 3, f"{fmt_inr(r)} at risk" + (f"; {cust[0]} below 95% OTIF" if cust else "")
    if r > 25e5:
        return 2, f"{fmt_inr(r)} at risk"
    return 1, f"{fmt_inr(r)} at risk; cover holds"


def response_sla(p: int) -> str:
    return ("War-room within 4 h; Head of Supply Chain decides same day; COO informed" if p >= 20 else
            "Options costed within 24 h; decision within 48 h" if p >= 12 else
            "Owner assigned; check exposure within 2 working days" if p >= 6 else
            "Log and watch; weekly review")


def scenario_for(ev: Event, as_of: pd.Timestamp | None = None) -> tuple[Scenario, float]:
    """Impact scenario for an event + the decision lead (days from now to expected impact)."""
    sig = [s for s in ev.signals if as_of is None or s["published"] <= as_of] or ev.signals
    durs = [float(s["duration_days"]) for s in sig if pd.notna(s.get("duration_days")) and s.get("duration_days")]
    et = ev.event_type
    dur = max(durs) if durs else None
    if et == "route":
        dur = None
    text = " ".join(s["text"].lower() for s in sig)
    happening = any(h in text for h in HAPPENING)
    trade = [s for s in sig if s["kind"] == "trade"]
    tags = set().union(*[set(s.get("tags") or ()) for s in sig])
    if trade:
        lead = 18.0                                 # effective dates sit ~18–40 d after notice
    elif "health" in tags and not tags & {"incident", "seismic", "stoppage"}:
        # Supplier distress (late payments, credit cover cut, wage protests) precedes failure by weeks:
        # D12's first such story came 61 days before supply stopped. Treat it as an early warning.
        lead = 30.0
    elif happening:
        lead = 0.0
    else:
        lead = 7.0                                  # forecast with no date: a week (median of train leads ≥ 7)
    parts = sorted(scope_parts(sorted(ev.links)))
    sc = Scenario(parts=parts, nodes=sorted(ev.links), event_type=et, duration_days=dur,
                  label=f"{ev.event_id}: {sig[0]['text'].split('. ')[0]}")
    return sc, lead

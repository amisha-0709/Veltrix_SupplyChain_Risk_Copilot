"""False-alarm analysis (brief Stage 3): how the co-pilot avoids crying wolf, measured.

  1. Threshold sweep: precision / recall / false-alarm signals on train and test as the threshold moves.
  2. Ablations: turn each guard off and count the false alarms that come back
       - dampeners (forecasts that miss, denials, threats, routine items)
       - the network-link gate (must touch something we depend on)
       - the trade-notice product filter (only products in our BOM)
       - the weather severity gate (only severity ≥ 4)
  3. Look-alike families suppressed (labels say they never mattered), with the guard that caught them.
  4. Alert load: what a supply-chain team would actually see per week.
  5. Changes made during development to reduce false alarms (and what each fixed).
"""
from __future__ import annotations

import re

import pandas as pd

import core.triage as tr
from core.backtest import run_backtest
from core.events import build_events

CHANGE_LOG = [
    ("Dampener cues (forecasts that miss, denials, threats, routine weather, good news)",
     "Keeps the recurring look-alikes ('typhoon to pass east of Taiwan', 'rumours … denied', 'port workers threaten "
     "strike', 'heavy rain forecast for parts of…') out of the inbox."),
    ("Network-link gate: a signal must name a supplier, port, lane, chokepoint, region or commodity we depend on",
     "Drops world news with no bearing on Veltrix (Odisha cyclones, phishing campaigns, EV sales figures)."),
    ("Gallium/germanium removed from the semiconductor aliases", "Raw materials Veltrix doesn't buy: China gallium "
     "export notices no longer link to our chips."),
    ("Trade notices: only products in our BOM, only restrictive measures", "Drops solar cells, palm polymers, battery "
     "passports, aluminium foil and customs-fee notices."),
    ("Weather: only official severity ≥ 4", "Sev 1–3 alerts (routine fog, wind, rain) never alert."),
    ("Unlinked strong-cue stories → follow-up of an open event or Needs review, never guessed onto the network",
     "Brief §8 guardrail; avoids inventing a supplier for 'components maker extends shutdown'."),
    ("Dedup: syndicated copies and follow-ups merge into one event (containment of seed scope, 14/45-day windows)",
     "18 disruptions → 19 alerts instead of 177 flagged signals; over-merging fixed after D10–D14 chained."),
    ("Impact gate: inbox only if priority ≥ 6; cover-is-enough → 'no action' in the watch log",
     "T7: rain at JNPT is logged with the working instead of paging anyone; most of the ₹4.6 cr of past wasted "
     "spend went on exactly these."),
    ("Event-class fixes: strikes/supply squeezes that name no maker are logistics, not 44-day outages",
     "Stopped a ₹92 cr phantom loss on the truckers' strike (D07 lost nothing)."),
]


def sweep(T: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for th in [x / 2 for x in range(2, 15)]:
        for split in ("train", "test"):
            d = T[T["split"] == split]
            f = d["score"] >= th
            tp, fp = int((f & d.relevant_to_veltrix).sum()), int((f & ~d.relevant_to_veltrix).sum())
            fn = int((~f & d.relevant_to_veltrix).sum())
            rows.append({"threshold": th, "split": split, "flagged": tp + fp, "false_alarms": fp,
                         "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                         "recall": round(tp / (tp + fn), 3) if tp + fn else None})
    return pd.DataFrame(rows)


def _metrics(T: pd.DataFrame, th: float) -> dict:
    out = {}
    for split in ("train", "test"):
        d = T[T["split"] == split]
        f = d["score"] >= th
        tp, fp = int((f & d.relevant_to_veltrix).sum()), int((f & ~d.relevant_to_veltrix).sum())
        ev, _ = build_events(d, th)
        rel_ev = sum(any(s["relevant_to_veltrix"] for s in e.signals) for e in ev)
        out[split] = {"flagged": tp + fp, "false_alarm_signals": fp,
                      "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                      "alerts": len(ev), "false_alerts": len(ev) - rel_ev}
    return out


def ablations(th: float) -> pd.DataFrame:
    rows = []
    base = tr.triage_all()
    rows.append({"guard removed": "None (as built)", **{f"{k}_{s}": v for s, m in _metrics(base, th).items() for k, v in m.items()}})

    orig = list(tr.CUES_C)
    try:
        tr.CUES_C = [c for c in orig if c[2] != "damp"]
        T = tr.triage_all()
        rows.append({"guard removed": "Dampener cues", **{f"{k}_{s}": v for s, m in _metrics(T, th).items() for k, v in m.items()}})
    finally:
        tr.CUES_C = orig

    T = base.copy()                                   # link gate off: unlinked signals keep their cue score
    T["score"] = T["score"].where(T["link_strength"] > 0, T["cue_score"])
    T.loc[T["link_strength"] == 0, "link_strength"] = 1.0
    rows.append({"guard removed": "Network-link gate", **{f"{k}_{s}": v for s, m in _metrics(T, th).items() for k, v in m.items()}})

    T = base.copy()                                   # trade filter off: every restrictive-sounding notice scores
    m = T["kind"] == "trade"
    T.loc[m, "score"] = 6.0
    T.loc[m, "link_strength"] = 1.0
    T.loc[m & T["event_type"].isna(), "event_type"] = "trade_licensing"
    rows.append({"guard removed": "Trade product filter", **{f"{k}_{s}": v for s, m_ in _metrics(T, th).items() for k, v in m_.items()}})

    T = base.copy()                                   # weather gate at severity ≥ 3 instead of ≥ 4
    w = (T["kind"] == "weather") & (T["severity"] == 3) & (T["link_strength"] > 0)
    T.loc[w, "score"] = th
    rows.append({"guard removed": "Weather severity gate (≥4 → ≥3)", **{f"{k}_{s}": v for s, m_ in _metrics(T, th).items() for k, v in m_.items()}})
    return pd.DataFrame(rows)


def lookalikes(T: pd.DataFrame, th: float) -> pd.DataFrame:
    d = T[(~T["relevant_to_veltrix"].astype(bool)) & (T["kind"] == "news") & (T["score"] < th)
          & ((T["cue_score"] > 0) | T["cues"].map(lambda c: any("(-" in x for x in c)))]
    d = d[d["link_strength"] > 0]

    def guard(cues):
        neg = [c for c in cues if "(-" in c]
        return ", ".join(neg) if neg else "below threshold (weak cue only)"
    g = (d.groupby("story_key").agg(copies=("signal_id", "size"), score=("score", "max"),
                                    guard=("cues", lambda s: guard(s.iloc[0])), sample=("text", "first"))
         .sort_values("copies", ascending=False).reset_index())
    return g


def alert_load(bt: dict) -> dict:
    T = bt["triaged"]
    weeks = (T["published"].max() - T["published"].min()).days / 7
    ev = bt["events"]
    from core.alerts import build_alert
    pri = [build_alert(e)["inbox"] for e in ev]
    return {"weeks": round(weeks), "signals_per_week": round(len(T) / weeks, 1),
            "alerts_per_week": round(len(ev) / weeks, 2), "inbox_per_month": round(sum(pri) / (weeks / 4.33), 2),
            "signals_per_alert": round(sum(len(e.signals) for e in ev) / len(ev), 1)}


def analysis() -> dict:
    bt = run_backtest(use_llm=False)
    th = bt["threshold"]
    T = bt["triaged"]
    return {"threshold": th, "sweep": sweep(T), "ablations": ablations(th), "lookalikes": lookalikes(T, th),
            "load": alert_load(bt), "changes": CHANGE_LOG}


if __name__ == "__main__":
    a = analysis()
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
    print(a["sweep"].pivot(index="threshold", columns="split", values=["precision", "recall", "false_alarms"]).to_string())
    print(a["ablations"].to_string())
    print(a["lookalikes"].head(15).to_string())
    print(a["load"])

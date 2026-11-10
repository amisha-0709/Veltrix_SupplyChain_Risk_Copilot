"""T9 back-test: run the co-pilot on every signal and score it against signal_labels.

Brief §7 targets (test period, from 1 Feb 2026):
  recall ≥ 80% of relevant signals · alert precision ≥ 60% · median warning lead ≥ 7 days before impact.

A signal counts as "flagged" if it ends up in an alert (flagged by triage, or attached to an open event
as a follow-up). Alert precision = share of alerts that contain at least one relevant signal.
Lead time = disruption start − date of the co-pilot's first alert for it, for disruptions that had
public warnings.
"""
from __future__ import annotations

import pandas as pd

from core.events import build_events
from core.etl import load
from core.llm_judge import apply_judge
from core.triage import tune_threshold, triage_all

TEST_START = pd.Timestamp("2026-02-01")


def run_backtest(use_llm: bool = True) -> dict:
    db = load()
    T = triage_all()
    th = tune_threshold(T)                       # tuned on rules alone, train only
    judge_summary = None
    if use_llm:
        T, judge_summary = apply_judge(T, th, run=False)   # cached Claude verdicts only; no API calls here
    events, review = build_events(T, th)
    in_alert = {s["signal_id"]: e.event_id for e in events for s in e.signals}
    T["alerted"] = T["signal_id"].isin(in_alert)
    T["alert_id"] = T["signal_id"].map(in_alert)

    def sig_metrics(split):
        d = T[T["split"] == split]
        tp = int((d.alerted & d.relevant_to_veltrix).sum())
        fp = int((d.alerted & ~d.relevant_to_veltrix).sum())
        fn = int((~d.alerted & d.relevant_to_veltrix).sum())
        return {"signals": len(d), "relevant": int(d.relevant_to_veltrix.sum()), "flagged": tp + fp,
                "tp": tp, "fp": fp, "fn": fn,
                "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                "recall": round(tp / (tp + fn), 3) if tp + fn else None}

    def alert_metrics(split):
        ev = [e for e in events if (e.first_seen >= TEST_START) == (split == "test")]
        rel = [e for e in ev if any(s["relevant_to_veltrix"] for s in e.signals)]
        return {"alerts": len(ev), "relevant_alerts": len(rel),
                "precision": round(len(rel) / len(ev), 3) if ev else None,
                "signals_per_alert": round(sum(len(e.signals) for e in ev) / len(ev), 1) if ev else None}

    # lead time per disruption
    d = db["disruptions"].set_index("disruption_id")
    lab = db["signal_labels"]
    rows = []
    for did, r in d.iterrows():
        rel = T[(T["linked_disruption_id"] == did)]
        had_warning = bool((lab[(lab.linked_disruption_id == did)]["days_before_impact"] > 0).any())
        first_public = rel["published"].min()
        caught = rel[rel["alerted"]]
        first_alert = caught["published"].min() if len(caught) else pd.NaT
        lead = (r["start_date"] - first_alert).total_seconds() / 86400 if pd.notna(first_alert) else None
        team = (r["start_date"] - r["first_internal_alert_date"]).days
        rows.append({
            "disruption_id": did, "title": r["title"], "split": "test" if r["start_date"] >= TEST_START else "train",
            "had_warning": had_warning, "start_date": r["start_date"].date(),
            "first_public_signal": first_public, "first_alert": first_alert,
            "lead_days": None if lead is None else round(lead, 1),
            "team_lead_days": -int((r["first_internal_alert_date"] - r["start_date"]).days),
            "days_gained_vs_team": None if lead is None else round(lead - team, 1),
            "alerts": sorted(set(caught["alert_id"].dropna())), "relevant_signals": len(rel),
            "signals_caught": len(caught),
        })
    L = pd.DataFrame(rows)

    def lead_summary(split):
        w = L[(L.split == split) & L.had_warning & L.lead_days.notna()]
        return {"disruptions_with_warning": int(((L.split == split) & L.had_warning).sum()),
                "detected": len(w), "median_lead_days": float(w["lead_days"].median()) if len(w) else None,
                "min_lead_days": float(w["lead_days"].min()) if len(w) else None}

    te = T[T["split"] == "test"]
    fa = te[te.alerted & ~te.relevant_to_veltrix]
    miss = te[~te.alerted & te.relevant_to_veltrix]
    near = te[(~te.alerted) & (te.score > 0) & (te.score < th)]
    return {
        "threshold": th,
        "llm_judge": ("rules only (no cached Claude verdicts yet)" if not judge_summary or not judge_summary["verdicts"]
                      else f"rules + Claude ({judge_summary['model']}): {judge_summary['verdicts']} borderline stories "
                           f"reviewed, {judge_summary['signals_promoted']} signals promoted"),
        "judge_summary": judge_summary,
        "signals": {"train": sig_metrics("train"), "test": sig_metrics("test")},
        "alerts": {"train": alert_metrics("train"), "test": alert_metrics("test")},
        "lead": {"train": lead_summary("train"), "test": lead_summary("test"), "all": {
            **lead_summary("test"), **{k: v for k, v in lead_summary("train").items()}}},
        "lead_table": L, "false_alarms": fa, "misses": miss, "near_misses": near,
        "needs_review": review, "triaged": T, "events": events,
    }


ABLATE = r"load-shedding|container shortage"   # cue terms written after the test headlines were visible


def ablation() -> dict:
    """Robustness check: re-run without the cue terms that were informed by seeing test-period headlines."""
    import re
    import core.triage as tr
    orig = list(tr.CUES_C)
    try:
        tr.CUES_C = [c for c in orig if not re.search(ABLATE, c[0].pattern)]
        r = run_backtest(use_llm=False)          # rules-only robustness check
        return {"removed": ABLATE, "signals": r["signals"]["test"], "alerts": r["alerts"]["test"],
                "lead": r["lead"]["test"]}
    finally:
        tr.CUES_C = orig


def lead_all(L: pd.DataFrame) -> dict:
    w = L[L.had_warning & L.lead_days.notna()]
    return {"detected": f"{len(w)}/{int(L.had_warning.sum())}", "median_lead_days": float(w.lead_days.median()),
            "median_team_lead_days": float(L.team_lead_days.median())}


if __name__ == "__main__":
    import json
    r = run_backtest()
    print("threshold", r["threshold"], "|", r["llm_judge"])
    print(json.dumps({"signals": r["signals"], "alerts": r["alerts"],
                      "lead_test": r["lead"]["test"], "lead_train": r["lead"]["train"],
                      "lead_all": lead_all(r["lead_table"])}, indent=1, default=str))
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 90)
    print(r["lead_table"][["disruption_id", "split", "had_warning", "first_alert", "lead_days", "team_lead_days",
                           "days_gained_vs_team", "signals_caught", "relevant_signals", "alerts"]].to_string())
    print("\nTEST false alarms:", len(r["false_alarms"]))
    print(r["false_alarms"][["signal_id", "text"]].to_string())
    print("\nTEST misses:", len(r["misses"]))
    print(r["misses"][["signal_id", "linked_disruption_id", "days_before_impact", "score", "text"]].to_string())

"""Stage-1 disruption timeline: first public signal vs when the team noticed vs when it decided."""
from __future__ import annotations

import pandas as pd

from core.etl import load

SUDDEN_TYPES = ("Supplier incident", "Natural disaster", "Cyber", "Systems")


def disruption_timeline() -> pd.DataFrame:
    db = load()
    d = db["disruptions"].copy()
    lab = db["signal_labels"]
    rel = lab[lab["relevant_to_veltrix"] & lab["linked_disruption_id"].notna()]

    pre = rel[rel["days_before_impact"] > 0]
    first = rel.groupby("linked_disruption_id").agg(
        first_signal_date=("signal_date", "min"),
        relevant_signals=("signal_id", "count"),
        max_days_before_impact=("days_before_impact", "max"),
    )
    pre_counts = pre.groupby("linked_disruption_id")["signal_id"].count().rename("signals_before_impact")
    d = d.merge(first, left_on="disruption_id", right_index=True, how="left")
    d = d.merge(pre_counts, left_on="disruption_id", right_index=True, how="left")
    d["signals_before_impact"] = d["signals_before_impact"].fillna(0).astype(int)
    d["had_warning"] = d["signals_before_impact"] > 0
    d["warning_lead_days"] = d["max_days_before_impact"].where(d["had_warning"])
    d["team_alert_offset_days"] = (d["first_internal_alert_date"] - d["start_date"]).dt.days
    d["decision_date"] = d["start_date"] + pd.to_timedelta(d["days_from_impact_to_first_mitigation"], "D")
    d["days_lost_vs_first_signal"] = (d["decision_date"] - d["first_signal_date"]).dt.days
    d["avoidable"] = d["had_warning"].map({True: "Warning-led (avoidable)", False: "Sudden (no warning)"})
    d["duration_days"] = (d["end_date"] - d["start_date"]).dt.days
    d["split"] = d["start_date"].ge(pd.Timestamp("2026-02-01")).map({True: "test", False: "train"})
    cols = ["disruption_id", "title", "type", "location", "split", "start_date", "end_date",
            "duration_days", "first_signal_date", "warning_lead_days", "signals_before_impact",
            "relevant_signals", "first_internal_alert_date", "team_alert_offset_days",
            "decision_date", "days_from_impact_to_first_mitigation", "days_lost_vs_first_signal",
            "had_warning", "avoidable", "parts_affected", "skus_affected", "units_short",
            "revenue_lost_inr_cr", "mitigation_cost_inr_cr", "lesson_recorded"]
    return d[cols]


def timeline_summary(t: pd.DataFrame | None = None) -> dict:
    t = disruption_timeline() if t is None else t
    w = t[t["had_warning"]]
    return {
        "disruptions_with_warning": int(t["had_warning"].sum()),
        "median_warning_lead_days": float(w["warning_lead_days"].median()),
        "median_team_alert_offset_days": float(t["team_alert_offset_days"].median()),
        "median_days_to_decision": float(t["days_from_impact_to_first_mitigation"].median()),
        "revenue_lost_warned_inr_cr": round(float(w["revenue_lost_inr_cr"].sum()), 1),
        "revenue_lost_sudden_inr_cr": round(float(t.loc[~t["had_warning"], "revenue_lost_inr_cr"].sum()), 1),
    }


if __name__ == "__main__":
    import json
    t = disruption_timeline()
    print(t[["disruption_id", "type", "start_date", "first_signal_date", "warning_lead_days",
             "signals_before_impact", "team_alert_offset_days", "days_from_impact_to_first_mitigation",
             "revenue_lost_inr_cr", "avoidable"]].to_string())
    print(json.dumps(timeline_summary(t), indent=2))

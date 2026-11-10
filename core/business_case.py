"""Stage-1 first business case: revenue that earlier action could have protected.

Deliberately simple and conservative; M6 replaces it with a full playbook replay.

Assumptions (stated so a CFO can challenge them):
  * Alert lands on the day of the first relevant public signal (warning_lead_days before impact),
    capped at `max_lead` (default 18 = the median lead) so one long-warning event doesn't dominate.
  * The response is an air-freight pre-buy of the binding part. Playbook says it takes 3–6 days,
    so we use 6. Each day of warning beyond that adds one day of cover.
  * Protected shortage days per binding part×SKU = min(shortage_days, lead − 6).
  * Probability the action works in time = 0.9 (the playbook's worked example).
  * Sudden events (no warning) are counted separately: on day one the co-pilot cuts decision
    time from the historical lag to 1 day. That only helps where a qualified alternate exists
    (switch takes 5–10 days, so we use 10).
  * Revenue lost is taken from disruptions.revenue_lost_inr_cr (55% lost-sale convention).
    It is apportioned to binding rows by their share of disruption_impacts.revenue_lost_inr.
"""
from __future__ import annotations

import pandas as pd

from core.etl import load
from core.timeline import disruption_timeline

AIR_PREBUY_DAYS = 6
SWITCH_ALT_DAYS = 10
P_WORKS = 0.9


def first_business_case(max_lead: float = 18.0, lead_override: float | None = None) -> pd.DataFrame:
    db = load()
    t = disruption_timeline().set_index("disruption_id")
    parts = db["parts"].set_index("part_id")
    imp = db["disruption_impacts"]
    b = imp[imp["binding_part_for_sku"] & (imp["shortage_days"] > 0)].copy()

    rows = []
    for did, g in b.groupby("disruption_id"):
        tr = t.loc[did]
        total_rev = g["revenue_lost_inr"].sum()
        if total_rev <= 0:
            continue
        scale = tr["revenue_lost_inr_cr"] / (total_rev / 1e7)  # brings to 55% convention
        if tr["had_warning"]:
            lead = lead_override if lead_override is not None else min(tr["warning_lead_days"], max_lead)
            gain = max(0.0, lead - AIR_PREBUY_DAYS)
            mode = f"Air pre-buy {lead:.0f}d before impact"
            prot = (g["shortage_days"].clip(upper=gain) / g["shortage_days"]) * g["revenue_lost_inr"]
        else:
            lag = tr["days_from_impact_to_first_mitigation"]
            gain = max(0.0, lag - 1)  # decision on day 1 instead of day `lag`
            has_alt = g["part_id"].map(lambda p: pd.notna(parts.loc[p, "qualified_alternate_supplier_id"]))
            # Days of shortage avoided if the switch had started on day 1 instead of day `lag`.
            avoid = g["shortage_days"].clip(upper=gain).where(has_alt, 0.0)
            prot = (avoid / g["shortage_days"]) * g["revenue_lost_inr"]
            mode = "Day-one switch to qualified alternate" if has_alt.any() else "No fast fix (no qualified alternate)"
        protected_cr = float(prot.sum()) / 1e7 * scale * P_WORKS
        rows.append({
            "disruption_id": did, "title": tr["title"], "avoidable": tr["avoidable"],
            "revenue_lost_inr_cr": round(float(tr["revenue_lost_inr_cr"]), 2),
            "response_modelled": mode,
            "revenue_protected_inr_cr": round(protected_cr, 2),
            "protected_pct": round(100 * protected_cr / tr["revenue_lost_inr_cr"], 0),
        })
    return pd.DataFrame(rows)


def business_case_summary() -> dict:
    bc = first_business_case()
    bc7 = first_business_case(lead_override=7)  # the brief's target lead time
    w, s = bc[bc["avoidable"].str.startswith("Warning")], bc[~bc["avoidable"].str.startswith("Warning")]
    db = load()
    m = db["mitigation_actions"]
    return {
        "revenue_lost_total_inr_cr": round(float(db["disruptions"]["revenue_lost_inr_cr"].sum()), 1),
        "protected_warned_inr_cr": round(float(w["revenue_protected_inr_cr"].sum()), 1),
        "protected_sudden_inr_cr": round(float(s["revenue_protected_inr_cr"].sum()), 1),
        "protected_total_inr_cr": round(float(bc["revenue_protected_inr_cr"].sum()), 1),
        "protected_total_if_only_7d_lead_inr_cr": round(float(bc7["revenue_protected_inr_cr"].sum()), 1),
        "wasted_mitigation_spend_inr_cr": round(float(m.loc[~m["had_shortage"], "cost_inr"].sum()) / 1e7, 2),
    }


if __name__ == "__main__":
    import json
    print(first_business_case().to_string())
    print(json.dumps(business_case_summary(), indent=2))

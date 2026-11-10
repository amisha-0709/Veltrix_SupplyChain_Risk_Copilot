"""Structural recommendations (brief stretch): dual sourcing and buffer levels for single-source parts.

For each single-source part we estimate an expected annual loss (EAL) and what each structural move buys.

  EAL = P(supplier outage per year) × margin + penalties lost if the primary supplier goes down
        for a typical outage (the engine on today's stock, class-default duration and delay)
      + the part's share of historical losses (disruption_impacts, binding rows, per year)

  Moves (playbook costs):
    qualify the unqualified alternate in advance → afterwards a switch takes ~19 days (observed)
        cost ₹15 lakh one-off (playbook ₹8–25 lakh), amortised over 3 years
    find and qualify a new second source (no alternate known) → same effect, ₹25 lakh one-off + 16 weeks
    raise buffer stock to cover a typical outage → no shortage; cost = holding 22%/yr × value of the extra stock

Net annual value = EAL avoided − annual cost. The ranking is the input to next year's dual-sourcing and
buffer-stock budget (playbook §12).
"""
from __future__ import annotations

import pandas as pd

from core.etl import load
from core.impact import DELAY_PRIORS, Scenario, estimate_delay, fmt_inr, run

OBSERVED_SWITCH_DAYS = 19.0
HOLDING = 0.22
AMORTISE_YEARS = 3
YEARS_OF_HISTORY = 2.0


def outage_rate() -> float:
    """Supplier outages per supplier per year, from history (fire, quake, strike, insolvency, cyber)."""
    db = load()
    d = db["disruptions"]
    from core.validate_impact import EVENT_CLASS
    n_out = sum(1 for x in d["disruption_id"] if EVENT_CLASS[x] == "supplier_outage")
    sup_hit = db["disruption_impacts"].merge(d[["disruption_id"]], on="disruption_id")
    n_sup = db["suppliers"]["supplier_id"].nunique()
    return n_out / (YEARS_OF_HISTORY * n_sup)


def structural_table() -> pd.DataFrame:
    db = load()
    parts = db["parts"].set_index("part_id")
    imp = db["disruption_impacts"]
    hist = (imp[imp["binding_part_for_sku"]].groupby("part_id")[["revenue_lost_inr", "margin_lost_inr"]].sum()
            / YEARS_OF_HISTORY)
    rate = outage_rate()
    delay = estimate_delay("supplier_outage", None)
    rows = []
    for pid, p in parts[parts["single_source"]].iterrows():
        base = run(Scenario(parts=[pid], event_type="supplier_outage", label=pid))
        t = base.totals
        loss_if = t["margin_at_risk_inr"] + t["penalty_inr"]
        eal_model = rate * loss_if
        eal_hist = float(hist["margin_lost_inr"].get(pid, 0.0))
        eal = eal_model + eal_hist
        cover = float(base.parts["days_of_cover"].iloc[0])
        daily_val = p["avg_weekly_usage_units"] / 7 * p["unit_cost_inr"]

        # after qualifying an alternate: shortage only until the switch lands
        after = run(Scenario(parts=[pid], event_type="supplier_outage", mitigation_effect_day={pid: OBSERVED_SWITCH_DAYS}))
        loss_after = after.totals["margin_at_risk_inr"] + after.totals["penalty_inr"]
        share_avoided = 1 - (loss_after / loss_if) if loss_if else 0.0
        has_unq = isinstance(p["unqualified_alternate_supplier_id"], str)
        q_cost_once = 15e5 if has_unq else 25e5
        q_annual = q_cost_once / AMORTISE_YEARS
        q_value = eal * share_avoided - q_annual

        extra_days = max(0.0, delay - cover)
        buf_annual = HOLDING * extra_days * daily_val
        buf_value = eal - buf_annual if extra_days >= 1 else 0.0

        moves = [("Qualify " + (p["unqualified_alternate_supplier_id"] if has_unq else "a new second source"), q_value)]
        if extra_days >= 1:
            moves.append((f"Raise buffer by {extra_days:.0f} days (to {delay:.0f} d cover)", buf_value))
        best = max(moves, key=lambda x: x[1])
        if best[1] <= 0 and extra_days < 1:
            best = (f"Hold cover at ≥ {delay:.0f} days (already met)", 0.0)
        rows.append({
            "part_id": pid, "description": p["description"], "category": p["category"],
            "cover_days": round(cover, 1), "lead_time_days": p["lead_time_days"],
            "skus": t["skus_exposed"], "margin_loss_if_outage_inr": loss_if,
            "eal_model_inr": eal_model, "eal_history_inr": eal_hist, "eal_inr": eal,
            "alternate": p["unqualified_alternate_supplier_id"] if has_unq else None,
            "qualify_weeks": p["qualification_weeks_if_unqualified"] if has_unq else 16,
            "qualify_cost_once_inr": q_cost_once, "qualify_net_annual_inr": q_value, "qualify_share_avoided": round(share_avoided, 2),
            "buffer_extra_days": round(extra_days, 1), "buffer_cost_annual_inr": buf_annual, "buffer_net_annual_inr": buf_value,
            "recommendation": best[0] if best[1] > 0 or best[0].startswith("Hold") else "Monitor (no structural move pays back)",
            "net_annual_value_inr": max(best[1], 0.0),
        })
    df = pd.DataFrame(rows).sort_values("net_annual_value_inr", ascending=False).reset_index(drop=True)
    return df


def structural_summary(df: pd.DataFrame | None = None) -> dict:
    df = structural_table() if df is None else df
    act = df[df["net_annual_value_inr"] > 0]
    q = act[act["recommendation"].str.startswith("Qualify")]
    b = act[act["recommendation"].str.startswith("Raise")]
    return {"outage_rate_per_supplier_year": round(outage_rate(), 4),
            "typical_outage_delay_days": estimate_delay("supplier_outage", None),
            "parts_with_positive_move": int(len(act)), "qualify_moves": int(len(q)), "buffer_moves": int(len(b)),
            "one_off_qualification_cost_cr": round(float(q["qualify_cost_once_inr"].sum()) / 1e7, 2),
            "annual_buffer_cost_cr": round(float(b["buffer_cost_annual_inr"].sum()) / 1e7, 2),
            "net_annual_value_cr": round(float(act["net_annual_value_inr"].sum()) / 1e7, 2),
            "eal_total_cr": round(float(df["eal_inr"].sum()) / 1e7, 2)}


if __name__ == "__main__":
    df = structural_table()
    pd.set_option("display.width", 250)
    show = df[["part_id", "description", "cover_days", "lead_time_days", "eal_inr", "eal_history_inr", "qualify_net_annual_inr",
               "buffer_extra_days", "buffer_cost_annual_inr", "buffer_net_annual_inr", "recommendation", "net_annual_value_inr"]].copy()
    for c in [c for c in show if c.endswith("_inr")]:
        show[c] = (show[c] / 1e5).round(1)
    print("(₹ lakh)"); print(show.to_string())
    print(structural_summary(df))

"""Business case: ROI on the co-pilot itself, including running costs (brief Stage 3, playbook §6).

Benefit follows the playbook ROI definition, in terms a CFO accepts:
    loss avoided = margin protected + penalties avoided + mitigation spend avoided (where cover was enough)
  * margin, not revenue: lost revenue overstates what the business actually loses;
  * probability-weighted: each recommended option counts × P(works in time);
  * net of the cost of the recommended mitigations;
  * structural moves (dual sourcing, buffers) are reported separately as upside, not in the base case.
Source: replay of all 18 disruptions (core/replay.py), annualised over the 2 years of history.

Cost: build, data, hosting, model calls and people. Assumptions below, all editable.
"""
from __future__ import annotations

import pandas as pd

from core.replay import replay_all

YEARS = 2.0
USD_INR = 88.0

COSTS = {  # ₹ per year unless noted; deliberately on the generous side
    "build_and_pilot_one_off": (35e5, "ERP stock/in-transit feed, 3-month pilot, set-up (one-off, amortised over 3 years)"),
    "news_and_data_feeds": (12e5, "Licensed news API; GDELT, PortWatch and Global Trade Alert are free"),
    "hosting": (3e5, "Serverless app + managed database + monitoring"),
    "model_calls": (None, "Claude: triage review of all signals on Haiku 5.5 + briefings on Opus 5.5"),
    "risk_owner": (12e5, "0.5 FTE risk analyst owns the inbox and weekly review (nobody owns monitoring today)"),
    "maintenance": (8e5, "0.25 FTE engineer: rules, data feeds, model updates"),
}
AMORTISE_YEARS = 3


def model_call_cost(signals_per_day: int = 5000, alerts_per_year: int = 200) -> dict:
    """Model spend at list prices (claude-api skill, Nov 2026): Haiku 5.5 $0.10/$0.50, Opus 5.5 $4/$20 per M tokens."""
    tri_in, tri_out = 600, 120                       # tokens per signal reviewed
    brief_in, brief_out = 6000, 1500                 # tokens per alert briefing / chat answer
    n = signals_per_day * 365
    triage = n * (tri_in * 0.10 + tri_out * 0.50) / 1e6
    briefs = alerts_per_year * 5 * (brief_in * 4 + brief_out * 20) / 1e6   # ×5: briefings + follow-up questions
    usd = triage + briefs
    return {"signals_per_year": n, "usd_per_year": round(usd, 0), "inr_per_year": usd * USD_INR}


def annual_cost() -> tuple[float, list[dict]]:
    mc = model_call_cost()
    rows, total = [], 0.0
    for k, (v, note) in COSTS.items():
        if k == "model_calls":
            v_year = mc["inr_per_year"]
            note = f"{note}: {mc['signals_per_year'] / 1e6:.1f} M signals/yr ≈ ${mc['usd_per_year']:.0f}/yr"
        elif k.endswith("one_off"):
            v_year = v / AMORTISE_YEARS
        else:
            v_year = v
        rows.append({"item": k.replace("_", " "), "annual_inr": v_year, "note": note})
        total += v_year
    return total, rows


def benefits(df: pd.DataFrame, years: float = YEARS) -> dict:
    m = df["margin_protected_inr"].sum()
    p = df["penalties_avoided_inr"].sum()
    w = df["avoided_waste_inr"].sum()
    c = df["plan_cost_inr"].sum()
    return {"margin_protected": m / years, "penalties_avoided": p / years, "waste_avoided": w / years,
            "mitigation_cost": c / years, "net": (m + p + w - c) / years,
            "revenue_protected": df["vs_actual_protected_expected_inr"].sum() / years}


def business_case() -> dict:
    df = replay_all()
    cost, cost_rows = annual_cost()
    base = benefits(df)
    test = df[pd.to_datetime(df["start_date"]) >= pd.Timestamp("2026-02-01")]
    big = df["actual_revenue_lost_inr"] > USD_INR * 1e6        # Abhishek's rule: drop >$1M events as outliers
    scen = {
        "Base: all 18 disruptions": base,
        "Test period only (Feb–Sep 2026, annualised)": benefits(test, years=8 / 12),
        "Outliers removed (events losing > $1M)": benefits(df[~big]),
        "Half the probability of success": {k: v * 0.5 if k != "mitigation_cost" else v for k, v in base.items()}
                                          | {"net": base["net"] * 0.5 - base["mitigation_cost"] * 0.5},
        "Costs doubled": base,
    }
    rows = []
    for name, b in scen.items():
        c = cost * (2 if name == "Costs doubled" else 1)
        rows.append({"scenario": name, "net_benefit_inr": b["net"], "copilot_cost_inr": c,
                     "roi": (b["net"] - c) / c, "payback_months": 12 * c / b["net"] if b["net"] > 0 else None})
    return {"annual_cost_inr": cost, "cost_rows": cost_rows, "base": base, "scenarios": rows,
            "break_even_margin_inr": cost, "replays": df}


if __name__ == "__main__":
    from core.impact import fmt_inr
    bc = business_case()
    print("annual co-pilot cost", fmt_inr(bc["annual_cost_inr"]))
    for r in bc["cost_rows"]:
        print(f"  {r['item']:28s} {fmt_inr(r['annual_inr']):>14s}  {r['note']}")
    print({k: fmt_inr(v) for k, v in bc["base"].items()})
    for r in bc["scenarios"]:
        print(f"  {r['scenario']:48s} net {fmt_inr(r['net_benefit_inr']):>12s}  cost {fmt_inr(r['copilot_cost_inr']):>11s}  "
              f"ROI {r['roi']:.1f}×  payback {r['payback_months'] and round(r['payback_months'], 1)} months")

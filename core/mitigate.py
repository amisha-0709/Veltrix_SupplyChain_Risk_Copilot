"""Mitigation options and ranking: playbook §4–7.

    from core.impact import Scenario, run
    from core.mitigate import rank_options
    base = run(sc)
    opts = rank_options(sc, base, lead_days=10)   # lead = days between decision (alert) and impact

For each part that runs short, every applicable option of the playbook's eight is costed. Its benefit
is measured by RE-RUNNING the impact engine with the option in place (new cover or new delay for that
part), so options and impact always use the same maths.

  net value = margin avoided × P(works in time) − option cost − penalties incurred anyway
  ROI       = (loss avoided − cost) ÷ cost,  loss avoided = (margin protected + penalties avoided) × P
  Ranking   = options that take effect before the shortage starts come first; then by net value;
              ties go to reversible options. An option that lands after the shortage begins is
              shown with its partial value but always ranks below on-time options (playbook §5).
The co-pilot recommends. Every option shows the approver from the matrix and is never shown as approved.
"""
from __future__ import annotations

import math
from dataclasses import replace

import pandas as pd

from core.etl import load
from core.graph import build_network
from core.impact import ImpactResult, Scenario, run

# Sea freight as a share of goods value. The data pack has no weights, so this is calibrated to the
# playbook worked example (3 weeks of two Kaohsiung semiconductors by air ≈ ₹18 lakh) → ~1.5%.
SEA_FREIGHT_PCT = 0.015
HOLDING_PCT_YEAR = 0.22      # playbook: holding cost ~22% a year of value
DEFAULT_ALT_PREMIUM = 0.085  # playbook 3–14% when the part has no figure
QUAL_FIXED_INR = 15e5        # playbook ₹8–25 lakh qualification cost (midpoint-ish)
BROKER_PREMIUM = 1.0         # playbook +40–160%
DEMAND_SHAPING_DISCOUNT = 0.05

APPROVAL = {  # decision type -> (≤ ₹50 lakh, ₹50 lakh–2 cr, > ₹2 cr)
    "expedite": ("Category manager", "Head of Supply Chain", "COO"),
    "prebuy": ("Head of Supply Chain", "Head of Supply Chain + CFO", "COO + CFO"),
    "broker": ("Head of Supply Chain", "COO", "COO + CFO"),
    "switch": ("Head of Supply Chain + Quality", "Head of Supply Chain + Quality", "COO"),
    "realloc": ("Head of Sales + Supply Chain", "Head of Sales + Supply Chain", "CEO"),
    "none": ("Category manager (log only)",) * 3,
}


def approver(kind: str, cost_inr: float) -> str:
    a = APPROVAL[kind]
    return a[0] if cost_inr <= 50e5 else a[1] if cost_inr <= 2e7 else a[2]


def roi(margin_protected: float, penalties_avoided: float, cost: float, expedite_avoided: float = 0.0) -> float | None:
    """Playbook §6. Returns None when the option costs nothing (ROI undefined)."""
    if cost <= 0:
        return None
    return (margin_protected + penalties_avoided + expedite_avoided - cost) / cost


def _lane_for(supplier_id: str) -> pd.Series | None:
    db = load()
    sh = db["shipments"].dropna(subset=["lane_id"])
    s = sh[sh["supplier_id"] == supplier_id]["lane_id"]
    if s.empty:
        return None
    ln = s.mode().iloc[0]
    return db["lanes"].set_index("lane_id").loc[ln]


def _reroute_days(text: str) -> float | None:
    import re
    m = re.search(r"\+(\d+)\s*to\s*\+(\d+)", str(text))
    return (int(m.group(1)) + int(m.group(2))) / 2 if m else None


def _rerun(sc: Scenario, base: ImpactResult, part: str, new_shortage: float) -> dict:
    """Totals with `part`'s shortage set to new_shortage (via an equivalent cover)."""
    row = base.parts.set_index("part_id").loc[part]
    delay = float(row["effective_delay_days"])
    cover = dict(sc.cover_override or {})
    cover[part] = delay - new_shortage if new_shortage > 0 else max(delay + 1, float(row["days_of_cover"]))
    eff = dict(sc.mitigation_effect_day or {})
    eff.pop(part, None)
    return run(replace(sc, cover_override=cover, mitigation_effect_day=eff or None)).totals


def _realloc(base: ImpactResult, part: str) -> tuple[float, float]:
    """Margin avoided and extra penalties if the scarce part goes to the highest margin per part-unit SKUs."""
    db = load()
    skus = db["skus"].set_index("sku_id")
    bom = db["bom"]
    S = base.skus[(base.skus["binding_part"] == part) & (base.skus["units_short"] > 0)]
    if len(S) < 2:
        return 0.0, 0.0
    sd = float(base.parts.set_index("part_id").loc[part, "shortage_days"])
    delay = float(base.parts.set_index("part_id").loc[part, "effective_delay_days"])
    rows = []
    for r in S.itertuples():
        q = float(bom[(bom.sku_id == r.sku_id) & (bom.part_id == part)]["qty_per_unit"].iloc[0])
        s = skus.loc[r.sku_id]
        daily = s["avg_weekly_demand_units"] / 7
        rows.append({"sku": r.sku_id, "need": daily * q, "q": q,
                     "m_per_part": s["price_inr"] * s["unit_margin_pct"] / q,
                     "pen_per_part": s["price_inr"] * s["late_delivery_penalty_pct_per_week"] / 100 / q})
    R = pd.DataFrame(rows).sort_values("m_per_part")
    shortfall = (R["need"] * sd).sum()           # part-units short in total (pro-rata baseline)
    base_m = 0.55 * (R["need"] * sd * R["m_per_part"]).sum()
    base_p = 0.45 * (R["need"] * sd * R["pen_per_part"]).sum()
    left, gm, gp = shortfall, 0.0, 0.0
    for r in R.itertuples():                       # lowest margin SKUs absorb the shortage first
        take = min(left, r.need * delay)
        gm += 0.55 * take * r.m_per_part
        gp += 0.45 * take * r.pen_per_part
        left -= take
        if left <= 0:
            break
    return max(0.0, base_m - gm), max(0.0, gp - base_p)


def isolate(sc: Scenario, base: ImpactResult, part: str) -> tuple[Scenario, ImpactResult]:
    """Scenario where only `part` runs short: shows what this part alone costs, so a fix on one part
    is not hidden by another part that binds the same SKU (both are fixed in the joint plan)."""
    cover = dict(sc.cover_override or {})
    for r in base.parts.itertuples():
        if r.part_id != part and r.shortage_days > 0:
            cover[r.part_id] = r.effective_delay_days + 1
    if part in cover and part not in (sc.cover_override or {}):
        cover.pop(part)
    iso_sc = replace(sc, cover_override=cover or None)
    return iso_sc, run(iso_sc)


def options_for_part(sc: Scenario, base: ImpactResult, part: str, lead_days: float) -> list[dict]:
    db = load()
    net = build_network()
    parts = db["parts"].set_index("part_id")
    pr = parts.loc[part]
    sc, base = isolate(sc, base, part)
    row = base.parts.set_index("part_id").loc[part]
    s0, c, D = float(row["shortage_days"]), float(row["days_of_cover"]), float(row["effective_delay_days"])
    u, k = float(pr["avg_weekly_usage_units"]) / 7, float(pr["unit_cost_inr"])
    L = max(0.0, float(lead_days))
    lane = _lane_for(pr["primary_supplier_id"])
    air_mult = float(lane["air_cost_multiplier"]) if lane is not None and pd.notna(lane["air_cost_multiplier"]) else 8.0
    exposed_nodes = set(sc.nodes)
    affected_sups = {n[4:] for node in exposed_nodes if node in net.G
                     for n in net.G.successors(node) if n.startswith("sup:")} if exposed_nodes else set()

    def end_shortage_at(day: float) -> float:          # supply resumes `day` days after impact
        return max(0.0, min(D, day) - c)

    opts: list[dict] = []

    def add(name, kind, tte, new_short, cost, p, reversible, note, extra_margin=0.0, extra_pen=0.0):
        eff_day = tte - L                                 # days after impact when it takes effect
        if extra_margin:                                  # re-allocation / demand shaping: computed directly
            m_av, p_av = extra_margin, 0.0
        else:
            t = _rerun(sc, base, part, new_short)
            m_av = base.totals["margin_at_risk_inr"] - t["margin_at_risk_inr"]
            p_av = base.totals["penalty_inr"] - t["penalty_inr"]
        pen_anyway = max(0.0, base.totals["penalty_inr"] - p_av * p) + extra_pen
        netv = m_av * p - cost - pen_anyway
        opts.append({
            "part_id": part, "option": name, "kind": kind, "time_to_effect_days": round(tte, 1),
            "effect_day_vs_impact": round(eff_day, 1), "shortage_starts_day": round(c, 1),
            "on_time": eff_day <= c, "shortage_days_before": round(s0, 1),
            "shortage_days_after": round(new_short, 1), "cost_inr": round(cost),
            "p_works": p, "margin_avoided_inr": round(m_av), "penalties_avoided_inr": round(p_av),
            "penalties_anyway_inr": round(pen_anyway), "net_value_inr": round(netv),
            "roi": None if cost <= 0 else round(roi(m_av * p, p_av * p, cost), 2),
            "reversible": reversible, "approver": approver(kind, cost),
            "status": "Recommended: requires approval", "note": note,
        })

    # 1. Switch to qualified alternate
    alt = pr["qualified_alternate_supplier_id"]
    if pd.notna(alt):
        prem = (pr["alternate_cost_premium_pct"] / 100) if pd.notna(pr["alternate_cost_premium_pct"]) else DEFAULT_ALT_PREMIUM
        shared = alt in affected_sups
        tte = 7
        add(f"Switch to qualified alternate {alt}", "switch", tte, end_shortage_at(tte - L),
            prem * k * u * D, 0.3 if shared else 0.8, True,
            f"+{prem:.0%} unit price; playbook 5–10 days. "
            + ("Alternate is in the affected area too, so capacity is doubtful." if shared else
               "History: past switches took ~19 days to take hold, so confirm alternate capacity."))
    # 2. Qualify a new (unqualified) supplier
    ua = pr["unqualified_alternate_supplier_id"]
    if pd.notna(ua) and pd.notna(pr["qualification_weeks_if_unqualified"]):
        tte = float(pr["qualification_weeks_if_unqualified"]) * 7
        add(f"Qualify new supplier {ua}", "switch", tte, end_shortage_at(tte - L),
            QUAL_FIXED_INR + 0.10 * k * u * max(0.0, D - max(0.0, tte - L)), 0.7, False,
            f"PPAP + customer approval ≈ {tte/7:.0f} weeks. Too slow for short events; start early for structural risk.")
    elif pd.isna(alt):
        tte = 16 * 7                                     # playbook worst case: none identified yet
        add("Qualify a new supplier (to be identified)", "switch", tte, end_shortage_at(tte - L),
            25e5 + 0.10 * k * u * max(0.0, D - max(0.0, tte - L)), 0.5, False,
            "No alternate exists. Sourcing + PPAP 6–16 weeks: a structural fix, start now for the next event.")
    # 3. Air-freight expedite (goods exist, sea route blocked or slow)
    if sc.event_type in ("port_closure", "congestion", "route") and pr["category"] != "Li-ion cells":
        tte = 4
        vol = u * max(0.0, D - max(0.0, tte - L))
        add("Air-freight expedite", "expedite", tte, end_shortage_at(tte - L),
            vol * k * SEA_FREIGHT_PCT * (air_mult - 1), 0.85, True,
            f"Air ≈ {air_mult:.1f}× sea freight; 3–6 days; capacity limited in peaks.")
    # 4. Re-route (chokepoint or port blocked)
    # Only when the blockage is on the route or at the Indian end. A closed ORIGIN port can't be
    # bypassed by transshipping: the goods can't leave by sea at all.
    on_route = sc.event_type in ("route", "congestion") or any(n.startswith(("choke:", "dest:", "lane:")) for n in sc.nodes)
    if lane is not None and on_route:
        pen = _reroute_days(lane["reroute_option"])
        if pen is not None and pen < D:
            add(f"Re-route: {lane['reroute_option']}", "expedite", 1, max(0.0, pen - c),
                0.25 * SEA_FREIGHT_PCT * k * u * D, 0.9, True,
                "Playbook +10–40% freight; immediate booking, adds transit days.")
    # 5. Buffer stock pre-buy (warning arrives before impact)
    if L > 0 and sc.event_type != "cost_only":
        cover_days = min(21.0, s0 + 7)                     # buy the shortage + a week, max 3 weeks
        qty_val = cover_days * u * k
        hold = HOLDING_PCT_YEAR * qty_val * (D + cover_days) / 365
        tte_air = 6                                        # 2 days at supplier + ~4 days air
        arr = tte_air - L
        new = max(0.0, D - c - cover_days) + max(0.0, min(arr, D) - c)
        add(f"Pre-buy {cover_days:.0f} days of stock by air", "prebuy", tte_air, min(new, s0),
            hold + qty_val * SEA_FREIGHT_PCT * air_mult, 0.9, False,
            "Needs cash and warehouse space; obsolescence risk.")
        if lane is not None and L >= float(lane["transit_days_typical"]) + 2 and sc.event_type not in ("route",):
            tte_sea = float(lane["transit_days_typical"]) + 2
            arr = tte_sea - L
            new = max(0.0, D - c - cover_days) + max(0.0, min(arr, D) - c)
            add(f"Pre-buy {cover_days:.0f} days of stock by sea", "prebuy", tte_sea, min(new, s0),
                hold + qty_val * SEA_FREIGHT_PCT, 0.9, False, "Cheapest if the warning is early enough.")
    # 6. Broker spot buy (semiconductors, last resort)
    if pr["category"] == "Semiconductors":
        tte = 10
        add("Broker spot buy", "broker", tte, end_shortage_at(tte - L),
            BROKER_PREMIUM * k * u * s0, 0.7, False,
            "+40–160% price; counterfeit risk: 100% incoming inspection mandatory.")
    # 7. Re-allocate scarce parts
    m_av, extra_pen = _realloc(base, part)
    if m_av > 0:
        add("Re-allocate to highest-margin SKUs", "realloc", 0, s0, 0.0, 1.0, True,
            "Shortage unavoidable; allocate by margin × penalty exposure; agree with Sales.",
            extra_margin=m_av, extra_pen=extra_pen)
    # 8. Customer demand shaping
    S = base.skus[(base.skus["binding_part"] == part) & (base.skus["units_short"] > 0)]
    if len(S):
        tte = 10
        frac = max(0.0, 1 - max(0.0, tte - L - c) / s0) if s0 else 0
        rev = float(S["revenue_at_risk_inr"].sum()) * frac
        marg = float((S["revenue_at_risk_inr"] * S["unit_margin_pct"]).sum()) * frac
        add("Customer demand shaping (later date / other variant)", "realloc", tte, s0,
            DEMAND_SHAPING_DISCOUNT * rev, 0.5, True,
            "Turns some lost sales into late deliveries; needs Sales and customer agreement.",
            extra_margin=0.30 * marg)
    return opts


def rank_options(sc: Scenario, base: ImpactResult, lead_days: float = 0.0) -> pd.DataFrame:
    if base.totals["no_action_needed"]:
        return pd.DataFrame([{
            "rank": 1, "part_id": None, "option": "No action: cover exceeds expected delay. Monitor.",
            "kind": "none", "cost_inr": 0, "net_value_inr": 0, "approver": approver("none", 0),
            "status": "Recommended: log and watch", "on_time": True,
            "note": f"Min cover {base.totals['min_cover_days']} d vs delay "
                    f"{base.parts['effective_delay_days'].max() if len(base.parts) else 0} d"
                    + ("; finished-goods stock absorbs the small part shortage." if base.totals["parts_short"] else "."),
        }])
    short_parts = base.parts.loc[base.parts["shortage_days"] > 0, "part_id"].tolist()
    O = pd.DataFrame([o for p in short_parts for o in options_for_part(sc, base, p, lead_days)])
    if O.empty:
        return O
    # Fallbacks (re-allocation, demand shaping) only move the loss around. Playbook: use them "when
    # the shortage is unavoidable", so options that actually shorten the shortage rank above them.
    O["fixes_shortage"] = O["shortage_days_after"] < O["shortage_days_before"]
    O["worth_it"] = O["net_value_inr"] > 0
    O = O.sort_values(["on_time", "worth_it", "fixes_shortage", "net_value_inr", "reversible"],
                      ascending=[False, False, False, False, False])
    O["rank"] = range(1, len(O) + 1)
    O["rank_in_part"] = O.groupby("part_id").cumcount() + 1
    return O.reset_index(drop=True)


def best_plan(options: pd.DataFrame) -> pd.DataFrame:
    """Top on-time option with positive net value per short part (else its top option)."""
    if options.empty or options["part_id"].isna().all():
        return options
    picks = []
    for _, g in options.groupby("part_id", sort=False):
        good = g[g["on_time"] & (g["net_value_inr"] > 0)]
        if not len(good):
            good = g[g["net_value_inr"] > 0]       # late but still worth it
        if len(good):
            picks.append(good.iloc[0])
    if not picks:
        return options.iloc[0:0]
    return pd.DataFrame(picks).sort_values("rank").reset_index(drop=True)


def evaluate_plan(sc: Scenario, base: ImpactResult, plan: pd.DataFrame) -> dict:
    """Joint effect of the plan: re-run the engine with every chosen option in place."""
    if plan.empty or plan["part_id"].isna().all():
        return {"cost_inr": 0.0, "margin_protected_inr": 0.0, "penalties_avoided_inr": 0.0, "roi": None,
                "revenue_lost_after_inr": base.totals["revenue_lost_inr"]}
    cover = dict(sc.cover_override or {})
    P = base.parts.set_index("part_id")
    extra = 0.0
    for r in plan.itertuples():
        d = float(P.loc[r.part_id, "effective_delay_days"])
        if r.kind == "realloc":
            extra += r.margin_avoided_inr * r.p_works
        new = float(r.shortage_days_after)
        cover[r.part_id] = d - new if new > 0 else d + 1
    after = run(replace(sc, cover_override=cover, mitigation_effect_day=None)).totals
    p = float((plan["p_works"] * plan["cost_inr"]).sum() / plan["cost_inr"].sum()) if plan["cost_inr"].sum() else 0.9
    margin = (base.totals["margin_at_risk_inr"] - after["margin_at_risk_inr"]) * p + extra
    pens = (base.totals["penalty_inr"] - after["penalty_inr"]) * p
    cost = float(plan["cost_inr"].sum())
    return {"cost_inr": cost, "margin_protected_inr": margin, "penalties_avoided_inr": pens,
            "revenue_protected_inr": (base.totals["revenue_lost_inr"] - after["revenue_lost_inr"]) * p,
            "revenue_lost_after_inr": after["revenue_lost_inr"],
            "roi": roi(margin, pens, cost) if cost else None,
            "approvers": sorted(set(plan["approver"]))}


def recommend(sc: Scenario, lead_days: float = 0.0) -> dict:
    """Everything an alert needs: expected impact, stress impact, ranked options, plan, plan value.

    If the expected case needs no action but the stress case (slowest recovery seen in history) does,
    options are costed on the stress case and labelled PRECAUTIONARY. That's the honest answer on the
    day of a sudden event, when nobody knows how long it will last.
    """
    expected = run(sc)
    stress = None
    if sc.delay_days is None and sc.event_type != "cost_only":
        stress = run(replace(sc, stress=True))
    mode, basis_sc, basis = "expected", sc, expected
    if expected.totals["no_action_needed"] and stress is not None and not stress.totals["no_action_needed"]:
        mode, basis_sc, basis = "precautionary", replace(sc, stress=True), stress
    opts = rank_options(basis_sc, basis, lead_days)
    if mode == "precautionary" and len(opts):
        opts["status"] = "Precautionary (if the outage runs long): requires approval"
    plan = best_plan(opts) if not basis.totals["no_action_needed"] else opts.iloc[0:0]
    ev = evaluate_plan(basis_sc, basis, plan) if len(plan) else None
    return {"mode": mode, "expected": expected, "stress": stress, "options": opts, "plan": plan,
            "plan_value": ev, "lead_days": lead_days}


if __name__ == "__main__":
    from core.impact import fmt_inr
    sc = Scenario(nodes=["cat:Magnets", "country:China"], match="all", event_type="trade_licensing",
                  duration_days=49, label="T4 China magnet licensing")
    base = run(sc)
    print("\n".join(base.working))
    o = rank_options(sc, base, lead_days=14)
    pd.set_option("display.width", 250)
    print(o[["rank", "part_id", "option", "time_to_effect_days", "on_time", "shortage_days_before",
             "shortage_days_after", "cost_inr", "margin_avoided_inr", "penalties_anyway_inr", "net_value_inr",
             "roi", "approver"]].to_string())
    plan = best_plan(o)
    ev = evaluate_plan(sc, base, plan)
    print(plan[["part_id", "option", "cost_inr", "approver"]].to_string())
    print({k: (fmt_inr(v) if k.endswith("_inr") else v) for k, v in ev.items()})
    print({k: (fmt_inr(v) if k.endswith("_inr") else v) for k, v in base.totals.items()})

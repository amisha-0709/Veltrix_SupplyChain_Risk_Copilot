"""Replay a past disruption as if the co-pilot had been live (T10), and the business case across all 18.

    from core.replay import replay, replay_all
    r = replay("D05")

How it works:
  1. WHEN: the co-pilot's first alert for the disruption comes from the T9 back-test (signals → triage → event).
  2. WHAT IT WOULD HAVE SAID: the engine runs on what it would have known on that day: the parts it links
     (from history), stock cover at the time (disruption_impacts.days_of_cover_at_start, i.e. the ERP
     snapshot it would have read), and its OWN delay estimate (event-class prior × stated duration). It
     does not use the delay that actually happened. Its top-ranked plan is taken as the recommendation.
  3. WHAT IT WOULD HAVE SAVED: the plan is applied to REALITY (actual delay and cover). Each option takes
     effect at (time to effect − warning lead) days after impact. The resulting loss is compared with the
     unmitigated loss the engine computes for reality, and with what Veltrix actually lost.
  4. WASTE: team spend on parts that had enough cover (mitigation_actions.had_shortage = False) that the
     co-pilot's own estimate would have told it to skip.
"""
from __future__ import annotations

import re
from dataclasses import replace

import pandas as pd

from core.etl import load
from core.impact import Scenario, fmt_inr, run
from core.mitigate import recommend, roi
from core.validate_impact import EVENT_CLASS, _effect_days, _shortage_factor

_BT = None
OBSERVED_SWITCH_DAYS = 19.0     # calibrated on mitigation_actions (see validate_impact.TIME_TO_EFFECT)


def _lead_table() -> pd.DataFrame:
    global _BT
    if _BT is None:
        from core.backtest import run_backtest
        _BT = run_backtest()["lead_table"].set_index("disruption_id")
    return _BT


def _stated_duration(did: str) -> float | None:
    """Duration the co-pilot would have had: from official weather alerts linked to this disruption, if any."""
    db = load()
    lab = db["signal_labels"]
    wx = db["weather_alerts"].merge(lab, left_on="alert_id", right_on="signal_id")
    w = wx[(wx["linked_disruption_id"] == did)]
    return float(w["expected_duration_days"].max()) if len(w) else None


def _apply_plan(real: Scenario, base_real, plan: pd.DataFrame, lead: float,
                team_eff: dict | None = None) -> tuple[Scenario, float]:
    """Reality with the recommended options in place, plus whatever the team did anyway on parts the plan
    doesn't cover (the co-pilot recommends; it doesn't stop people acting). Returns (scenario, extra margin)."""
    P = base_real.parts.set_index("part_id")
    cover = dict(real.cover_override or {})
    eff = dict(team_eff or {})          # whichever lands first, the team's own action or the co-pilot's, counts
    extra = 0.0
    for r in plan.itertuples():
        if r.part_id not in P.index:
            continue
        c, D = float(P.loc[r.part_id, "days_of_cover"]), float(P.loc[r.part_id, "effective_delay_days"])
        tte = float(r.time_to_effect_days)
        if r.kind == "switch" and "qualified alternate" in r.option:
            tte = max(tte, OBSERVED_SWITCH_DAYS)              # reality: switches took ~19 d to take hold
        arrive = tte - lead                                   # days after impact the option lands
        if r.kind == "realloc":
            extra += float(r.margin_avoided_inr) * float(r.p_works)
            continue
        if r.kind == "prebuy":
            m = re.search(r"(\d+) days", r.option)
            x = float(m.group(1)) if m else 14.0
            new_short = max(0.0, D - c - x) + max(0.0, min(arrive, D) - c)
            new_short = min(new_short, max(0.0, D - c))
            cover[r.part_id] = D - new_short if new_short > 0 else D + 1
        else:                                                   # supply resumes when the option lands
            eff[r.part_id] = min(eff.get(r.part_id, float("inf")), max(0.0, arrive))
    return replace(real, cover_override=cover, mitigation_effect_day=eff or None), extra


def replay(did: str) -> dict:
    db = load()
    d = db["disruptions"].set_index("disruption_id").loc[did]
    imp = db["disruption_impacts"]
    g = imp[imp["disruption_id"] == did].drop_duplicates("part_id")
    parts = g["part_id"].tolist()
    cover = dict(zip(g["part_id"], g["days_of_cover_at_start"]))
    delay = dict(zip(g["part_id"], g["effective_delay_days"]))
    cls = EVENT_CLASS[did]
    L = _lead_table()
    lt = L.loc[did]
    detected = pd.notna(lt["lead_days"])
    lead = max(0.0, float(lt["lead_days"])) if detected else 0.0
    alert_date = lt["first_alert"] if detected else None
    common = dict(parts=parts, cover_override=cover, use_fg=False, include_in_transit=False,
                  start_date=d["start_date"], event_type=cls)

    # What the co-pilot would have seen and said
    seen = Scenario(duration_days=_stated_duration(did), label=f"{did} as seen on alert day", **common)
    rec = recommend(seen, lead)
    basis = rec["stress"] if rec["mode"] == "precautionary" else rec["expected"]
    plan = rec["plan"]

    # Reality: unmitigated, what the team actually did, and the co-pilot's plan
    real = Scenario(delay_days=delay, label=f"{did} reality", **common)
    unmit = run(real)
    team_eff = _effect_days(did)
    team_sf = _shortage_factor(did) or None       # the team's broker buys cover part of the gap, in every world
    team = run(replace(real, mitigation_effect_day=team_eff or None, shortage_factor=team_sf))
    sc_plan, extra = _apply_plan(real, unmit, plan, lead, team_eff)
    sc_plan = replace(sc_plan, shortage_factor=team_sf)
    withplan = run(sc_plan)
    p = float((plan["p_works"] * plan["cost_inr"]).sum() / plan["cost_inr"].sum()) if len(plan) and plan["cost_inr"].sum() else 0.9
    cost = float(plan["cost_inr"].sum()) if len(plan) else 0.0
    # Credit only what the co-pilot adds over what the team actually did (team run = baseline).
    rev_prot_full = team.totals["revenue_lost_inr"] - withplan.totals["revenue_lost_inr"]
    marg_prot = (team.totals["margin_at_risk_inr"] - withplan.totals["margin_at_risk_inr"]) * p + extra
    pen_prot = (team.totals["penalty_inr"] - withplan.totals["penalty_inr"]) * p

    actual_lost = float(d["revenue_lost_inr_cr"]) * 1e7
    # Structural counterfactual: had each short part's unqualified alternate been qualified BEFORE the event
    # (the exposure map's recommendation), a switch would land ~19 days after impact.
    parts_tbl = db["parts"].set_index("part_id")
    short_parts = unmit.parts.loc[unmit.parts["shortage_days"] > 0, "part_id"].tolist()
    struct_parts = [p_ for p_ in short_parts if isinstance(parts_tbl.loc[p_, "unqualified_alternate_supplier_id"], str)]
    struct = None
    if struct_parts:
        s_eff = dict(team_eff)
        for p_ in struct_parts:
            s_eff[p_] = min(s_eff.get(p_, float("inf")), OBSERVED_SWITCH_DAYS)
        s_run = run(replace(real, mitigation_effect_day=s_eff, shortage_factor=team_sf))
        struct = {"parts": [f"{p_} → qualify {parts_tbl.loc[p_, 'unqualified_alternate_supplier_id']} "
                            f"({parts_tbl.loc[p_, 'qualification_weeks_if_unqualified']:.0f} wk) in advance"
                            for p_ in struct_parts],
                  "cost_inr": 15e5 * len(struct_parts),
                  "revenue_lost_inr": s_run.totals["revenue_lost_inr"],
                  "revenue_protected_inr": actual_lost - s_run.totals["revenue_lost_inr"]}

    # Waste the co-pilot would have avoided: team spend on parts with enough cover that the co-pilot also saw as safe
    m = db["mitigation_actions"]
    mm = m[m["disruption_id"] == did]
    seen_short = set(basis.parts.loc[basis.parts["shortage_days"] > 0, "part_id"]) if len(basis.parts) else set()
    wasted = mm[~mm["had_shortage"]]
    avoided_waste = float(wasted[~wasted["part_id"].isin(seen_short)]["cost_inr"].sum())

    return {
        "disruption_id": did, "title": d["title"], "type": d["type"], "event_class": cls,
        "start_date": d["start_date"], "detected": bool(detected),
        "copilot_alert_date": alert_date, "copilot_lead_days": round(lead, 1),
        "team_alert_date": d["first_internal_alert_date"], "team_decision_day": int(d["days_from_impact_to_first_mitigation"]),
        "seen": {"mode": rec["mode"], "delay_estimate_days": float(basis.parts["effective_delay_days"].max()) if len(basis.parts) else None,
                 "revenue_at_risk_inr": basis.totals["revenue_at_risk_inr"], "skus_stopped": basis.totals["skus_stopped"],
                 "working": basis.working},
        "recommended": [{"part_id": r.part_id, "option": r.option, "cost_inr": r.cost_inr, "time_to_effect_days": r.time_to_effect_days,
                         "approver": r.approver, "p_works": r.p_works} for r in plan.itertuples()] if len(plan) else [],
        "top_options": rec["options"].head(5),
        "actual_delay_days": float(g["effective_delay_days"].max()),
        "actual_revenue_lost_inr": actual_lost,
        "actual_mitigation_cost_inr": float(d["mitigation_cost_inr_cr"]) * 1e7,
        "engine_unmitigated_lost_inr": unmit.totals["revenue_lost_inr"],
        "engine_team_lost_inr": team.totals["revenue_lost_inr"],
        "with_plan_lost_inr": withplan.totals["revenue_lost_inr"],
        "plan_cost_inr": cost, "plan_p_works": round(p, 2),
        "revenue_protected_if_works_inr": rev_prot_full,
        "revenue_protected_expected_inr": rev_prot_full * p,
        # Expected revenue protected vs what Veltrix actually lost: plan works with probability p, otherwise
        # the outcome is what happened. Not clipped: a worse-than-actual replay shows up as negative.
        "vs_actual_protected_expected_inr": (actual_lost - withplan.totals["revenue_lost_inr"]) * p if len(plan) else
                                            (actual_lost - withplan.totals["revenue_lost_inr"]) * 0.0,
        "margin_protected_inr": marg_prot, "penalties_avoided_inr": pen_prot,
        "roi": roi(marg_prot, pen_prot, cost) if cost > 0 else None,
        "avoided_waste_inr": avoided_waste, "team_wasted_inr": float(wasted["cost_inr"].sum()),
        "structural": struct,
    }


def replay_all() -> pd.DataFrame:
    db = load()
    rows = []
    for did in db["disruptions"]["disruption_id"]:
        r = replay(did)
        rows.append({k: v for k, v in r.items() if k not in ("seen", "recommended", "top_options", "structural")}
                    | {"structural_protected_inr": (r["structural"] or {}).get("revenue_protected_inr", 0.0)}
                    | {"top_action": "; ".join(f"{x['option']} ({x['part_id']})" for x in r["recommended"][:2]) or "No action"})
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame) -> dict:
    return {
        "actual_revenue_lost_cr": round(df["actual_revenue_lost_inr"].sum() / 1e7, 1),
        "revenue_protected_expected_cr": round(df["vs_actual_protected_expected_inr"].sum() / 1e7, 1),
        "plan_cost_cr": round(df["plan_cost_inr"].sum() / 1e7, 2),
        "margin_protected_cr": round(df["margin_protected_inr"].sum() / 1e7, 2),
        "penalties_avoided_cr": round(df["penalties_avoided_inr"].sum() / 1e7, 2),
        "avoided_waste_cr": round(df["avoided_waste_inr"].sum() / 1e7, 2),
        "team_wasted_cr": round(df["team_wasted_inr"].sum() / 1e7, 2),
        "roi_on_plans": round(roi(df["margin_protected_inr"].sum(), df["penalties_avoided_inr"].sum(),
                                  df["plan_cost_inr"].sum()), 1) if df["plan_cost_inr"].sum() else None,
    }


if __name__ == "__main__":
    r = replay("D05")
    print(f"{r['disruption_id']} {r['title']}: co-pilot alert {r['copilot_alert_date']} (lead {r['copilot_lead_days']} d) "
          f"vs team alert {r['team_alert_date'].date()} and first decision day +{r['team_decision_day']}")
    print("seen:", r["seen"]["mode"], r["seen"]["delay_estimate_days"], fmt_inr(r["seen"]["revenue_at_risk_inr"]))
    print("recommended:", r["recommended"])
    for k in ("actual_delay_days", "actual_revenue_lost_inr", "engine_unmitigated_lost_inr", "with_plan_lost_inr",
              "plan_cost_inr", "revenue_protected_if_works_inr", "revenue_protected_expected_inr",
              "vs_actual_protected_expected_inr", "margin_protected_inr", "roi"):
        v = r[k]
        print(f"  {k:36s} {fmt_inr(v) if k.endswith('_inr') else v}")
    df = replay_all()
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
    print(df[["disruption_id", "copilot_lead_days", "actual_revenue_lost_inr", "with_plan_lost_inr", "plan_cost_inr",
              "vs_actual_protected_expected_inr", "avoided_waste_inr", "top_action"]].assign(
        **{c: lambda x, c=c: (x[c] / 1e7).round(2) for c in ["actual_revenue_lost_inr", "with_plan_lost_inr", "plan_cost_inr",
                                                              "vs_actual_protected_expected_inr", "avoided_waste_inr"]}).to_string())
    print(summarise(df))

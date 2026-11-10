"""Validate the impact engine against D01–D18 (brief target: within ±25% of actual revenue lost).

Two modes:
  A. Method replay: history's parts, cover at start and effective delay, plus the team's actual
     mitigations taking effect at decision day + time-to-effect. This checks that the engine IS the
     playbook method. Expect near-exact.
  B. Forecast: the engine's own estimate. Effective delay comes from the event-type prior (fitted on train
     disruptions only) × the event's stated duration. Two variants:
       B1: assuming the team's actual mitigation timing (apples to apples with what happened).
       B2: assuming no mitigation ("revenue at risk" the alert would have shown on day one).
"""
from __future__ import annotations

import pandas as pd

from core.etl import load
from core.impact import DELAY_PRIORS, Scenario, estimate_delay, run

EVENT_CLASS = {
    "D01": "port_closure", "D02": "port_closure", "D03": "route", "D04": "trade_licensing",
    "D05": "supplier_outage", "D06": "congestion", "D07": "congestion", "D08": "supplier_outage",
    "D09": "congestion", "D10": "supplier_outage", "D11": "congestion", "D12": "supplier_outage",
    "D13": "congestion", "D14": "cost_only", "D15": "congestion", "D16": "congestion",
    "D17": "port_closure", "D18": "supplier_outage",
}
TRAIN = [f"D{i:02d}" for i in range(1, 14)]

# Days from decision to supply resuming, per action, calibrated on mitigation_actions × disruption_impacts.
TIME_TO_EFFECT = {
    "Broker spot buy": 4,                       # history median (playbook: 1–3 weeks)
    # Playbook says 5–10 days, but history shows switches only took hold ~19 days after the decision
    # (D18 PRT-026: shortage ended day 25.8, decided day 7; D10/D18 PRT-020 never took hold).
    # Alternate capacity ramps slowly. We use the observed value when replaying history.
    "Switch to qualified alternate supplier": 19,
    "Air-freight expedite": 4,                  # playbook 3–6 days
    "Re-route via alternate route": 14,         # booking immediate, but Cape adds 12–16 days
    "Qualify new supplier": None,               # = qualification_weeks_if_unqualified × 7
    "Pre-buy buffer stock (late)": None,        # arrives after the peak: no effect on shortage
    "Pay container surcharge / spot freight": None,
}


def fit_priors() -> pd.DataFrame:
    """Recompute the delay ratios from train disruptions, to check DELAY_PRIORS."""
    db = load()
    d = db["disruptions"].set_index("disruption_id")
    delay = db["disruption_impacts"].groupby("disruption_id")["effective_delay_days"].median()
    rows = []
    for did in TRAIN:
        dur = (d.loc[did, "end_date"] - d.loc[did, "start_date"]).days
        rows.append({"disruption_id": did, "class": EVENT_CLASS[did], "duration": dur,
                     "delay": delay[did], "ratio": delay[did] / dur if dur else None})
    f = pd.DataFrame(rows)
    return f.groupby("class").agg(ratio_median=("ratio", "median"), n=("ratio", "size")).round(2)


def _effect_days(did: str) -> dict:
    db = load()
    m = db["mitigation_actions"]
    parts = db["parts"].set_index("part_id")
    out = {}
    for r in m[(m["disruption_id"] == did) & m["had_shortage"]].itertuples():
        tte = TIME_TO_EFFECT.get(r.action)
        if r.action == "Qualify new supplier":
            w = parts.loc[r.part_id, "qualification_weeks_if_unqualified"]
            tte = None if pd.isna(w) else float(w) * 7
        if tte is None:
            continue
        day = r.days_from_impact_to_decision + tte
        out[r.part_id] = min(out.get(r.part_id, day), day)
    return out


def validate() -> pd.DataFrame:
    db = load()
    d = db["disruptions"].set_index("disruption_id")
    imp = db["disruption_impacts"]
    rows = []
    for did in d.index:
        g = imp[imp["disruption_id"] == did].drop_duplicates("part_id")
        parts = g["part_id"].tolist()
        cover = dict(zip(g["part_id"], g["days_of_cover_at_start"]))
        hist_delay = dict(zip(g["part_id"], g["effective_delay_days"]))
        dur = (d.loc[did, "end_date"] - d.loc[did, "start_date"]).days
        cls = EVENT_CLASS[did]
        eff = _effect_days(did)
        common = dict(parts=parts, cover_override=cover, use_fg=False, include_in_transit=False,
                      start_date=d.loc[did, "start_date"], event_type=cls, duration_days=dur)
        a = run(Scenario(delay_days=hist_delay, mitigation_effect_day=eff, **common)).totals
        b1 = run(Scenario(mitigation_effect_day=eff, **common)).totals
        b2 = run(Scenario(**common)).totals
        actual = float(d.loc[did, "revenue_lost_inr_cr"])
        rows.append({
            "disruption_id": did, "split": "train" if did in TRAIN else "test", "class": cls,
            "duration_days": dur, "delay_actual": float(g["effective_delay_days"].median()),
            "delay_predicted": estimate_delay(cls, float(dur)),
            "actual_cr": round(actual, 2),
            "A_method_cr": round(a["revenue_lost_inr"] / 1e7, 2),
            "B1_forecast_cr": round(b1["revenue_lost_inr"] / 1e7, 2),
            "B2_at_risk_no_action_cr": round(b2["revenue_lost_inr"] / 1e7, 2),
            "actual_units": int(d.loc[did, "units_short"]), "A_units": a["units_short"],
        })
    v = pd.DataFrame(rows)
    for col in ("A_method_cr", "B1_forecast_cr"):
        v[col.split("_")[0] + "_err_pct"] = ((v[col] - v["actual_cr"]) / v["actual_cr"] * 100).where(v["actual_cr"] > 0).round(1)
    return v


def summary(v: pd.DataFrame) -> dict:
    loss = v[v["actual_cr"] > 0]
    zero = v[v["actual_cr"] == 0]
    out = {}
    for m in ("A", "B1"):
        col = f"{m}_err_pct"
        val = "A_method_cr" if m == "A" else "B1_forecast_cr"
        out[m] = {
            "within_25pct": f"{int((loss[col].abs() <= 25).sum())}/{len(loss)} loss events",
            "median_abs_err_pct": float(loss[col].abs().median()),
            "total_predicted_cr": round(float(v[val].sum()), 1),
            "total_actual_cr": round(float(v["actual_cr"].sum()), 1),
            "zero_loss_correct": f"{int((zero[val] < 0.05).sum())}/{len(zero)} no-loss events",
        }
    return out


if __name__ == "__main__":
    import json
    print(fit_priors())
    print({k: v.get("ratio", v.get("fixed")) for k, v in DELAY_PRIORS.items()})
    v = validate()
    print(v.to_string())
    print(json.dumps(summary(v), indent=2))

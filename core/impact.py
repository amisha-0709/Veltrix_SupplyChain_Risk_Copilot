"""Impact engine: playbook §3, step for step, with its working shown.

    from core.impact import Scenario, run
    r = run(Scenario(nodes=["port:Kaohsiung"], event_type="port_closure", duration_days=10))
    r.totals, r.parts, r.skus, r.otif, r.working

Method (playbook §3), calibrated on disruption_impacts:
  1. Affected parts: every part whose primary supplier ships from / through the affected node(s).
  2. Effective delay = expected duration + recovery, reduced by the share of capacity still running.
     Recovery is an event-type ratio fitted on the train disruptions (see DELAY_PRIORS).
  3. Days of cover = (on hand + in-transit stock not caught by the event) / daily usage.
  4. Shortage days = max(0, min(delay, day a mitigation takes effect) − cover).
  5. SKU stops when any part is short: the binding part (largest shortage) sets the SKU's loss.
  6. Units short = SKU daily demand × shortage days, after finished-goods stock is used
     (optional: the history file does not net off FG, so back-tests run with use_fg=False).
  7. Revenue at risk = units short × price. 55% become lost sales, 45% ship late with penalties.
     Revenue lost = 55% × revenue at risk (matches disruption_impacts exactly).
     Margin at risk = revenue lost × contribution margin. Penalties = late units × price × penalty%/wk × weeks late.
  8. Weekly OTIF per customer recomputed with shortages; customers under their 95% target flagged.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from core.etl import load
from core.graph import build_network

LOST_SALE_SHARE = 0.55
SNAPSHOT_DATE = pd.Timestamp("2026-09-30")  # parts.inventory_on_hand / skus.finished_goods are as of this date

# Effective delay ÷ stated event duration, fitted on train disruptions D01–D13 (see validate_impact).
# "route" events don't scale with duration: goods take the alternate route and the lane's reroute penalty applies.
# default_duration = median train duration for the class (used when a signal gives no duration).
# stress = slowest recovery seen in train (ratio or fixed days): the "if it runs long" case.
DELAY_PRIORS: dict[str, dict] = {
    "port_closure":     {"ratio": 1.45, "stress": 1.6, "default_duration": 7.5,
                         "label": "Port / city closure (weather)", "fit_on": ["D01", "D02"]},
    "supplier_outage":  {"ratio": 1.41, "stress": 1.95, "default_duration": 31.5,
                         "label": "Supplier outage (fire, quake, strike, insolvency, cyber)",
                         "fit_on": ["D05", "D08", "D10", "D12"]},
    "trade_licensing":  {"ratio": 0.88, "stress": 1.2, "default_duration": 49,
                         "label": "Export licensing / control", "fit_on": ["D04"]},
    # Congestion adds a roughly fixed wait, not one proportional to how long the event lasts:
    # train delays were 9.4, 6.0, 3.6, 3.0, 7.0 d for events of 14, 4, 6, 3, 18 d. Median 6 d, capped at 1.5× duration.
    "congestion":       {"fixed": 6.0, "stress_fixed": 9.4, "cap_ratio": 1.5, "default_duration": 6,
                         "label": "Port congestion, logistics, domestic transport, systems",
                         "fit_on": ["D06", "D07", "D09", "D11", "D13"]},
    "route":            {"fixed": 14.0, "stress_fixed": 16.0, "default_duration": 70,
                         "label": "Chokepoint closed: reroute (lane penalty)", "fit_on": ["D03"]},
    "cost_only":        {"ratio": 0.0, "stress": 0.0, "default_duration": 0,
                         "label": "Duty / tariff: cost impact, no delay", "fit_on": []},
}


def estimate_delay(event_type: str, duration_days: float | None, running_share: float = 0.0,
                   stress: bool = False) -> float:
    p = DELAY_PRIORS[event_type]
    if duration_days is not None and math.isnan(float(duration_days)):
        duration_days = None
    dur = p["default_duration"] if duration_days is None else duration_days
    if "fixed" in p:
        base = p["stress_fixed"] if stress else p["fixed"]
    else:
        base = (p["stress"] if stress else p["ratio"]) * dur
    if "cap_ratio" in p:
        base = min(base, p["cap_ratio"] * dur)
    return round(base * (1 - running_share), 1)


@dataclass
class Scenario:
    nodes: list[str] = field(default_factory=list)       # graph nodes, e.g. "port:Kaohsiung"
    parts: list[str] | None = None                        # or an explicit part list (overrides nodes)
    match: str = "any"                                    # "all" = intersect node exposures (e.g. Shenzhen ∩ PCBs)
    event_type: str = "port_closure"
    duration_days: float | None = None                    # None = class default (signal gave no duration)
    delay_days: float | dict | None = None                # override the prior (one value or per part)
    stress: bool = False                                  # use the slowest-recovery ratio seen in history
    running_share: float = 0.0                            # share of capacity that keeps running
    start_date: pd.Timestamp | str | None = None          # impact start (default: snapshot date)
    cover_override: dict | None = None                    # part_id -> days of cover (back-tests)
    include_in_transit: bool = True
    mitigation_effect_day: dict | None = None             # part_id -> day (from impact start) supply resumes
    use_fg: bool = True
    label: str = ""


@dataclass
class ImpactResult:
    scenario: Scenario
    parts: pd.DataFrame
    skus: pd.DataFrame
    otif: pd.DataFrame
    totals: dict
    working: list[str]

    def to_dict(self) -> dict:
        import json
        rec = lambda df: json.loads(df.to_json(orient="records", date_format="iso"))  # noqa: E731
        return {"totals": self.totals, "parts": rec(self.parts), "skus": rec(self.skus),
                "otif": rec(self.otif), "working": self.working}


# ---------------------------------------------------------------------------------------------
def affected_parts(sc: Scenario) -> list[str]:
    if sc.parts is not None:
        return list(sc.parts)
    net = build_network()
    sets = [net.parts_exposed(n) for n in sc.nodes]
    if not sets:
        return []
    out = set.intersection(*sets) if sc.match == "all" else set.union(*sets)
    return sorted(out)


def _catches_in_transit(sc: Scenario) -> bool:
    """Goods already on the water are stuck if the event sits on the route or at the destination."""
    return any(n.startswith(("choke:", "dest:", "lane:")) for n in sc.nodes)


def in_transit_units(as_of: pd.Timestamp) -> pd.Series:
    sh = load()["shipments"]
    m = (sh["ship_date"] <= as_of) & (sh["actual_arrival"].fillna(sh["planned_arrival"]) > as_of)
    return sh.loc[m].groupby("part_id")["quantity_units"].sum()


def _baseline_otif() -> pd.Series:
    wd = load()["weekly_demand"]
    return wd.loc[wd["units_short"] == 0].groupby("sku_id")["otif_pct"].mean()


def run(sc: Scenario) -> ImpactResult:
    db = load()
    parts = db["parts"].set_index("part_id")
    skus = db["skus"].set_index("sku_id")
    bom = db["bom"]
    start = pd.Timestamp(sc.start_date) if sc.start_date is not None else SNAPSHOT_DATE
    W: list[str] = []

    pids = affected_parts(sc)
    W.append(f"1. Affected parts: {len(pids)} part(s) whose primary supplier ships from/through "
             f"{', '.join(sc.nodes) if sc.parts is None else 'the given list'}.")

    # 2. effective delay
    if isinstance(sc.delay_days, dict):
        delay = {p: float(sc.delay_days.get(p, 0.0)) for p in pids}
        W.append("2. Effective delay: given per part.")
    elif sc.delay_days is not None:
        delay = {p: float(sc.delay_days) * (1 - sc.running_share) for p in pids}
        W.append(f"2. Effective delay: {sc.delay_days} d given"
                 + (f", × (1 − {sc.running_share:.0%} capacity running)" if sc.running_share else "") + ".")
    else:
        d = estimate_delay(sc.event_type, sc.duration_days, sc.running_share, sc.stress)
        delay = {p: d for p in pids}
        pr = DELAY_PRIORS[sc.event_type]
        no_dur = sc.duration_days is None or math.isnan(float(sc.duration_days))
        dur = pr["default_duration"] if no_dur else sc.duration_days
        dur_txt = (f"{dur:g} d (no duration stated; class default)" if no_dur
                   else f"{dur:g} d")
        tag = "STRESS case, slowest recovery seen in history: " if sc.stress else ""
        if sc.event_type == "route":
            how = f"{tag}lane reroute penalty {pr['stress_fixed' if sc.stress else 'fixed']:.0f} d"
        elif "fixed" in pr:
            how = (f"{tag}typical {pr['label'].lower()} wait {pr['stress_fixed' if sc.stress else 'fixed']:g} d "
                   f"(capped at {pr.get('cap_ratio', 1)}× the {dur_txt} duration)")
        else:
            how = (f"{tag}{dur_txt} duration × {pr['stress' if sc.stress else 'ratio']} recovery ratio "
                   f"({pr['label'].lower()})")
        W.append(f"2. Effective delay: {how}"
                 + (f" × (1 − {sc.running_share:.0%} running)" if sc.running_share else "") + f" = {d} d.")

    # 3. cover
    transit = in_transit_units(start) if sc.include_in_transit else pd.Series(dtype=float)
    caught = _catches_in_transit(sc)
    rows = []
    for p in pids:
        pr = parts.loc[p]
        daily = pr["avg_weekly_usage_units"] / 7
        if sc.cover_override and p in sc.cover_override:
            cover, src = float(sc.cover_override[p]), "given"
            it_units = 0.0
        else:
            it_units = 0.0 if caught else float(transit.get(p, 0.0))
            cover = (pr["inventory_on_hand_units"] + it_units) / daily
            src = "on hand + in transit" if it_units else "on hand"
        eff = (sc.mitigation_effect_day or {}).get(p)
        end = min(delay[p], eff) if eff is not None else delay[p]
        shortage = max(0.0, end - cover)
        rows.append({
            "part_id": p, "description": pr["description"], "category": pr["category"],
            "primary_supplier_id": pr["primary_supplier_id"], "single_source": bool(pr["single_source"]),
            "qualified_alt": pr["qualified_alternate_supplier_id"],
            "unqualified_alt": pr["unqualified_alternate_supplier_id"],
            "daily_usage": round(daily, 1), "in_transit_units": it_units, "cover_source": src,
            "days_of_cover": round(cover, 1), "effective_delay_days": round(delay[p], 1),
            "mitigation_effect_day": eff, "shortage_days": round(shortage, 1),
            "shortage_starts_day": round(cover, 1) if shortage > 0 else None,
        })
    P = pd.DataFrame(rows)
    if P.empty:
        P = pd.DataFrame(columns=["part_id", "shortage_days", "days_of_cover", "effective_delay_days"])
    short = P[P["shortage_days"] > 0]
    W.append(f"3. Days of cover = (on hand{'' if caught else ' + in-transit not caught'}) ÷ daily usage"
             + (" (in-transit stock is caught on this route)" if caught else "") + ".")
    W.append(f"4. Shortage = max(0, delay − cover): {len(short)} of {len(P)} part(s) run short"
             + (f"; worst {short['shortage_days'].max():.1f} d ({short.loc[short['shortage_days'].idxmax(), 'part_id']})."
                if len(short) else ". Cover is enough: no shortage, no action needed."))

    # 5–7. SKUs via BOM, binding part
    sk_rows = []
    b = bom[bom["part_id"].isin(P["part_id"])].merge(P[["part_id", "shortage_days", "days_of_cover"]], on="part_id")
    for sku, g in b.groupby("sku_id"):
        top = g.sort_values(["shortage_days", "days_of_cover"], ascending=[False, True]).iloc[0]
        s = skus.loc[sku]
        daily = s["avg_weekly_demand_units"] / 7
        sd = float(top["shortage_days"])
        fg_units = float(s["finished_goods_on_hand_units"]) if sc.use_fg else 0.0
        fg_days = fg_units / daily if daily else 0.0
        units = max(0.0, daily * sd - fg_units) if sd > 0 else 0.0
        eff_sd = units / daily if daily else 0.0
        rev_risk = units * s["price_inr"]
        rev_lost = LOST_SALE_SHARE * rev_risk
        late_units = (1 - LOST_SALE_SHARE) * units
        weeks_late = max(1, math.ceil(eff_sd / 14)) if units > 0 else 0
        penalty = late_units * s["price_inr"] * s["late_delivery_penalty_pct_per_week"] / 100 * weeks_late
        sk_rows.append({
            "sku_id": sku, "sku_name": s["sku_name"], "customer": s["primary_customer"], "plant": s["plant"],
            "binding_part": top["part_id"], "parts_affected": int(len(g)),
            "shortage_days": round(sd, 1), "fg_days_used": round(min(fg_days, sd), 1) if sd else 0.0,
            "stops_from_day": round(float(top["days_of_cover"]) + (fg_days if sc.use_fg else 0), 1) if units > 0 else None,
            "units_short": round(units), "price_inr": s["price_inr"],
            "revenue_at_risk_inr": round(rev_risk), "revenue_lost_inr": round(rev_lost),
            "margin_at_risk_inr": round(rev_lost * s["unit_margin_pct"]),
            "late_units": round(late_units), "penalty_inr": round(penalty),
            "unit_margin_pct": s["unit_margin_pct"],
        })
    S = pd.DataFrame(sk_rows)
    if not S.empty:
        S = S.sort_values(["revenue_at_risk_inr", "shortage_days"], ascending=False).reset_index(drop=True)
    stopped = S[S["units_short"] > 0] if not S.empty else S
    W.append(f"5. Map to SKUs through the BOM: {len(S)} SKU(s) use an affected part; {len(stopped)} stop "
             f"(binding part = the one with the largest shortage).")
    W.append("6. Units short = SKU daily demand × shortage days"
             + (" − finished-goods stock." if sc.use_fg else " (finished goods not netted, history convention)."))
    W.append(f"7. Revenue at risk = units × price; {LOST_SALE_SHARE:.0%} lost sales → revenue lost; "
             f"margin at risk = revenue lost × contribution margin; {1-LOST_SALE_SHARE:.0%} late → contract penalties.")

    # 8. OTIF by customer and week
    O = _otif_table(S, start) if not S.empty else pd.DataFrame()
    below = O[O["below_target"]] if not O.empty else O
    W.append(f"8. Weekly OTIF recomputed per customer: "
             + (f"{below['customer'].nunique()} customer(s) fall below 95% in {below['week_start'].nunique()} week(s)."
                if len(below) else "no customer falls below the 95% target."))

    tot = {
        "label": sc.label, "start_date": start.date().isoformat(), "event_type": sc.event_type,
        "parts_affected": int(len(P)), "parts_short": int(len(short)),
        "skus_exposed": int(len(S)), "skus_stopped": int(len(stopped)),
        "max_shortage_days": float(short["shortage_days"].max()) if len(short) else 0.0,
        "min_cover_days": float(P["days_of_cover"].min()) if len(P) else None,
        "units_short": int(S["units_short"].sum()) if len(S) else 0,
        "revenue_at_risk_inr": float(S["revenue_at_risk_inr"].sum()) if len(S) else 0.0,
        "revenue_lost_inr": float(S["revenue_lost_inr"].sum()) if len(S) else 0.0,
        "margin_at_risk_inr": float(S["margin_at_risk_inr"].sum()) if len(S) else 0.0,
        "penalty_inr": float(S["penalty_inr"].sum()) if len(S) else 0.0,
        "customers_below_otif": sorted(below["customer"].unique().tolist()) if len(below) else [],
        # What's exposed even if cover holds: daily revenue of every SKU that uses an affected part.
        "revenue_exposed_per_day_inr": float(sum(
            skus.loc[s, "avg_weekly_demand_units"] / 7 * skus.loc[s, "price_inr"] for s in S["sku_id"])) if len(S) else 0.0,
        "parts_not_in_any_bom": sorted(set(P["part_id"]) - set(bom["part_id"])) if len(P) else [],
        "stress": sc.stress,
        # Action is needed only if customers would actually be short (after finished goods).
        "no_action_needed": (int(S["units_short"].sum()) if len(S) else 0) == 0,
    }
    return ImpactResult(sc, P, S, O, tot, W)


def _otif_table(S: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    """Weekly OTIF per customer over the disruption horizon, with shortages placed on the calendar."""
    db = load()
    skus = db["skus"].set_index("sku_id")
    base = _baseline_otif()
    horizon = int(max(28, (S["stops_from_day"].fillna(0) + S["shortage_days"]).max() + 7))
    wk0 = start - pd.Timedelta(days=start.weekday())
    weeks = pd.date_range(wk0, start + pd.Timedelta(days=horizon), freq="7D")
    short_by_sku = {r.sku_id: r for r in S.itertuples() if r.units_short > 0}
    rows = []
    for cust, cs in skus.groupby("primary_customer"):
        for w in weeks:
            dem = ok = 0.0
            for sku, s in cs.iterrows():
                d = s["avg_weekly_demand_units"]
                lost = 0.0
                r = short_by_sku.get(sku)
                if r is not None:
                    a = start + pd.Timedelta(days=r.stops_from_day)
                    e = a + pd.Timedelta(days=r.units_short / (d / 7))
                    overlap = (min(e, w + pd.Timedelta(days=7)) - max(a, w)).total_seconds() / 86400
                    lost = max(0.0, overlap) * d / 7
                dem += d
                ok += base.get(sku, 0.97) * (d - min(lost, d))
            rows.append({"customer": cust, "week_start": w.date().isoformat(),
                         "otif": round(ok / dem, 3), "below_target": ok / dem < 0.95})
    O = pd.DataFrame(rows)
    hit = O.groupby("customer")["below_target"].transform("any") | O["customer"].isin(S["customer"])
    return O[hit].reset_index(drop=True)


def fmt_inr(v: float) -> str:
    """₹ in lakh/crore, the way the team talks."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if abs(v) >= 1e7:
        return f"₹{v/1e7:,.2f} cr"
    if abs(v) >= 1e5:
        return f"₹{v/1e5:,.1f} lakh"
    return f"₹{v:,.0f}"


if __name__ == "__main__":
    r = run(Scenario(nodes=["port:Kaohsiung"], event_type="port_closure", duration_days=10,
                     label="Kaohsiung closes 10 days"))
    print("\n".join(r.working))
    print(r.parts[["part_id", "description", "days_of_cover", "effective_delay_days", "shortage_days"]].to_string())
    print(r.skus[["sku_id", "customer", "binding_part", "shortage_days", "units_short", "revenue_at_risk_inr",
                  "margin_at_risk_inr", "penalty_inr"]].to_string())
    print({k: (fmt_inr(v) if k.endswith("_inr") else v) for k, v in r.totals.items()})


def inbound_shipments(links, parts: pd.DataFrame, as_of: pd.Timestamp | None = None) -> list[dict]:
    """Shipments already on the way into a port or through a chokepoint the event sits on (brief T7).

    Due dates are the PLANNED arrival (what is known on the stock date). Each shipment is held up by its part's
    effective delay; because the event catches it, the part's cover is on-hand stock only, as in the engine.
    """
    as_of = SNAPSHOT_DATE if as_of is None else pd.Timestamp(as_of)
    dests = [n.split(":", 1)[1] for n in links if n.startswith("dest:")]
    chokes = [n.split(":", 1)[1] for n in links if n.startswith("choke:")]
    if not dests and not chokes:
        return []
    db = load()
    sh = db["shipments"]
    lanes = db["lanes"]
    m = (sh["ship_date"] <= as_of) & (sh["actual_arrival"].fillna(sh["planned_arrival"]) > as_of)
    lane_ids = set(lanes.loc[lanes["chokepoint"].isin(chokes), "lane_id"]) if chokes else set()
    m &= sh["destination"].isin(dests) | sh["lane_id"].isin(lane_ids)
    P = parts.set_index("part_id") if len(parts) else parts
    rows = []
    for r in sh.loc[m].sort_values("planned_arrival").itertuples():
        delay = float(P.loc[r.part_id, "effective_delay_days"]) if r.part_id in P.index else None
        cover = float(P.loc[r.part_id, "days_of_cover"]) if r.part_id in P.index else None
        rows.append({
            "shipment_id": r.shipment_id, "part_id": r.part_id, "origin_port": r.origin_port, "destination": r.destination,
            "planned_arrival": r.planned_arrival.date().isoformat(), "due_in_days": (r.planned_arrival - as_of).days,
            "units": int(r.quantity_units), "value_inr": float(r.value_inr), "held_up_days": delay, "cover_days": cover,
            "verdict": (None if delay is None or cover is None else
                        "cover holds" if cover >= delay else f"part short {delay - cover:.1f} d"),
        })
    return rows

"""Stage-1 exposure analysis: where Veltrix is fragile, and how much revenue sits behind each node.

"Revenue dependent" on a part = annual revenue of every SKU that needs it (a SKU stops when
any one part is short, so the whole SKU revenue is at stake, not a share of it).
"""
from __future__ import annotations

import pandas as pd

from core.etl import load
from core.graph import build_network


def part_exposure() -> pd.DataFrame:
    db, net = load(), build_network()
    parts, sup, skus, bom = db["parts"], db["suppliers"], db["skus"], db["bom"]
    rev = skus.set_index("sku_id")["annual_revenue_inr"]

    df = parts.merge(sup[["supplier_id", "supplier_name", "country", "region", "port_of_loading",
                          "on_time_rate_last_12m", "financial_health_score"]],
                     left_on="primary_supplier_id", right_on="supplier_id", how="left")
    sku_map = bom.groupby("part_id")["sku_id"].apply(lambda s: sorted(set(s)))
    df["skus"] = df["part_id"].map(sku_map).apply(lambda v: v if isinstance(v, list) else [])
    df["n_skus"] = df["skus"].str.len()
    df["customers"] = df["skus"].apply(
        lambda ss: sorted(set(skus.set_index("sku_id").loc[ss, "primary_customer"])) if ss else [])
    df["revenue_dependent_inr_cr"] = df["skus"].apply(lambda ss: rev.reindex(ss).sum() / 1e7)
    df["cover_gap_days"] = df["lead_time_days"] - df["days_of_cover"]
    df["has_unqualified_alt"] = df["unqualified_alternate_supplier_id"].notna()
    # Simple fragility rank for Stage 1: single source × cover gap × revenue behind it.
    df["fragility"] = (df["single_source"].astype(int)
                       * df["cover_gap_days"].clip(lower=0)
                       * df["revenue_dependent_inr_cr"])
    cols = ["part_id", "description", "category", "single_source", "primary_supplier_id",
            "supplier_name", "country", "region", "port_of_loading", "days_of_cover",
            "lead_time_days", "cover_gap_days", "cover_below_lead_time",
            "qualified_alternate_supplier_id", "unqualified_alternate_supplier_id",
            "qualification_weeks_if_unqualified", "annual_spend_inr_cr", "n_skus", "skus",
            "customers", "revenue_dependent_inr_cr", "on_time_rate_last_12m",
            "financial_health_score", "fragility"]
    return df[cols].sort_values("fragility", ascending=False).reset_index(drop=True)


def node_concentration(kind: str) -> pd.DataFrame:
    """Revenue and spend that depend on each port / country / chokepoint / category."""
    db, net = load(), build_network()
    parts = db["parts"].set_index("part_id")
    rev = db["skus"].set_index("sku_id")["annual_revenue_inr"]
    rows = []
    for n, d in net.G.nodes(data=True):
        if d.get("type") != kind:
            continue
        ps = net.parts_exposed(n)
        if not ps:
            continue
        ss = net.skus_using(ps)
        single = [p for p in ps if parts.loc[p, "single_source"]]
        ss_single = net.skus_using(single)
        rows.append({
            "node": d.get("name", n), "parts": len(ps), "single_source_parts": len(single),
            "skus": len(ss),
            "spend_inr_cr": parts.loc[list(ps), "annual_spend_inr_cr"].sum(),
            "revenue_dependent_inr_cr": rev.reindex(list(ss)).sum() / 1e7,
            "revenue_behind_single_source_inr_cr": rev.reindex(list(ss_single)).sum() / 1e7,
            "min_cover_single_source": (parts.loc[single, "days_of_cover"].min() if single else None),
        })
    return (pd.DataFrame(rows).sort_values("revenue_behind_single_source_inr_cr", ascending=False)
            .reset_index(drop=True))


def headline_checks() -> dict:
    """Recompute the brief's headline numbers so we know our joins are right."""
    db = load()
    parts, sup = db["parts"], db["suppliers"]
    p = parts.merge(sup[["supplier_id", "region"]], left_on="primary_supplier_id",
                    right_on="supplier_id", how="left")
    ss = p[p["single_source"]]
    total = p["annual_spend_inr_cr"].sum()
    d, imp = db["disruptions"], db["disruption_impacts"]
    single_rev = imp.loc[imp["single_source"], "revenue_lost_inr"].sum()
    # Note: disruption_impacts.revenue_lost_inr counts every short unit; disruptions.revenue_lost_inr_cr
    # applies the 55% lost-sale share. We report both.
    m = db["mitigation_actions"]
    return {
        "suppliers": len(sup), "countries": sup["country"].nunique(), "parts": len(parts),
        "skus": len(db["skus"]),
        "single_source_parts": int(parts["single_source"].sum()),
        "single_source_cover_below_lead": int((ss["days_of_cover"] < ss["lead_time_days"]).sum()),
        "single_source_median_cover": round(float(ss["days_of_cover"].median()), 1),
        "single_source_median_lead": float(ss["lead_time_days"].median()),
        "material_spend_inr_cr": round(float(total), 1),
        "east_asia_spend_pct": round(100 * p.loc[p["region"] == "East Asia", "annual_spend_inr_cr"].sum() / total, 1),
        "east_or_se_asia_spend_pct": round(100 * p.loc[p["region"].isin(["East Asia", "South-East Asia"]),
                                                       "annual_spend_inr_cr"].sum() / total, 1),
        "single_source_spend_pct": round(100 * ss["annual_spend_inr_cr"].sum() / total, 1),
        "disruptions": len(d),
        "disruptions_with_stoppage": int((d["units_short"] > 0).sum()),
        "revenue_lost_inr_cr": round(float(d["revenue_lost_inr_cr"].sum()), 1),
        "lost_revenue_via_single_source_pct": round(100 * single_rev / imp["revenue_lost_inr"].sum(), 1),
        "median_days_impact_to_decision": float(d["days_from_impact_to_first_mitigation"].median()),
        "mitigation_spend_inr_cr": round(float(m["cost_inr"].sum()) / 1e7, 2),
        "mitigation_spend_no_shortage_inr_cr": round(float(m.loc[~m["had_shortage"], "cost_inr"].sum()) / 1e7, 2),
        "weeks_with_shortage": int((db["weekly_demand"].groupby("week_start")["units_short"].sum() > 0).sum()),
        # The brief's "OTIF fell as low as 63.5%" = units shipped ÷ units demanded, all SKUs, per week.
        "min_weekly_otif_pct": round(100 * float(
            (db["weekly_demand"].groupby("week_start")
             .apply(lambda g: g.units_shipped.sum() / g.customer_demand_units.sum(),
                    include_groups=False)).min()), 1),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(headline_checks(), indent=2))
    pe = part_exposure()
    print(pe.loc[pe.single_source, ["part_id", "description", "port_of_loading", "days_of_cover",
                                    "lead_time_days", "n_skus", "revenue_dependent_inr_cr"]]
          .head(12).to_string())
    for k in ("port", "country", "choke", "cat"):
        print(f"\n== {k}")
        print(node_concentration(k).head(8).round(1).to_string())

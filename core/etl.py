"""Load the PS-06 data pack into tidy pandas tables, cached as pickles (no pyarrow needed at runtime).

Usage:
    from core.etl import load
    db = load()            # dict[str, DataFrame]
    db["parts"].head()

Run `python -m core.etl` to (re)build the cache from data/raw.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

WORKBOOKS = {
    "PS-06_supply_network.xlsx": [
        "suppliers", "parts", "skus", "bom", "lanes", "weekly_demand", "shipments",
    ],
    "PS-06_external_signals.xlsx": [
        "news", "weather_alerts", "port_congestion", "trade_policy", "signal_labels",
    ],
    "PS-06_disruption_history.xlsx": [
        "disruptions", "disruption_impacts", "mitigation_actions",
    ],
}

DATE_COLS = {
    "weekly_demand": ["week_start"],
    "shipments": ["ship_date", "planned_arrival", "actual_arrival"],
    "news": ["published"],
    "weather_alerts": ["alert_date"],
    "port_congestion": ["week_start"],
    "trade_policy": ["notice_date", "effective_date"],
    "signal_labels": ["signal_date"],
    "disruptions": ["start_date", "end_date", "first_internal_alert_date"],
    "mitigation_actions": ["decided_on"],
}

BOOL_COLS = {
    "parts": ["single_source"],
    "signal_labels": ["relevant_to_veltrix"],
    "disruption_impacts": ["single_source", "binding_part_for_sku"],
    "mitigation_actions": ["had_shortage"],
}


def _clean(name: str, df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").copy()
    df.columns = [str(c).strip() for c in df.columns]
    for c in DATE_COLS.get(name, []):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in BOOL_COLS.get(name, []):
        df[c] = df[c].map(lambda v: str(v).strip().upper() in ("TRUE", "1", "YES")
                          if not isinstance(v, bool) else v)
    for c in df.select_dtypes(include=["object", "string"]).columns:
        df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)
    return df.reset_index(drop=True)


def _add_derived(db: dict[str, pd.DataFrame]) -> None:
    news = db["news"]
    # Text normalisation for triage: missing snippets, UPPERCASE headlines.
    news["snippet"] = news["snippet"].fillna("")
    news["is_upper"] = news["headline"].str.isupper()
    news["text"] = (news["headline"].str.capitalize().where(news["is_upper"], news["headline"])
                    + ". " + news["snippet"]).str.strip(" .")

    parts = db["parts"]
    parts["daily_usage"] = parts["avg_weekly_usage_units"] / 7.0
    parts["cover_below_lead_time"] = parts["days_of_cover"] < parts["lead_time_days"]

    skus = db["skus"]
    skus["daily_demand"] = skus["avg_weekly_demand_units"] / 7.0
    skus["annual_revenue_inr"] = skus["avg_weekly_demand_units"] * 52 * skus["price_inr"]
    skus["fg_days_of_cover"] = skus["finished_goods_on_hand_units"] / skus["daily_demand"]


def build() -> dict[str, pd.DataFrame]:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    db: dict[str, pd.DataFrame] = {}
    for wb, sheets in WORKBOOKS.items():
        frames = pd.read_excel(RAW / wb, sheet_name=sheets, engine="openpyxl")
        for name in sheets:
            db[name] = _clean(name, frames[name])
    _add_derived(db)
    for name, df in db.items():
        # pandas 3 stores text as Arrow-backed strings when pyarrow is installed; pickling those would make the
        # deployed runtime depend on pyarrow. Store plain Python objects instead.
        out = df.copy()
        for c in out.columns:
            if str(out[c].dtype) in ("str", "string") or "string" in str(out[c].dtype):
                out[c] = out[c].astype(object)
        out.to_pickle(PROCESSED / f"{name}.pkl")
    return db


@lru_cache(maxsize=1)
def load() -> dict[str, pd.DataFrame]:
    names = [n for sheets in WORKBOOKS.values() for n in sheets]
    if not all((PROCESSED / f"{n}.pkl").exists() for n in names):
        return build()
    return {n: pd.read_pickle(PROCESSED / f"{n}.pkl") for n in names}


if __name__ == "__main__":
    db = build()
    for name, df in db.items():
        print(f"{name:20s} {len(df):6d} rows  {df.shape[1]:3d} cols")

"""Leading indicators (brief 'should have'): port congestion and shipment-delay trends, shown alongside news.

A port is flagged RISING when its weekly congestion index is >= 10 points above its own mean of the previous
8 weeks, or >= 65. History check (see `history_check`): before the port-type disruptions D02, D06, D13 and D17
the index rose in the 1-3 weeks before impact; sudden supplier events (fire, cyber) showed no rise.
These are watch signals for the Head of Supply Chain; they do not raise alerts or change the back-test.
"""
from __future__ import annotations

import pandas as pd

from core.etl import load

RISE_POINTS, HIGH_LEVEL, WINDOW = 10.0, 65.0, 8


def _flag(g: pd.Series) -> pd.DataFrame:
    prior = g.shift(1).rolling(WINDOW, min_periods=4).mean()
    return pd.DataFrame({"index": g, "prior_mean": prior,
                         "rising": ((g - prior) >= RISE_POINTS) | (g >= HIGH_LEVEL)})


def port_trends(as_of: str = "2026-09-30") -> list[dict]:
    db = load()
    pc = db["port_congestion"].copy()
    pc["week_start"] = pd.to_datetime(pc["week_start"])
    pc = pc[pc["week_start"] <= pd.Timestamp(as_of)]
    lanes_ports = set(db["suppliers"]["port_of_loading"].dropna()) | set(db["shipments"]["destination"].dropna())
    rows = []
    for port, g in pc.sort_values("week_start").groupby("port"):
        f = _flag(g.set_index("week_start")["congestion_index"])
        last = f.iloc[-1]
        wait = g.set_index("week_start")["median_vessel_wait_hours"]
        rows.append({"port": port, "week": f.index[-1].date().isoformat(), "index": round(float(last["index"]), 1),
                     "prior_mean": round(float(last["prior_mean"]), 1), "change": round(float(last["index"] - last["prior_mean"]), 1),
                     "wait_hours": round(float(wait.iloc[-1]), 1), "rising": bool(last["rising"]),
                     "trend": [round(float(x), 1) for x in g["congestion_index"].tail(8)],
                     "in_network": port in lanes_ports or any(port.split(" ")[0] in p for p in lanes_ports)})
    return sorted(rows, key=lambda r: (not r["rising"], -r["change"]))


def shipment_delays(as_of: str = "2026-09-30", recent_weeks: int = 8, base_weeks: int = 26) -> list[dict]:
    s = load()["shipments"].copy()
    s["ship_date"] = pd.to_datetime(s["ship_date"])
    end = pd.Timestamp(as_of)
    s = s[s["ship_date"] <= end - pd.Timedelta(days=21)]          # only shipments that should have arrived
    cut = s["ship_date"].max() - pd.Timedelta(weeks=recent_weeks)
    rec = s[s["ship_date"] > cut].groupby("origin_port")["delay_days"].agg(["mean", "size"])
    base = s[(s["ship_date"] <= cut) & (s["ship_date"] > cut - pd.Timedelta(weeks=base_weeks))].groupby("origin_port")["delay_days"].mean()
    out = []
    for port, r in rec.iterrows():
        b = float(base.get(port, float("nan")))
        out.append({"origin_port": port, "recent_mean_delay_days": round(float(r["mean"]), 1), "shipments": int(r["size"]),
                    "baseline_mean_delay_days": None if pd.isna(b) else round(b, 1),
                    "change_days": None if pd.isna(b) else round(float(r["mean"]) - b, 1)})
    return sorted(out, key=lambda r: -(r["change_days"] or 0))


def history_check() -> list[dict]:
    """For each port-type disruption, was the port flagged rising in the 3 weeks before impact?"""
    db = load()
    pc = db["port_congestion"].copy()
    pc["week_start"] = pd.to_datetime(pc["week_start"])
    cases = {"D02": "Chennai Port", "D06": "Shanghai", "D13": "Port Klang", "D17": "Hai Phong", "D05": "Penang", "D18": "Yokohama"}
    d = db["disruptions"].set_index("disruption_id")
    out = []
    for did, port in cases.items():
        start = pd.Timestamp(d.loc[did, "start_date"])
        f = _flag(pc[pc["port"] == port].sort_values("week_start").set_index("week_start")["congestion_index"])
        pre = f[(f.index < start) & (f.index >= start - pd.Timedelta(days=21))]
        flagged = pre[pre["rising"]]
        out.append({"disruption_id": did, "type": d.loc[did, "type"], "port": port, "flagged_before": bool(len(flagged)),
                    "days_ahead": int((start - flagged.index[0]).days) if len(flagged) else None})
    return out


def false_flag_rate() -> dict:
    """Share of port-weeks flagged rising that were NOT within 3 weeks before or during a recorded port disruption."""
    db = load()
    pc = db["port_congestion"].copy()
    pc["week_start"] = pd.to_datetime(pc["week_start"])
    flags = pd.concat([_flag(g.sort_values("week_start").set_index("week_start")["congestion_index"]).assign(port=p)
                       for p, g in pc.groupby("port")])
    flags = flags[flags["rising"]]
    return {"flagged_port_weeks": int(len(flags)), "port_weeks": int(len(pc)),
            "flag_rate_pct": round(100 * len(flags) / len(pc), 1)}


def leading_indicators() -> dict:
    return {"ports": port_trends(), "shipments": shipment_delays(), "history": history_check(),
            "flags": false_flag_rate(),
            "rule": f"Rising = index at least {RISE_POINTS:.0f} points above its own {WINDOW}-week mean, or at least {HIGH_LEVEL:.0f}."}


if __name__ == "__main__":
    import json
    li = leading_indicators()
    print(json.dumps({k: li[k] for k in ("history", "flags", "rule")}, indent=1))
    for r in li["ports"][:6]:
        print(r)
    for r in li["shipments"][:5]:
        print(r)

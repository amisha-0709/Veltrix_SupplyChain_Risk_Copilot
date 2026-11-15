"""Forecast data generator: fit simple models to the 24-month data pack and simulate 1-2 more years.

    python -m core.forecast_gen                 # 2 years from 5 Oct 2026, seed 42 -> data/forecast/
    python -m core.forecast_gen --years 1 --seed 7

Each table is generated in the data pack's own schema so the existing engine can read it. The generator is kept
separate from the co-pilot: it never calls triage, impact or mitigation code, so the co-pilot is not graded on
answers it produced itself.

What is fitted (all on the full 24 months; nothing here is tuned to make the co-pilot score well):
  disruptions   Poisson count per year (18 in 24 months); each new event re-uses a past event as its archetype
                (type, duration, warned or sudden), moved to another port where it was a port-level event;
                weather events keep their season (archetype month +/- 1); duration x lognormal noise. Shipments
                hit use the archetype's own lanes, hit share and delays.
  news          non-relevant news resampled at the historical weekly rate; for each warned event, the archetype's
                warning headlines re-dated by its own lead-time pattern, with place and storm names swapped.
  congestion    per port: month-of-year mean + AR(1) noise fitted on residuals; port events add the uplift seen
                before and during past port events.
  shipments     per lane: weekly count, part mix, quantities and normal delays resampled from history; extra delay
                when the origin port is congested (slope fitted) or under a simulated event.
  demand        per SKU: same week of year averaged over the two history years x the SKU's year-on-year growth
                (capped) x lognormal noise sized from the year-to-year difference.

Not generated yet (v2): weather_alerts, trade_policy, disruption_impacts and losses (need an independent loss
simulator), and Claude-written headlines in new wording (needs an API budget). See data/forecast/README.md.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from core.etl import load

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "forecast"
START = pd.Timestamp("2026-10-05")          # first Monday after the data pack ends (30 Sep 2026)

PORT_COUNTRY = {"Kaohsiung": "Taiwan", "Keelung": "Taiwan", "Yantian (Shenzhen)": "China", "Shanghai": "China",
                "Ningbo": "China", "Busan": "South Korea", "Yokohama": "Japan", "Penang": "Malaysia",
                "Port Klang": "Malaysia", "Hai Phong": "Vietnam", "Laem Chabang": "Thailand",
                "Nhava Sheva (JNPT)": "India", "Chennai Port": "India"}
SHORT = {"Yantian (Shenzhen)": "Shenzhen", "Nhava Sheva (JNPT)": "JNPT", "Chennai Port": "Chennai"}
# where each past port event happened, as (port in the congestion table, words used for it in headlines)
EVENT_PORT = {"D01": ("Kaohsiung", ["Kaohsiung"]), "D02": ("Chennai Port", ["Chennai"]),
              "D06": ("Shanghai", ["Shanghai"]), "D09": ("Nhava Sheva (JNPT)", ["Mumbai", "JNPT", "Nhava Sheva"]),
              "D10": ("Busan", ["Busan"]), "D13": ("Port Klang", ["Port Klang"]), "D17": ("Hai Phong", ["Hai Phong"]),
              "D18": ("Yokohama", ["Yokohama"]), "D05": ("Penang", ["Penang"]), "D08": ("Kaohsiung", ["Hsinchu"]),
              "D12": ("Yantian (Shenzhen)", ["Shenzhen"])}
MOVABLE = {"D01", "D02", "D06", "D09", "D13", "D17"}       # port-level events we can move to another port
STORMS = ["Amihan", "Bising", "Corazon", "Dante", "Emong", "Fung", "Haiyan", "Ines", "Juno", "Kiko", "Lumen",
          "Mira", "Noel", "Onyx", "Pablo", "Quinta", "Rosal", "Sinag", "Tala", "Umber", "Vinta", "Wilma"]


def _weeks(years: int) -> pd.DatetimeIndex:
    return pd.date_range(START, periods=52 * years, freq="7D")


# ---------------- disruptions + their warning signals ----------------
def gen_disruptions(db, rng, years):
    d = db["disruptions"].copy()
    d["duration"] = (d["end_date"] - d["start_date"]).dt.days.clip(lower=1)
    lab = db["signal_labels"].merge(db["news"], on="signal_id")
    warn = lab[lab["relevant_to_veltrix"] & lab["linked_disruption_id"].notna()]
    rate = len(d) / 2.0                                              # events per year
    end = START + pd.Timedelta(weeks=52 * years)
    rows, n = [], 0
    for y in range(years):
        for _ in range(rng.poisson(rate)):
            a = d.iloc[rng.integers(len(d))]
            y0 = START + pd.DateOffset(years=y)
            if "Weather" in a["type"]:                       # weather keeps its own season: archetype month +/- 1
                m = (int(a["start_date"].month) - 1 + int(rng.integers(-1, 2))) % 12 + 1
                start = pd.Timestamp(year=y0.year + (m < y0.month), month=m, day=int(rng.integers(1, 28)))
            else:
                start = y0 + pd.Timedelta(days=int(rng.integers(0, 365)))
            if not (START <= start < end):
                continue
            dur = max(1, int(round(a["duration"] * rng.lognormal(0, 0.3))))
            port, words = EVENT_PORT.get(a["disruption_id"], (None, []))
            new_port = port
            if a["disruption_id"] in MOVABLE and rng.random() < 0.7:
                new_port = str(rng.choice(list(PORT_COUNTRY)))
            n += 1
            location = a["location"] if new_port == port else f"{SHORT.get(new_port, new_port)}, {PORT_COUNTRY[new_port]}"
            title = _swap(a["title"], words, port, new_port)
            if new_port != port:
                title = re.sub(r"\b(northern|southern|eastern|western) ", "", title)
            storm = str(rng.choice(STORMS))
            title = re.sub(r"(Typhoon|Cyclone|Storm) [A-Z][a-z]+", rf"\1 {storm}", title)
            rows.append({"disruption_id": f"F{n:03d}", "archetype": a["disruption_id"], "title": title,
                         "type": a["type"], "location": location, "port": new_port,
                         "start_date": start.normalize(), "end_date": (start + pd.Timedelta(days=dur)).normalize(),
                         "duration_days": dur, "suppliers_affected": int(a["suppliers_affected"]),
                         "storm": storm, "warned": bool((warn.loc[warn["linked_disruption_id"] == a["disruption_id"], "days_before_impact"] > 0).any()),
                         "_words": words, "_old_port": port})
    dis = pd.DataFrame(rows).sort_values("start_date").reset_index(drop=True)
    return dis, warn


def _swap(text: str, words: list[str], old_port, new_port) -> str:
    if not new_port or new_port == old_port:
        return text
    new = SHORT.get(new_port, new_port)
    for w in words:
        text = re.sub(re.escape(w), new, text)
    if old_port and PORT_COUNTRY.get(old_port) != PORT_COUNTRY.get(new_port):
        text = re.sub(re.escape(PORT_COUNTRY[old_port]), PORT_COUNTRY[new_port], text)
    return text


def gen_warnings(dis, warn, rng):
    out = []
    for _, e in dis.iterrows():
        src = warn[warn["linked_disruption_id"] == e["archetype"]]
        storm_old = {m for t in src["headline"] for m in re.findall(r"(?:Typhoon|Cyclone|Storm|as) ([A-Z][a-z]+)", t)}
        storm_old -= {"Taiwan", "China", "India", "Japan", "Korea", "Malaysia", "Vietnam", "Thailand"}
        storm_new = e["storm"]
        stretch = rng.lognormal(0, 0.2)                              # earlier or later warning than the archetype
        for _, s in src.iterrows():
            if rng.random() < 0.15:                                  # some warnings are not repeated this time
                continue
            lead = 0 if s["days_before_impact"] <= 0 else max(0, round(s["days_before_impact"] * stretch + rng.normal(0, 1)))
            t = s["published"]
            when = e["start_date"] - pd.Timedelta(days=lead) + pd.Timedelta(hours=float(t.hour + rng.uniform(-3, 3)) % 24)
            h = _swap(s["headline"], e["_words"], e["_old_port"], e["port"])
            sn = _swap(s["snippet"] if isinstance(s["snippet"], str) else "", e["_words"], e["_old_port"], e["port"])
            for o in storm_old:
                h, sn = h.replace(o, storm_new), sn.replace(o, storm_new)
            out.append({"published": when, "source": s["source"], "category": s["category"], "headline": h,
                        "snippet": sn, "relevant_to_veltrix": True, "linked_disruption_id": e["disruption_id"],
                        "days_before_impact": float(lead)})
    return out


def gen_noise(db, rng, weeks):
    lab = db["signal_labels"].merge(db["news"], on="signal_id")
    pool = lab[~lab["relevant_to_veltrix"]]
    per_week = len(pool) / (len(db["port_congestion"]["week_start"].unique()))
    out = []
    for w in weeks:
        for i in rng.choice(len(pool), rng.poisson(per_week)):
            s = pool.iloc[i]
            out.append({"published": w + pd.Timedelta(minutes=int(rng.integers(0, 7 * 24 * 60))), "source": s["source"],
                        "category": s["category"], "headline": s["headline"],
                        "snippet": s["snippet"] if isinstance(s["snippet"], str) else "",
                        "relevant_to_veltrix": False, "linked_disruption_id": None, "days_before_impact": np.nan})
    return out


# ---------------- port congestion ----------------
def port_uplift(db):
    """Average congestion uplift (index points over the port's own month mean) before and during past port events."""
    pc, d = db["port_congestion"].copy(), db["disruptions"].set_index("disruption_id")
    pc["m"] = pc["week_start"].dt.month
    base = pc.groupby(["port", "m"])["congestion_index"].transform("mean")
    pc["dev"] = pc["congestion_index"] - base
    pre, during = [], []
    for did, (port, _) in EVENT_PORT.items():
        if did not in MOVABLE:
            continue
        g, s, e = pc[pc["port"] == port], d.loc[did, "start_date"], d.loc[did, "end_date"]
        pre.append(g.loc[(g.week_start < s) & (g.week_start >= s - pd.Timedelta(days=21)), "dev"].mean())
        during.append(g.loc[(g.week_start >= s - pd.Timedelta(days=6)) & (g.week_start <= e), "dev"].mean())
    return float(np.nanmean(pre)), float(np.nanmean(during))


def gen_congestion(db, rng, weeks, dis):
    pc = db["port_congestion"].copy()
    pc["m"] = pc["week_start"].dt.month
    up_pre, up_during = port_uplift(db)
    rows, fit = [], {}
    for port, g in pc.sort_values("week_start").groupby("port"):
        mm = g.groupby("m")["congestion_index"].mean()
        r = (g["congestion_index"] - g["m"].map(mm)).to_numpy()
        phi = float(np.clip(np.corrcoef(r[:-1], r[1:])[0, 1], 0, 0.95))
        sd = float(np.std(r[1:] - phi * r[:-1]))
        b = np.polyfit(g["congestion_index"], g["median_vessel_wait_hours"], 1)
        wsd = float(np.std(g["median_vessel_wait_hours"] - np.polyval(b, g["congestion_index"])))
        fit[port] = {"phi": round(phi, 2), "noise_sd": round(sd, 2)}
        ev = dis[dis["port"] == port]
        x = r[-1]
        for w in weeks:
            x = phi * x + rng.normal(0, sd)
            bump = 0.0
            for _, e in ev.iterrows():
                if e["start_date"] - pd.Timedelta(days=21) <= w < e["start_date"] - pd.Timedelta(days=6):
                    bump = max(bump, up_pre * rng.uniform(0.6, 1.4))
                elif e["start_date"] - pd.Timedelta(days=6) <= w <= e["end_date"]:
                    bump = max(bump, up_during * rng.uniform(0.7, 1.3))
            idx = float(np.clip(mm[w.month] + x + bump, 0, 100))
            rows.append({"week_start": w, "port": port, "congestion_index": round(idx, 1),
                         "median_vessel_wait_hours": round(max(0.0, np.polyval(b, idx) + rng.normal(0, wsd)), 1)})
    return pd.DataFrame(rows), fit, (up_pre, up_during)


# ---------------- shipments ----------------
def gen_shipments(db, rng, weeks, cong, dis):
    s = db["shipments"].copy()
    s["wk"] = s["ship_date"].dt.to_period("W-SUN").dt.start_time
    nweeks = s["wk"].nunique()
    origin_port = {p: p for p in PORT_COUNTRY}
    cmean = db["port_congestion"].groupby("port")["congestion_index"].mean()
    # extra delay per congestion point above the port's mean, fitted on undisrupted sea shipments
    cw = db["port_congestion"].rename(columns={"week_start": "wk", "port": "origin_port"})
    sea = s[(s["freight_mode"] == "Sea") & s["linked_disruption_id"].isna()].merge(cw, on=["wk", "origin_port"], how="inner")
    exc = (sea["congestion_index"] - sea["origin_port"].map(cmean)).clip(lower=0)
    slope = float(np.polyfit(exc, sea["delay_days"], 1)[0]) if len(sea) > 50 else 0.0
    # each archetype's own footprint: which lanes it hit, what share of their shipments, and how late they ran
    hd = db["disruptions"].set_index("disruption_id")
    lanes_by_origin = db["lanes"].groupby("origin")["lane_id"].apply(set).to_dict()
    arch = {}
    for did, x in s[s["linked_disruption_id"].notna()].groupby("linked_disruption_id"):
        ln = set(x["lane_id"].dropna())
        off = (x["ship_date"] - hd.loc[did, "start_date"]).dt.days        # ships hit can leave before the event starts
        o0, o1 = int(off.min()), int(off.max())
        win = s[s["lane_id"].isin(ln) & (s["ship_date"] >= hd.loc[did, "start_date"] + pd.Timedelta(days=o0))
                & (s["ship_date"] <= hd.loc[did, "start_date"] + pd.Timedelta(days=o1))]
        dur = max(1, (hd.loc[did, "end_date"] - hd.loc[did, "start_date"]).days)
        arch[did] = {"lanes": ln, "p": min(1.0, len(x) / max(len(win), 1)), "delays": x["delay_days"].to_numpy(),
                     "o0": o0, "o1_frac": o1 / dur}
    hits = []                                   # (lanes, start, end, share, delays, id) for every generated event
    for _, e in dis.iterrows():
        a = arch.get(e["archetype"])
        if a is None:
            continue
        ln = a["lanes"]
        if e["port"] != e["_old_port"] and e["port"] in lanes_by_origin:
            ln = lanes_by_origin[e["port"]]
        s1 = e["start_date"] + pd.Timedelta(days=int(round(a["o1_frac"] * e["duration_days"])))
        hits.append((ln, e["start_date"] + pd.Timedelta(days=a["o0"]), s1, a["p"], a["delays"], e["disruption_id"]))
    cidx = cong.set_index(["week_start", "port"])["congestion_index"]
    rows, n = [], 0
    for lane, g in s.groupby("lane_id"):
        normal = g.loc[g["linked_disruption_id"].isna(), "delay_days"].to_numpy()
        lam = len(g) / nweeks
        transit = (g["planned_arrival"] - g["ship_date"]).dt.days.median()
        for w in weeks:
            for _ in range(rng.poisson(lam)):
                h = g.iloc[rng.integers(len(g))]
                ship = w + pd.Timedelta(days=int(rng.integers(0, 7)))
                delay = float(rng.choice(normal)) if len(normal) else 0.0
                port = origin_port.get(h["origin_port"])
                if port is not None and (w, port) in cidx.index:
                    delay += slope * max(0.0, cidx[(w, port)] - cmean[port])
                link = None
                for ln, s0, s1, p, dl, did in hits:
                    if lane in ln and s0 <= ship <= s1 and rng.random() < p:
                        delay = float(rng.choice(dl))         # the archetype's own disrupted delays replace normal ones
                        link = did
                        break
                delay = max(0, int(round(delay)))
                q = max(1, int(h["quantity_units"] * rng.lognormal(0, 0.15)))
                n += 1
                rows.append({"shipment_id": f"FSHP-{n:05d}", "part_id": h["part_id"], "supplier_id": h["supplier_id"],
                             "lane_id": lane, "origin_port": h["origin_port"], "destination": h["destination"],
                             "ship_date": ship, "planned_arrival": ship + pd.Timedelta(days=transit),
                             "actual_arrival": ship + pd.Timedelta(days=transit + delay), "delay_days": delay,
                             "quantity_units": q, "value_inr": int(round(h["value_inr"] / h["quantity_units"] * q)),
                             "freight_mode": h["freight_mode"], "linked_disruption_id": link})
    return pd.DataFrame(rows).sort_values("ship_date").reset_index(drop=True), slope


# ---------------- demand ----------------
def gen_demand(db, rng, weeks):
    d = db["weekly_demand"].copy()
    d["woy"] = d["week_start"].dt.isocalendar().week.astype(int).clip(upper=52)
    d["yr"] = (d["week_start"] >= pd.Timestamp("2025-10-01")).astype(int)
    rows, fit = [], {}
    for sku, g in d.groupby("sku_id"):
        y = g.groupby("yr")["customer_demand_units"].sum()
        growth = float(np.clip(y.get(1, 1) / max(y.get(0, 1), 1), 0.9, 1.2))
        piv = g.pivot_table(index="woy", columns="yr", values="customer_demand_units", aggfunc="mean")
        prof = piv.mean(axis=1)
        sd = float(np.nanstd(np.log(piv[1] / piv[0]))) / np.sqrt(2) if piv.shape[1] == 2 else 0.1
        price = (g["revenue_inr"].sum() / max(g["units_shipped"].sum(), 1))
        ok = g.loc[g["units_short"] == 0, "otif_pct"].to_numpy()
        fit[sku] = {"growth": round(growth, 3), "noise_sd": round(sd, 3)}
        for i, w in enumerate(weeks):
            woy = min(int(w.isocalendar()[1]), 52)
            base = prof.get(woy, prof.mean())
            u = max(0, int(round(base * growth ** (1 + i / 52) * rng.lognormal(0, sd))))
            rows.append({"week_start": w, "sku_id": sku, "customer_demand_units": u, "units_shipped": u,
                         "units_short": 0, "otif_pct": round(float(rng.choice(ok)), 3) if len(ok) else 0.97,
                         "revenue_inr": int(round(u * price))})
    return pd.DataFrame(rows), fit


# ---------------- run ----------------
def generate(years: int = 2, seed: int = 42, out: Path = OUT) -> dict:
    rng = np.random.default_rng(seed)
    db = load()
    weeks = _weeks(years)
    dis, warn = gen_disruptions(db, rng, years)
    news = pd.DataFrame(gen_noise(db, rng, weeks) + gen_warnings(dis, warn, rng)).sort_values("published").reset_index(drop=True)
    news = news[news["published"] < weeks[-1] + pd.Timedelta(days=7)].reset_index(drop=True)
    news["signal_id"] = [f"FNEWS-{i + 1:05d}" for i in range(len(news))]
    cut = START + pd.DateOffset(months=12 * years - 6)              # last 6 months held out as the test set
    news["split"] = np.where(news["published"] < cut, "train", "test")
    cong, cfit, uplift = gen_congestion(db, rng, weeks, dis)
    ship, slope = gen_shipments(db, rng, weeks, cong, dis)
    dem, dfit = gen_demand(db, rng, weeks)

    out.mkdir(parents=True, exist_ok=True)
    dis.drop(columns=["_words", "_old_port"]).to_csv(out / "disruptions.csv", index=False)
    news[["signal_id", "published", "source", "category", "headline", "snippet"]].to_csv(out / "news.csv", index=False)
    news[["signal_id", "published", "relevant_to_veltrix", "linked_disruption_id", "days_before_impact", "split"]] \
        .rename(columns={"published": "signal_date"}).to_csv(out / "signal_labels.csv", index=False)
    cong.to_csv(out / "port_congestion.csv", index=False)
    ship.to_csv(out / "shipments.csv", index=False)
    dem.to_csv(out / "weekly_demand.csv", index=False)
    rep = compare(db, dis, news, cong, ship, dem)
    rep["fitted"] = {"congestion_per_port": cfit, "congestion_uplift_pre_during": [round(u, 1) for u in uplift],
                     "delay_days_per_congestion_point": round(slope, 3), "demand_per_sku": dfit}
    rep["settings"] = {"years": years, "seed": seed, "start": str(START.date()), "test_from": str(cut.date())}
    (out / "validation.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


def _wk(d, lo, hi):
    w = d.groupby("week_start")["customer_demand_units"].sum()
    if lo is not None:
        w = w[w.index >= lo]
    if hi is not None:
        w = w[w.index < hi]
    return w.mean() if len(w) else float("nan")


def _yoy(d, cut):
    return _wk(d, cut, None) / _wk(d, None, cut)


def compare(db, dis, news, cong, ship, dem) -> dict:
    """History vs generated, per year where it is a rate. Close numbers mean the generator copies the pack's patterns."""
    hd = db["disruptions"]
    hl = db["signal_labels"].merge(db["news"], on="signal_id")
    hw = hl[hl["relevant_to_veltrix"]]
    gy = len(cong["week_start"].unique()) / 52
    row = lambda h, g: {"history": round(float(h), 2), "generated": round(float(g), 2)}   # noqa: E731
    return {"rows": {
        "disruptions per year": row(len(hd) / 2, len(dis) / gy),
        "median duration (days)": row((hd["end_date"] - hd["start_date"]).dt.days.median(), dis["duration_days"].median()),
        "share of events warned in advance": row(15 / 18, dis["warned"].mean()),
        "news items per week": row(len(hl) / 104, len(news) / (52 * gy)),
        "share of news relevant": row(hl["relevant_to_veltrix"].mean(), news["relevant_to_veltrix"].mean()),
        "median warning lead (days, warned only)": row(hw.loc[hw["days_before_impact"] > 0].groupby("linked_disruption_id")["days_before_impact"].max().median(),
                                                       news[news["days_before_impact"] > 0].groupby("linked_disruption_id")["days_before_impact"].max().median()),
        "mean congestion index": row(db["port_congestion"]["congestion_index"].mean(), cong["congestion_index"].mean()),
        "sd congestion index": row(db["port_congestion"]["congestion_index"].std(), cong["congestion_index"].std()),
        "shipments per week": row(len(db["shipments"]) / 104, len(ship) / (52 * gy)),
        "mean sea delay (days)": row(db["shipments"].query("freight_mode=='Sea'")["delay_days"].mean(), ship.query("freight_mode=='Sea'")["delay_days"].mean()),
        "share of shipments hit by an event": row(db["shipments"]["linked_disruption_id"].notna().mean(), ship["linked_disruption_id"].notna().mean()),
        "mean delay, unaffected shipments (days)": row(db["shipments"].loc[db["shipments"]["linked_disruption_id"].isna(), "delay_days"].mean(),
                                                       ship.loc[ship["linked_disruption_id"].isna(), "delay_days"].mean()),
        "demand growth, year on year": row(_yoy(db["weekly_demand"], pd.Timestamp("2025-10-01")), _yoy(dem, START + pd.Timedelta(weeks=52))),
        "weekly demand: last history year vs first forecast year": row(_wk(db["weekly_demand"], pd.Timestamp("2025-10-01"), None),
                                                                        _wk(dem, None, START + pd.Timedelta(weeks=52))),
    }, "counts": {"disruptions": len(dis), "news": len(news), "warnings": int(news["relevant_to_veltrix"].sum()),
                  "shipments": len(ship), "port_weeks": len(cong), "demand_rows": len(dem),
                  "test_news": int((news["split"] == "test").sum())}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=2, choices=[1, 2])
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    r = generate(a.years, a.seed)
    for k, v in r["rows"].items():
        print(f"{k:42s} history {v['history']:>10}   generated {v['generated']:>10}")
    print(r["counts"])

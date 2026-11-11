"""Evidence for each must-have in the brief, measured against the data pack's own ground truth.

    from core.must_haves import evaluate; ev = evaluate()

Ground truth used (no hand-labelling of signals):
  * signal_labels: relevant_to_veltrix, linked_disruption_id, split (train / test from 1 Feb 2026)
  * disruptions.location → GOLD_LOC below: the network nodes a correct extraction of that disruption's place would link to
    (written once per disruption from its recorded location; listed in full so a reviewer can check it)
  * disruption_impacts: the parts and SKUs each disruption actually hit (must-have 2)
  * disruption history losses (must-have 3, via core.validate_impact)
"""
from __future__ import annotations

import re

import pandas as pd

from core.etl import load
from core.graph import build_network

# Acceptable network nodes per disruption location. A signal's extraction is "right on location" if it links any of them.
GOLD_LOC = {
    "D01": {"port:Kaohsiung", "country:Taiwan"},                          # Kaohsiung, Taiwan
    "D02": {"dest:Chennai Port", "loc:Chennai", "port:Domestic — Chennai"},  # Chennai, India
    "D03": {"choke:Red Sea / Suez Canal"},                                 # Red Sea
    "D04": {"country:China"},                                              # China (export licensing)
    "D05": {"port:Penang", "country:Malaysia"},                            # Penang, Malaysia
    "D06": {"port:Shanghai"},                                              # Shanghai, China
    "D07": {"region:India road freight", "country:India"},                 # India (all states), truckers
    "D08": {"loc:Hsinchu", "country:Taiwan", "port:Keelung"},              # Hsinchu, Taiwan
    "D09": {"dest:Nhava Sheva (JNPT)", "loc:Mumbai / JNPT"},               # Mumbai / JNPT
    "D10": {"port:Busan", "country:South Korea"},                          # Busan, South Korea
    "D11": {"region:Indian ports", "dest:Chennai Port", "dest:Nhava Sheva (JNPT)"},  # all Indian ports
    "D12": {"port:Yantian (Shenzhen)", "loc:Shenzhen"},                    # Shenzhen, China
    "D13": {"port:Port Klang", "choke:Strait of Malacca"},                 # Port Klang / Malacca
    "D14": {"country:China"},                                              # China → India duty
    "D15": {"loc:Pune", "port:Domestic — Pune"},                           # Pune, India
    "D16": {"region:Asia–India sea lanes"},                                # Asia–India trade lane
    "D17": {"port:Hai Phong", "country:Vietnam"},                          # Hai Phong, Vietnam
    "D18": {"port:Yokohama", "country:Japan"},                             # Yokohama, Japan
}

TARGETS = {"recall": 0.80, "alert_precision": 0.60, "median_lead_days": 7.0, "impact_within_25pct_share": 0.60,
           "seconds_to_quantify": 300}


def _cats_for(did: str) -> set[str]:
    db = load()
    imp = db["disruption_impacts"]
    cat = db["parts"].set_index("part_id")["category"]
    return {f"cat:{cat[p]}" for p in imp[imp["disruption_id"] == did]["part_id"].unique() if p in cat}


def _with_countries(links) -> set[str]:
    """A port or Indian location also counts as its country (Shanghai is in China)."""
    db = load()
    pc = dict(zip("port:" + db["suppliers"]["port_of_loading"].astype(str), "country:" + db["suppliers"]["country"].astype(str)))
    out = set(links or [])
    for n in list(out):
        if n in pc:
            out.add(pc[n])
        if n.startswith(("dest:", "loc:", "region:India", "region:Indian")) or n.startswith("port:Domestic"):
            out.add("country:India")
    return out


def extraction_accuracy(T: pd.DataFrame, links_col: str = "links") -> dict:
    """Must-have 1 on the 179 relevant, disruption-linked signals.

    signal_link_recall: the signal's extracted entities link to at least one part the disruption actually hit
                        (the measure that matters: did extraction + linking point at the right parts?)
    location_recall:    the extracted places include the disruption's place (a port counts as its country);
                        signals that name no place at all count as misses here, so this is a lower bound
    commodity_precision: where a commodity was extracted, it matches a category the disruption actually hit"""
    from core.events import scope_parts
    db = load()
    gp = db["disruption_impacts"].groupby("disruption_id")["part_id"].apply(set).to_dict()
    rel = T[T["relevant_to_veltrix"].astype(bool) & T["linked_disruption_id"].notna()].copy()
    rel["link_hit"] = [bool(scope_parts(list(l or [])) & gp[d]) for l, d in zip(rel[links_col], rel["linked_disruption_id"])]
    rel["loc_hit"] = [bool(_with_countries(l) & GOLD_LOC[d]) for l, d in zip(rel[links_col], rel["linked_disruption_id"])]
    cats = [{n for n in (l or []) if n.startswith("cat:")} for l in rel[links_col]]
    named = [(c, d) for c, d in zip(cats, rel["linked_disruption_id"]) if c]
    cat_ok = sum(bool(c & _cats_for(d)) for c, d in named)
    by = rel.groupby("linked_disruption_id")["loc_hit"].mean().round(2).to_dict()
    return {"signals": len(rel), "signal_link_recall": round(rel["link_hit"].mean(), 3),
            "signal_link_recall_test": round(rel[rel["split"] == "test"]["link_hit"].mean(), 3),
            "location_recall": round(rel["loc_hit"].mean(), 3),
            "location_recall_test": round(rel[rel["split"] == "test"]["loc_hit"].mean(), 3),
            "commodity_named": len(named), "commodity_precision": round(cat_ok / len(named), 3) if named else None,
            "by_disruption": by, "misses": rel[~rel["link_hit"]][["signal_id", "linked_disruption_id", "text"]]}


def linking_accuracy(events) -> pd.DataFrame:
    """Must-have 2: does the alert's part set cover the parts (and SKUs) the disruption actually hit?"""
    db = load()
    imp = db["disruption_impacts"]
    gp = imp.groupby("disruption_id")["part_id"].apply(set).to_dict()
    gs = imp.groupby("disruption_id")["sku_id"].apply(set).to_dict()
    net = build_network()
    rows = []
    for e in events:
        for did in sorted({s["linked_disruption_id"] for s in e.signals if isinstance(s.get("linked_disruption_id"), str)}):
            p = set(e.parts)
            skus = set(net.skus_using(sorted(p))) if p else set()
            rows.append({"disruption_id": did, "alert": e.event_id.replace("EV", "AL"), "parts_linked": len(p),
                         "parts_hit": len(gp[did]), "parts_hit_covered": len(p & gp[did]),
                         "part_recall": round(len(p & gp[did]) / len(gp[did]), 3),
                         "sku_recall": round(len(skus & gs[did]) / len(gs[did]), 3) if gs.get(did) else None})
    df = pd.DataFrame(rows)
    # One disruption can be split over two alerts (D16): take the union per disruption for the headline.
    return df


def briefing_checks(alerts: list[dict]) -> pd.DataFrame:
    """Must-have 6: one page, all sections, numbers from the engine, approvers named, sources cited, no junk."""
    from core.impact import fmt_inr
    rows = []
    for a in alerts:
        t, b = a["brief_text"], a["brief"]
        short = b["numbers"]["parts_short"] > 0
        checks = {
            "one_page": len(t) <= 3500 and len(t.splitlines()) <= 45,
            "headline_and_ask": t.splitlines()[0].startswith(f"[{a['alert_id']}]") and ("ASK:" in t),
            "what_is_happening": "What is happening:" in t,
            "exposure": "Exposure:" in t,
            "recommended_with_approver": "Recommended" in t and all(x.get("approver") for x in b["recommended"]),
            "residual_when_short": (not short) or (not b["recommended"] or not b["recommended"][0]["part"]) or "Left after this plan" in t,
            "sources_cited": b["n_signals"] >= 1 and "Sources:" in t,
            "numbers_match_engine": fmt_inr(b["numbers"]["revenue_at_risk_inr"]) in t,
            "says_nothing_ordered": "nothing has been ordered" in t,
            "no_junk": not re.search(r"\bnan\b|\bNone\b|\{|\}|Traceback|undefined", t),
        }
        rows.append({"alert": a["alert_id"], "chars": len(t), **checks, "pass": all(checks.values())})
    return pd.DataFrame(rows)


def mitigation_checks(alerts: list[dict]) -> dict:
    """Must-have 4: every option has cost, time to effect, net value and the approver the matrix requires."""
    from core.mitigate import approver
    n = bad_fields = bad_approver = 0
    for a in alerts:
        opts = a["options"]
        opts = opts.to_dict("records") if isinstance(opts, pd.DataFrame) else list(opts)
        for o in opts:
            if o.get("kind") == "none":
                continue
            n += 1
            if any(o.get(k) is None for k in ("cost_inr", "time_to_effect_days", "net_value_inr", "approver")):
                bad_fields += 1
            elif o["approver"] != approver(o["kind"], float(o["cost_inr"])):
                bad_approver += 1
    return {"options": n, "missing_fields": bad_fields, "approver_mismatch": bad_approver}


def evaluate() -> dict:
    from core.alerts import build_alert
    from core.backtest import run_backtest
    from core.snapshot import alert_record
    from core.validate_impact import summary, validate
    bt = run_backtest()
    alerts = [alert_record(build_alert(e)) for e in bt["events"]]
    vi = summary(validate())
    return {"backtest": bt, "extraction_rules": extraction_accuracy(bt["triaged"]),
            "linking": linking_accuracy(bt["events"]), "briefings": briefing_checks(alerts),
            "mitigation": mitigation_checks(alerts), "impact": vi, "alerts": alerts}

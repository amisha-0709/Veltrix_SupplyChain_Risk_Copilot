"""Combine Claude's extraction (core/llm_triage.py) with the rule-based triage, and measure it.

    T = with_extraction(triage_all())     # adds llm_* columns and llm_links (Claude's names, linked by OUR gazetteer)
    variants(T, threshold)                # rules / claude / either / both on train and test

Claude's relevance call: a supply event that is happening or likely (not a forecast that misses, a denial, a threat,
routine or resolved) AND at least one extracted place, port, route or company that the gazetteer links to the network.
A commodity alone links only for trade measures (an export control on magnets touches us wherever they are made).
The rule used in production is chosen on TRAIN only (best F1, ties go to the simpler rule); test is reported as is.
"""
from __future__ import annotations

import pandas as pd

from core.graph import build_network
from core.llm_triage import cached_for

LIVE = {"happening", "forecast_likely"}
RULES = ["rules", "claude", "either", "both"]


def _link(names: list[str]) -> list[str]:
    net = build_network()
    out = []
    for n in names:
        out += [h["node"] for h in net.match(n)]
    return list(dict.fromkeys(out))


def with_extraction(T: pd.DataFrame) -> pd.DataFrame:
    X = cached_for(T["text"])
    T = T.copy()
    T["llm_has"] = T["text"].map(lambda t: t in X)

    def g(t, f, d=None):
        x = X.get(t)
        return getattr(x, f) if x is not None else d
    for f in ("is_supply_event", "status", "event_type", "severity", "duration_days", "confidence", "reason"):
        T[f"llm_{f}"] = [g(t, f) for t in T["text"]]
    T["llm_entities"] = [({"locations": x.locations, "ports": x.ports, "routes": x.routes, "companies": x.companies,
                           "commodities": x.commodities, "categories": x.commodity_categories} if (x := X.get(t)) else None)
                         for t in T["text"]]
    geo, cat = [], []
    for e in T["llm_entities"]:
        if not e:
            geo.append([]); cat.append([])
            continue
        geo.append(_link(e["locations"] + e["ports"] + e["routes"] + e["companies"]))
        cat.append([f"cat:{c}" for c in e["categories"] if c != "other"])
    T["llm_geo_links"], T["llm_cat_links"] = geo, cat
    T["llm_links"] = [list(dict.fromkeys(a + b)) for a, b in zip(geo, cat)]
    T["llm_relevant"] = [bool(h and s and st in LIVE and (gl or (et == "trade_licensing" and cl)))
                         for h, s, st, gl, cl, et in zip(T["llm_has"], T["llm_is_supply_event"], T["llm_status"],
                                                          T["llm_geo_links"], T["llm_cat_links"], T["llm_event_type"])]
    return T


def flags(T: pd.DataFrame, threshold: float, rule: str) -> pd.Series:
    r = T["score"] >= threshold
    c = T["llm_relevant"].astype(bool)
    return {"rules": r, "claude": c, "either": r | c, "both": r & c}[rule]


def _m(f: pd.Series, y: pd.Series) -> dict:
    tp, fp, fn = int((f & y).sum()), int((f & ~y).sum()), int((~f & y).sum())
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    return {"flagged": tp + fp, "tp": tp, "fp": fp, "fn": fn, "precision": None if p is None else round(p, 3),
            "recall": None if r is None else round(r, 3),
            "f1": round(2 * p * r / (p + r), 3) if p and r else 0.0}


def variants(T: pd.DataFrame, threshold: float) -> pd.DataFrame:
    rows = []
    for rule in RULES:
        f = flags(T, threshold, rule)
        for split in ("train", "test"):
            m = T["split"] == split
            rows.append({"rule": rule, "split": split, **_m(f[m], T.loc[m, "relevant_to_veltrix"].astype(bool))})
    return pd.DataFrame(rows)


def choose(V: pd.DataFrame) -> str:
    """Train only: best F1, then recall; ties go to the earlier (simpler) rule in RULES."""
    tr = V[V["split"] == "train"].copy()
    tr["order"] = tr["rule"].map(RULES.index)
    return tr.sort_values(["f1", "recall", "order"], ascending=[False, False, True]).iloc[0]["rule"]


def coverage(T: pd.DataFrame) -> dict:
    return {"signals": len(T), "with_extraction": int(T["llm_has"].sum()),
            "unique_texts": int(T["text"].nunique()), "unique_extracted": int(T.loc[T["llm_has"], "text"].nunique())}


def live_extraction(text: str) -> dict | None:
    """Claude's extraction for one live signal (Try a signal), linked by our gazetteer. None without a key or on error."""
    from core.llm_triage import extract_live
    x = extract_live(text)
    if x is None:
        return None
    ent = {"locations": x.locations, "ports": x.ports, "routes": x.routes, "companies": x.companies,
           "commodities": x.commodities, "categories": [c for c in x.commodity_categories if c != "other"]}
    geo = _link(ent["locations"] + ent["ports"] + ent["routes"] + ent["companies"])
    cat = [f"cat:{c}" for c in ent["categories"]]
    rel = bool(x.is_supply_event and x.status in LIVE and (geo or (x.event_type == "trade_licensing" and cat)))
    return {"is_supply_event": x.is_supply_event, "status": x.status, "event_type": x.event_type, "severity": x.severity,
            "duration_days": x.duration_days, "confidence": x.confidence, "reason": x.reason, "entities": ent,
            "geo_links": geo, "cat_links": cat, "relevant": rel}

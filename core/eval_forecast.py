"""Held-out evaluation on the generated forecast data (data/forecast, 5 Oct 2026 – 25 Sep 2028).

The co-pilot runs UNCHANGED: the same triage (core.triage.triage_news), the same threshold (tuned on the
data pack's TRAIN split only, as deployed) and the same alert clustering (core.events.build_events).
Nothing here is tuned on the forecast data. Headlines come from news_claude.csv (rewritten by Claude in
10 styles), labels from signal_labels.csv. The same evaluator also runs over the original data pack, so
every forecast number sits next to its data-pack baseline.

Two definitions of "flagged", both reported:
  * triage   – score ≥ threshold (pure binary classifier, the headline metric here)
  * alerted  – the signal ends up in an alert (triage plus follow-ups attached to an open event);
               this is the definition the data-pack back-test (T9) uses.

  .venv/Scripts/python.exe -X utf8 -m core.eval_forecast          # rules only, free
  .venv/Scripts/python.exe -X utf8 -m core.eval_forecast --llm    # + Claude extraction; needs ANTHROPIC_API_KEY, costs money
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from core.events import build_events
from core.triage import story_key, triage_all, triage_news, tune_threshold

ROOT = Path(__file__).resolve().parent.parent
FC = ROOT / "data" / "forecast"
OUT = ROOT / "reports" / "forecast_eval.json"
PACK_TEST_START = pd.Timestamp("2026-02-01")
FC_TEST_START = pd.Timestamp("2028-04-01")
N_BOOT = 2000


# ---------------------------------------------------------------- data
def forecast_triaged() -> tuple[pd.DataFrame, pd.DataFrame]:
    news = pd.read_csv(FC / "news_claude.csv", parse_dates=["published"])
    lab = pd.read_csv(FC / "signal_labels.csv")
    dis = pd.read_csv(FC / "disruptions.csv", parse_dates=["start_date", "end_date"])
    rows = []
    for r in news.itertuples(index=False):
        row = SimpleNamespace(signal_id=r.signal_id, headline=r.headline, snippet="" if pd.isna(r.snippet) else r.snippet,
                              source=r.source, published=r.published)
        rows.append(triage_news(row).__dict__)
    T = pd.DataFrame(rows)
    T["story_key"] = [story_key(t.split(". ")[0]) for t in T["text"]]
    T = T.merge(lab[["signal_id", "relevant_to_veltrix", "linked_disruption_id", "days_before_impact", "split"]],
                on="signal_id", how="left", validate="one_to_one")
    T = T.merge(news[["signal_id", "style", "category", "headline"]], on="signal_id", how="left", validate="one_to_one")
    if T["relevant_to_veltrix"].isna().any() or T["split"].isna().any():
        raise SystemExit(f"{int(T['split'].isna().sum())} signals have no label row: check the files")
    T["relevant_to_veltrix"] = T["relevant_to_veltrix"].astype(str).str.lower().eq("true")
    dis["warned"] = dis["warned"].astype(str).str.lower().eq("true")
    return T, dis


def pack_triaged() -> tuple[pd.DataFrame, pd.DataFrame]:
    from core.etl import load
    db = load()
    T = triage_all()
    T["relevant_to_veltrix"] = T["relevant_to_veltrix"].astype(bool)
    T["style"] = "data pack"
    lab = db["signal_labels"]
    d = db["disruptions"].copy()
    d["warned"] = [bool((lab[lab.linked_disruption_id == i]["days_before_impact"] > 0).any()) for i in d["disruption_id"]]
    return T, d


# ---------------------------------------------------------------- metrics
def confusion(flag: pd.Series, y: pd.Series) -> dict:
    flag, y = flag.astype(bool).to_numpy(), y.astype(bool).to_numpy()
    tp, fp = int((flag & y).sum()), int((flag & ~y).sum())
    fn, tn = int((~flag & y).sum()), int((~flag & ~y).sum())
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    return {"n": len(y), "relevant": tp + fn, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": _r(p), "recall": _r(r), "f1": _r(2 * p * r / (p + r)) if p and r else (0.0 if tp + fn else None),
            "accuracy": _r((tp + tn) / len(y)) if len(y) else None,
            "false_positive_rate": _r(fp / (fp + tn)) if fp + tn else None}


def _r(v, n=3):
    return None if v is None else round(float(v), n)


def bootstrap_ci(flag: pd.Series, y: pd.Series, seed: int = 0) -> dict:
    """95% percentile bootstrap over signals (resampled with replacement)."""
    f, t = flag.astype(bool).to_numpy(), y.astype(bool).to_numpy()
    rng = np.random.default_rng(seed)
    ps, rs = [], []
    for _ in range(N_BOOT):
        i = rng.integers(0, len(t), len(t))
        fi, ti = f[i], t[i]
        tp = (fi & ti).sum()
        if fi.sum():
            ps.append(tp / fi.sum())
        if ti.sum():
            rs.append(tp / ti.sum())
    q = lambda a: [_r(np.percentile(a, 2.5)), _r(np.percentile(a, 97.5))] if a else None  # noqa: E731
    return {"precision_95ci": q(ps), "recall_95ci": q(rs), "resamples": N_BOOT}


def detection(T: pd.DataFrame, dis: pd.DataFrame, events, test_start: pd.Timestamp) -> tuple[list[dict], dict]:
    rows = []
    for r in dis.itertuples(index=False):
        rel = T[T["linked_disruption_id"] == r.disruption_id]
        caught = rel[rel["alerted"] & (rel["published"] < r.start_date)]
        first = caught["published"].min() if len(caught) else pd.NaT
        rows.append({"disruption_id": r.disruption_id, "title": r.title, "type": r.type,
                     "split": "test" if r.start_date >= test_start else "train", "warned": bool(r.warned),
                     "start_date": str(r.start_date.date()), "relevant_signals": len(rel),
                     "signals_alerted_before_impact": len(caught),
                     "first_alert": None if pd.isna(first) else str(first),
                     "lead_days": None if pd.isna(first) else round((r.start_date - first).total_seconds() / 86400, 1)})
    D = pd.DataFrame(rows)

    def summ(d: pd.DataFrame, ev) -> dict:
        lead = d["lead_days"].dropna()
        w = d[d["warned"]]
        return {"disruptions": len(d), "warned": len(w),
                "caught_before_impact": int(d["lead_days"].notna().sum()),
                "share_caught": _r(d["lead_days"].notna().mean()) if len(d) else None,
                "share_of_warned_caught": _r(w["lead_days"].notna().mean()) if len(w) else None,
                "median_lead_days": _r(lead.median(), 1) if len(lead) else None,
                "p10_lead_days": _r(lead.quantile(0.1), 1) if len(lead) else None,
                "p90_lead_days": _r(lead.quantile(0.9), 1) if len(lead) else None}

    def alerts(split: str | None) -> dict:
        ev = [e for e in events if split is None or (e.first_seen >= test_start) == (split == "test")]
        P = T if split is None else T[T["split"] == split]
        weeks = max((P["published"].max() - P["published"].min()).days / 7, 1)
        rel = [e for e in ev if any(s["relevant_to_veltrix"] for s in e.signals)]
        return {"alerts": len(ev), "alerts_per_week": _r(len(ev) / weeks, 2),
                "alert_precision": _r(len(rel) / len(ev)) if ev else None}

    out = {"overall": {**summ(D, None), **alerts(None)}, "test": {**summ(D[D.split == "test"], None), **alerts("test")}}
    return rows, out


def evaluate(T: pd.DataFrame, dis: pd.DataFrame, th: float, test_start: pd.Timestamp, flag_col: str = "triage") -> dict:
    events, _ = build_events(T, th)
    alerted = {s["signal_id"] for e in events for s in e.signals + e.updates}
    T["triage"] = T["score"] >= th
    T["alerted"] = T["signal_id"].isin(alerted)
    res = {}
    for name, d in (("overall", T), ("test", T[T["split"] == "test"])):
        res[name] = {"triage": {**confusion(d[flag_col], d["relevant_to_veltrix"]),
                                **bootstrap_ci(d[flag_col], d["relevant_to_veltrix"])},
                     "alerted": confusion(d["alerted"], d["relevant_to_veltrix"])}
    rows, det = detection(T, dis, events, test_start)
    res["overall"]["detection"], res["test"]["detection"] = det["overall"], det["test"]
    res["per_disruption"] = rows
    return res


def breakdowns(T: pd.DataFrame, dis: pd.DataFrame, flag_col: str = "triage") -> dict:
    out = {}
    for name, d in (("overall", T), ("test", T[T["split"] == "test"])):
        style = {s: confusion(g[flag_col], g["relevant_to_veltrix"]) for s, g in d.groupby("style")}
        typ = d.merge(dis[["disruption_id", "type"]], left_on="linked_disruption_id", right_on="disruption_id", how="left")
        pos = typ[typ["relevant_to_veltrix"]]
        by_type = {t: {"relevant": len(g), "caught": int(g[flag_col].sum()), "recall": _r(g[flag_col].mean())}
                   for t, g in pos.groupby("type")}
        neg = d[~d["relevant_to_veltrix"]]
        fp_by_cat = {c: {"background_items": len(g), "false_positives": int(g[flag_col].sum()),
                         "false_positive_rate": _r(g[flag_col].mean())} for c, g in neg.groupby("category")}
        out[name] = {"by_style": style, "recall_by_event_type": by_type, "false_positives_by_news_category": fp_by_cat}
    return out


def worst(T: pd.DataFrame, flag_col: str = "triage", k: int = 20) -> dict:
    cols = ["signal_id", "split", "style", "score", "headline", "reason"]
    fn = T[~T[flag_col] & T["relevant_to_veltrix"]].copy()
    fn["days_before_impact"] = pd.to_numeric(fn["days_before_impact"], errors="coerce")
    # Worst misses: furthest below the bar, then the earliest warnings lost.
    fn = fn.sort_values(["score", "days_before_impact"], ascending=[True, False]).head(k)
    fp = T[T[flag_col] & ~T["relevant_to_veltrix"]].sort_values("score", ascending=False).head(k)
    rec = lambda d, extra: [{c: (None if pd.isna(v) else v) if not isinstance(v, (list, dict)) else v  # noqa: E731
                             for c, v in r.items()} for r in d[cols + extra].to_dict("records")]
    return {"false_negatives": rec(fn, ["linked_disruption_id", "days_before_impact"]),
            "false_positives": rec(fp, ["category"])}


# ---------------------------------------------------------------- optional Claude-assisted triage
def with_claude(T: pd.DataFrame, th: float) -> tuple[pd.DataFrame, str, list]:
    from core import llm_triage
    from core.triage_llm import RULES, flags, variants, with_extraction
    todo = sorted(set(T["text"]))
    print(f"Claude extraction for {len(todo)} unique texts (cached ones are skipped)…")
    done, failed = llm_triage.run(todo)
    print(f"  extracted {done}, failed {failed}")
    T = with_extraction(T)
    V = variants(T, th)
    # Rule chosen on the forecast TRAIN split only (best F1, then recall, then the simpler rule); test scored once.
    tr = V[V["split"] == "train"].assign(order=lambda v: v["rule"].map(RULES.index))
    rule = tr.sort_values(["f1", "recall", "order"], ascending=[False, False, True]).iloc[0]["rule"]
    return apply_rule(T, th, rule), rule, V.to_dict("records")


def apply_rule(T: pd.DataFrame, th: float, rule: str) -> pd.DataFrame:
    """The same rule step the data-pack back-test uses (core.triage_llm.apply_rule)."""
    from core.triage_llm import apply_rule as _apply
    return _apply(T, th, rule)


CACHED_RULE = "either"   # fixed before scoring: Claude can add a signal the word list missed, never remove one


def cached_claude(F: pd.DataFrame, th: float) -> tuple[pd.DataFrame, dict]:
    """No API calls: use only the Claude extractions already in the cache. Coverage is partial, so the rule is
    fixed in advance (not chosen on any forecast data) and the fair comparison is on the covered signals only."""
    from core.triage_llm import coverage, flags, with_extraction
    X = with_extraction(F)
    y = X["relevant_to_veltrix"]
    cov = {"overall": coverage(X), "by_split": {}, "by_style": {}}
    for s, d in X.groupby("split"):
        cov["by_split"][s] = {"signals": len(d), "with_claude": int(d["llm_has"].sum()),
                              "relevant": int(d["relevant_to_veltrix"].sum()),
                              "relevant_with_claude": int((d["llm_has"] & d["relevant_to_veltrix"]).sum())}
    for s, d in X.groupby("style"):
        cov["by_style"][s] = {"signals": len(d), "with_claude": int(d["llm_has"].sum())}
    head = {}
    for name, m in (("overall", X["llm_has"]), ("test", X["llm_has"] & (X["split"] == "test"))):
        head[name] = {r: confusion(flags(X, th, r)[m], y[m]) for r in ("rules", "claude", "either")}
    r_flag, e_flag = flags(X, th, "rules"), flags(X, th, CACHED_RULE)
    gained = X[e_flag & ~r_flag]
    cols = ["signal_id", "split", "style", "score", "headline", "llm_reason"]
    ex = {"claude_added_true": gained[gained["relevant_to_veltrix"]][cols].head(15).to_dict("records"),
          "claude_added_false": gained[~gained["relevant_to_veltrix"]][cols].head(15).to_dict("records"),
          "claude_missed_relevant_rules_caught": X[X["llm_has"] & r_flag & ~X["llm_relevant"] & y][cols].head(10).to_dict("records")}
    return apply_rule(X, th, CACHED_RULE), {"rule": CACHED_RULE, "coverage": cov, "covered_subset": head, "examples": ex}


# ---------------------------------------------------------------- report
def fmt(v, pct=True):
    return "—" if v is None else (f"{v * 100:.1f}%" if pct else f"{v}")


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--llm", action="store_true", help="add Claude extraction (needs ANTHROPIC_API_KEY; costs money)")
    ap.add_argument("--cached-llm", action="store_true",
                    help="free: use only Claude extractions already cached (partial coverage, fixed 'either' rule)")
    a = ap.parse_args(argv)
    out = OUT.with_name("forecast_eval_llm_cached.json") if a.cached_llm else OUT

    P, pdis = pack_triaged()
    th = tune_threshold(P)                     # data-pack TRAIN only: the deployed threshold
    F, fdis = forecast_triaged()
    flag_col = "triage"
    llm = None
    if a.llm:
        F, rule, V = with_claude(F, th)
        llm = {"rule_chosen_on_forecast_train": rule, "variants": V}
    elif a.cached_llm:
        F, llm = cached_claude(F, th)

    base = evaluate(P, pdis, th, PACK_TEST_START)
    fc = evaluate(F, fdis, th, FC_TEST_START, flag_col)
    rep = {
        "what": "Co-pilot run unchanged on generated forecast data (news_claude.csv) vs signal_labels.csv",
        "threshold": th, "threshold_source": "tune_threshold on the data pack's train split (as deployed)",
        "mode": "rules + Claude" if a.llm else "rules + cached Claude (partial)" if a.cached_llm else "rules only",
        "llm": llm,
        "notes": ["Forecast data has news only; the data-pack baseline also includes weather alerts and trade notices.",
                  "Detection counts a disruption as caught when at least one of its labelled signals is in an alert "
                  "before the disruption starts. Sudden events (warned = false) cannot be caught before impact.",
                  "alerts_per_week counts every alert (inbox and watch log)."],
        "forecast": {"overall": fc["overall"], "test": fc["test"], "per_disruption": fc["per_disruption"],
                     "breakdowns": breakdowns(F, fdis, flag_col), "worst": worst(F, flag_col)},
        "data_pack_baseline": {"overall": base["overall"], "test": base["test"]},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    _print(rep, out)
    if a.cached_llm:
        _print_cached(llm)
    return rep


def _print_cached(llm: dict) -> None:
    c = llm["coverage"]
    print(f"\nClaude coverage (cache only, no API calls): {c['overall']['unique_extracted']} of {c['overall']['unique_texts']} unique texts")
    for s, v in c["by_split"].items():
        print(f"  {s:6} {v['with_claude']:>4}/{v['signals']:<5} signals · {v['relevant_with_claude']}/{v['relevant']} relevant ones")
    print("  by style: " + ", ".join(f"{k} {v['with_claude']}/{v['signals']}" for k, v in c["by_style"].items()))
    print(f"\nHead to head on the signals Claude read (rule fixed in advance: {llm['rule']})")
    print(f"  {'':8} {'rule':8} {'n':>5} {'rel':>4} {'tp':>4} {'fp':>4} {'fn':>4} {'precision':>10} {'recall':>8} {'F1':>7}")
    for split, rules in llm["covered_subset"].items():
        for r, m in rules.items():
            print(f"  {split:8} {r:8} {m['n']:>5} {m['relevant']:>4} {m['tp']:>4} {m['fp']:>4} {m['fn']:>4} "
                  f"{fmt(m['precision']):>10} {fmt(m['recall']):>8} {fmt(m['f1']):>7}")
    ex = llm["examples"]
    print("\nClaude caught, word list missed (relevant):")
    for r in ex["claude_added_true"]:
        print(f"  [{r['style']}] {str(r['headline'])[:100]}")
    print("Claude flagged, not relevant (new false alarms):")
    for r in ex["claude_added_false"]:
        print(f"  [{r['style']}] {str(r['headline'])[:100]}")


def _print(rep: dict, out: Path = OUT) -> None:
    f, b = rep["forecast"], rep["data_pack_baseline"]
    print(f"\nForecast held-out evaluation · {rep['mode']} · threshold {rep['threshold']} (from data-pack train)\n")
    print(f"{'Triage (score ≥ threshold)':34} {'forecast all':>13} {'forecast test':>14} {'pack all':>10} {'pack test':>10}")
    for k in ("precision", "recall", "f1", "accuracy", "false_positive_rate"):
        print(f"  {k:32} {fmt(f['overall']['triage'][k]):>13} {fmt(f['test']['triage'][k]):>14} "
              f"{fmt(b['overall']['triage'][k]):>10} {fmt(b['test']['triage'][k]):>10}")
    for k in ("precision_95ci", "recall_95ci"):
        c = lambda x: "—" if not x else f"{x[0] * 100:.0f}–{x[1] * 100:.0f}%"  # noqa: E731
        print(f"  {k:32} {c(f['overall']['triage'][k]):>13} {c(f['test']['triage'][k]):>14} "
              f"{c(b['overall']['triage'][k]):>10} {c(b['test']['triage'][k]):>10}")
    for s in ("overall", "test"):
        t = f[s]["triage"]
        print(f"  confusion {s:8} tp {t['tp']}  fp {t['fp']}  fn {t['fn']}  tn {t['tn']}")
    print(f"\n{'Signals in an alert (T9 definition)':34}")
    for k in ("precision", "recall", "f1"):
        print(f"  {k:32} {fmt(f['overall']['alerted'][k]):>13} {fmt(f['test']['alerted'][k]):>14} "
              f"{fmt(b['overall']['alerted'][k]):>10} {fmt(b['test']['alerted'][k]):>10}")
    print(f"\n{'Event detection':34}")
    for k, pct in (("share_caught", True), ("share_of_warned_caught", True), ("median_lead_days", False),
                   ("p10_lead_days", False), ("p90_lead_days", False), ("alerts_per_week", False), ("alert_precision", True)):
        print(f"  {k:32} {fmt(f['overall']['detection'][k], pct):>13} {fmt(f['test']['detection'][k], pct):>14} "
              f"{fmt(b['overall']['detection'][k], pct):>10} {fmt(b['test']['detection'][k], pct):>10}")
    d = f["overall"]["detection"]
    print(f"  caught {d['caught_before_impact']} of {d['disruptions']} disruptions ({d['warned']} had a public warning)")
    print("\nBy headline style (forecast, all signals)")
    print(f"  {'style':12} {'n':>5} {'relevant':>9} {'precision':>10} {'recall':>8} {'F1':>7}")
    for s, m in sorted(f["breakdowns"]["overall"]["by_style"].items(), key=lambda x: (x[1]["recall"] is None, -(x[1]["recall"] or 0))):
        print(f"  {s:12} {m['n']:>5} {m['relevant']:>9} {fmt(m['precision']):>10} {fmt(m['recall']):>8} {fmt(m['f1']):>7}")
    print("\nRecall by disruption type (forecast, all signals)")
    for t, m in sorted(f["breakdowns"]["overall"]["recall_by_event_type"].items(), key=lambda x: x[1]["recall"] or 0):
        print(f"  {t:22} {m['caught']:>4}/{m['relevant']:<4} {fmt(m['recall']):>7}")
    print("\n20 worst misses (relevant, not flagged)")
    for r in f["worst"]["false_negatives"]:
        print(f"  {r['signal_id']} [{r['style']}] score {r['score']:+.1f} · {str(r['headline'])[:110]}")
    print("\n20 worst false alarms (flagged, not relevant)")
    for r in f["worst"]["false_positives"]:
        print(f"  {r['signal_id']} [{r['style']}] score {r['score']:+.1f} · {str(r['headline'])[:110]}")
    print(f"\nWritten: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

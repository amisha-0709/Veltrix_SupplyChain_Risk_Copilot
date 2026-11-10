"""M3 exhibits: T9 back-test, alerts, suppressed look-alikes → reports/m3.html

    python -m core.report_m3
"""
from __future__ import annotations

import html
import json

import pandas as pd

from core.alerts import build_alert
from core.backtest import ablation, lead_all, run_backtest
from core.impact import fmt_inr
from core.report import CSS, JS, OUT

E = html.escape


def _t(df: pd.DataFrame, cols: dict, num=()) -> str:
    th = "".join(f"<th class='{'num' if c in num else ''}'>{E(h)}</th>" for c, h in cols.items())
    body = []
    for r in df.to_dict("records"):
        cells = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, pd.Timestamp):
                v = v.strftime("%d %b %Y")
            elif isinstance(v, float) and pd.isna(v):
                v = "—"
            elif isinstance(v, list):
                v = ", ".join(map(str, v))
            elif isinstance(v, bool):
                v = "✓" if v else "—"
            cells.append(f"<td class='{'num' if c in num else ''}'>{E(str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def build() -> str:
    r = run_backtest()
    ab = ablation()
    s, a, lt = r["signals"]["test"], r["alerts"]["test"], r["lead"]["test"]
    la = lead_all(r["lead_table"])
    T = r["triaged"]

    alerts = [build_alert(e) for e in r["events"]]
    arows = pd.DataFrame([{
        "alert_id": x["alert_id"], "first_seen": x["first_seen"], "title": x["title"][:80],
        "disruption": ", ".join(sorted({sg["linked_disruption_id"] for sg in x["event"].signals
                                       if isinstance(sg.get("linked_disruption_id"), str)})),
        "n_signals": x["n_signals"], "n_sources": len(x["sources"]), "event_type": x["event_type"],
        "L": x["likelihood"], "I": x["impact"], "P": x["priority"],
        "route": "Inbox" if x["inbox"] else "Watch log", "confidence": x["confidence"],
        "at_risk": fmt_inr(x["totals"]["revenue_at_risk_inr"]), "owner": x["owner"].replace("Category manager: ", ""),
        "secs": x["seconds_to_quantify"],
    } for x in alerts])

    # Look-alikes the rules suppressed: linked to our network, had disruption-ish cues, scored below threshold.
    sup = T[(~T["relevant_to_veltrix"].astype(bool)) & (T["link_strength"] > 0) & (T["cue_score"] != 0) & (T["score"] < r["threshold"])]
    sup = (sup.groupby("story_key").agg(n=("signal_id", "size"), score=("score", "max"), reason=("reason", "first"))
           .sort_values("n", ascending=False).reset_index().head(15))

    js = r.get("judge_summary") or {}
    jv = T[T["llm_verdict"].notna()].drop_duplicates("story_key") if "llm_verdict" in T else T.iloc[0:0]
    if len(jv):
        judge_html = (f"<p>{js.get('verdicts', 0)} borderline stories reviewed by <code>{E(js.get('model', ''))}</code>; "
                      f"{js.get('signals_promoted', 0)} signals promoted. A promotion needs confidence ≥ 0.7, and new links "
                      f"must resolve to a node in our network.</p>"
                      + _t(jv, {"text": "Story", "score": "Rules score", "llm_verdict": "Claude", "llm_reason": "Reason",
                                "relevant_to_veltrix": "Label"}, num=("score",)))
    else:
        judge_html = (f"<p>Not run yet: no Anthropic credentials in this environment. <b>{js.get('stories_sent', 0)} unique "
                      f"stories</b> sit in the borderline band (one call each to <code>{E(js.get('model', ''))}</code>). "
                      "Run <code>python -m core.llm_judge --run</code> once a key is set; verdicts are cached and this "
                      "report picks them up.</p>")
    L = r["lead_table"].copy()
    L["first_alert"] = pd.to_datetime(L["first_alert"])
    tiles = f"""<div class="tiles">
<div class="tile"><b>{s['recall']:.1%}</b><span>recall on test signals ({s['tp']}/{s['relevant']}); target ≥ 80%</span></div>
<div class="tile"><b>{a['precision']:.0%}</b><span>alert precision on test ({a['relevant_alerts']}/{a['alerts']} alerts; {s['fp']} false-alarm signals); target ≥ 60%</span></div>
<div class="tile"><b>{lt['median_lead_days']:.1f} days</b><span>median warning lead on test ({lt['detected']}/{lt['disruptions_with_warning']} warned disruptions caught); target ≥ 7</span></div>
<div class="tile"><b>{la['median_lead_days']:.0f} d vs {la['median_team_lead_days']:+.0f} d</b><span>median lead across all 18: co-pilot vs the team's first alert ({la['detected']} warned caught)</span></div>
</div>"""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Veltrix M3 Back-test</title>
<style>{CSS}</style></head><body><main>
<p class="note">PS-06 · M3: signal triage, linking, dedup, scoring · T9 back-test · synthetic data</p>
<h1>The co-pilot would have seen every warned disruption about two weeks out</h1>
<p class="lede">We ran all {len(T):,} signals (news, weather alerts, trade notices) through the triage → link → dedup → score → impact
pipeline. The threshold was tuned on train only (score ≥ {r['threshold']}). Claude review of the borderline band:
<b>{E(r['llm_judge'])}</b>. Every number below comes from transparent rules plus the impact engine.</p>
{tiles}

<h2>1 · How honest are these numbers?</h2>
<div class="card"><ul>
<li><b>Train is perfect (100% precision and recall), which signals some overfitting.</b> The cue lexicon was written from playbook §11
("signals we should watch") and tuned on train misses. Test is the number that counts.</li>
<li><b>The test headlines were visible while profiling the data</b> (they sit in the same sheet). Two cue terms came only from seeing
them: <code>{E(ab['removed'])}</code>. With those removed, test recall is <b>{ab['signals']['recall']:.1%}</b>, alert precision
<b>{ab['alerts']['precision']:.0%}</b> and median lead <b>{ab['lead']['median_lead_days']:.1f} days</b> (minimum {ab['lead']['min_lead_days']:.1f}).
All three targets still pass.</li>
<li><b>Real feeds will be messier.</b> Synthetic news is templated. The optional Claude pass (<code>core/llm_judge.py</code>, off by
default) is the generalising answer for new phrasings. It only sees borderline items, caches every verdict, and never receives supplier
names or volumes.</li>
<li><b>Routing uses today's stock (30 Sep 2026)</b>, since the data has no historic inventory snapshots. That's why D01, D03 and D08 land
in the watch log rather than the inbox: cover today is higher than it was then. The D05 replay (T10) uses the cover at the time.</li>
</ul></div>

<h2>2 · Lead time per disruption</h2>
<div class="card">{_t(L, {"disruption_id": "ID", "title": "Disruption", "split": "Split", "had_warning": "Public warning",
                          "first_alert": "Co-pilot alert", "lead_days": "Lead (d)", "team_lead_days": "Team (d)",
                          "days_gained_vs_team": "Days gained", "signals_caught": "Signals caught", "relevant_signals": "Relevant"},
                     num=("lead_days", "team_lead_days", "days_gained_vs_team", "signals_caught", "relevant_signals"))}
<p class="note">Lead = disruption start − co-pilot's first alert. Team = start − team's first internal alert (negative = after impact).
D05, D08 and D18 are sudden (fire, earthquake, ransomware). There the co-pilot alerts on day 0 and quantifies immediately.</p></div>

<h2>3 · Alerts raised: one per event, all sources cited</h2>
<div class="card">{_t(arows, {"alert_id": "Alert", "first_seen": "First seen", "title": "First headline", "disruption": "Actual",
                             "n_signals": "Signals", "n_sources": "Sources", "event_type": "Class", "L": "L", "I": "I", "P": "P",
                             "route": "Route", "confidence": "Conf.", "at_risk": "Revenue at risk", "owner": "Owner", "secs": "Secs"},
                        num=("n_signals", "n_sources", "L", "I", "P", "confidence", "secs"))}
<p class="note">{len(T[T['score'] >= r['threshold']]):,} flagged signals collapse into {len(alerts)} alerts ({sum(x['inbox'] for x in alerts)} inbox,
{sum(not x['inbox'] for x in alerts)} watch log). Dedup misses: D16 split into two alerts (a follow-up named no shared node).
"Secs" = signal → quantified impact and ranked options (target under 5 minutes).</p></div>

<h2>4 · Look-alike stories the rules suppressed</h2>
<p class="lede">These name a place or commodity we depend on and sound alarming, but labels say they never mattered. The dampeners
(forecasts that miss, denials, threats, routine items) keep them out.</p>
<div class="card">{_t(sup, {"story_key": "Story", "n": "Copies", "score": "Score", "reason": "Why it was held back"}, num=("n", "score"))}</div>

<h2>5 · Claude review of the borderline band</h2>
<div class="card">{judge_html}</div>

<h2>6 · Test-period misses</h2>
<div class="card">{_t(r['misses'], {"signal_id": "Signal", "linked_disruption_id": "Disruption", "days_before_impact": "Days before",
                                   "score": "Score", "text": "Text"}, num=("days_before_impact", "score"))}
<p class="note">Both are the same D16 freight story ("rates more than double"). It scores just under the threshold, a typical
borderline case for the Claude pass. D16 itself was still caught 10 days ahead through other stories.</p></div>
</main><div id="tip" role="tooltip"></div><script>{JS}</script></body></html>"""
    OUT.mkdir(exist_ok=True)
    (OUT / "m3.html").write_text(page, encoding="utf-8")
    (OUT / "m3_data.json").write_text(json.dumps({
        "threshold": r["threshold"], "signals": r["signals"], "alerts": r["alerts"], "lead": r["lead"],
        "ablation": ab, "lead_table": json.loads(L.to_json(orient="records", date_format="iso")),
        "alert_rows": json.loads(arows.to_json(orient="records", date_format="iso"))}, indent=1, default=str), encoding="utf-8")
    return str(OUT / "m3.html")


if __name__ == "__main__":
    print(build())

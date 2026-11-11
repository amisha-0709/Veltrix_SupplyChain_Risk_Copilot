"""Conversational layer: answer supply-risk questions with the impact engine, showing the working.

    from core.ask import ask
    ask("Which customers miss their 95% OTIF target if Penang semiconductor output stops for six weeks?")

Deterministic: the question is parsed (places/commodities via the network gazetteer, duration, intent),
then answered by the same engine that quantifies alerts, so the chat can never contradict a briefing.
Every answer returns its working and assumptions. Unclear questions get a clarification, not a guess.

Intents
  what_if      "Which products stop first if Kaohsiung closes for ten days?" / "...if Penang output stops 6 weeks"
  exposure     "How exposed are we to Shanghai?" / "What depends on the Red Sea?"
  alerts       "What's open right now?" / "Show the inbox"
  options      "What should we do about AL-005?"
"""
from __future__ import annotations

import re

import pandas as pd

from core.graph import build_network
from core.impact import Scenario, fmt_inr, run

UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
         "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
OTHER = {"a": 1, "an": 1, "a couple of": 2}
NUM_WORDS = {**UNITS, **TEENS, **TENS, **OTHER}
_NUM = (r"\d+(?:\.\d+)?|(?:" + "|".join(TENS) + r")(?:[\s-](?:" + "|".join(UNITS) + r"))?|"
        + "|".join(sorted(list(TEENS) + list(UNITS) + list(OTHER), key=len, reverse=True)))
DUR_RE = re.compile(r"\b(" + _NUM + r")[\s-]*(day|week|month)s?\b", re.I)
FORTNIGHT = re.compile(r"\b(a|one|two|\d+)\s+fortnights?\b", re.I)
# "for <words> days/weeks/months" that we could not read as a number → ask, never guess
UNREAD_DUR = re.compile(r"\b(?:for|lasting|over|about|around)\s+((?:[a-z]+[\s-]){0,2}?[a-z]+)\s+(?:days?|weeks?|months?)\b", re.I)

WHAT_IF = re.compile(r"\bif\b|\bwhat happens\b|\bsuppose\b|\bwhat would\b|\bstops?\b|\bcloses?\b|\bshut", re.I)
EXPOSURE = re.compile(r"exposed|exposure|depend|reliant|rely|single[- ]source|concentrat", re.I)
ALERTS = re.compile(r"\b(open|inbox|alerts?|risks?|register|right now|this week|this month)\b", re.I)
ALERT_ID = re.compile(r"\b(AL-\d{3}|SIM-AL-\d{3})\b", re.I)
SUPPLIER_WORDS = re.compile(r"output|supplier|plant|factory|fab|maker|production|cyber|fire|strike|insolven", re.I)
ROUTE_WORDS = re.compile(r"strait|canal|red sea|suez|malacca|route|lane", re.I)
CONGESTION_WORDS = re.compile(r"congest|slow|delay", re.I)


def _number(raw: str) -> float:
    raw = raw.lower().replace("-", " ").strip()
    if raw in NUM_WORDS:
        return float(NUM_WORDS[raw])
    parts = raw.split()
    if len(parts) == 2 and parts[0] in TENS and parts[1] in UNITS:
        return float(TENS[parts[0]] + UNITS[parts[1]])
    return float(raw)


def _duration_days(q: str) -> float | None:
    m = DUR_RE.search(q)
    if m:
        unit = m.group(2).lower()
        return _number(m.group(1)) * (7 if unit == "week" else 30 if unit == "month" else 1)
    f = FORTNIGHT.search(q)
    if f:
        k = f.group(1).lower()
        return 14.0 * (1 if k in ("a", "one") else 2 if k == "two" else float(k))
    return None


def _unread_duration(q: str) -> str | None:
    """A duration phrase is present but we couldn't read the number (e.g. 'a few weeks', 'several months')."""
    if _duration_days(q) is not None:
        return None
    m = UNREAD_DUR.search(q)
    return m.group(0) if m else None


def _event_type(q: str, nodes: list[str]) -> str:
    if ROUTE_WORDS.search(q) and any(n.startswith("choke:") for n in nodes):
        return "route"
    if SUPPLIER_WORDS.search(q) or any(n.startswith("sup:") for n in nodes):
        return "supplier_outage"
    if CONGESTION_WORDS.search(q):
        return "congestion"
    return "port_closure"


def _scope(nodes: list[str]) -> tuple[list[str], str, str | None]:
    """Places + commodity → intersect (Penang ∩ Semiconductors); otherwise union.

    If the intersection is empty (e.g. Chakan ∩ Magnets: Chakan is where we build, not where magnets come from),
    fall back to the commodity alone and say so, rather than reporting that nothing is exposed."""
    places = [n for n in nodes if not n.startswith(("cat:", "country:"))]
    cats = [n for n in nodes if n.startswith("cat:")]
    countries = [n for n in nodes if n.startswith("country:")]
    net = build_network()

    def exp(ns):
        return set().union(*[net.parts_exposed(n) for n in ns])
    for other in (places, countries):
        if other and cats:
            ps = exp(other) & exp(cats)
            if ps:
                return sorted(ps), "all", None
            if exp(cats):
                c = ", ".join(_node_name(n) for n in cats)
                o = ", ".join(_node_name(n) for n in other)
                return (sorted(exp(cats)), "cats",
                        f"No {c} part is supplied from or shipped through {o}, so I used every {c} part wherever it comes from.")
    use = places or cats or countries
    return (sorted(exp(use)) if use else []), "any", None


def _node_name(n: str) -> str:
    return n.split(":", 1)[1]


def _table(title: str, df: pd.DataFrame, cols: dict) -> dict:
    d = df[list(cols)].copy() if len(df) else pd.DataFrame(columns=list(cols))
    rows = []
    for r in d.to_dict("records"):
        row = []
        for c in cols:
            v = r[c]
            if c.endswith("_inr"):
                v = fmt_inr(v)
            elif isinstance(v, float):
                v = round(v, 1)
            row.append(v)
        rows.append(row)
    return {"title": title, "columns": list(cols.values()), "rows": rows}


# ---------------------------------------------------------------------------------------------
def answer_what_if(q: str, nodes: list[str]) -> dict:
    dur = _duration_days(q)
    unread = _unread_duration(q)
    if unread:
        return {"intent": "clarify", "answer": f"I couldn't read how long \"{unread}\" is, so I won't guess a duration. "
                "Please give a number, e.g. \"for 40 days\" or \"for six weeks\".", "tables": [], "working": [],
                "assumptions": []}
    et = _event_type(q, nodes)
    parts, how, scope_note = _scope(nodes)
    if not parts:
        return {"intent": "clarify", "answer": "I couldn't link " + ", ".join(_node_name(n) for n in nodes)
                + " to any part we buy, so I can't say what would stop. Try naming the supplier's country, port or the "
                "commodity.", "tables": [], "working": [], "assumptions": []}
    if dur is None:
        sc = Scenario(parts=parts, nodes=nodes, event_type=et, label=q)
        dur_note = "No duration given: used the typical duration for this kind of event from history."
    else:
        # The user states how long supply stops: use it as the effective delay (no extra recovery assumed).
        sc = Scenario(parts=parts, nodes=nodes, event_type=et, delay_days=dur, label=q)
        dur_note = f"Supply assumed stopped for exactly {dur:g} days as asked (no extra recovery time added)."
    r = run(sc)
    t = r.totals
    S = r.skus[r.skus["units_short"] > 0].copy() if len(r.skus) else r.skus
    if len(S):
        S = S.sort_values(["stops_from_day", "revenue_at_risk_inr"], ascending=[True, False])
    O = r.otif
    below = O[O["below_target"]] if len(O) else O
    where = (" ∩ ".join(_node_name(n) for n in nodes) if how == "all"
             else ", ".join(_node_name(n) for n in nodes if n.startswith("cat:")) if how == "cats"
             else ", ".join(_node_name(n) for n in nodes))

    if t["no_action_needed"]:
        ans = (f"Nothing stops. {t['parts_affected']} part(s) depend on {where}, and the lowest cover is "
               f"{t['min_cover_days']} days against a {r.parts['effective_delay_days'].max():g}-day delay"
               + (". Finished goods absorb the small gap" if t["parts_short"] else "") + ". "
               f"{fmt_inr(t['revenue_exposed_per_day_inr'])}/day of revenue depends on these parts.")
    else:
        first = S.iloc[0]
        cust = below.groupby("customer").agg(weeks=("week_start", "nunique"), worst=("otif", "min"),
                                             first=("week_start", "min")).reset_index() if len(below) else pd.DataFrame()
        ans = (f"{t['skus_stopped']} product(s) stop. First to stop: {first['sku_id']} ({first['customer']}) from day "
               f"{first['stops_from_day']:.0f}, when {first['binding_part']} runs out. "
               f"{fmt_inr(t['revenue_at_risk_inr'])} revenue at risk ({fmt_inr(t['revenue_lost_inr'])} lost sales, "
               f"{fmt_inr(t['margin_at_risk_inr'])} margin). ")
        if len(cust):
            ans += (f"{len(cust)} customer(s) miss the 95% OTIF target: "
                    + "; ".join(f"{c.customer} for {c.weeks} week(s), worst {c.worst:.0%}" for c in cust.itertuples()) + ".")
        else:
            ans += "No customer falls below 95% OTIF."
    recovery_note = None
    if dur is not None:
        # Briefings and 'Try a signal' add the typical recovery time after supply restarts. Show that reading too,
        # so the same scenario never shows two unexplained numbers in two places.
        r2 = run(Scenario(parts=parts, nodes=nodes, event_type=et, duration_days=dur, label=q))
        d2 = float(r2.parts["effective_delay_days"].max()) if len(r2.parts) else dur
        if abs(d2 - dur) >= 1:
            lead = (f"Allowing the typical recovery time after supply restarts, as alert briefings do "
                    f"({dur:g} d → {d2:g} d): ")
            recovery_note = lead + ("still nothing stops." if r2.totals["no_action_needed"] else
                                    f"{fmt_inr(r2.totals['revenue_at_risk_inr'])} revenue at risk, "
                                    f"{fmt_inr(r2.totals['margin_at_risk_inr'])} margin.")
            ans += " " + recovery_note
    if scope_note:
        ans = scope_note + " " + ans
    tables = []
    if len(S):
        tables.append(_table("Products that stop (first to stop at the top)", S, {
            "sku_id": "SKU", "customer": "Customer", "binding_part": "Binding part", "stops_from_day": "Stops from day",
            "shortage_days": "Short (d)", "units_short": "Units short", "revenue_at_risk_inr": "Revenue at risk"}))
    if len(below):
        wk = below.pivot_table(index="customer", columns="week_start", values="otif", aggfunc="min")
        wk = wk.map(lambda v: f"{v:.0%}" if pd.notna(v) else "")
        tables.append({"title": "Weeks below 95% OTIF, by customer", "columns": ["Customer"] + [str(c) for c in wk.columns],
                       "rows": [[i] + list(r) for i, r in wk.iterrows()]})
    tables.append(_table("Parts in scope", r.parts, {
        "part_id": "Part", "description": "Description", "days_of_cover": "Cover (d)",
        "effective_delay_days": "Delay (d)", "shortage_days": "Short (d)"}))
    return {"intent": "what_if", "answer": ans, "tables": tables, "working": r.working,
            "assumptions": [f"Scope: parts whose primary supplier ships from/through {where}."]
            + ([scope_note] if scope_note else []) + [dur_note] + ([recovery_note] if recovery_note else []) + [
                            f"Event class: {et.replace('_', ' ')}.", "Stock: on hand + in transit, 30 Sep 2026.",
                            "Start date: the stock snapshot date; weeks are counted from there."],
            "scenario": {"nodes": nodes, "parts": parts, "event_type": et, "duration_days": dur}}


def answer_exposure(q: str, nodes: list[str]) -> dict:
    from core.exposure import part_exposure
    parts, how, scope_note = _scope(nodes)
    pe = part_exposure()
    d = pe[pe["part_id"].isin(parts)].copy()
    where = " ∩ ".join(_node_name(n) for n in nodes) if how == "all" else ", ".join(_node_name(n) for n in nodes)
    if d.empty:
        return {"intent": "clarify", "answer": f"I couldn't link {where} to any part we buy, so I can't size the exposure.",
                "tables": [], "working": [], "assumptions": []}
    ss = d[d["single_source"]]
    skus = sorted({s for lst in d["skus"] for s in lst})
    below = ss[ss["cover_below_lead_time"]]
    ans = (f"{len(d)} part(s) depend on {where} ({len(ss)} single-source), feeding {len(skus)} product(s). "
           f"Annual spend ₹{d['annual_spend_inr_cr'].sum():.1f} cr. "
           + (f"{len(below)} single-source part(s) have less cover than their lead time: "
              + ", ".join(f"{r.part_id} ({r.days_of_cover:.0f} d vs {r.lead_time_days:.0f} d)" for r in below.itertuples())
              + "." if len(below) else "Every single-source part here has cover above its lead time."))
    d["fallback"] = [("qualified " + a) if isinstance(a, str) else ("unqualified " + b) if isinstance(b, str) else "none"
                     for a, b in zip(d["qualified_alternate_supplier_id"], d["unqualified_alternate_supplier_id"])]
    if scope_note:
        ans = scope_note + " " + ans
    return {"intent": "exposure", "answer": ans, "working": [], "assumptions": ["Stock: 30 Sep 2026 snapshot."],
            "tables": [_table("Parts", d.sort_values("fragility", ascending=False), {
                "part_id": "Part", "description": "Description", "supplier_name": "Supplier", "single_source": "Single source",
                "days_of_cover": "Cover (d)", "lead_time_days": "Lead (d)", "n_skus": "SKUs",
                "revenue_dependent_inr_cr": "Revenue dep. (₹ cr/yr)", "fallback": "Fallback"})]}


def answer_alerts(alerts: list[dict]) -> dict:
    inbox = [a for a in alerts if a.get("inbox")]
    inbox.sort(key=lambda a: -a["priority"])
    if not inbox:
        return {"intent": "alerts", "answer": "No alerts in the inbox.", "tables": [], "working": [], "assumptions": []}
    ans = (f"{len(inbox)} alert(s) need an owner. Highest: {inbox[0]['alert_id']} {inbox[0]['title']} "
           f"(priority {inbox[0]['priority']}, {inbox[0]['revenue_at_risk_fmt']} at risk).")
    return {"intent": "alerts", "answer": ans, "working": [], "assumptions": [],
            "tables": [{"title": "Inbox", "columns": ["Alert", "Priority", "Title", "At risk", "Owner", "Response"],
                        "rows": [[a["alert_id"], a["priority"], a["title"], a["revenue_at_risk_fmt"], a["owner"],
                                  a["response"]] for a in inbox]}]}


def answer_options(alert: dict) -> dict:
    o = pd.DataFrame(alert["options"])
    b = alert["brief"]
    return {"intent": "options", "answer": f"{alert['alert_id']}: {b['headline_impact']} {b['ask']}",
            "working": alert.get("working", []), "assumptions": b.get("caveats", []),
            "tables": [_table("Ranked options (recommended, not approved)", o.head(8), {
                "rank": "#", "part_id": "Part", "option": "Option", "time_to_effect_days": "Effect (d)",
                "cost_inr": "Cost", "net_value_inr": "Net value", "approver": "Approver"})] if len(o) and "rank" in o else []}


HELP = ("I can answer questions like:\n"
        "• Which products stop first if Kaohsiung closes for ten days?\n"
        "• Which customers miss their 95% OTIF target if Penang semiconductor output stops for six weeks?\n"
        "• How exposed are we to Shanghai?\n"
        "• What's in the inbox right now?\n"
        "• What should we do about AL-005?")


def ask(question: str, alerts: list[dict] | None = None, get_alert=None) -> dict:
    q = question.strip()
    if len(q) < 4:
        return {"intent": "help", "answer": HELP, "tables": [], "working": [], "assumptions": []}
    m = ALERT_ID.search(q)
    if m and get_alert is not None:
        a = get_alert(m.group(1).upper())
        if a:
            return answer_options(a)
    nodes = [h["node"] for h in build_network().match(q)]
    if nodes and WHAT_IF.search(q):
        return answer_what_if(q, nodes)
    if nodes and EXPOSURE.search(q):
        return answer_exposure(q, nodes)
    if nodes:
        return answer_what_if(q, nodes) if _duration_days(q) else answer_exposure(q, nodes)
    if ALERTS.search(q) and alerts is not None:
        return answer_alerts(alerts)
    return {"intent": "clarify",
            "answer": "I couldn't link that to a supplier, port, lane, country or commodity in Veltrix's network, "
                      "so I won't guess. Try naming a place or commodity.\n\n" + HELP,
            "tables": [], "working": [], "assumptions": []}


if __name__ == "__main__":
    for q in ["Which customers miss their 95% OTIF target if Penang semiconductor output stops for six weeks?",
              "Which products stop first if Kaohsiung closes for ten days?",
              "Which products stop first if Kaohsiung closes for thirty days?",
              "How exposed are we to Shanghai?",
              "What if the Red Sea closes?",
              "What happens if Port Klang is congested for two weeks?",
              "Will it rain tomorrow?"]:
        r = ask(q)
        print(f"Q: {q}\n[{r['intent']}] {r['answer']}")
        for t in r["tables"][:2]:
            print("  ", t["title"], "|", t["columns"]); [print("    ", row) for row in t["rows"][:5]]
        print()

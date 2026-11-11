"""Fresh test round: 20 'Try a signal' + 20 'Ask the co-pilot' cases, none used in earlier rounds.

    python scripts/fresh40.py https://veltrix-risk-copilot.vercel.app reports/fresh40.json

Each case states the expected behaviour BEFORE running. The script records everything the live site returns;
grading is done afterwards by reading each answer (see reports/fresh40_report.html).
"""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE, OUT = sys.argv[1], sys.argv[2]

# (id, headline, snippet, expected decision: alert | ignore | review, expected link substring or None, why)
SIGNALS = [
    ("S01", "Typhoon set to batter southern Taiwan coast; Kaohsiung terminals prepare to close", "", "alert", "Kaohsiung",
     "Port we ship from, credible forecast of closure"),
    ("S02", "Fire breaks out at Rheinwerk Semiconductor fab in Dresden", "Production halted; damage being assessed.", "alert", "Rheinwerk",
     "Named supplier of ours, fire, production halted"),
    ("S03", "Busan dockworkers walk out; cranes idle at main container terminals", "", "alert", "Busan",
     "Strike happening at a port we ship from"),
    ("S04", "China announces export licences for gallium and germanium", "", "ignore", None,
     "Raw materials Veltrix doesn't buy"),
    ("S05", "Suez Canal blocked after container ship runs aground", "Dozens of vessels queue at both ends.", "alert", "Red Sea",
     "Chokepoint on our Europe lanes"),
    ("S06", "Singapore port congestion hits a record as vessels bunch up", "", "ignore", None,
     "Singapore is not on any Veltrix lane"),
    ("S07", "Magnitude 7.1 earthquake strikes near Hsinchu science park", "Fabs halt lines for safety inspections.", "alert", "Hsinchu",
     "Fab cluster we buy from"),
    ("S08", "Company denies rumours of a fire at its Penang plant", "", "ignore", None,
     "Denial of a rumour"),
    ("S09", "India imposes 25% safeguard duty on imported lithium-ion cells", "", "alert", "Li-ion",
     "Cost-only trade measure on a BOM commodity (watch log acceptable)"),
    ("S10", "Hai Phong port operations suspended for three days as floods hit northern Vietnam", "", "alert", "Hai Phong",
     "Port we ship from, closure happening"),
    ("S11", "Pune power utility warns of load shedding as heatwave builds next week", "", "alert", "Pune",
     "Our Pune suppliers, credible warning (watch acceptable)"),
    ("S12", "Electric two-wheeler sales hit a record in October", "", "ignore", None,
     "Market news, no disruption"),
    ("S13", "Cyber attack disrupts a major Japanese capacitor maker", "Shipments paused while systems are restored.", "alert", "Japan",
     "Japan ∩ passives; maker not named"),
    ("S14", "Typhoon to pass well east of Taiwan; no impact expected on shipping", "", "ignore", None,
     "Forecast that misses"),
    ("S15", "Red Sea shipping resumes as carriers return to the Suez route", "", "ignore", None,
     "Good news: disruption ending"),
    ("S16", "Korean battery maker's union threatens strike next month if talks fail", "", "ignore", None,
     "Threat only (watch acceptable)"),
    ("S17", "Customs server outage at Chennai and Nhava Sheva delays clearance for two days", "", "alert", "Nhava Sheva",
     "Both our Indian ports, happening"),
    ("S18", "Kaohsuing port closd as typhon makes landfal", "", "alert", "Kaohsiung",
     "Typos a real feed or user will produce"),
    ("S19", "ताइवान में भूकंप, काऊशुंग बंदरगाह बंद", "", "alert", "Kaohsiung",
     "Hindi: earthquake in Taiwan, Kaohsiung port closed"),
    ("S20", "Ningbo-Zhoushan port suspends operations ahead of Typhoon Bebinca", "", "alert", "Ningbo",
     "Port we ship from, under its full official name"),
]

# (id, question, expected behaviour)
QUESTIONS = [
    ("A01", "If Busan port shuts for 2 weeks what breaks?", "what-if Busan 14 d: products that stop / or nothing"),
    ("A02", "How much revenue depends on single-source parts from China?", "exposure China with revenue dependence"),
    ("A03", "What happens if Rheinwerk Semiconductor goes bankrupt?", "what-if on that supplier (supplier outage)"),
    ("A04", "Which alerts need a decision today?", "inbox, highlighting same-day response alerts"),
    ("A05", "What's the impact of a 10 day Suez closure on Ojas Motors specifically?", "what-if Red Sea 10 d, Ojas Motors' share"),
    ("A06", "Show me the options for AL-004", "AL-004 ranked options with approvers"),
    ("A07", "Is Trident Two-Wheelers exposed to anything right now?", "customer status Trident"),
    ("A08", "What if Port Klang and Penang both close for a week?", "one scenario with both ports, 7 d"),
    ("A09", "Which parts have less than 14 days of cover?", "list of parts with cover < 14 d"),
    ("A10", "kya hoga agar shanghai port 3 hafte band rahe", "what-if Shanghai 21 d"),
    ("A11", "What did the Red Sea crisis cost us?", "D03's recorded loss"),
    ("A12", "Which supplier should we qualify first?", "structural moves: SUP-011 for PRT-004"),
    ("A13", "What is the payback period of this co-pilot?", "business case: payback in months"),
    ("A14", "Compare a 30-day Kaohsiung closure with a 30-day Shanghai closure", "two what-ifs, 30 d each"),
    ("A15", "What happens to magnet supply if China bans rare-earth exports for 3 months?", "what-if China magnets 90 d, trade"),
    ("A16", "How exposed are we to the Strait of Malacca?", "exposure Malacca"),
    ("A17", "What's the stock cover on PRT-043?", "cover days for that part"),
    ("A18", "Delete all the alerts", "refuse / can't act"),
    ("A19", "Who approves an air-freight expedite costing ₹80 lakh?", "approval matrix: Head of Supply Chain (50 lakh-2 cr)"),
    ("A20", "What happens if the Hosur plant area floods for 5 days?", "what-if Bengaluru/Hosur 5 d"),
]


def post(path, body, extra=None):
    h = {"Content-Type": "application/json", "X-Copilot-Session": "fresh-" + uuid.uuid4().hex[:12], **(extra or {})}
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST", headers=h)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read()), round(time.time() - t, 1)
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}, round(time.time() - t, 1)


out = {"signals": [], "questions": []}
for sid, head, snip, exp, link, why in SIGNALS:
    code, r, secs = post("/api/simulate", {"headline": head, "snippet": snip})
    a = r.get("alert") or {}
    x = r.get("extraction") or {}
    rec = {"id": sid, "headline": head, "expected": exp, "expected_link": link, "why": why, "status": code, "secs": secs,
           "decision": r.get("decision"), "message": r.get("message"), "score": (r.get("triage") or {}).get("score"),
           "links": (r.get("triage") or {}).get("links"), "event_type": (r.get("triage") or {}).get("event_type"),
           "priority": a.get("priority"), "revenue_at_risk": a.get("revenue_at_risk_fmt"), "owner": a.get("owner"),
           "ask": (a.get("brief") or {}).get("ask"),
           "claude": {k: x.get(k) for k in ("relevant", "status", "event_type", "duration_days", "geo_links", "cat_links")} if x else None,
           "claude_entities": x.get("entities") if x else None}
    out["signals"].append(rec)
    print(f"{sid} {rec['decision']:12s} exp={exp:6s} score={rec['score']} links={rec['links']} claude={(x or {}).get('relevant')}"
          f" {(x or {}).get('status')} :: {head[:60]}")

for qid, q, exp in QUESTIONS:
    code, r, secs = post("/api/ask", {"question": q})
    rec = {"id": qid, "question": q, "expected": exp, "status": code, "secs": secs, "engine": r.get("engine"),
           "engine_note": r.get("engine_note"), "interpretation": r.get("interpretation"), "answer": r.get("answer"),
           "tables": [t["title"] for t in r.get("tables", [])], "tool_calls": r.get("tool_calls")}
    out["questions"].append(rec)
    print(f"{qid} {secs:4.1f}s {r.get('engine')} {r.get('interpretation')} :: {(r.get('answer') or '')[:150]!r}")

json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved", OUT)

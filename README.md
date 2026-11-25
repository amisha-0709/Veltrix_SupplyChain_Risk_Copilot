# Veltrix Supply Chain Resilience Co-Pilot (PS-06)

Reads news, weather, port and trade-policy signals, links them to Veltrix's supplier → part → product network,
quantifies revenue / margin / OTIF impact with the playbook method, ranks mitigations by net value with the
required approver, and writes a one-page briefing per alert. **It recommends; people decide.** It never
orders, books freight or contacts suppliers. All data is synthetic (Veltrix Components is fictional).

## Project status: complete (final pitch delivered)

**Live:** https://veltrix-risk-copilot.vercel.app — role-based desks for the Category manager, Head of Supply Chain,
COO and Sales, plus Alerts, Live news, Risk register, Replay, Business case and the Ask bar.

**What it showed, replayed on Veltrix's 18 disruptions (Oct 2024 – Sep 2026):**
- ₹170.3 cr was lost; 15 of 18 disruptions were in the news first, a median 18 days before impact.
- With only what was known on the day, the co-pilot would have protected ₹59.1 cr: ₹11.03 cr a year net, 22.5× return including running costs.
- D04 (rare-earth magnets): alert on 28 Jan 2025, 19 days before impact; a ₹32.9 lakh plan protects about ₹13.5 cr (expected) of the ₹22.4 cr lost.

**Final pitch materials (`docs/`):**

| File | What |
|---|---|
| `Veltrix_CoPilot_Pitch.pdf` | the final pitch deck as presented |
| `Veltrix_CoPilot_Pitch.pptx` | editable deck: 21 click-by-click slides with speaker notes |
| `Veltrix_Pitch_and_Demo_Script.pdf` | pitch and 3-minute demo, line by line |
| `PITCH_AND_DEMO_SCRIPT.md` | the same script with speakers, timings and demo click paths |
| `DECK_PLAN_AND_PROMPT.md` | deck plan and slide-builder prompt |
| `EVALUATION.md` | evaluation notes |

**Next step for a real pilot:** 3 months on PCBs and semiconductors, with live feeds, a database for the decision
log (today it lives in `/tmp` on Vercel) and the persona sessions in `docs/persona_feedback_kit.md`.

**Team 6:** Amisha, Moksh Jain, Aryan Dewangan · Mentor: Abhishek Raj, EY.

## Run locally

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m uvicorn app:app --port 8000      # UI + API at http://localhost:8000
.venv/Scripts/python -m pytest -q                         # 114 tests: M1–M6, acceptance T1–T10, persona fixes, role nav, Claude chat (mocked)
```

## Rebuild data and reports (after changing rules or the engine)

```bash
.venv/Scripts/python -m core.etl          # data/raw/*.xlsx → data/processed/*.pkl
.venv/Scripts/python -m core.report       # reports/stage1.html  (exposure, timeline, first business case)
.venv/Scripts/python -m core.report_m2    # reports/m2.html      (impact engine validation, T1/T4–T8)
.venv/Scripts/python -m core.report_m3    # reports/m3.html      (T9 back-test)
.venv/Scripts/python -m core.report_m6   # reports/m6.html + coo_onepager.html (business case, structural, false alarms)
.venv/Scripts/python -m core.snapshot     # data/snapshot.json   (what the UI serves, incl. 18 replays and M6 data)
.venv/Scripts/python -m core.acceptance   # reports/acceptance.html (T1–T10 end to end through the API)
```

Copy `reports/*.html` into `public/reports/` after rebuilding them.

## Claude chat

Set `ANTHROPIC_API_KEY` (on Vercel: Project → Settings → Environment Variables, then redeploy). Limits: 20 Claude
answers per visitor per hour and 300 per server instance per day (`COPILOT_CHAT_PER_HOUR`, `COPILOT_CHAT_PER_DAY`);
beyond them, or on any error, the rule-based chat answers. Send `X-Copilot-Engine: rules` to force the rule engine.

```bash
.venv/Scripts/python scripts/claude_eval.py https://veltrix-risk-copilot.vercel.app reports/claude_eval.json   # 14 Claude questions, ~$0.06
.venv/Scripts/python scripts/persona40.py https://veltrix-risk-copilot.vercel.app reports/persona40_live.json  # 40 persona cases
```

## Deploy (Vercel)

Root `app.py` exposes the FastAPI `app`, and `public/` is served by Vercel's CDN. Runtime dependencies are in
`requirements.txt` (no pyarrow, no openpyxl). `.vercelignore` keeps raw data, tests and the venv out of the bundle.

```bash
npx vercel login
npx vercel deploy --prod
```

On Vercel the decision log is written to `/tmp`, which is per server instance and temporary. Use a database
for a real pilot.

## Layout

| Path | What |
|---|---|
| `core/etl.py`, `core/graph.py` | data pack → tables → network graph + gazetteer |
| `core/impact.py` | playbook §3 impact engine (cover vs delay, binding part, units, ₹, OTIF) |
| `core/mitigate.py` | playbook §4–7 options, net value, ROI, approval matrix |
| `core/triage.py`, `core/events.py`, `core/alerts.py` | signal triage, dedup into events, L×I scoring |
| `core/briefing.py` | one-page briefing (HTML + text), numbers straight from the engine |
| `core/backtest.py`, `core/validate_impact.py` | T9 back-test, D01–D18 impact validation |
| `core/llm_chat.py` | Claude chat: Claude (Sonnet 5.5) answers by calling the engine as tools; every number comes from a tool result |
| `core/ask.py` | rule-based chat: the fallback when there's no API key, Claude fails or a limit is hit; also the tools' backend |
| `core/replay.py` | T10 replay of any disruption as if live + structural counterfactual; business case |
| `core/acceptance.py` | brief §6 T1–T10 checks with evidence, end to end through the API |
| `core/roi.py`, `core/structural.py`, `core/false_alarms.py` | M6: co-pilot ROI with running costs, dual-sourcing / buffer moves, false-alarm ablations |
| `core/report_m6.py` | M6 report and the printable COO one-pager |
| `docs/persona_feedback_kit.md` | scripts and scoring sheet for the 3 persona sessions (results still to be collected) |
| `core/llm_judge.py` | optional Claude review of borderline signals (off by default) |
| `backend/main.py` | FastAPI: alerts, briefings, register, exposure, back-test, simulate, decisions |
| `public/` | web UI (no build step) |

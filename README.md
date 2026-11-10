# Veltrix Supply Chain Resilience Co-Pilot (PS-06)

Reads news, weather, port and trade-policy signals, links them to Veltrix's supplier → part → product network,
quantifies revenue / margin / OTIF impact with the playbook method, ranks mitigations by net value with the
required approver, and writes a one-page briefing per alert. **It recommends; people decide.** It never
orders, books freight or contacts suppliers. All data is synthetic (Veltrix Components is fictional).

## Run locally

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m uvicorn app:app --port 8000      # UI + API at http://localhost:8000
.venv/Scripts/python -m pytest -q                         # 52 tests: M1–M6 incl. acceptance scenarios T1–T10
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
| `core/ask.py` | conversational layer: what-ifs, exposure, inbox, options; answered by the engine with working |
| `core/replay.py` | T10 replay of any disruption as if live + structural counterfactual; business case |
| `core/acceptance.py` | brief §6 T1–T10 checks with evidence, end to end through the API |
| `core/roi.py`, `core/structural.py`, `core/false_alarms.py` | M6: co-pilot ROI with running costs, dual-sourcing / buffer moves, false-alarm ablations |
| `core/report_m6.py` | M6 report and the printable COO one-pager |
| `docs/persona_feedback_kit.md` | scripts and scoring sheet for the 3 persona sessions (results still to be collected) |
| `core/llm_judge.py` | optional Claude review of borderline signals (off by default) |
| `backend/main.py` | FastAPI: alerts, briefings, register, exposure, back-test, simulate, decisions |
| `public/` | web UI (no build step) |

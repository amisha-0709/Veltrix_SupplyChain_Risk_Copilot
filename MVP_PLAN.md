# Veltrix Supply Chain Resilience Co-Pilot — MVP Plan (PS-06)

## 0. What the MVP must prove

A Head of Supply Chain at Veltrix gets **one alert per real event, days before impact**, already quantified in ₹ and cover days, with ranked options and the named approver, as a one-page briefing they can forward. They also see a back-test showing it would have caught the test-period events with few false alarms.

Scope rule for the MVP (from the brief + the call with Abhishek):
- **Must-haves only** (triage, linking, impact, ranking, back-test, briefing, public URL), plus **dedup** and **chat**. Both are on the T3/T6 acceptance tests.
- Everything numeric is **deterministic code that shows its working**. The LLM classifies, extracts and writes prose. It never computes ₹.
- **Recommend, never act.** Never show an option as approved.

### Data facts that shape the design
| Fact | Design consequence |
|---|---|
| 3,609 signals, only 179 relevant (≈5%); test split (from 1 Feb 2026) has 43 relevant of 1,218 | Cheap gazetteer pre-filter first, LLM only on candidates. Tune on train, report on test. |
| ~160 "looks relevant" false alarms (e.g. T2 naval exercise) | LLM judge must check *does it touch a named node of ours*, not "is it dramatic". |
| Syndicated duplicates, missing snippets, UPPERCASE headlines | Normalize text, then cluster into events (T3). |
| 95.5% of lost revenue via single-source parts with cover < lead time | Impact engine works on the **binding (worst) part per SKU**, not part counts. |
| D05 fire, D08 quake, D18 ransomware have no warning | Value there = quantify on day one + rank options (T8, T10). |
| ₹4.6 cr of ₹7.0 cr mitigation spend was wasted where cover was enough | Engine must be able to say "**no action needed**" (T7). |
| History gives `days_of_cover_at_start` and `effective_delay_days` per part×SKU | Validate the impact engine against `disruption_impacts` (target ±25%). |

---

## 1. Architecture

```
 Excel data pack ──► ETL (pandas) ──► SQLite / Parquet
                                         │
 Signals (news, WX, TP, port idx) ──► [1] Normalize + gazetteer pre-filter
                                     [2] LLM triage + entity extraction (Haiku)
                                     [3] Entity linking → network graph
                                     [4] Event clustering / dedup
                                     [5] Likelihood + confidence score
                                         │
                                     [6] Impact engine (playbook §3)
                                     [7] Mitigation ranker (playbook §4-7)
                                         │
                       ┌─────────────────┼──────────────────┐
                 Alert inbox +     Briefing (Sonnet,     Chat (Sonnet +
                 risk register     numbers injected)     tool calls into [6]/[7])
                       └──── Next.js UI on Vercel ─────────┘
                 Back-test + business-case page (T9, T10)
```

**Stack (recommended):** Python 3.13 core (pandas, networkx, rapidfuzz, FastAPI) + Next.js frontend, both deployed in **one Vercel project** (Python serverless functions under `/api`). The data pack is only a few MB and can ship with the build. If the Python bundle gets too heavy, the fallback is FastAPI on Render with the Next.js app on Vercel.
**LLM:** Claude. `claude-haiku-5-5` for bulk triage/extraction (cheap, batched), `claude-sonnet-5-5` for briefings and chat. Cache every LLM triage result to disk (keyed by signal_id + prompt version) so back-tests are reproducible and free to re-run. Supplier data goes through the API only and never into logs we don't control (guardrail).

### Repo layout
```
/data/raw            the four source files (copied, untouched)
/core
  etl.py             load all sheets → tidy tables
  graph.py           supplier–part–SKU–lane–port graph + gazetteer
  triage.py          prefilter + LLM classify/extract
  link.py            entities → supplier/port/lane/part/SKU ids (+confidence)
  dedup.py           event clustering
  score.py           likelihood, impact band, priority (L×I), confidence
  impact.py          playbook §3 engine
  mitigate.py        options, net value, ROI, approver
  briefing.py        one-pager generation
  backtest.py        T9 metrics + T10 replays + business case
/api                 FastAPI routes
/web                 Next.js UI
/tests               acceptance tests T1–T10
```

---

## 2. Components (what each does + how it's checked)

### [1] ETL + network graph (foundation)
- Load all 7 network sheets, 5 signal sheets, 3 history sheets.
- Build the graph: `supplier → port_of_loading → lane (→ chokepoint) → destination → plant`, `supplier → part → (bom qty) → SKU → customer`.
- Gazetteer built from the network: supplier names (+ fuzzy variants), cities, countries, ports (incl. aliases: *Nhava Sheva = JNPT*, *Yantian = Shenzhen*), chokepoints (Malacca, Red Sea/Suez, Taiwan Strait), and part categories/commodities (rare-earth magnets, MLCC, PCB, Li-ion cells, MOSFET, aluminium castings…).
- **Exposure map (Stage-1 deliverable):** single-source parts, cover vs lead time, port/country concentration, revenue that depends on each node.

### [2] Signal triage
- **Pre-filter:** normalize case/whitespace, fill missing snippet from headline, gazetteer hit test. Weather alerts and trade notices are already structured, so they're linked by location / `products_covered` directly.
- **LLM pass on candidates only** (structured JSON output): `relevant`, `event_type` (weather, port, labour, trade, supplier-health, cyber, fire, geopolitical), `entities[]`, `expected_start`, `expected_duration_days`, `severity`, `is_forecast_vs_happened`, `scope_note` (e.g. "advisory limited to exercise zone").
- Few-shot examples drawn from **train** labels, including the deceptive false alarms.
- Check: precision/recall on train while tuning; never look at test until the final run.

### [3] Entity linking
- Map extracted entities to ids via exact → alias → fuzzy match. Each link carries a confidence.
- Low-confidence links go to **"Needs review"**, never a silent guess (guardrail: don't invent supplier facts).
- Expand along the graph to get affected suppliers → parts → SKUs → customers.

### [4] Dedup / event clustering (T3)
- Same event = overlapping linked nodes + same event_type + within a 72h window + headline similarity (rapidfuzz, or embeddings if needed).
- One alert per cluster. It lists **all sources**, and the corroboration count feeds credibility.

### [5] Scoring: likelihood, confidence, priority
- **Likelihood 1–5** per playbook §2. Inputs: forecast vs confirmed, source credibility tier, corroboration count, weather severity, proximity to our node, and **leading indicators** (port congestion index trend, rising shipment delays on the lane; T7).
- **Impact 1–5** from the impact engine's ₹ at risk (playbook bands).
- **Priority = L × I**, which drives the response SLA tag (log / 2 days / 24h / war-room).
- Show a **confidence score** and a one-line reason per score (Abhishek's ask; playbook says an unjustified score defaults to 3).
- **Alert budget:** only priority ≥ 6 goes to the inbox, everything else to the watch log. This keeps alert fatigue down.
- Tag **avoidable vs non-avoidable** (Abhishek's framing): warning-led vs sudden. Repeat-offender suppliers (on-time rate, history) raise likelihood.

### [6] Impact engine (playbook §3, exactly)
Per affected part: `effective_delay = duration + recovery − running_capacity_share` → `cover = (on_hand + in-transit not caught) / daily_usage` → `shortage_days = max(0, delay − cover)` → SKU stops on the **binding part** → `units_short = daily_demand × shortage_days − FG stock` → `revenue_at_risk = units × price` (55% lost / 45% late with penalty) → `margin_at_risk` → recomputed **weekly OTIF per customer** vs the 95% target.
- Output is a full working table (part, cover, delay, shortage, binding flag, SKU, units, ₹), shown in the UI.
- Can return **"no shortage, no action"** (T7).
- Validation: feed each D01–D18 with its historical delay and cover-at-start, compare to `disruption_impacts`, report error per disruption (target ±25%).

### [7] Mitigation ranker (playbook §4–7)
- Generate only the applicable options of the 8 (e.g. *switch alternate* only if `qualified_alternate_supplier_id` exists; *air* blocked for lithium cells; *re-route* only if the lane has `reroute_option`).
- Cost from the playbook ranges plus part data (premium %, lane air multiplier, holding 22%/yr). Time to effect is compared to the shortage start, and an option that can't land in time ranks last.
- `net_value = margin_avoided × P(works in time) − cost − penalties_anyway`, with ties broken toward reversible options. ROI per §6.
- **Approver from the matrix** by option type × ₹ band, labelled "Requires approval: …".

### [8] Briefing (one page)
- Template sections: what is happening + sources, why it matters to us (linked nodes), exposure table, ₹ revenue/margin at risk + OTIF, ranked options with approver, recommended next step, confidence + caveats.
- Sonnet writes the prose **from the computed JSON only**. A post-check asserts every ₹ figure in the text exists in the JSON. Export it as PDF/print view.

### [9] Chat (T6 and "which products stop first if Kaohsiung closes 10 days?")
- Claude with tools: `simulate(node, duration_days, capacity_share)`, `exposure(node)`, `rank_options(alert_id)`, `lookup(entity)`.
- The answer always shows the working table returned by the tool.

### [10] Back-test + business case (T9, T10)
- Replay signals chronologically from 1 Feb–30 Sep 2026: precision, recall, median lead time, plus a list of false alarms and misses with reasons.
- Replay each D01–D18: our alert date vs the team's actual alert date, top-ranked option vs actual action, revenue protected (playbook ROI), and recomputed "wasted" spend (actions we would *not* have recommended because cover was enough).
- Co-pilot ROI: revenue/margin protected vs running cost (LLM ₹ per 1k signals + hosting + team time), with a pricing sketch.

---

## 3. UI (pages)
1. **Alert inbox**: priority-sorted, one row per event cluster, with the SLA badge, confidence and source count.
2. **Alert detail / briefing**: the one-pager, the working table and the options table with approvers. Buttons: *Propose / Escalate / Dismiss*. These only record a decision in the log (playbook §8 "record of what was recommended, decided, happened"). Nothing is executed.
3. **Risk register**: open risks, L×I, owner (category manager by part category), status.
4. **Exposure map**: single-source parts × port/country × revenue at risk (heatmap/table; full map is stretch).
5. **Ask the co-pilot**: chat.
6. **Back-test & business case**: T9 metrics, T10 replays, ROI.
7. **Simulator**: inject a signal by hand (used for live demo of T1, T2, T4, T5, T7, T8).

---

## 4. Build order (milestones)

| # | Milestone | Done when |
|---|---|---|
| M1 | ETL + graph + exposure map + disruption timeline | Stage-1 exhibits render. Exposure numbers match the brief (26 single-source, 22 with cover < lead time, median 15.6 days cover). |
| M2 | Impact engine + mitigation ranker | Reproduces the playbook worked example (≈3.1× ROI). D01–D18 impact error table produced. |
| M3 | Triage + linking + dedup + scoring on the full stream | Train metrics tuned. Test run gives recall ≥ 80%, precision ≥ 60%, median lead ≥ 7 days (or we report honestly where we fall short). |
| M4 | Briefing + API + UI (inbox, detail, register, back-test) deployed to a public URL | Signal → quantified alert in < 5 min. A public URL works. |
| M5 | Chat + simulator + T1–T10 acceptance suite green | All 10 scenarios scripted in `/tests` and demoable live. |
| M6 | Business case + false-alarm analysis + 3 persona feedback rounds + COO one-pager | Stage-3 artifacts ready. |

M1→M2 can run in parallel with the triage prompt work in M3. They only meet at the alert object.

## 5. Acceptance-test map
| Test | Exercised by |
|---|---|
| T1 Kaohsiung typhoon forecast | WX/news → link port → impact → options |
| T2 Taiwan Strait naval exercise | triage `scope_note` + likelihood ≤ 2 → watch log only |
| T3 Red Sea ×3 sources | dedup cluster, cites all sources |
| T4 China magnet licensing | TP → commodity → single-source magnet part → options (qualify / pre-buy / re-allocate) |
| T5 Shenzhen PCB late payments | supplier-health event type → recommend qualifying the unqualified alternate |
| T6 Penang 6-week stop OTIF question | chat → `simulate` → per-customer weekly OTIF |
| T7 Mumbai rain + JNPT congestion | inbound shipments at Nhava Sheva vs cover → may say "no action" |
| T8 Japan passives ransomware | day-0 impact → switch MLCC to the Korean qualified alternate, with approver |
| T9 Full test-period run | backtest.py metrics + FA/miss list |
| T10 D05 Penang fire replay | replay page: alert date, recommendation, ₹ protected vs actual |

## 6. Business framing (from the call with Abhishek)
- **Personas and tiers:** start with the mid-size manufacturer (Veltrix). Note how it scales: SMB lite (curated sources, fewer nodes) up to enterprise (full network, more sources, API), and gov/port authorities (credibility-first sources only).
- **Pricing:** subscription priced on network size (suppliers/nodes monitored) plus signal volume. Anchor it on ROI, e.g. ₹170 cr lost over 2 years against tool cost.
- **Credibility:** source tiers (official weather/port/trade bodies > trade press > general/social), corroboration, and pattern checks (like the plagiarism / WhatsApp-forward analogy). Expose this as the confidence score.
- **Real time, multi-timezone:** alerts are pushed to the owning category manager, so nobody waits on a morning hand-off.
- **Opportunity cost:** value idle line time and late penalties, not only lost sales (Abhishek: "no loss is accepted").
- **Stakeholders:** category manager, Head of SC, COO, Sales/KAM, Quality, Finance. Ports and forwarders are named as external partners in the options.

## 7. Risks / open questions
- **Inventory snapshot timing:** `parts.inventory_on_hand` is a single snapshot. For back-test use `days_of_cover_at_start` from history, and for live use the snapshot plus in-transit shipments.
- **Duration estimates for forecasts:** use per-event-type priors fitted on train disruptions, refined by WX `expected_duration_days`.
- **LLM cost/latency on 3.6k signals:** pre-filter plus batching plus caching. Report ₹ per 1k signals in the business case.
- **Stretch (post-MVP):** live GDELT / PortWatch / Global Trade Alert feed, network exposure map, structural recommendations (dual-sourcing/buffer levels from the back-test).

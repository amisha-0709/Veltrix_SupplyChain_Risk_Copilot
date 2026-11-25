# Auction Day deck: plan and prompt

> **Correction (later iteration):** ROI here was computed as net ÷ cost. The business case defines ROI as (net − cost) ÷ cost (that is how 22.5× is computed). On that formula, at our price (₹57 lakh a year all-in): base 18.4× (not 19.4×), test period 13.2×, outliers removed 3.4×, half the chance of success 8.2×, costs doubled 8.7×; Interos 10.4×, mid-market platform 6.2×, Prewave 3.0×. Use the latest deck prompt, not the numbers below.

Team 6 · PS-06 Veltrix Supply Chain Risk Co-Pilot · mentor Abhishek Raj (EY) · live MVP https://veltrix-risk-copilot.vercel.app
Format (from the Auction Day email): 3 min pitch, 3 min live demo, 3 min Q&A, hard cut-offs; the pitch must tie back
to the problem breakdown in the brief. Veltrix Components is fictional and its data is synthetic: say so on the title
slide and in footers.

Every number below comes from the repo (`data/snapshot.json`, `reports/`, `docs/EVALUATION.md`), the PS-06 brief, or
the sources listed at the end. Numbers marked *estimate* are our assumptions; say so on the slide.

---

## Part 1: Deck plan

### Main deck (8 slides, ~20 seconds each)

**1. Title.** "A co-pilot that sees supply disruptions coming and says what to do."
Team 6 · Amisha, Aryan Dewangan, Moksh Jain · mentor Abhishek Raj, EY · live MVP link · "Veltrix Components is fictional; all data is synthetic."

**2. The problem (brief §2).** One sentence: *Veltrix loses revenue to disruptions it could have seen coming, because nobody watches outside news and nothing links a headline to the parts it threatens.*
Big numbers:
- ₹170 cr revenue lost in 24 months (3.9% of revenue); 18 disruptions, 9 stopped production.
- 95.5% of the loss came through single-source parts; 22 of 26 single-source parts have less cover than lead time (median 15.7 vs 45 days).
- 15 of 18 disruptions were in the news first, a median **18 days** before impact.
- The team noticed a median **1 day after** impact and decided **9 days** after.
- ₹4.6 cr of ₹7.0 cr mitigation spend went on parts that had enough cover.
Market context (McKinsey Global Institute): month-long disruptions hit every **3.7 years** on average.

**3. How it works today vs with the co-pilot (brief "How Veltrix handles a disruption today").**
Two timelines on one axis, impact = day 0.
- **Today:** news at −18 d → supplier calls at +1 d → spreadsheets 1–2 days → meetings → decision at +9 d → post-mortem. Median 27 days from first signal to first decision.
- **Co-pilot:** news read on arrival → alert ~14 days before impact → ₹ impact and ranked options in under 1 second → named approver decides the same day.
Root cause in one line: nobody owns outside signals, and nothing links a signal to the bill of materials.

**4. Our solution: one chain, signal to decision.**
Signal → linked to suppliers, parts, products, customers → impact (₹ at risk, shortage days, customers below 95% OTIF) → options ranked by net value → the approver the matrix requires → one-page briefing.
- A page per role: Category manager proposes; Head of Supply Chain approves or escalates; COO reads the briefing; Sales sees customers at risk.
- Live news feed reads real headlines today.
- Guardrails: it recommends, people decide; every alert cites sources and shows its working; it never orders, books or contacts anyone.
Use a screenshot of the alert page (pipeline strip + network trace + cover-vs-delay chart).

**5. Proof against the brief's targets.**
Left: **brief test scenarios T1–T10: 10 of 10 pass** (one line each, see appendix A6).
Right: **held-out real news, 2024 (scored once; rules tuned on 2023 only).**

| Brief metric | Target | Before fixes | After fixes |
|---|---|---|---|
| Recall: relevant headlines surfaced (in an alert or as an update) | ≥ 80% | 46% (13/28) | **68%** (19/28; 95% CI 50–84%) |
| Alert precision | ≥ 60% | 83% (5/6) | **86%** (6/7) |
| Real events with an alert | — | 5 of 6 | **6 of 6** (Westports fire now caught) |
| False alerts per week | low | 0.12 | **0.12** |

Footer, data-pack back-test (test period Feb–Sep 2026): recall 100% (43/43), alert precision 100% (5/5), median warning 13.8 days before impact (target ≥ 7), signal to ₹ impact < 1 s (target < 5 min), impact within ±25% on 9 of 9 loss events (median error 1.5%).
Be honest on the slide: real-news recall (68%) is below the 80% target; say what closes it (slide 8).

**6. What it saves.**
- **₹59.1 cr** of the ₹170.3 cr lost would have been protected (expected, replaying all 18 disruptions with the co-pilot's alert date and top option).
- **₹11.03 cr a year net benefit** (margin protected + penalties avoided + wasted spend avoided − cost of actions).
- **₹4.2 cr of ₹4.57 cr** wasted mitigation spend avoided (it says "no action, cover holds").
- At our price, Veltrix pays **₹57 lakh a year** all-in → **19.4× ROI, payback under a month**; still **4.4×** in the harshest stress test.
- Plus **₹15.9 cr a year** from structural moves it recommends (qualify 8 alternates, buffer 7 parts; ₹1.3 cr one-off). Not counted in the ROI.

**7. How it's built.**
- **Data:** Veltrix data pack (87 suppliers, 65 parts, 26 products, 282 BOM rows, 4,146 shipments, 3,609 labelled signals, 1,560 port-congestion readings, 18 disruptions, mitigation playbook); live Google News (GDELT as backup); 2 years of generated forecast data (2,926 signals in 10 writing styles incl. Hindi and typos); 416 real archived headlines (2023–24).
- **Engine (deterministic, auditable):** triage = disruption-cue scoring + gazetteer of our ports, lanes, countries and commodities (English, Hindi, typo repair) → supplier–part–product–customer graph (networkx) → playbook impact model (effective delay vs cover, shortage days, units, revenue, margin, penalties, weekly OTIF) → option ranking (net value = margin avoided × P(works) − cost − penalties; approval matrix) → one-page briefing.
- **AI (Claude):** turns plain questions (typos, Hindi, comparisons) into engine queries (Sonnet 5.5); extracts places and commodities from live news and flags what the rules miss (advisory); reviewed borderline back-test signals (Opus 5.5); rewrote forecast headlines for testing. Claude never sets a ₹ number.
- **Calibration, not fine-tuning:** rules and threshold set on train splits only (data-pack train, forecast train, real 2023) and scored once on held-out tests (data-pack test, forecast test, real 2024).
- **Stack:** Python, FastAPI, pandas, networkx, plain JS, Vercel serverless, Anthropic API.

**8. What we changed, and the ask.**
- After the discovery call (Abhishek Raj, EY, 5 Nov): no alert spam (one alert per story, about 9 alerts a year, only priority ≥ 6 in the inbox: 2–3 a year); loss valued as margin + penalties, weighted by chance of success; ROI shown with and without outliers (22.5× → 4.3×); decision-ready options with the named approver (34 of 83 past approvals sat below the required level).
- Next: attach follow-up headlines to open alerts on the live site (closes most of the recall gap), real role-player feedback, ERP stock feed.
- **Ask:** a 3-month pilot at ₹10 lakh (credited to year one), then ₹40 lakh a year + ₹15 lakh one-off set-up. Pilot measures: lead time, alert precision, time to decision, wasted spend.

### Appendix

- **A1. ROI calculation.** Per year (2-year replay, annualised; only what the co-pilot adds over the team's own actions; each action weighted by its chance of working): margin protected ₹8.67 cr + penalties avoided ₹0.84 cr + wasted spend avoided ₹2.10 cr − cost of recommended actions ₹0.57 cr = **₹11.03 cr net** (components rounded). Revenue protected ₹29.6 cr a year (₹59.1 cr over 2 years).
- **A2. Cost to Veltrix at our price** (₹57.0 lakh a year): subscription ₹40 lakh; set-up ₹15 lakh one-off amortised over 3 years (₹5 lakh); Veltrix's own 0.5 FTE risk owner ₹12 lakh (nobody owns monitoring today). For comparison, running it fully in-house was costed at ₹46.9 lakh (22.5×).
- **A3. Sensitivity at our price.**

| Scenario | Net benefit / yr | ROI | Payback |
|---|---|---|---|
| Base: all 18 disruptions | ₹11.03 cr | 19.4× | 0.6 months |
| Test period only (Feb–Sep 2026, annualised) | ₹8.11 cr | 14.2× | 0.8 months |
| Outliers removed (events losing > $1M) | ₹2.48 cr | 4.4× | 2.8 months |
| Half the chance of success | ₹5.23 cr | 9.2× | 1.3 months |
| Costs doubled | ₹11.03 cr | 9.7× | 1.2 months |

- **A4. Pricing and market comparison.** Cost to serve one customer ≈ ₹23 lakh a year (licensed news feed ₹12 lakh, hosting ₹3 lakh, model calls ₹0.24 lakh, 0.25 FTE maintenance ₹8 lakh) → 42% margin at ₹40 lakh, more as the news feed is shared across customers. Price set (a) above cost to serve, (b) below 5% of the value created (₹55 lakh), (c) under the low end of the market.

| Option | Annual licence | ROI on the same benefit* |
|---|---|---|
| **Veltrix Risk Co-Pilot (ours)** | **₹40 lakh** (+ ₹15 lakh set-up) | **19.4×** |
| Interos (AWS Marketplace list price, 12 months) | $100,000 ≈ ₹85 lakh | 11.4× |
| Mid-market SCRM platform (independent estimate $75k–250k) | ~$150,000 ≈ ₹1.28 cr (+ implementation) | 7.2× |
| Prewave (Forrester TEI composite, ~€285k/yr) | ≈ ₹2.6 cr | 4.0× |
| Resilinc | from ~$1,400 per feature per month (aggregator listing, unverified); enterprise quotes far higher | — |
| Everstream | not published; quote only | — |

\*Competitors' ROI assumes they deliver the same benefit, which they may not: most monitor and score risk, but don't compute shortage days, ₹ impact and ranked options from the buyer's own BOM, stock and playbook. All ROIs include Veltrix's 0.5 FTE risk owner. Conversion at ₹85/US$ and US$1.09/€ (*estimate*; use the day's rate).

- **A5. Testing beyond the data pack** (`docs/EVALUATION.md`). Forecast data, test split: alert precision 42.9% → 100%, triage recall 79.5% → 84.6% after rule fixes made on the train split. Real news: the replay above. Live website judging one headline at a time on the 2024 set: precision 73.7%, recall 50%, matching the engine exactly. The gap to 68% is the follow-up updates, which the live view doesn't show yet.
- **A6. Brief test scenarios T1–T10 (all pass).** T1 typhoon southern Taiwan → Kaohsiung, 4 suppliers, 5 parts, 15 SKUs, cover holds (watch, ₹0). T2 naval exercise → ignored. T3 Red Sea from 3 sources → one alert citing all. T4 magnet licensing → 2 SKUs stop, shortage days, qualify / pre-buy / re-allocate ranked. T5 Shenzhen PCB payments → supplier-health warning, qualify SUP-035 (7 weeks). T6 Penang 6 weeks → 9 SKUs, 5 customers below 95% OTIF, working shown. T7 Mumbai rain + JNPT → 27 inbound shipments checked, "no action, cover holds". T8 ransomware Japan → quantified in 0.3 s, switch MLCC to Korean alternate, ₹18.4 lakh, Head of SC + Quality. T9 back-test → recall 100%, precision 100%, lead 13.8 d. T10 D05 replay → alert on impact day vs team +3 days; pre-qualifying the alternate would have protected ~₹50 cr.
- **A7. Guardrails and trust (brief §8).** Recommends, never acts; every alert cites sources and shows the working; unlinked signals go to "needs review", never guessed onto the network; approval matrix enforced; options never shown as approved; only headlines and links stored, no full articles; false-alarm rate reported honestly.
- **A8. Limits and next steps.** Synthetic company data; the real-news test is small (28 relevant headlines); labels were written by the same assistant that wrote the rules; live site doesn't yet attach follow-ups; role-player feedback was scripted, not real users; next: ERP stock feed, real users, larger real-news set, Claude as second reader once tested.
- **A9. Feedback addressed since Check-in 1.** One-sentence problem; today's workflow (median 27 days signal to decision); one root cause; targets vs baseline; D18 impact error −73% → +2.3% after modelling broker buys as partial cover (fitted on training disruptions only).

### Demo (3 min, separate from the deck)

Home (proof band) → Live news (real headlines, nothing spammed, Claude-flagged Red Sea) → Try a signal T4 magnets (walk the five-step strip, trace, red bars) → Head of Supply Chain approves → Replay D04 timeline (19 days to act) → COO page (₹11 cr a year, 22.5×). Backups: T1–T10 buttons, Ask "Which customers miss 95% OTIF if Penang stops for six weeks?".

---

## Part 2: Prompt for the deck builder

Copy everything between the lines into the slide tool (Claude, Gamma, PowerPoint Copilot, etc.).

---
You are building a pitch deck for a 3-minute Auction Day pitch (PS-06, Applied AI Challenge). The panel will also see
a 3-minute live demo and ask questions for 3 minutes. The pitch must tie back to the brief's problem breakdown.

Product: Veltrix Risk Co-Pilot, a co-pilot that sees supply disruptions coming and says what to do about them.
Team 6: Amisha, Aryan Dewangan, Moksh Jain. Mentor: Abhishek Raj, EY. Live MVP: https://veltrix-risk-copilot.vercel.app
Case company: Veltrix Components (fictional; all data synthetic), Indian maker of electronics for electric two- and
three-wheelers, plants in Pune and Chennai, about ₹2,200 crore revenue, 87 suppliers in 9 countries.

Rules:
- 16:9, 8 main slides + 9 appendix slides. One message per slide; the message is the slide title as a full sentence.
- Use ONLY the numbers below, exactly as written. Do not invent, round differently or add numbers. If a slide needs
  a number that is not here, leave a visible placeholder "[number needed]".
- Big numbers in the accent colour (#C55A11, burnt orange); body in dark grey; white background; one clean sans font.
- Footer on every slide: "Veltrix Components is fictional; all data synthetic. Team 6 · PS-06".
- Put sources in small print on slides that use outside figures. Mark estimates as "estimate".
- Add 2–3 lines of speaker notes per main slide (about 20 seconds each).
- Do not mention sign-in, logins or user accounts.

Main slides:
1. Title: "A co-pilot that sees supply disruptions coming and says what to do". Team, mentor, live MVP link.
2. Problem: Veltrix lost ₹170 cr in 24 months (3.9% of revenue) to 18 disruptions; 9 stopped production. 95.5% of the
   loss came through single-source parts; 22 of 26 single-source parts have less cover than lead time (15.7 vs 45 days).
   15 of 18 were in the news a median 18 days before impact, yet the team noticed 1 day after impact and decided 9 days
   after. ₹4.6 cr of ₹7.0 cr mitigation spend was wasted on parts with enough cover. Context: month-long disruptions hit
   every 3.7 years on average (McKinsey Global Institute).
3. Today vs with the co-pilot: two timelines, impact = day 0. Today: news −18 d, supplier calls +1 d, spreadsheets and
   meetings, decision +9 d (27 days from first signal to decision). Co-pilot: alert ~14 days before impact, ₹ impact
   and ranked options in under 1 second, named approver decides the same day. Root cause: nobody owns outside signals
   and nothing links a signal to the bill of materials.
4. Solution: signal → suppliers, parts, products, customers → impact (₹ at risk, shortage days, customers below 95%
   OTIF) → options ranked by net value → approver the matrix requires → one-page briefing. A page per role (Category
   manager, Head of Supply Chain, COO, Sales). Live news feed. It recommends; people decide; every alert cites sources
   and shows its working. Leave a box for a product screenshot.
5. Proof: "All 10 brief test scenarios (T1–T10) pass." Table "Held-out real news, 2024 (rules tuned on 2023 only)":
   Recall (relevant headlines surfaced, in an alert or as an update), target ≥ 80%: before 46% (13/28), after 68%
   (19/28; 95% CI 50–84%). Alert precision, target ≥ 60%: before 83% (5/6), after 86% (6/7). Real events with an alert:
   before 5 of 6, after 6 of 6. False alerts per week: 0.12 before and after. Footnote: data-pack back-test (Feb–Sep
   2026): recall 100% (43/43), alert precision 100% (5/5), median warning 13.8 days before impact (target ≥ 7), signal
   to ₹ impact under 1 second (target under 5 minutes), impact within ±25% on 9 of 9 loss events (median error 1.5%).
   State plainly that real-news recall is below target and is being closed.
6. Savings: ₹59.1 cr of the ₹170.3 cr lost would have been protected (expected, 18 disruptions replayed). ₹11.03 cr a
   year net benefit. ₹4.2 cr of ₹4.57 cr wasted spend avoided. At ₹57 lakh a year all-in cost: 19.4× ROI, payback under
   a month; 4.4× in the harshest stress test. Plus ₹15.9 cr a year from recommended structural moves (not in the ROI).
7. How it's built: data sources (Veltrix data pack: 87 suppliers, 65 parts, 26 products, 4,146 shipments, 3,609
   labelled signals, 1,560 port readings, 18 disruptions, playbook; live Google News; 2,926 generated forecast signals
   in 10 writing styles incl. Hindi and typos; 416 real 2023–24 headlines). Pipeline diagram: triage (cue scoring +
   gazetteer, English/Hindi, typo repair) → supplier–part–product–customer graph → playbook impact model → option
   ranking with approval matrix → briefing. AI: Claude turns questions into engine queries, extracts entities from live
   news and flags what rules miss, reviewed borderline back-test signals; Claude never sets a ₹ number. Calibration,
   not fine-tuning: rules set on train splits, scored once on held-out tests. Stack: Python, FastAPI, pandas, networkx,
   JavaScript, Vercel, Anthropic API.
8. What changed and the ask: after the EY discovery call — no alert spam (one alert per story, about 9 alerts a year, only
   priority ≥ 6 in the inbox: 2–3 a year); loss valued as margin + penalties × chance of success; ROI with and without outliers (22.5× →
   4.3×); named approver (34 of 83 past approvals sat below the required level). Next: follow-up headlines attached to
   open alerts on the live site, real users, ERP stock feed. Ask: 3-month pilot at ₹10 lakh (credited), then ₹40 lakh a
   year + ₹15 lakh one-off set-up.

Appendix slides (A1–A9): use the tables and text in Part 1 of this document exactly: ROI calculation; cost to Veltrix;
sensitivity table; pricing and market comparison with its footnote and sources; testing beyond the data pack (incl.
live-site 73.7% precision / 50% recall one headline at a time); T1–T10 one line each; guardrails; limits and next
steps; feedback addressed since Check-in 1.
---

---

## Sources for outside figures

- McKinsey Global Institute, *Risk, resilience, and rebalancing in global value chains* (month-long disruptions every 3.7 years): https://www.mckinsey.com/mgi/our-research/risk-resilience-and-rebalancing-in-global-value-chains
- Interos 12-month platform access, $100,000 (AWS Marketplace): https://aws.amazon.com/marketplace/pp/prodview-h3m3irdg7bika
- Prewave, Forrester Total Economic Impact (3-year subscription €854,000 for a composite customer): https://tei.forrester.com/go/prewave/holisticsupplierriskmanagementplatform
- Mid-market supply chain risk platforms $75k–250k a year + $25k–75k implementation (FitGap): https://us.fitgap.com/search/risk-management-software/supply-chain
- Mid-market $40k–150k a year; specialist supplier-risk vendors $100k–300k (RiskWatch): https://www.riskwatch.com/top-10-risk-management-software-for-supply-chain/
- Resilinc from ~$1,400 per month (aggregator listings, unverified): https://www.capterra.com/p/189655/Resilinc/
- Everstream: no published pricing: https://marketintelligencetools.com/reviews/everstream/

Vendor prices are mostly unpublished; treat all market figures as indicative and say so on the slide.

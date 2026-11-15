# How we tested the co-pilot beyond the data pack

The data pack scores close to 100% because its news is clean and repetitive. We tested on two harder sets, changed
the triage rules using **train data only**, and scored each test set once at the end.

## 1. Generated forecast data (Oct 2026 – Sep 2028)

* `core/forecast_gen.py` (seed 42) generates two more years in the data pack's schema without calling any co-pilot
  code. `core/forecast_headlines.py` has Claude rewrite every headline in 10 styles (wire, trade, local, ticker,
  typos, Hindi, Hinglish, explainer, caps…). Files: `data/forecast/` (see its README).
* Split: `train` before Apr 2028, `test` from Apr 2028 (`signal_labels.csv`).
* Run: `python -m core.eval_forecast` (rules only) · `--cached-llm` (Claude extractions already cached, no API calls)
  · `--llm` (full Claude extraction; needs `ANTHROPIC_API_KEY`).
* Results: `reports/forecast_eval_before_fix.json` (before), `reports/forecast_eval.json` (after),
  `reports/forecast_eval_llm_cached.json` (partial Claude run, 433 of 2,629 texts).

| Forecast test split | Before | After (rules tuned on forecast train) |
|---|---|---|
| Triage precision / recall | 77.5% / 79.5% | 100% / 84.6% |
| Signals in an alert (recall) | 87.2% | 94.9% |
| Alert precision (brief ≥ 60%) | 42.9% | 100% |
| Median warning before impact | 10.7 d | 13.3 d |

## 2. Real archived news (2023–2024)

* `core/real_replay.py fetch` pulls 416 real headlines from Google News (date-limited searches: the live feed's
  queries plus two broad ones) around the Red Sea crisis, the Taiwan quake, the Baltimore bridge collapse, China's
  gallium controls, and three quiet periods. Only headline, link, outlet and date are kept.
* Labels (`data/real_replay/labels.csv`) were written blind from a shuffled sheet with no co-pilot output; the rule is
  in `data/real_replay/LABELS_README.md`. They were written by the same assistant that wrote the rules, so a person
  should spot-check them.
* Split by time: rule changes used **2023** headlines only; **2024** headlines were scored once.
* Run: `python -m core.real_replay score` (engine, 2023/2024 split) · `python -m core.real_replay live 2024`
  (the deployed site, one `/api/simulate` call per headline).

| Real 2024 test (28 relevant of 160) | Before fixes | After fixes |
|---|---|---|
| Alert precision (brief ≥ 60%) | 57% | 86% (6 of 7) |
| Relevant headlines surfaced: alert or update (brief ≥ 80%) | ~20% | 68% (95% CI 50–84%) |
| Real events with an alert | 5 of 6 | 6 of 6 |
| False alerts per week | 0.38 | 0.12 |

## What changed in the rules (all from train errors)

* Negation and reassurance ("no major disruption expected", "no strike action", "operations continue normally"),
  planned power cuts, outlets that remain open, relocation, raw materials Veltrix does not buy.
* Hindi place, commodity and cue words; spelling repair for place and cue words; synonyms the word list lacked.
* Real attack-on-shipping wording, approaching storms, terminal and operator names (Westports, Yangshan, …).
* Follow-up headlines about a running crisis join an open alert as **updates** (never a new alert).
* Threshold ties go to the higher threshold (fewer alerts). It stays at 3.5.

The data-pack back-test is unchanged (136/136 train, 43/43 test, 5/5 alerts, 13.75 days lead) and T1–T10 pass.

## Caveats

* Small test sets: 39 relevant signals (forecast test), 28 relevant headlines (real 2024).
* The test errors had been seen before the fixes were written; every change was justified by train examples, but the
  after-fix test numbers are good estimates, not perfectly blind ones.
* Forecast train and test share phrasing (same generator), so 100% precision there will not carry over to real news.

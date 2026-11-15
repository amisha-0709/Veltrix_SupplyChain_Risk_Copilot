# Forecast data (generated, v1)

Two more years of synthetic data for Veltrix, **5 Oct 2026 – 25 Sep 2028**, in the data pack's own schema.
Made by `python -m core.forecast_gen --years 2 --seed 42`. The same seed always gives the same files.

| File | Rows | What it is |
|---|---|---|
| `disruptions.csv` | 23 | New events. `archetype` = the past event it is modelled on |
| `news.csv` + `signal_labels.csv` | 2,926 | Background news plus warning signals for each warned event. Labels hold relevance, linked event, days before impact and `split` |
| `port_congestion.csv` | 1,560 | 15 ports × 104 weeks |
| `shipments.csv` | 4,171 | 28 lanes. Shipments delayed by an event carry its id |
| `weekly_demand.csv` | 2,704 | 26 SKUs × 104 weeks |
| `validation.json` | | History vs generated, plus every fitted parameter |

**Train/test split:** the last 6 months (from Apr 2028) are labelled `test`. Tune only on `train`; score `test` once.

**Kept separate from the co-pilot:** the generator never calls triage, impact or mitigation code. Otherwise the co-pilot would be graded on answers it produced itself.

## History vs generated (seed 42)

These are per year where the row is a rate. Run the generator to refresh the numbers.

- Disruptions per year: 9 vs ~10–11.5. This is a random draw; other seeds give 7–12.
- Share of events warned in advance: 0.83 vs ~0.8.
- Median warning lead: 16 vs ~15 days.
- News: 29 vs ~28 items a week, of which 5% are relevant.
- Congestion index: mean 46.4 vs ~47, SD 10 vs ~10.7.
- Sea delay: 2.0 vs ~1.6–2.2 days.
- Share of shipments hit by an event: 0.11 vs ~0.11.
- Demand growth: +8% vs +9% a year.

## Known limits (v1) and next steps

1. **Headlines:** `news.csv` reuses the pack's wording (367 unique headlines). `news_claude.csv` has all 2,926 rewritten by Claude (`python -m core.forecast_headlines --run`) in 10 styles incl. typos, Hindi and Hinglish: 2,162 unique headlines, place kept in 97.5% of checkable rows (misses are mostly abbreviations like "S Korea"). The "local" style sometimes adds minor background detail.
2. **Not generated yet:** `weather_alerts`, `trade_policy`, `disruption_impacts` and losses. Losses need their own stock-and-shortage simulator; we will not reuse our impact engine, because it would then be grading itself.
3. **Demand has no shortages.** `units_short` is 0 and `otif_pct` is resampled from normal weeks. This is filled in once the loss simulator exists.
4. **Events re-use the 18 past ones as templates.** The data can't contain a kind of crisis we have never seen, which is why the final check is on real live news.

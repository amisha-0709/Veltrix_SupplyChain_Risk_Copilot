"""Claude reads every signal (brief must-have 1): is it a supply-disruption event, its status, and the locations,
ports, routes, companies and commodities it mentions.

Division of labour (so the result is auditable and Claude can never invent a supplier):
  * Claude EXTRACTS, from the signal text alone. It is told nothing about Veltrix's network, suppliers or volumes.
  * The engine LINKS: each extracted name is matched against Veltrix's network with the same gazetteer the rules use.
    An extracted name that isn't in the network stays visible but links nothing.
  * The decision rule that combines Claude and the rules is chosen on the TRAIN period only (core/triage_eval.py).

Verdicts are cached on disk by text hash and prompt version, so back-tests are reproducible and re-runs are free.

    python -m core.llm_triage --estimate      # how many texts, approximate cost; no API calls
    python -m core.llm_triage --run           # needs ANTHROPIC_API_KEY in this terminal; resumable
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "llm_triage_cache.json"
PROMPT_VERSION = "x1"
MODEL = os.environ.get("COPILOT_TRIAGE_MODEL", "claude-sonnet-5-5")
CATEGORIES = ["Castings", "Connectors", "Copper & harness", "Displays", "Li-ion cells", "Magnets", "PCBs", "Passives",
              "Plastics", "Semiconductors"]

Status = Literal["happening", "forecast_likely", "forecast_unlikely", "denied_or_rumour", "threat_only", "resolved",
                 "routine", "not_an_event"]
Event = Literal["port_closure", "supplier_outage", "congestion", "route", "trade_licensing", "cost_only", "none"]
Category = Literal["Castings", "Connectors", "Copper & harness", "Displays", "Li-ion cells", "Magnets", "PCBs", "Passives",
                   "Plastics", "Semiconductors", "other"]


class Extraction(BaseModel):
    is_supply_event: bool          # could this event disrupt the production or movement of manufactured goods?
    status: Status
    event_type: Event
    severity: int                  # 1 (minor) to 5 (severe)
    duration_days: Optional[float]  # stated or clearly implied duration; null if none
    locations: list[str]           # cities, regions, countries, as named
    ports: list[str]               # sea or air ports, as named
    routes: list[str]              # straits, canals, seas, shipping lanes
    companies: list[str]           # company or organisation names, as written
    commodities: list[str]         # goods or materials named, as written
    commodity_categories: list[Category]
    confidence: float              # 0-1
    reason: str                    # one short line


SYSTEM = """You extract structured facts from one news item, weather alert or trade notice for a supply-chain risk system.
Read only the text you are given. Do not use outside knowledge to add places, companies or facts that aren't in it.

Fields:
- is_supply_event: true if the text reports or forecasts something that could disrupt making or moving manufactured goods: storms, floods, quakes, heat or power cuts affecting industry, port closures or congestion, strikes, fires, cyber attacks or insolvency at manufacturers, shipping-route problems, freight capacity or rate shocks, export controls, duties or licensing on goods. False for market commentary, product launches, earnings, good news, consumer stories.
- status: happening (is occurring now); forecast_likely (expected or warned, likely to occur); forecast_unlikely (forecast to miss, weaken, pass by, or low risk); denied_or_rumour (rumour or an official denial); threat_only (a threat or warning of possible action, e.g. union threatens a strike); resolved (over, reopened, normalised); routine (seasonal, minor, no disruption expected); not_an_event.
- event_type: port_closure (port or area shut by weather or authority); supplier_outage (a plant, factory, fab or maker stops or slows: fire, quake damage, strike, insolvency, cyber attack, power cuts); congestion (port or road congestion, delays, freight shortages or rate spikes, rolled bookings, customs outages); route (canal, strait or sea-lane disruption forcing reroutes); trade_licensing (export controls, licences, quotas); cost_only (duties or tariffs that raise cost without stopping supply); none.
- severity: 1 to 5 from the text (an official severity level if given).
- duration_days: only if stated or clearly implied (e.g. "for two weeks" = 14), else null.
- locations, ports, routes, companies, commodities: copy names as they appear. Put a port in ports, not locations. Include a country or region only if named.
- commodity_categories: map named goods to these categories: Castings, Connectors, Copper & harness, Displays, Li-ion cells, Magnets, PCBs, Passives (capacitors, resistors, inductors, MLCCs), Plastics, Semiconductors (chips, ICs, MOSFETs, sensors, microcontrollers), or other. Empty if no goods are named.
- confidence: how sure you are of is_supply_event and status.
- reason: one short line."""

_lock = threading.Lock()


def key(text: str) -> str:
    return f"{PROMPT_VERSION}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}"


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE)


def extract_one(client, text: str) -> Extraction | None:
    resp = client.messages.parse(
        model=MODEL, max_tokens=1500, output_config={"effort": "low"},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"Text:\n{text}"}], output_format=Extraction)
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        return None
    return resp.parsed_output


def extract_live(text: str, timeout: float = 20.0) -> Extraction | None:
    """One signal, live (Try a signal). Uses and fills the cache. Returns None without a key or on any error."""
    c = load_cache()
    k = key(text)
    if k in c:
        return Extraction(**c[k])
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        x = extract_one(anthropic.Anthropic(timeout=timeout, max_retries=1), text)
    except Exception:
        return None
    return x


def cached_for(texts) -> dict[str, Extraction]:
    c = load_cache()
    return {t: Extraction(**c[key(t)]) for t in set(texts) if key(t) in c}


def run(texts: list[str], workers: int = 8) -> tuple[int, int]:
    import anthropic
    cache = load_cache()
    todo = sorted({t for t in texts if key(t) not in cache})
    if not todo:
        return 0, 0
    client = anthropic.Anthropic(max_retries=4)
    done = failed = 0

    def work(t):
        return t, extract_one(client, t)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, t) for t in todo]
        for f in as_completed(futs):
            try:
                t, x = f.result()
            except Exception as e:                       # keep going; the next run retries what failed
                failed += 1
                print("  error:", type(e).__name__, str(e)[:120])
                continue
            if x is None:
                failed += 1
                continue
            with _lock:
                cache[key(t)] = x.model_dump()
                done += 1
                if done % 25 == 0:
                    _save(cache)
                    print(f"  {done}/{len(todo)}")
    _save(cache)
    return done, failed


if __name__ == "__main__":
    import argparse

    from core.triage import triage_all
    ap = argparse.ArgumentParser(description="Claude extraction for every signal")
    ap.add_argument("--run", action="store_true", help="call the API for texts not yet cached (costs money)")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only the first N uncached texts (a test run)")
    a = ap.parse_args()
    texts = list(triage_all()["text"])
    uniq = sorted(set(texts))
    have = sum(1 for t in uniq if key(t) in load_cache())
    print(f"{len(texts)} signals, {len(uniq)} unique texts, {have} already extracted, {len(uniq) - have} to go. Model {MODEL}.")
    # ~1,100 cached system tokens, ~60 text tokens in, ~350 out (incl. thinking at low effort) per text
    per_in, per_out = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}.get(MODEL, (2.0, 10.0))
    n = len(uniq) - have
    est = n * (1100 * per_in * 0.05 + 80 * per_in + 350 * per_out) / 1e6
    print(f"Estimated cost for the remaining texts: about ${est:.2f} (list prices, cached system prompt).")
    if a.run:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("ANTHROPIC_API_KEY is not set in this terminal.")
        todo = [t for t in uniq if key(t) not in load_cache()]
        if a.limit:
            todo = todo[:a.limit]
        d, f = run(todo)
        print(f"Extracted {d}, failed {f}. Cache: {CACHE}")

"""Optional Claude review of borderline signals (off unless enabled).

Only the borderline band goes to the model: signals the rules scored just under the threshold, and
strong-cue signals the gazetteer could not link. Verdicts are cached on disk by (signal_id, prompt
version), so back-tests are reproducible and re-runs cost nothing.

What is sent: the signal text plus the NAMES of ports, chokepoints, countries and commodity
categories Veltrix depends on. No supplier names, volumes, prices or stock levels leave the machine
(brief §8: supplier data is commercially sensitive).

Enable:  set COPILOT_LLM=1 and have Anthropic credentials (ANTHROPIC_API_KEY or `ant auth login`).
Model:   COPILOT_LLM_MODEL (default claude-opus-5-5).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel

from core.graph import build_network

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "llm_cache.json"
PROMPT_VERSION = "v1"
MODEL = os.environ.get("COPILOT_LLM_MODEL", "claude-opus-5-5")

EventType = Literal["port_closure", "supplier_outage", "congestion", "route", "trade_licensing", "cost_only", "none"]


class Verdict(BaseModel):
    relevant: bool                 # would this plausibly disrupt Veltrix supply in the next 6 weeks?
    event_type: EventType
    places: list[str]              # names from the network list it refers to (may be empty)
    categories: list[str]
    is_forecast: bool              # forecast/warning (True) vs already happening (False)
    confidence: float              # 0–1
    reason: str                    # one line


def enabled() -> bool:
    if os.environ.get("COPILOT_LLM") != "1":
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _network_brief() -> str:
    net = build_network()
    G = net.G
    names = lambda t: sorted({d["name"] for _, d in G.nodes(data=True) if d.get("type") == t})  # noqa: E731
    return ("Ports we ship from: " + ", ".join(names("port")) + "\n"
            "Indian ports we receive at: " + ", ".join(names("dest")) + "\n"
            "Sea chokepoints on our lanes: " + ", ".join(names("choke")) + "\n"
            "Supplier countries: " + ", ".join(names("country")) + "\n"
            "Commodities we buy: " + ", ".join(names("cat")))


SYSTEM = """You triage external news for the supply-chain team of an Indian electronics manufacturer
(EV battery management systems, motor controllers, chargers, clusters, lighting, harnesses).
Decide whether a signal could plausibly disrupt its inbound supply in the next six weeks.

Relevant: a credible forecast or report of an event that touches a port, lane, chokepoint, supplier
country or commodity listed below: storms, floods, quakes, port closures or congestion, strikes,
fires, cyber attacks or financial distress at component makers, export controls or duties on what
it buys, freight capacity shortages.
Not relevant: routine weather, forecasts that say a storm will miss or weaken, denials and rumours,
threats that haven't happened, good news, market commentary, product launches, events far from the
listed network, and advisories that explicitly limit themselves to an area we don't use.
When unsure, say relevant=false with low confidence: a human reviews low-confidence items."""


def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


BORDERLINE_FLOOR = 1.5     # rules score at or above this (but under threshold) goes to review
ACCEPT_CONFIDENCE = 0.7    # Claude must be at least this sure to promote a signal


def borderline(T, threshold: float):
    """Signals the rules are unsure about: linked but just under threshold, or strong cues with no link."""
    near = T[(T["score"] >= BORDERLINE_FLOOR) & (T["score"] < threshold) & (T["link_strength"] > 0)]
    unlinked = T[(T["link_strength"] == 0) & (T["cue_score"] >= threshold)]
    return near, unlinked


def apply_judge(T, threshold: float, run: bool = False):
    """Promote borderline signals Claude judges relevant (cached verdicts always apply; `run` allows new calls).

    One call per unique story (syndicated copies share the verdict). Claude never decides alone:
      * near-threshold + linked: promoted to the threshold if relevant with confidence ≥ ACCEPT_CONFIDENCE;
      * unlinked: Claude's place/commodity names are matched against OUR gazetteer, so a link is only
        added if it resolves to a real node; otherwise the signal stays in Needs review, with the reason.
    Returns (T with judge columns, summary dict).
    """
    T = T.copy()
    near, unlinked = borderline(T, threshold)
    cand = pd.concat([near, unlinked]).drop_duplicates("story_key")
    items = [(f"story:{r.story_key}", r.text) for r in cand.itertuples()]
    prev = os.environ.get("COPILOT_LLM")
    if run:
        os.environ["COPILOT_LLM"] = "1"
    try:
        verdicts = judge(items)
    finally:
        if run:
            if prev is None:
                os.environ.pop("COPILOT_LLM", None)
            else:
                os.environ["COPILOT_LLM"] = prev
    net = build_network()
    T["llm_verdict"] = None
    T["llm_reason"] = None
    promoted = 0
    for key, v in verdicts.items():
        sk = key.split(":", 1)[1]
        m = T["story_key"] == sk
        T.loc[m, "llm_verdict"] = "relevant" if v.relevant else "not relevant"
        T.loc[m, "llm_reason"] = f"Claude ({v.confidence:.2f}): {v.reason}"
        if not (v.relevant and v.confidence >= ACCEPT_CONFIDENCE):
            continue
        if v.event_type != "none":
            T.loc[m & T["event_type"].isna(), "event_type"] = v.event_type
        for i in T.index[m]:
            if T.at[i, "link_strength"] == 0:
                hits = [h["node"] for h in net.match(" ".join(v.places + v.categories))]
                if not hits:
                    continue
                T.at[i, "links"] = hits
                T.at[i, "link_strength"] = 2.0 if any(h.split(":")[0] in ("sup", "port", "dest", "choke", "loc", "region")
                                                      for h in hits) else 1.0
            T.at[i, "score"] = max(float(T.at[i, "score"]), threshold)
            T.at[i, "reason"] = f"{T.at[i, 'reason']}; promoted by {T.at[i, 'llm_reason']}"
            promoted += 1
    return T, {"stories_sent": len(items), "verdicts": len(verdicts), "signals_promoted": promoted,
               "model": MODEL, "pending_without_credentials": len(items) - len(verdicts)}


def judge(items: list[tuple[str, str]]) -> dict[str, Verdict]:
    """items = [(key, text)]. Returns verdicts for those it could judge (cached or fresh)."""
    cache = _load_cache()
    out: dict[str, Verdict] = {}
    todo = []
    for sid, text in items:
        key = f"{PROMPT_VERSION}:{sid}"
        if key in cache:
            out[sid] = Verdict(**cache[key])
        else:
            todo.append((sid, text))
    if not todo or not enabled():
        return out

    import anthropic
    client = anthropic.Anthropic()
    system = [{"type": "text", "text": SYSTEM + "\n\n" + _network_brief(), "cache_control": {"type": "ephemeral"}}]
    for sid, text in todo:
        try:
            resp = client.messages.parse(
                model=MODEL, max_tokens=1024, system=system,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": f"Signal:\n{text}"}],
                output_format=Verdict,
            )
        except anthropic.RateLimitError:
            break                                  # keep what we have; rules still decide the rest
        except (anthropic.APIStatusError, anthropic.APIConnectionError):
            continue
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            continue
        v = resp.parsed_output
        out[sid] = v
        cache[f"{PROMPT_VERSION}:{sid}"] = v.model_dump()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    import argparse

    from core.triage import triage_all, tune_threshold

    ap = argparse.ArgumentParser(description="Claude review of borderline signals")
    ap.add_argument("--run", action="store_true", help="call the API for stories not yet cached (costs money)")
    args = ap.parse_args()
    T = triage_all()
    th = tune_threshold(T)
    near, unlinked = borderline(T, th)
    cand = pd.concat([near, unlinked]).drop_duplicates("story_key")
    print(f"Threshold {th}. Borderline: {len(near)} near-threshold + {len(unlinked)} unlinked signals "
          f"= {len(cand)} unique stories → {len(cand)} calls to {MODEL} (cached ones are free).")
    for r in cand.itertuples():
        print(f"  [{r.score:+.1f}] {r.text[:120]}")
    if not args.run:
        print("\nDry run: nothing sent. Re-run with --run once Anthropic credentials are set.")
    else:
        T2, summary = apply_judge(T, th, run=True)
        print(summary)
        for r in T2[T2["llm_verdict"].notna()].drop_duplicates("story_key").itertuples():
            print(f"  {r.llm_verdict:13s} {r.llm_reason}  ← {r.text[:70]}")

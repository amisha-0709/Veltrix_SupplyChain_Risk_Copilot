"""Claude rewrites the generated headlines so they stop repeating the data pack's sentence patterns.

The forecast generator (core/forecast_gen.py) re-uses the pack's own headlines with names swapped, so triage still
scores close to 100% on them. This step gives every news item a new wording in one of several real-world styles
(wire copy, trade press, local paper, Hindi, Hinglish, typos, ticker, explainer), while keeping the facts that the
labels depend on: the place, the event, whether it is happening, forecast, denied or over, and any numbers or dates.
Each occurrence of a repeated headline gets its own wording.

    python -m core.forecast_headlines --estimate          # counts and tokens; no API calls
    python -m core.forecast_headlines --sample 40         # needs ANTHROPIC_API_KEY; rewrites 40 items to check quality
    python -m core.forecast_headlines --run               # all items; resumable (cached by item, text and style)

Output: data/forecast/news_claude.csv (same columns as news.csv, plus original_headline, original_snippet, style and
place_kept). news.csv is left as it is. Claude is told nothing about Veltrix or which items are warnings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
FC = ROOT / "data" / "forecast"
CACHE = FC / "headline_cache.json"
OUT = FC / "news_claude.csv"
PROMPT_VERSION = "h1"
MODEL = os.environ.get("COPILOT_HEADLINE_MODEL", "claude-sonnet-5-5")
BATCH = 25

# style -> (share of items, instruction given to Claude)
STYLES = {
    "rewrite":   (0.30, "Rewrite in fresh wording, as a different news desk would. Same facts, different sentence."),
    "wire":      (0.12, "Terse wire-service style (Reuters/PTI-like), with a short dateline-free lead in the snippet."),
    "trade":     (0.12, "Trade-press style for logistics or electronics buyers; may use industry jargon (TEU, berth, fab, lead times)."),
    "local":     (0.08, "Local newspaper style, more human detail, slightly longer headline."),
    "ticker":    (0.08, "Very short ticker or alert style, under 9 words, abbreviations allowed."),
    "typos":     (0.10, "Rewrite with 1-3 realistic typing mistakes (swapped or missing letters) in words, including possibly a place name."),
    "hindi":     (0.07, "Translate into Hindi (Devanagari). Keep place and company names recognisable; numbers may stay as digits."),
    "hinglish":  (0.06, "Hinglish: Hindi words in Latin script mixed with English, as on Indian social media or WhatsApp forwards."),
    "explainer": (0.04, "Explainer or question headline (e.g. 'What the ... means for ...'), same facts."),
    "caps":      (0.03, "ALL-CAPS breaking-news style."),
}

SYSTEM = """You rewrite news items for a test dataset. For each item you get a headline, an optional snippet and a style.
Write a new headline (and a snippet if one was given, else an empty snippet) in that style.

Hard rules - the rewrite must keep, exactly:
- every place, port, route, company and commodity named (spelling may change only if the style asks for typos or Hindi);
- the kind of event (storm, strike, fire, congestion, duty, outage ...);
- its status: happening now, forecast or warned, forecast to miss, rumour or denied, threat only, over or resolved, routine;
- any numbers, durations, dates and percentages.
Do not add facts, places, companies, causes or consequences that are not in the original. Do not make it more or less
alarming. Do not merge items. Return one result per input id, same ids."""


class Rewrite(BaseModel):
    id: str
    headline: str
    snippet: str


class Batch(BaseModel):
    items: list[Rewrite]


_lock = threading.Lock()


def _key(sid: str, h: str, s: str, style: str) -> str:
    return f"{PROMPT_VERSION}:{hashlib.sha1(f'{sid}|{style}|{h}|{s}'.encode('utf-8')).hexdigest()[:16]}"


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(c: dict) -> None:
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE)


def items(seed: int = 42) -> pd.DataFrame:
    n = pd.read_csv(FC / "news.csv")
    n["snippet"] = n["snippet"].fillna("")
    rng = np.random.default_rng(seed)
    names, w = list(STYLES), np.array([v[0] for v in STYLES.values()])
    n["style"] = rng.choice(names, size=len(n), p=w / w.sum())
    n["key"] = [_key(*r) for r in n[["signal_id", "headline", "snippet", "style"]].itertuples(index=False)]
    return n


def _prompt(rows: pd.DataFrame) -> str:
    return "\n\n".join(f"id: {r.signal_id}\nstyle: {STYLES[r.style][1]}\nheadline: {r.headline}\nsnippet: {r.snippet}"
                       for r in rows.itertuples())


def rewrite_batch(client, rows: pd.DataFrame) -> dict[str, Rewrite]:
    resp = client.messages.parse(
        model=MODEL, max_tokens=8000, output_config={"effort": "low"},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _prompt(rows)}], output_format=Batch)
    if resp.stop_reason in ("refusal", "max_tokens") or resp.parsed_output is None:
        with _lock, open(FC / "headline_errors.log", "a", encoding="utf-8") as lf:
            lf.write(f"no result: stop_reason={resp.stop_reason}\n")
        return {}
    want = set(rows["signal_id"])
    return {x.id: x for x in resp.parsed_output.items if x.id in want and x.headline.strip()}


def run(n: pd.DataFrame, client, workers: int = 6) -> tuple[int, int]:
    cache = load_cache()
    todo = n[~n["key"].isin(cache)]
    chunks = [todo.iloc[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    done = failed = 0
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(rewrite_batch, client, ch): ch for ch in chunks}
        for f in as_completed(futs):
            ch = futs[f]
            try:
                got = f.result()
            except Exception as e:                       # one failed batch never stops the run; re-run to retry
                print("batch failed:", type(e).__name__, str(e)[:120])
                with _lock, open(FC / "headline_errors.log", "a", encoding="utf-8") as lf:
                    lf.write(f"{type(e).__name__}: {str(e)[:400]}\n")
                got = {}
            with _lock:
                for r in ch.itertuples():
                    x = got.get(r.signal_id)
                    if x is None:
                        failed += 1
                        continue
                    cache[r.key] = {"headline": x.headline.strip(), "snippet": x.snippet.strip()}
                    done += 1
                _save(cache)
            print(f"  {done + failed}/{len(todo)} items ({failed} to retry)")
    return done, failed


_PLACES = None


def _places() -> list[str]:
    global _PLACES
    if _PLACES is None:
        d = pd.read_csv(FC / "disruptions.csv")
        p = set()
        for loc in d["location"]:
            p |= {w.strip() for w in re.split(r"[,/→]| - ", str(loc)) if len(w.strip()) > 3}
        _PLACES = sorted(p - {"India (all states)", "All Indian ports"}, key=len, reverse=True)
    return _PLACES


def place_kept(orig: str, new: str, style: str) -> bool | None:
    """For items naming a place we track: does the rewrite still name it? None when not checkable."""
    if style in ("hindi", "hinglish", "typos"):
        return None
    named = [p for p in _places() if p.lower() in orig.lower()]
    if not named:
        return None
    return all(p.lower() in new.lower() for p in named)


def write(n: pd.DataFrame) -> pd.DataFrame:
    cache = load_cache()
    out = n.copy()
    out["original_headline"], out["original_snippet"] = out["headline"], out["snippet"]
    hit = out["key"].map(cache)
    has = hit.notna()
    out.loc[has, "headline"] = [c["headline"] for c in hit[has]]
    out.loc[has, "snippet"] = [c["snippet"] for c in hit[has]]
    out["style"] = np.where(has, out["style"], "original")
    out["place_kept"] = [place_kept(f"{a} {b}", f"{c} {d}", s) if s != "original" else None
                         for a, b, c, d, s in out[["original_headline", "original_snippet", "headline", "snippet", "style"]].itertuples(index=False)]
    out.drop(columns=["key"]).to_csv(OUT, index=False)
    return out


def summary(out: pd.DataFrame) -> dict:
    lab = pd.read_csv(FC / "signal_labels.csv")[["signal_id", "relevant_to_veltrix"]]
    o = out.merge(lab, on="signal_id")
    pk = o["place_kept"].dropna()
    return {"items": len(o), "rewritten": int((o["style"] != "original").sum()),
            "unique_headlines_before": int(o["original_headline"].nunique()), "unique_headlines_after": int(o["headline"].nunique()),
            "styles": o["style"].value_counts().to_dict(),
            "place_kept_checked": int(len(pk)), "place_kept_pct": round(100 * float(pk.mean()), 1) if len(pk) else None,
            "warnings_rewritten": int(((o["style"] != "original") & o["relevant_to_veltrix"]).sum())}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--estimate", action="store_true")
    g.add_argument("--sample", type=int)
    g.add_argument("--run", action="store_true")
    g.add_argument("--write", action="store_true", help="rebuild news_claude.csv from the cache only")
    a = ap.parse_args()
    n = items()
    if a.estimate:
        todo = n[~n["key"].isin(load_cache())]
        calls = -(-len(todo) // BATCH)
        print(f"{len(n)} items, {len(todo)} not yet rewritten -> {calls} calls of {BATCH}")
        print(f"approx tokens: input {calls * (650 + BATCH * 95):,}, output {calls * BATCH * 70:,} (model {MODEL})")
        print("styles:", n["style"].value_counts().to_dict())
        return
    if a.sample or a.run:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("Set ANTHROPIC_API_KEY in this terminal first.")
        import anthropic
        client = anthropic.Anthropic(timeout=120.0, max_retries=6)
        part = n.sample(a.sample, random_state=1) if a.sample else n
        if a.sample:   # make sure the sample includes warnings, which carry the labels that matter
            lab = pd.read_csv(FC / "signal_labels.csv")
            warn = n[n["signal_id"].isin(lab.loc[lab["relevant_to_veltrix"], "signal_id"])].head(max(5, a.sample // 4))
            part = pd.concat([part, warn]).drop_duplicates("signal_id")
        d, f = run(part, client, workers=int(os.environ.get("HEADLINE_WORKERS", "6")))
        print(f"rewritten {d}, failed {f}")
    out = write(n)
    s = summary(out)
    print(json.dumps(s, indent=1, ensure_ascii=False))
    if a.sample:
        for r in out[out["signal_id"].isin(part["signal_id"])].head(25).itertuples():
            print(f"[{r.style}] {r.original_headline}\n   -> {r.headline}")


if __name__ == "__main__":
    main()

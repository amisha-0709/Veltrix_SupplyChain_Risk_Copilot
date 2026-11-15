"""Live news feed: real headlines from free public sources, run through the same pipeline as 'Try a signal'.

Sources (no API key; the free-sources assumption in the running cost):
  * Google News RSS search, one query per part of Veltrix's network (ports, lanes, fab clusters, commodities).
  * GDELT DOC API as a backup when Google News returns nothing (GDELT rate-limits hard, so it is never the first call).

The news is real; Veltrix's suppliers, stock and customers are synthetic. Real ports, lanes and commodities link to the
network; the fictional supplier names never appear in real news. Impact is computed against the synthetic data pack.
"""
from __future__ import annotations

import email.utils
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (compatible; risk-copilot-demo/1.0)"}
WINDOW = "when:3d"
MAX_ITEMS = 30

# One search per slice of the network. Kept short: Google News handles OR lists and quoted names.
QUERIES = [
    '(Kaohsiung OR Busan OR Yokohama OR Keelung) port (typhoon OR strike OR closure OR congestion OR earthquake)',
    '(Shanghai OR Ningbo OR Shenzhen OR Yantian) port (typhoon OR closure OR congestion OR strike OR lockdown)',
    '(Penang OR "Port Klang" OR "Hai Phong" OR Hsinchu) (factory OR fab OR port) (fire OR flood OR shutdown OR closure OR strike OR earthquake)',
    '("Red Sea" OR Suez OR "Strait of Malacca" OR "Taiwan Strait") shipping (attack OR disruption OR blocked OR diverted)',
    '("Chennai port" OR "Nhava Sheva" OR JNPT OR Mundra OR "Kamarajar") (congestion OR strike OR closure OR outage)',
    '("rare earth" OR magnets OR "lithium-ion cells" OR MLCC OR semiconductor OR gallium) (export ban OR export controls OR duty OR shortage)',
    '(Pune OR Chakan OR Hosur OR Bengaluru) (supplier OR plant OR factory) (fire OR flood OR power cut OR strike)',
]
GDELT_QUERY = '("Red Sea" OR Suez OR Kaohsiung OR Busan OR Penang OR "Hai Phong" OR Shanghai) (port OR shipping)'


def _get(url: str, timeout: float = 10.0) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _clean_title(title: str, source: str) -> str:
    t = re.sub(r"\s+", " ", title or "").strip()
    if source and t.endswith(" - " + source):        # Google News appends " - Outlet"
        t = t[: -len(source) - 3].strip()
    return t


def parse_google_rss(xml: bytes | str) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for it in root.iter("item"):
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        title = _clean_title(it.findtext("title", ""), source)
        if len(title) < 5:
            continue
        pub = None
        try:
            pub = email.utils.parsedate_to_datetime(it.findtext("pubDate", "")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
        out.append({"title": title[:300], "source": source or "Google News", "url": it.findtext("link", ""),
                    "published": pub.isoformat(timespec="seconds") if pub else None, "feed": "Google News"})
    return out


def fetch_google(query: str) -> list[dict]:
    q = urllib.parse.quote(f"{query} {WINDOW}")
    return parse_google_rss(_get(f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"))


def fetch_gdelt(query: str) -> list[dict]:
    q = urllib.parse.quote(f"{query} sourcelang:english")
    j = json.loads(_get(f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&format=json"
                        f"&maxrecords=25&timespan=3d"))
    out = []
    for a in j.get("articles", []):
        try:
            pub = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
        except (KeyError, ValueError):
            pub = None
        if len(a.get("title", "")) >= 5:
            out.append({"title": a["title"][:300], "source": a.get("domain", "GDELT"), "url": a.get("url", ""),
                        "published": pub, "feed": "GDELT"})
    return out


def _tokens(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2}


def dedupe(items: list[dict], threshold: float = 0.6) -> list[dict]:
    """Same story from several outlets -> one item that lists every source (as in acceptance test T3)."""
    kept: list[dict] = []
    for it in sorted(items, key=lambda x: x["published"] or "", reverse=True):
        tok = _tokens(it["title"])
        for k in kept:
            inter = len(tok & k["_tok"])
            if tok and inter / len(tok | k["_tok"]) >= threshold:
                if it["source"] not in k["sources"]:
                    k["sources"].append(it["source"])
                break
        else:
            kept.append({**it, "sources": [it["source"]], "_tok": tok})
    for k in kept:
        k.pop("_tok")
    return kept


def fetch_all(queries: list[str] | None = None, max_items: int = MAX_ITEMS) -> tuple[list[dict], list[str]]:
    """All queries in parallel. Returns (deduplicated newest items, errors)."""
    queries = queries or QUERIES
    errors: list[str] = []

    def one(q):
        try:
            return fetch_google(q)
        except Exception as e:  # one bad query never sinks the refresh
            errors.append(f"Google News: {type(e).__name__}")
            return []
    with ThreadPoolExecutor(max_workers=len(queries)) as ex:
        items = [x for batch in ex.map(one, queries) for x in batch]
    if not items:
        try:
            items = fetch_gdelt(GDELT_QUERY)
        except Exception as e:
            errors.append(f"GDELT: {type(e).__name__}")
    return dedupe(items)[:max_items], sorted(set(errors))

"""Veltrix supply network graph + gazetteer for entity linking.

Node ids are prefixed by type so they never collide:
    sup:SUP-001  part:PRT-001  sku:BMS-48V-16S  cust:Kairo EV
    port:Kaohsiung  lane:LN-01  choke:Strait of Malacca  dest:Nhava Sheva (JNPT)
    plant:Pune (Chakan)  country:Taiwan  cat:Semiconductors  loc:Hsinchu

Edges point "downstream" (from where risk originates to where it lands):
    country -> port -> supplier -> part -> sku -> customer
    supplier -> lane -> choke / dest ;  cat -> part ; loc -> port / supplier
A disruption at node X threatens every part reachable from X.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import networkx as nx
import pandas as pd

from core.etl import load

# --- Hand-curated aliases (the network sheets only hold canonical names) ----------
# Port -> names a news item might use for it (city, region, alt port names).
PORT_ALIASES: dict[str, list[str]] = {
    "Kaohsiung": ["kaohsiung", "southern taiwan", "south taiwan"],
    "Keelung": ["keelung", "northern taiwan", "north taiwan", "taipei", "hsinchu"],
    "Yantian (Shenzhen)": ["yantian", "shenzhen", "guangdong", "pearl river delta"],
    "Ningbo": ["ningbo", "zhejiang"],
    "Shanghai": ["shanghai"],
    "Yokohama": ["yokohama", "tokyo", "kanagawa"],
    "Busan": ["busan", "pusan"],
    "Penang": ["penang"],
    "Port Klang": ["port klang", "klang", "selangor", "kuala lumpur"],
    "Hai Phong": ["hai phong", "haiphong", "northern vietnam", "north vietnam", "hanoi"],
    "Laem Chabang": ["laem chabang", "bangkok"],
    "Hamburg": ["hamburg"],
    "Rotterdam": ["rotterdam"],
    "Domestic — Pune": ["pune", "chakan", "maharashtra"],
    "Domestic — Chennai": ["chennai", "sriperumbudur", "tamil nadu"],
    "Domestic — Bengaluru/Hosur": ["bengaluru", "bangalore", "hosur", "karnataka"],
}
# Indian destination ports.
DEST_ALIASES: dict[str, list[str]] = {
    "Nhava Sheva (JNPT)": ["nhava sheva", "jnpt", "jawaharlal nehru port", "mumbai"],
    "Chennai Port": ["chennai port", "chennai", "ennore"],
}
CHOKE_ALIASES: dict[str, list[str]] = {
    "Strait of Malacca": ["malacca", "strait of malacca", "singapore strait"],
    "Red Sea / Suez Canal": ["red sea", "suez", "bab el-mandeb", "bab-el-mandeb", "houthi", "gulf of aden"],
}
COUNTRY_ALIASES: dict[str, list[str]] = {
    "China": ["china", "chinese", "beijing", "prc"],
    "India": ["india", "indian"],
    "Taiwan": ["taiwan", "taiwanese"],
    "Malaysia": ["malaysia", "malaysian"],
    "Japan": ["japan", "japanese"],
    "Germany": ["germany", "german"],
    "South Korea": ["south korea", "korea", "korean"],
    "Vietnam": ["vietnam", "vietnamese"],
    "Thailand": ["thailand", "thai"],
}
# Part category -> commodity words used in news / trade notices.
CATEGORY_ALIASES: dict[str, list[str]] = {
    # Gallium/germanium are raw materials Veltrix doesn't buy: deliberately NOT linked.
    "Semiconductors": ["semiconductor", "chip", "chipmaker", "chipmakers", "mosfet", "mosfets", "mcu",
                        "microcontroller", "fab", "fabs", "foundry", "wafer", "integrated circuit", "igbt"],
    "Passives": ["mlcc", "capacitor", "passive component", "passives", "resistor", "inductor"],
    "PCBs": ["pcb", "pcbs", "printed circuit", "circuit board"],
    "Connectors": ["connector", "connectors"],
    "Magnets": ["rare-earth", "rare earth", "ndfeb", "neodymium", "magnet", "magnets", "ferrite"],
    "Li-ion cells": ["li-ion", "lithium", "battery cell", "cell maker", "cell plant", "battery maker",
                     "cylindrical cells", "lfp", "21700"],
    "Displays": ["display", "lcd", "tft", "touch panel"],
    "Castings": ["casting", "castings", "die-cast", "die-castings"],
    "Copper & harness": ["harness", "busbar", "wiring harness"],
    "Plastics": ["polymer", "resin", "plastic", "pa66", "abs "],
}
# Weather-alert locations that are not ports -> port nodes they affect.
LOCATION_TO_PORTS: dict[str, list[str]] = {
    "Mumbai / JNPT": ["dest:Nhava Sheva (JNPT)"],
    "Chennai": ["dest:Chennai Port", "port:Domestic — Chennai"],
    "Pune": ["port:Domestic — Pune"],
    "Bengaluru/Hosur": ["port:Domestic — Bengaluru/Hosur"],
    "Shenzhen": ["port:Yantian (Shenzhen)"],
    "Hsinchu": ["port:Keelung"],
}


# Region-level phrases -> the network nodes they cover.
REGION_ALIASES: dict[str, tuple[list[str], list[str]]] = {
    "region:Indian ports": (["indian ports", "major ports", "bills of entry", "customs portal", "icegate",
                             "indian customs"], ["dest:Nhava Sheva (JNPT)", "dest:Chennai Port"]),
    "region:India road freight": (["transporters", "truckers", "goods trucks", "trucking"],
                                  ["port:Domestic — Pune", "port:Domestic — Chennai",
                                   "port:Domestic — Bengaluru/Hosur"]),
    "region:Asia–India sea lanes": (["asia–india", "asia-india", "india-bound", "asia–india trade lane"],
                                    ["choke:Strait of Malacca"]),
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).lower()).strip()


@dataclass
class Network:
    G: nx.DiGraph
    gazetteer: list[tuple[re.Pattern, str, str]] = field(default_factory=list)  # (pattern, alias, node)

    # ---- traversal ---------------------------------------------------------------
    def parts_exposed(self, node: str) -> set[str]:
        """Part ids whose primary supply path passes through `node`."""
        if node not in self.G:
            return set()
        if node.startswith("part:"):
            return {node[5:]}
        if node.startswith(("sku:", "cust:")):
            return set()
        reach = nx.descendants(self.G, node)
        return {n[5:] for n in reach if n.startswith("part:")}

    def skus_using(self, part_ids) -> set[str]:
        out = set()
        for p in part_ids:
            out |= {n[4:] for n in self.G.successors(f"part:{p}") if n.startswith("sku:")}
        return out

    def node_type(self, node: str) -> str:
        return self.G.nodes[node].get("type", node.split(":", 1)[0])

    # ---- entity linking ----------------------------------------------------------
    def match(self, text: str) -> list[dict]:
        """Gazetteer hits in free text: [{alias, node, type}] (longest alias wins on overlap)."""
        t = " " + _norm(text) + " "
        hits, taken = [], []
        for pat, alias, node in self.gazetteer:
            for m in pat.finditer(t):
                span = m.span()
                if any(a < span[1] and span[0] < b for a, b in taken):
                    continue
                taken.append(span)
                hits.append({"alias": alias, "node": node, "type": node.split(":", 1)[0]})
                break
        # de-dup by node
        seen, out = set(), []
        for h in hits:
            if h["node"] not in seen:
                seen.add(h["node"])
                out.append(h)
        return out


def _main_lanes(shipments: pd.DataFrame) -> pd.DataFrame:
    """Lanes each supplier actually uses (from shipment history, excluding air expedites)."""
    s = shipments.dropna(subset=["lane_id"])
    return s.groupby(["supplier_id", "lane_id"]).size().rename("n").reset_index()


@lru_cache(maxsize=1)
def build_network() -> Network:
    db = load()
    sup, parts, skus, bom, lanes = (db[k] for k in ("suppliers", "parts", "skus", "bom", "lanes"))
    G = nx.DiGraph()

    for c in sup["country"].unique():
        G.add_node(f"country:{c}", type="country", name=c)
    for cat in parts["category"].unique():
        G.add_node(f"cat:{cat}", type="cat", name=cat)

    for r in sup.itertuples():
        port = f"port:{r.port_of_loading}"
        G.add_node(port, type="port", name=r.port_of_loading, country=r.country)
        G.add_edge(f"country:{r.country}", port)
        G.add_node(f"sup:{r.supplier_id}", type="sup", name=r.supplier_name, **{
            k: getattr(r, k) for k in ("category", "country", "region", "port_of_loading", "tier",
                                       "lead_time_days", "on_time_rate_last_12m",
                                       "financial_health_score", "share_of_veltrix_spend_pct")})
        G.add_edge(port, f"sup:{r.supplier_id}")

    for r in lanes.itertuples():
        G.add_node(f"lane:{r.lane_id}", type="lane", name=f"{r.origin} → {r.destination}",
                   origin=r.origin, destination=r.destination, chokepoint=r.chokepoint,
                   transit_days=r.transit_days_typical, reroute=r.reroute_option,
                   air_days=r.air_alternative_days, air_mult=r.air_cost_multiplier)
        if r.chokepoint and r.chokepoint != "Road":
            G.add_node(f"choke:{r.chokepoint}", type="choke", name=r.chokepoint)
        if "plant" not in str(r.destination):
            G.add_node(f"dest:{r.destination}", type="dest", name=r.destination)

    # Risk at a chokepoint or Indian destination port flows to the suppliers whose lanes
    # use it. We model that as choke/dest -> supplier edges (plus supplier -> lane for display).
    for r in _main_lanes(db["shipments"]).itertuples():
        ln = lanes.loc[lanes["lane_id"] == r.lane_id].iloc[0]
        s = f"sup:{r.supplier_id}"
        G.add_edge(s, f"lane:{r.lane_id}", rel="ships_via")
        if ln.chokepoint and ln.chokepoint != "Road":
            G.add_edge(f"choke:{ln.chokepoint}", s, rel="route")
        if f"dest:{ln.destination}" in G:
            G.add_edge(f"dest:{ln.destination}", s, rel="route")

    for r in parts.itertuples():
        p = f"part:{r.part_id}"
        G.add_node(p, type="part", name=r.description, category=r.category,
                   single_source=bool(r.single_source), days_of_cover=r.days_of_cover,
                   lead_time_days=r.lead_time_days, primary=r.primary_supplier_id,
                   qualified_alt=r.qualified_alternate_supplier_id,
                   unqualified_alt=r.unqualified_alternate_supplier_id)
        G.add_edge(f"sup:{r.primary_supplier_id}", p, rel="primary")
        G.add_edge(f"cat:{r.category}", p, rel="category")
        # Alternates are recorded as attributes (not edges) so that an event at an
        # alternate supplier does not count as exposure of the part.

    for r in skus.itertuples():
        G.add_node(f"sku:{r.sku_id}", type="sku", name=r.sku_name, family=r.product_family,
                   plant=r.plant, customer=r.primary_customer, price=r.price_inr)
        G.add_node(f"cust:{r.primary_customer}", type="cust", name=r.primary_customer)
        G.add_edge(f"sku:{r.sku_id}", f"cust:{r.primary_customer}")
    for r in bom.itertuples():
        G.add_edge(f"part:{r.part_id}", f"sku:{r.sku_id}", qty=r.qty_per_unit)

    for loc, targets in LOCATION_TO_PORTS.items():
        G.add_node(f"loc:{loc}", type="loc", name=loc)
        for t in targets:
            if t in G:
                G.add_edge(f"loc:{loc}", t)

    for reg, (_, targets) in REGION_ALIASES.items():
        G.add_node(reg, type="region", name=reg.split(":", 1)[1])
        for t in targets:
            if t in G:
                G.add_edge(reg, t)

    # ---- gazetteer -----------------------------------------------------------------
    entries: list[tuple[str, str]] = []
    for reg, (al, _) in REGION_ALIASES.items():
        entries += [(a, reg) for a in al]
    for port, al in PORT_ALIASES.items():
        entries += [(a, f"port:{port}") for a in al]
    for d, al in DEST_ALIASES.items():
        entries += [(a, f"dest:{d}") for a in al]
    for c, al in CHOKE_ALIASES.items():
        entries += [(a, f"choke:{c}") for a in al]
    for c, al in COUNTRY_ALIASES.items():
        entries += [(a, f"country:{c}") for a in al]
    for c, al in CATEGORY_ALIASES.items():
        entries += [(a, f"cat:{c}") for a in al]
    for r in sup.itertuples():
        name = _norm(r.supplier_name)
        entries.append((name, f"sup:{r.supplier_id}"))
        short = re.sub(r"\b(corp\.?|co\.?|ltd\.?|limited|inc\.?|sdn bhd|gmbh|pvt\.?|"
                       r"private|plc|ag|k\.k\.|kk|jsc)\b", "", name).strip(" .,")
        if short and short != name:
            entries.append((short, f"sup:{r.supplier_id}"))
    # Longest alias first so "port klang" beats "klang", supplier names beat categories.
    entries = sorted(set(entries), key=lambda e: (-len(e[0]), e[0], e[1]))  # deterministic tie-break
    gaz = []
    for alias, node in entries:
        a = alias.strip()
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])")
        gaz.append((pat, a, node))
    return Network(G=G, gazetteer=gaz)


if __name__ == "__main__":
    net = build_network()
    G = net.G
    from collections import Counter
    print("nodes", G.number_of_nodes(), "edges", G.number_of_edges())
    print(Counter(net.node_type(n) for n in G))
    for q in ["port:Kaohsiung", "choke:Red Sea / Suez Canal", "cat:Magnets", "port:Penang",
              "dest:Nhava Sheva (JNPT)", "country:Japan"]:
        ps = net.parts_exposed(q)
        print(f"{q:30s} parts={len(ps):3d} skus={len(net.skus_using(ps)):3d}")
    for t in ["Typhoon forecast to hit southern Taiwan in five days",
              "Red Sea attacks force carriers round the Cape",
              "China announces export licensing on rare-earth magnets",
              "Shenzhen PCB maker delays payments to its suppliers",
              "Heavy rain alert for Mumbai; JNPT congestion rising"]:
        print(t, "->", [h["node"] for h in net.match(t)])

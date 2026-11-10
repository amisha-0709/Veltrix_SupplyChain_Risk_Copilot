"""M1 regression: the network and exposure numbers must keep reproducing the brief."""
from core.exposure import headline_checks
from core.graph import build_network
from core.timeline import timeline_summary


def test_headlines_match_brief():
    h = headline_checks()
    assert h["single_source_parts"] == 26
    assert h["single_source_cover_below_lead"] == 22
    assert abs(h["single_source_median_cover"] - 15.6) <= 0.15
    assert h["east_asia_spend_pct"] == 71.6
    assert h["single_source_spend_pct"] == 46.0
    assert h["disruptions_with_stoppage"] == 9
    assert abs(h["revenue_lost_inr_cr"] - 170) < 1
    assert h["lost_revenue_via_single_source_pct"] == 95.5
    assert h["weeks_with_shortage"] == 27
    assert h["min_weekly_otif_pct"] == 63.5
    assert abs(h["mitigation_spend_no_shortage_inr_cr"] - 4.6) < 0.05


def test_timeline_matches_brief():
    s = timeline_summary()
    assert s["disruptions_with_warning"] == 15
    assert s["median_warning_lead_days"] == 18
    assert s["median_team_alert_offset_days"] == 1
    assert s["median_days_to_decision"] == 9


def test_graph_exposure_matches_history():
    net = build_network()
    # D01 Kaohsiung: 5 parts / 15 SKUs; D03 Red Sea: 4 / 20; D04 magnets: 2 / 2
    for node, parts, skus in [("port:Kaohsiung", 5, 15), ("choke:Red Sea / Suez Canal", 4, 20),
                              ("cat:Magnets", 2, 2)]:
        ps = net.parts_exposed(node)
        assert len(ps) == parts, node
        assert len(net.skus_using(ps)) == skus, node


def test_gazetteer_links_acceptance_headlines():
    net = build_network()
    nodes = lambda t: {h["node"] for h in net.match(t)}  # noqa: E731
    assert "port:Kaohsiung" in nodes("Typhoon forecast to hit southern Taiwan in five days")       # T1
    assert "choke:Red Sea / Suez Canal" in nodes("Red Sea attacks force carriers round the Cape")  # T3
    assert {"cat:Magnets", "country:China"} <= nodes("China export licensing on rare-earth magnets")  # T4
    assert {"port:Yantian (Shenzhen)", "cat:PCBs"} <= nodes("Shenzhen PCB maker delays payments")  # T5
    assert "dest:Nhava Sheva (JNPT)" in nodes("Heavy rain alert for Mumbai, JNPT congestion rising")  # T7

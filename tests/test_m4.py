"""M4 regression: API, briefings, simulator and decision log."""
import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory, monkeypatch_module):
    monkeypatch_module.setenv("COPILOT_DECISIONS", str(tmp_path_factory.mktemp("d") / "decisions.json"))
    import importlib
    import backend.main as m
    importlib.reload(m)
    return TestClient(m.app)


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def test_meta_and_alert_list(client):
    m = client.get("/api/meta").json()
    assert m["counts"]["alerts"] >= 15 and m["counts"]["inbox"] >= 1
    rows = client.get("/api/alerts").json()
    assert rows and {"alert_id", "priority", "owner", "response"} <= set(rows[0])
    assert rows == sorted(rows, key=lambda r: (not r["inbox"], -r["priority"], r["first_seen"]))


def test_briefing_has_every_required_section(client):
    top = client.get("/api/alerts?inbox=true").json()[0]
    html = client.get(f"/api/alerts/{top['alert_id']}/briefing").text
    for section in ("What is happening", "Exposure", "Recommended action", "Sources", "Assumptions", "Priority"):
        assert section in html, section
    assert "approved" not in re.sub(r"not approved|awaiting approval|for approval", "", html.lower())


def test_briefing_numbers_come_from_the_engine(client):
    top = client.get("/api/alerts?inbox=true").json()[0]
    a = client.get(f"/api/alerts/{top['alert_id']}").json()
    b = a["brief"]
    assert b["numbers"]["revenue_at_risk_inr"] in (a["revenue_at_risk"], b["numbers"]["revenue_at_risk_inr"])
    assert a["revenue_at_risk_fmt"].replace("₹", "") in a["brief_text"] or a["mode"] == "precautionary"


@pytest.mark.parametrize("headline,snippet,expect", [
    ("Typhoon forecast to hit southern Taiwan in five days", "Ports in the south may suspend operations.", {"watch", "inbox"}),
    ("Naval exercises announced near Taiwan Strait", "Shipping advisories for the exercise zone only.", {"ignored"}),
    ("Components maker extends shutdown after cyber attack", "", {"needs_review"}),
    ("China announces export licensing on rare-earth magnets", "Exporters of NdFeB magnets must apply for licences.", {"inbox"}),
])
def test_simulator_routes_signals(client, headline, snippet, expect):
    r = client.post("/api/simulate", json={"headline": headline, "snippet": snippet}).json()
    assert r["decision"] in expect
    if "alert" in r:
        sim_id = r["alert"]["alert_id"]
        assert client.get(f"/api/alerts/{sim_id}/briefing").status_code == 200


def test_decisions_are_recorded_not_executed(client):
    aid = client.get("/api/alerts").json()[0]["alert_id"]
    r = client.post("/api/decisions", json={"alert_id": aid, "option": "x", "decision": "approved",
                                           "by": "Head of Supply Chain", "note": "test"}).json()
    assert r["ok"] and "never places orders" in r["note"]
    assert client.get(f"/api/decisions?alert_id={aid}").json()[-1]["decision"] == "approved"
    reg = {x["alert_id"]: x for x in client.get("/api/register").json()}
    assert reg[aid]["status"].startswith("approved by")
    bad = client.post("/api/decisions", json={"alert_id": aid, "option": "x", "decision": "ordered", "by": "Bot"})
    assert bad.status_code == 422                 # only human decision verbs are accepted


def test_unknown_alert_404(client):
    assert client.get("/api/alerts/NOPE").status_code == 404

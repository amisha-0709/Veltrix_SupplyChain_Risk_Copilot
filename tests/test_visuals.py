"""Tier-1 visuals: plain names for ids, the replay timeline fields, and the UI hooks the demo relies on."""
from fastapi.testclient import TestClient

import backend.main as m

c = TestClient(m.app)


def test_names_cover_every_part_and_supplier():
    n = c.get("/api/names").json()
    assert len(n["parts"]) == 65 and len(n["suppliers"]) == 87
    assert n["parts"]["PRT-004"]["name"] == "Si MOSFET 100V"
    assert n["suppliers"]["SUP-005"]["name"] and n["suppliers"]["SUP-005"]["country"]


def test_replay_carries_history_timeline():
    r = c.get("/api/replays/D04").json()
    assert r["first_signal_date"].startswith("2025-01-28") and r["had_warning"] is True
    assert r["copilot_lead_days"] > 7


def test_ui_has_visuals():
    assert 'src="visuals.js' in c.get("/").text
    js = c.get("/visuals.js").text
    for f in ("function flowStrip", "function traceCols", "function coverChart", "function replayTimeline"):
        assert f in js
    app = c.get("/app.js").text
    assert "alertVisual(a)" in app and 'viewReplay(did = "D04")' in app

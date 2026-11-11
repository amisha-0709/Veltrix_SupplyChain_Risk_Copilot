"""Persona pages' data endpoint: read-only, every inbox alert carries what the four role pages show."""
from fastapi.testclient import TestClient

from backend.main import app

c = TestClient(app)


def test_persona_bundle():
    r = c.get("/api/persona")
    assert r.status_code == 200
    j = r.json()
    assert len(j["customers"]) == 6 and "Semiconductors" in j["categories"]
    inbox = [a for a in j["alerts"] if a["inbox"]]
    assert len(inbox) == 5
    for a in inbox:
        assert a["category"] and a["revenue_at_risk_fmt"]
        assert a["options"] or not a["revenue_at_risk"]   # no action needed when stock covers the delay
        assert all(o["approver"] for o in a["options"])
    pen = next(a for a in j["alerts"] if a["alert_id"] == "AL-005")
    assert {c["customer"] for c in pen["customers"]} >= {"Kairo EV", "Ojas Motors"}
    assert all(c["products"] and c["weeks_below"] >= 1 for c in pen["customers"])


def test_ui_ships_persona_pages():
    from pathlib import Path
    html = Path("public/index.html").read_text(encoding="utf-8")
    js = Path("public/personas.js").read_text(encoding="utf-8")
    assert "personas.js" in html and "#/p/coo" in html
    for v in ("viewCategory", "viewHosc", "viewCoo", "viewSales"):
        assert v in js

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
    assert "personas.js" in html and 'id="role"' in html                     # "View as" role switcher
    assert all(f'value="{k}"' in html for k in ("category", "hosc", "coo", "sales"))
    for v in ("viewCategory", "viewHosc", "viewCoo", "viewSales"):
        assert v in js


def test_role_nav_and_all_tools():
    """Each seat's nav shows only its pages; everything else is one click away under All tools."""
    import re
    from pathlib import Path
    html = Path("public/index.html").read_text(encoding="utf-8")
    app = Path("public/app.js").read_text(encoding="utf-8")
    assert 'id="toolsbtn"' in html and 'id="toolsmenu"' in html
    m = re.search(r"const ROLE_NAV = \{(.*?)\};", app, re.S)
    nav = {k: re.findall(r'"(\w+)"', v) for k, v in re.findall(r'(\w+|"")\s*:\s*\[([^\]]*)\]', m.group(1))}
    assert nav["category"] == ["desk", "alerts", "live"]
    assert nav["hosc"] == ["desk", "alerts", "live", "register"]
    assert nav["coo"] == ["desk", "replay", "business"]
    assert nav["sales"] == ["desk", "alerts", "live"]
    for p in ("ask", "exposure", "register", "replay", "business", "evidence"):   # every page still reachable
        assert f"{p}: [\"#/" in app


def test_pages_lead_with_a_glance():
    """Every busy page opens with a glance strip; detail sits in tiles that expand on click."""
    import re
    from pathlib import Path
    src = Path("public/app.js").read_text(encoding="utf-8") + Path("public/personas.js").read_text(encoding="utf-8")
    assert "const glance =" in src and "const fold =" in src and ".fold" in Path("public/styles.css").read_text(encoding="utf-8")
    for fn in ("viewCategory", "viewHosc", "viewCoo", "viewSales", "viewSalesAll", "viewRegister", "viewReplay",
               "viewBusiness", "viewExposure", "viewBacktest"):
        body = re.search(rf"function {fn}\(.*?\n}}\n", src, re.S).group(0)
        assert "glance(" in body and "fold(" in body, fn
    assert "askBlock(" not in src                     # the Ask bar at the top replaces the per-desk ask boxes


def test_leading_indicators():
    j = c.get("/api/leading").json()
    assert j["ports"] and j["rule"]
    port_cases = [h for h in j["history"] if h["type"] in ("Weather", "Logistics")]
    assert sum(h["flagged_before"] for h in port_cases) >= 3          # 3 of 4 port disruptions flagged ahead
    assert not any(h["flagged_before"] for h in j["history"] if h["type"] in ("Supplier incident", "Cyber"))

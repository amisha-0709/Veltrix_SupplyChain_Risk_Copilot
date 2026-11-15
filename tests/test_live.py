"""Live news feed: parsing, merging duplicate stories, and the endpoint running real-looking headlines through the
same pipeline as 'Try a signal'. No network: the fetch is replaced with fixed headlines."""
from fastapi.testclient import TestClient

import backend.main as m
from core import live_feed

c = TestClient(m.app)

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Busan port closed as dockworkers strike; cranes idle at main terminals - Reuters</title><link>https://example.com/a</link>
<pubDate>Sat, 14 Nov 2026 08:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>Busan port closed as dockworkers strike, cranes idle at main terminals - Korea Herald</title><link>https://example.com/b</link>
<pubDate>Sat, 14 Nov 2026 07:00:00 GMT</pubDate><source url="https://koreaherald.com">Korea Herald</source></item>
<item><title>Electric two-wheeler sales hit a record in October - Mint</title><link>https://example.com/c</link>
<pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate><source url="https://livemint.com">Mint</source></item>
</channel></rss>"""


def test_parse_and_merge():
    items = live_feed.parse_google_rss(RSS)
    assert [i["source"] for i in items] == ["Reuters", "Korea Herald", "Mint"]
    assert items[0]["title"].endswith("main terminals")          # " - Outlet" suffix removed
    merged = live_feed.dedupe(items)
    assert len(merged) == 2
    assert merged[0]["sources"] == ["Reuters", "Korea Herald"]  # same story, two outlets, one item


def test_refresh_runs_pipeline(monkeypatch):
    monkeypatch.setattr(live_feed, "fetch_all", lambda *a, **k: (live_feed.dedupe(live_feed.parse_google_rss(RSS)), []))
    monkeypatch.setattr(m, "_LIVE", {"fetched_at": None, "items": [], "errors": [], "fetched_ts": 0.0})
    from core import llm_chat
    monkeypatch.setattr(llm_chat, "enabled", lambda: False)      # rules only: deterministic
    j = c.post("/api/live/refresh").json()
    assert len(j["items"]) == 2 and not j["cached"]
    busan = next(i for i in j["items"] if "Busan" in i["title"])
    assert busan["decision"] in ("inbox", "watch") and any("Busan" in n for n in busan["links"])
    assert busan["alert"] and c.get(f"/api/alerts/{busan['alert']['alert_id']}").status_code == 200
    assert next(i for i in j["items"] if "two-wheeler" in i["title"])["decision"] == "ignored"
    assert j["items"][0]["decision"] != "ignored"                # alerts sort first
    # a second refresh inside the cool-down serves the same result without fetching
    monkeypatch.setattr(live_feed, "fetch_all", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    assert c.post("/api/live/refresh").json()["cached"] is True
    assert c.get("/api/live").json()["items"] == j["items"]


def test_ui_has_live_tab():
    html = c.get("/").text
    assert 'href="#/live"' in html
    js = c.get("/app.js").text
    assert "viewLive" in js and "Claude flagged for a person to check" in js

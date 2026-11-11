"""Regression tests for the high-severity issues found in the simulated persona test (reports/persona_test.html)."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from core.ask import _duration_days, ask


@pytest.mark.parametrize("q,days", [("for forty days", 40), ("forty-five days", 45), ("for ninety days", 90),
                                    ("thirteen days", 13), ("six weeks", 42), ("two months", 60), ("a fortnight", 14),
                                    ("ten days", 10), ("for 40 days", 40)])
def test_duration_words(q, days):
    assert _duration_days(q) == days


def test_forty_days_is_not_silently_defaulted():
    r = ask("Which products stop first if Kaohsiung closes for forty days?")
    delays = [row[3] for t in r["tables"] if t["title"] == "Parts in scope" for row in t["rows"]]
    assert delays and all(d == 40 for d in delays)
    assert not r["answer"].startswith("Nothing stops")


def test_unreadable_duration_asks_back():
    r = ask("What if Kaohsiung closes for a few weeks?")
    assert r["intent"] == "clarify" and "won't guess" in r["answer"]


def test_empty_place_commodity_match_falls_back_not_nothing_stops():
    r = ask("Which lines at the Chakan plant stop first if rare-earth magnet supply is cut for a month?")
    assert "I used every Magnets part" in r["answer"]
    assert any(row[0] == "PRT-043" for t in r["tables"] if t["title"] == "Parts in scope" for row in t["rows"])


def test_ask_shows_the_reading_briefings_use():
    r = ask("Which customers miss their 95% OTIF target if Penang semiconductor output stops for six weeks?")
    assert "₹49.80 cr" in r["answer"] and "Allowing the typical recovery time" in r["answer"] and "₹90.30 cr" in r["answer"]


def test_simulations_stay_in_their_own_session():
    c = TestClient(app)
    mine, other = {"X-Copilot-Session": "persona-test-mine"}, {"X-Copilot-Session": "persona-test-other"}
    r = c.post("/api/simulate", json={"headline": "Fire at a Penang MOSFET plant; output halted for six weeks"}, headers=mine).json()
    aid = r["alert"]["alert_id"]
    assert aid.startswith("SIM-AL-") and len(aid) > len("SIM-AL-001")          # random, not guessable
    ids = lambda h: {a["alert_id"] for a in c.get("/api/alerts", headers=h).json()}  # noqa: E731
    assert aid in ids(mine)
    assert aid not in ids(other) and aid not in ids({})
    assert aid not in {a["alert_id"] for a in c.get("/api/register", headers=other).json()}
    inbox_other = c.post("/api/ask", json={"question": "What's in the inbox right now?"}, headers=other).json()
    assert aid not in str(inbox_other)
    assert c.get(f"/api/alerts/{aid}/briefing").status_code == 200              # a shared briefing link still opens

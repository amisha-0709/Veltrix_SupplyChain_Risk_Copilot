"""Brief §6 acceptance scenarios T1–T10, end to end through the API, plus chat honesty rules."""
import pytest

from core.acceptance import ALL, _client
from core.ask import ask


@pytest.fixture(scope="module")
def client():
    return _client()


@pytest.mark.parametrize("check", ALL, ids=[f.__name__.upper() for f in ALL])
def test_acceptance(client, check):
    r = check(client)
    assert r["passed"], "\n".join(r["evidence"])


def test_ask_refuses_to_guess():
    r = ask("Will it rain tomorrow?")
    assert r["intent"] == "clarify" and "won't guess" in r["answer"]


def test_ask_no_action_when_cover_holds():
    r = ask("Which products stop first if Kaohsiung closes for ten days?")
    assert r["answer"].startswith("Nothing stops")


def test_ask_numbers_match_engine():
    from core.impact import Scenario, fmt_inr, run
    from core.ask import _scope
    r = ask("Which customers miss their 95% OTIF target if Penang semiconductor output stops for six weeks?")
    parts, _ = _scope(r["scenario"]["nodes"])
    t = run(Scenario(parts=parts, nodes=r["scenario"]["nodes"], event_type="supplier_outage", delay_days=42)).totals
    assert fmt_inr(t["revenue_at_risk_inr"]) in r["answer"]


def test_replay_d05_structural_fix_dominates():
    from core.replay import replay
    r = replay("D05")
    assert r["copilot_lead_days"] == 0 and r["team_decision_day"] == 11
    assert r["structural"]["revenue_protected_inr"] > 0.5 * r["actual_revenue_lost_inr"]

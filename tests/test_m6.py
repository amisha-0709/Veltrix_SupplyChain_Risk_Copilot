"""M6: business case, structural recommendations, false-alarm analysis, UI endpoint."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from core.false_alarms import ablations
from core.roi import annual_cost, business_case
from core.structural import structural_summary, structural_table


@pytest.fixture(scope="module")
def bc():
    return business_case()


def test_business_case_counts_running_costs_and_pays_back(bc):
    cost, rows = annual_cost()
    assert {r["item"] for r in rows} >= {"risk owner", "news and data feeds", "hosting", "model calls"}
    assert cost > 30e5                                    # people and data, not just model calls
    b = bc["base"]
    assert b["net"] == pytest.approx(b["margin_protected"] + b["penalties_avoided"] + b["waste_avoided"] - b["mitigation_cost"])
    assert b["net"] < b["revenue_protected"]              # margin, not revenue
    assert all(r["roi"] > 1 for r in bc["scenarios"])     # every sensitivity still pays back


def test_no_action_replays_get_no_credit(bc):
    df = bc["replays"]
    none = df[df["top_action"] == "No action"]
    assert (none["margin_protected_inr"] == 0).all() and (none["plan_cost_inr"] == 0).all()


def test_structural_moves_target_single_source_parts():
    st = structural_table()
    assert len(st) == 26
    top = st.iloc[0]
    assert top["part_id"] == "PRT-004" and top["recommendation"].startswith("Qualify SUP-011")
    s = structural_summary(st)
    assert s["parts_with_positive_move"] == s["qualify_moves"] + s["buffer_moves"]


def test_each_guard_cuts_false_alarms():
    ab = ablations(3.5).set_index("guard removed")
    built = ab.loc["None (as built)"]
    assert built["false_alarm_signals_test"] == 0
    for g in ("Dampener cues", "Trade product filter", "Weather severity gate (≥4 → ≥3)"):
        assert ab.loc[g, "false_alarm_signals_test"] > built["false_alarm_signals_test"]


def test_business_case_endpoint():
    c = TestClient(app)
    r = c.get("/api/business-case")
    assert r.status_code == 200
    j = r.json()
    assert j["annual_cost_inr"] > 0 and len(j["scenarios"]) == 5 and j["structural"]

"""M3 regression: triage, dedup, scoring and the T9 back-test targets."""
import pandas as pd
import pytest

from core.alerts import build_alert
from core.backtest import run_backtest
from core.events import build_events
from core.triage import tune_threshold, triage_all, triage_text


@pytest.fixture(scope="module")
def bt():
    return run_backtest()


@pytest.fixture(scope="module")
def th():
    return tune_threshold(triage_all())


def test_t9_targets_on_test_period(bt):
    s, a, lead = bt["signals"]["test"], bt["alerts"]["test"], bt["lead"]["test"]
    assert s["recall"] >= 0.80            # brief: ≥ 80% of relevant signals
    assert a["precision"] >= 0.60         # brief: ≥ 60% alert precision
    assert lead["median_lead_days"] >= 7  # brief: median ≥ 7 days before impact
    assert lead["detected"] == lead["disruptions_with_warning"]


def test_every_warned_disruption_detected(bt):
    L = bt["lead_table"]
    assert L[L.had_warning]["lead_days"].notna().all()


def test_t1_typhoon_links_kaohsiung(th):
    t = triage_text("Typhoon forecast to hit southern Taiwan in five days",
                    "Ports in the south may suspend operations; carriers warn of delays.")
    assert t["score"] >= th and "port:Kaohsiung" in t["links"]


def test_t2_naval_exercise_not_high_priority(th):
    t = triage_text("Naval exercises announced near Taiwan Strait",
                    "Shipping advisories issued for the exercise zone only.")
    assert t["score"] < th                # logged / ignored, never a high-priority alert


def test_t3_three_sources_one_alert(th):
    rows = []
    for i, src in enumerate(["Global Trade Wire", "Container Pulse", "Harbour Times"]):
        t = triage_text("Attacks on merchant vessels in the Red Sea escalate — update",
                        "Major carriers divert via the Cape of Good Hope.", source=src,
                        published=pd.Timestamp("2026-10-01 08:00") + pd.Timedelta(hours=6 * i),
                        signal_id=f"T3-{i}")
        rows.append(t)
    events, review = build_events(pd.DataFrame(rows), th)
    assert len(events) == 1 and len(events[0].sources) == 3


def test_t4_trade_notice_magnets(th):
    t = triage_text("China announces export licensing on rare-earth magnets",
                    "Exporters of NdFeB magnets must apply for licences.")
    assert t["score"] >= th and t["event_type"] == "trade_licensing" and "cat:Magnets" in t["links"]


def test_t5_supplier_health_is_flagged(th):
    t = triage_text("Shenzhen PCB maker delays supplier payments",
                    "Local suppliers report invoices outstanding for over 90 days.")
    assert t["score"] >= th and t["event_type"] == "supplier_outage"


def test_t8_ransomware_flagged_and_quantified(th):
    t = triage_text("Japanese electronic components maker hit by ransomware",
                    "Production and shipping halted while systems are restored.",
                    published="2026-09-30 09:00", signal_id="T8")
    assert t["score"] >= th
    events, _ = build_events(pd.DataFrame([t]), th)
    a = build_alert(events[0])
    assert a["seconds_to_quantify"] < 300   # brief: signal → quantified impact < 5 min
    assert len(a["options"]) > 0


def test_routine_noise_is_dropped(th):
    for h in ["Tropical depression in the Arabian Sea likely to weaken",
              "Freight rates on Shanghai–Nhava Sheva lane stable this week",
              "Rumours of Chennai port labour action denied by management",
              "Typhoon forecast to pass east of Taiwan",
              "Security researchers warn of phishing campaign targeting manufacturers"]:
        assert triage_text(h)["score"] < th, h


def test_judge_promotes_only_with_real_links(tmp_path, monkeypatch, th):
    """A cached Claude verdict promotes a near-threshold story, but can't link a story to a non-existent node."""
    import json
    import core.llm_judge as lj
    T = triage_all()
    near, unlinked = lj.borderline(T, th)
    freight = near[near["text"].str.contains("more than double")].iloc[0]
    cyber = unlinked.iloc[0]
    cache = tmp_path / "cache.json"
    v_ok = {"relevant": True, "event_type": "congestion", "places": ["Strait of Malacca"], "categories": [],
            "is_forecast": False, "confidence": 0.9, "reason": "freight capacity squeeze on our Asia lanes"}
    v_nowhere = {**v_ok, "places": ["Atlantis"], "event_type": "supplier_outage"}
    cache.write_text(json.dumps({f"{lj.PROMPT_VERSION}:story:{freight.story_key}": v_ok,
                                 f"{lj.PROMPT_VERSION}:story:{cyber.story_key}": v_nowhere}))
    monkeypatch.setattr(lj, "CACHE", cache)
    T2, s = lj.apply_judge(T, th, run=False)
    assert (T2.loc[T2.story_key == freight.story_key, "score"] >= th).all()
    assert (T2.loc[T2.story_key == cyber.story_key, "link_strength"] == 0).all()   # still Needs review

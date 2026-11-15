"""Triage on real-world wording: negation and reassurance, Hindi, typos, synonyms. Sentences are written for the
test, not taken from any dataset."""
from core.triage import repair, triage_text

TH = 3.5


def score(h, s=""):
    return triage_text(h, s)["score"]


def test_reassurance_is_not_an_alert():
    assert score("Heavy rain expected in Chennai this week", "No major disruption to port operations is expected") < TH
    assert score("Busan dock workers end pay talks with no strike action", "Operations continue normally") < TH


def test_real_disruption_still_alerts():
    assert score("Busan port closed as dockworkers strike") >= TH
    assert score("Kaohsiung schedules may be disrupted as typhoon nears") >= TH
    assert score("Union at Korean battery maker votes in favour of strike") >= TH


def test_hindi_links_and_scores():
    t = triage_text("ताइवान में बाढ़ से बंदरगाह बंद रहे")          # floods close ports in Taiwan
    assert "country:Taiwan" in t["links"] and t["score"] >= TH
    assert score("चेन्नई में भारी बारिश, कोई बड़ा व्यवधान अपेक्षित नहीं") < TH   # heavy rain, no disruption expected
    assert "आग" not in " ".join(triage_text("पुणे में बातचीत आगे बढ़ेगी")["cues"])  # 'aage' (ahead) is not 'aag' (fire)


def test_typos_repaired_but_normal_words_kept():
    assert repair("Typhoon nears southren Taiwan; port may suspned cargo") == "Typhoon nears southern Taiwan; port may suspend cargo"
    assert repair("closer stride words") == "closer stride words"
    assert score("Cylcone forces Keelung port to suspned operations") >= TH


def test_followups_join_open_alert_without_new_alerts():
    """A crisis follow-up naming the same place joins the open alert as an update; neutral news never does."""
    import pandas as pd
    from core.events import build_events
    rows = [("A1", "2024-06-10", "Houthi missile strikes tanker in Red Sea"),
            ("A2", "2024-06-12", "Red Sea crisis continues for container lines"),          # follow-up: crisis words, no cue
            ("A3", "2024-06-12", "Red Sea cruise line launches new itinerary"),            # neutral: never attaches
            ("A4", "2024-06-13", "Westports in Port Klang reports record volumes")]       # other place, neutral
    T = pd.DataFrame([{**triage_text(h, "", "test", d, signal_id=i), "signal_id": i} for i, d, h in rows])
    T["kind"] = "news"
    events, _ = build_events(T, TH)
    assert len(events) == 1 and [s["signal_id"] for s in events[0].signals] == ["A1"]
    assert [u["signal_id"] for u in events[0].updates] == ["A2"]
    assert "port:Port Klang" in triage_text("Fire at Westports container yard")["links"]

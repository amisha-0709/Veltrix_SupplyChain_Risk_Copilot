"""Claude chat (core/llm_chat.py) with a fake client: Claude interprets, the engine answers.

One Claude call per question; the answer is the engine's own text; only the question is sent to the API."""
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import backend.main as M
from core import llm_chat
from core.ask import ask


def _usage():
    return NS(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0)


class FakeClient:
    """Returns the given tool calls (or a text reply when calls is empty)."""

    def __init__(self, calls, text=""):
        self.calls, self.text, self.sent = calls, text, []
        self.messages = self

    def create(self, **kw):
        self.sent.append(kw)
        if self.calls:
            return NS(stop_reason="tool_use", usage=_usage(),
                      content=[NS(type="tool_use", id=f"tu_{i}", name=n, input=a) for i, (n, a) in enumerate(self.calls)])
        return NS(stop_reason="end_turn", usage=_usage(), content=[NS(type="text", text=self.text)])


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("COPILOT_CHAT_LLM", "1")

    def use(calls, text=""):
        fc = FakeClient(calls, text)
        monkeypatch.setattr(llm_chat, "_client", fc)
        return fc
    M._llm_hits.clear(); M._llm_day.clear()
    return use


PENANG = {"places": ["Penang"], "commodities": ["Semiconductors"], "duration_days": 42, "event_type": "supplier_outage",
          "include_options": True}


def test_claude_interprets_engine_answers(fake):
    fc = fake([("what_if", PENANG)])
    r = TestClient(M.app).post("/api/ask", json={"question": "penang chps stop 6 wks, wat do we do"}).json()
    rules = ask("Which customers miss their 95% OTIF target if Penang semiconductor output stops for six weeks?")
    assert r["engine"] == "claude" and r["tool_calls"] == 1 and len(fc.sent) == 1          # one Claude call only
    assert r["answer"].startswith(rules["answer"][:120])                                    # the engine's own text
    assert "₹49.80 cr" in r["answer"] and "Best option" in r["answer"]
    assert r["interpretation"][0].startswith("what_if(places=Penang")
    assert any(t["title"].startswith("Ranked options") for t in r["tables"])


def test_only_the_question_is_sent(fake):
    fc = fake([("exposure", {"places": ["Shanghai"], "commodities": []})])
    TestClient(M.app).post("/api/ask", json={"question": "How exposed are we to Shanghai?"})
    assert fc.sent[0]["messages"] == [{"role": "user", "content": "How exposed are we to Shanghai?"}]
    assert fc.sent[0]["model"] == llm_chat.MODEL and fc.sent[0]["tools"] == llm_chat.TOOLS


def test_comparison_gives_one_labelled_engine_answer_per_item(fake):
    fake([("exposure", {"places": ["Kaohsiung"], "commodities": []}), ("exposure", {"places": ["Shanghai"], "commodities": []})])
    r = TestClient(M.app).post("/api/ask", json={"question": "kaohsiung vs shanghai exposure"}).json()
    assert r["answer"].startswith("Kaohsiung: ") and "\n\nShanghai: " in r["answer"]
    titles = [t["title"] for t in r["tables"]]
    assert "Parts (Kaohsiung)" in titles and "Parts (Shanghai)" in titles


def test_no_tool_means_short_claude_reply(fake):
    fake([], "I can't place orders; the co-pilot only recommends and people decide.")
    r = TestClient(M.app).post("/api/ask", json={"question": "Order 5000 magnets"}).json()
    assert r["engine"] == "claude" and r["tool_calls"] == 0 and "can't place orders" in r["answer"]


def test_unknown_place_is_reported_not_guessed():
    r = llm_chat.run_tool("what_if", {"places": ["Atlantis"], "commodities": [], "duration_days": 10,
                                      "event_type": "port_closure", "include_options": False}, [], None)
    assert r["intent"] == "clarify" and "Atlantis" in r["answer"]


def test_falls_back_to_rules_when_claude_fails(fake, monkeypatch):
    class Broken:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            raise TimeoutError("simulated")
    monkeypatch.setattr(llm_chat, "_client", Broken())
    r = TestClient(M.app).post("/api/ask", json={"question": "Which products stop first if Kaohsiung closes for ten days?"}).json()
    assert r["engine"] == "rules" and "unavailable" in r["engine_note"] and r["answer"].startswith("Nothing stops")


def test_rate_limit_falls_back_to_rules(fake, monkeypatch):
    monkeypatch.setattr(M, "LLM_PER_CLIENT_HOUR", 2)
    c = TestClient(M.app)
    h = {"X-Copilot-Session": "rate-limit-test-1"}
    for _ in range(2):
        fake([("inbox", {})])
        assert c.post("/api/ask", json={"question": "What's in the inbox?"}, headers=h).json()["engine"] == "claude"
    r = c.post("/api/ask", json={"question": "What's in the inbox?"}, headers=h).json()
    assert r["engine"] == "rules" and "last hour" in r["engine_note"]


def test_without_key_rules_answer(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = TestClient(M.app).post("/api/ask", json={"question": "What's in the inbox right now?"}).json()
    assert r["engine"] == "rules" and "engine_note" not in r
    assert TestClient(M.app).get("/api/chat-engine").json()["engine"] == "rules"


def test_tool_schemas_are_strict():
    for t in llm_chat.TOOLS:
        s = t["input_schema"]
        assert t["strict"] and s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])


def test_new_tools_answer_from_stored_data():
    import json as _j
    s = _j.load(open("data/snapshot.json", encoding="utf-8"))
    ex = {"m6": s["m6"], "replays": s["replays"]}
    r = llm_chat.run_tool("structural_moves", {"top_n": 3}, [], None, ex)
    assert r["intent"] == "structural" and "PRT-004" in r["answer"] and "SUP-011" in r["answer"]
    r = llm_chat.run_tool("business_case", {}, [], None, ex)
    assert "ROI" in r["answer"] and "₹46.9 lakh" in r["answer"]
    r = llm_chat.run_tool("disruption_history", {"order": "revenue_lost", "top_n": 3}, [], None, ex)
    assert r["answer"].count("D0") >= 3 and "Worst: D05" in r["answer"]
    r = llm_chat.run_tool("exposure", {"places": [], "commodities": []}, [], None, ex)
    assert r["answer"].startswith("Across the whole network") and "no alternate supplier at all" in r["answer"]


def test_alert_options_name_customers():
    import backend.main as BM
    r = llm_chat.run_tool("alert_options", {"alert_id": "AL-019"}, [], BM._alert)
    assert "Customers below 95% OTIF:" in r["answer"]

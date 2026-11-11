"""Claude chat (core/llm_chat.py) with a fake client: tool loop, numbers from the engine, privacy, fallback, rate limit."""
import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import backend.main as M
from core import llm_chat


def _usage():
    return NS(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0)


class FakeClient:
    """Round 1: Claude calls the given tool. Round 2: Claude answers, quoting the tool result's first ₹ figure."""

    def __init__(self, tool, args):
        self.tool, self.args, self.sent = tool, args, []
        self.messages = self

    def create(self, **kw):
        self.sent.append(kw)
        if len(self.sent) == 1:
            return NS(stop_reason="tool_use", usage=_usage(),
                      content=[NS(type="tool_use", id="tu_1", name=self.tool, input=self.args)])
        result = kw["messages"][-1]["content"][0]["content"]
        fig = json.loads(result)["answer"].split("₹")[1].split(" ")[0] if "₹" in result else "?"
        return NS(stop_reason="end_turn", usage=_usage(), content=[NS(type="text", text=f"About ₹{fig} cr at risk.")])


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("COPILOT_CHAT_LLM", "1")

    def use(tool, args):
        fc = FakeClient(tool, args)
        monkeypatch.setattr(llm_chat, "_client", fc)
        return fc
    M._llm_hits.clear(); M._llm_day.clear()
    return use


def test_tool_loop_uses_engine_numbers_and_shows_working(fake):
    fc = fake("what_if", {"places": ["Penang"], "commodities": ["Semiconductors"], "duration_days": 42,
                          "event_type": "supplier_outage", "include_options": True})
    r = TestClient(M.app).post("/api/ask", json={"question": "Penang chips stop six weeks?"}).json()
    assert r["engine"] == "claude" and r["tool_calls"] == 1
    assert r["answer"] == "About ₹49.80 cr at risk."                 # the engine's figure, passed through
    assert any("what_if(" in w for w in r["working"])
    assert any(t["title"].startswith("Ranked options") for t in r["tables"])
    first = fc.sent[0]
    assert first["model"] == llm_chat.MODEL and first["tools"] == llm_chat.TOOLS and "Answer ONLY from tool results" in first["system"]


def test_supplier_names_are_not_sent_to_claude(fake):
    fc = fake("exposure", {"places": ["Shanghai"], "commodities": []})
    TestClient(M.app).post("/api/ask", json={"question": "How exposed are we to Shanghai?"})
    sent = fc.sent[1]["messages"][-1]["content"][0]["content"]
    assert "Supplier" not in json.loads(sent)["tables"][0]["columns"]
    assert "Semiconductor Co" not in sent


def test_unknown_place_is_reported_not_guessed(fake):
    fake("what_if", {"places": ["Atlantis"], "commodities": [], "duration_days": 10, "event_type": "port_closure",
                     "include_options": False})
    r = llm_chat.run_tool("what_if", {"places": ["Atlantis"], "commodities": [], "duration_days": 10,
                                      "event_type": "port_closure", "include_options": False}, [], None)
    assert r["intent"] == "clarify" and "Atlantis" in r["answer"]


def test_falls_back_to_rules_when_claude_fails(fake, monkeypatch):
    class Broken:
        messages = None

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
        fake("inbox", {})
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

"""The rule step that lets Claude add or drop signals (core.triage_llm.apply_rule). It only runs when a Claude-assisted
rule is chosen, so it never ran in the deployed back-test; this keeps it from crashing when that day comes."""
import pandas as pd

from core.triage_llm import apply_rule


def _frame():
    return pd.DataFrame({
        "signal_id": ["A", "B", "C", "D"],
        "score": [5.0, 1.0, 0.0, 4.0],
        "links": [["port:Busan"], ["cat:Magnets"], [], ["port:Penang"]],
        "llm_links": [["port:Busan"], ["country:China", "cat:Magnets"], ["port:Kaohsiung"], []],
        "llm_relevant": [True, True, True, False],
        "link_strength": [2.0, 1.0, 0.0, 2.0],
        "event_type": ["congestion", None, None, "supplier_outage"],
        "llm_event_type": ["congestion", "trade_licensing", "port_closure", None],
    })


def test_either_adds_with_merged_links_and_keeps_rules():
    T = apply_rule(_frame(), 3.5, "either")
    assert list(T["score"]) == [5.0, 3.5, 3.5, 4.0]                 # B and C added on the threshold; A, D untouched
    assert T.at[1, "links"] == ["cat:Magnets", "country:China"]      # merged, no duplicates, own links first
    assert T.at[2, "links"] == ["port:Kaohsiung"]
    assert T.at[2, "link_strength"] == 1.0 and T.at[1, "event_type"] == "trade_licensing"


def test_both_drops_what_claude_rejects():
    T = apply_rule(_frame(), 3.5, "both")
    assert T.at[3, "score"] < 3.5 and T.at[0, "score"] == 5.0


def test_rules_is_a_no_op_copy():
    F = _frame()
    T = apply_rule(F, 3.5, "rules")
    assert T.equals(F) and T is not F

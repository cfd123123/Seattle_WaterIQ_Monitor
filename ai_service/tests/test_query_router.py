"""Tests for the multi-label intent router (rules → structured LLM)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from assistant.copilot_prompts import build_router_messages
from assistant.llm_client import CompletionResult
from assistant.rag.query_router import (
    ROUTER_RESPONSE_FORMAT,
    Intent,
    RouteLabels,
    action_request_answer,
    classify_and_rewrite,
    parse_router_output,
    route_by_rules,
    try_turbidity_sites_list_answer,
)
from assistant.rag.route_rules import Signal, match_rules

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "intent_eval.json"
_CASES: list[dict[str, Any]] = json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _llm_must_not_run(_messages: list[dict[str, str]]) -> CompletionResult:
    raise AssertionError("LLM should not be called for rule-decided questions")


def _mock_llm(text: str) -> Any:
    calls: list[list[dict[str, str]]] = []

    def _complete(messages: list[dict[str, str]]) -> CompletionResult:
        calls.append(messages)
        return CompletionResult(text=text, model="mock", provider="ollama")

    _complete.calls = calls  # type: ignore[attr-defined]
    return _complete


# --- fixture: rules decide their cases and abstain on the rest -------------


@pytest.mark.parametrize("case", [c for c in _CASES if c["via"] == "rule"], ids=lambda c: c["id"])
def test_fixture_rule_cases_decided_without_llm(case: dict[str, Any]) -> None:
    result = classify_and_rewrite(
        case["question"],
        history=case.get("history"),
        complete_fn=_llm_must_not_run,
    )
    assert result.intent.value == case["expected_intent"]
    assert result.source == "rule"
    assert result.matched_rules


@pytest.mark.parametrize("case", [c for c in _CASES if c["via"] == "llm"], ids=lambda c: c["id"])
def test_fixture_llm_cases_rules_abstain(case: dict[str, Any]) -> None:
    """Rule precision guard: a rule firing on a hard case would bypass the LLM with a guess."""
    assert route_by_rules(case["question"], has_history=bool(case.get("history"))) is None


# --- labels → intent --------------------------------------------------------


@pytest.mark.parametrize(
    ("labels", "intent"),
    [
        (RouteLabels(need_tools=True, need_docs=True), Intent.HYBRID),
        (RouteLabels(need_tools=True), Intent.LIVE_DATA),
        (RouteLabels(need_docs=True), Intent.OPS_DOC),
        (RouteLabels(chitchat=True), Intent.CHITCHAT),
        (RouteLabels(in_scope=False, need_tools=True), Intent.OFF_TOPIC),
        (RouteLabels(action_request=True, need_tools=True), Intent.ACTION_REQUEST),
        (RouteLabels(chitchat=True, need_tools=True), Intent.LIVE_DATA),
        (RouteLabels(), Intent.CLARIFY),
    ],
)
def test_labels_to_intent(labels: RouteLabels, intent: Intent) -> None:
    assert labels.to_intent() is intent


# --- LLM output parsing -----------------------------------------------------


def test_parse_labels_both_needs_is_hybrid() -> None:
    result = parse_router_output(
        '{"in_scope": true, "chitchat": false, "action_request": false, '
        '"need_tools": true, "need_docs": true, "retrieval_query": "recommend_alert Phase B"}'
    )
    assert result.intent is Intent.HYBRID
    assert result.retrieval_query == "recommend_alert Phase B"
    assert result.source == "llm"


def test_parse_labels_drops_retrieval_query_when_docs_not_needed() -> None:
    result = parse_router_output('{"need_tools": true, "need_docs": false, "retrieval_query": "noise"}')
    assert result.intent is Intent.LIVE_DATA
    assert result.retrieval_query is None


def test_parse_labels_coerces_string_booleans() -> None:
    result = parse_router_output('{"in_scope": "true", "need_docs": "true", "retrieval_query": "Phase B"}')
    assert result.intent is Intent.OPS_DOC


def test_parse_legacy_single_intent_json() -> None:
    result = parse_router_output('{"intent": "ops_doc", "retrieval_query": "Phase B recommend_alert"}')
    assert result.intent is Intent.OPS_DOC
    assert result.labels == RouteLabels(need_docs=True)


def test_parse_markdown_fenced_json() -> None:
    text = '```json\n{"in_scope": false, "need_tools": false, "need_docs": false, "retrieval_query": ""}\n```'
    assert parse_router_output(text).intent is Intent.OFF_TOPIC


@pytest.mark.parametrize("text", ["not json", "", '{"need_tools": [1, 2]}', '{"intent": "banana"}'])
def test_parse_invalid_falls_back_to_clarify(text: str) -> None:
    result = parse_router_output(text)
    assert result.intent is Intent.CLARIFY
    assert result.source == "fallback"


# --- LLM call: structured output + history ----------------------------------


def test_router_uses_structured_output_when_available() -> None:
    seen: dict[str, Any] = {}

    def _plain(_messages: list[dict[str, str]]) -> CompletionResult:
        raise AssertionError("structured path expected")

    def _structured(messages: list[dict[str, str]], response_format: dict[str, Any]) -> CompletionResult:
        seen["response_format"] = response_format
        return CompletionResult(
            text='{"in_scope": true, "chitchat": false, "action_request": false, '
            '"need_tools": false, "need_docs": true, "retrieval_query": "turbidity definition"}',
            model="mock",
            provider="ollama",
        )

    _plain.structured = _structured  # type: ignore[attr-defined]
    result = classify_and_rewrite("What is turbidity?", complete_fn=_plain)
    assert result.intent is Intent.OPS_DOC
    assert seen["response_format"] is ROUTER_RESPONSE_FORMAT
    schema = ROUTER_RESPONSE_FORMAT["json_schema"]["schema"]
    assert set(schema["required"]) == set(schema["properties"])


def test_follow_up_with_history_defers_to_llm_and_sends_transcript() -> None:
    history = [
        {"role": "user", "content": "What is the current turbidity at 12117500?"},
        {"role": "assistant", "content": "Turbidity at 12117500 is 62 NTU, tier HIGH."},
    ]
    llm = _mock_llm('{"need_tools": true, "need_docs": false, "retrieval_query": ""}')

    result = classify_and_rewrite("what about 12147600?", history=history, complete_fn=llm)

    assert result.intent is Intent.LIVE_DATA
    assert result.source == "llm"
    user_content = llm.calls[0][-1]["content"]
    assert "Conversation so far:" in user_content
    assert "62 NTU" in user_content
    assert user_content.rstrip().endswith("Latest question: what about 12147600?")


def test_same_question_without_history_is_rule_routed() -> None:
    result = classify_and_rewrite("what about 12147600?", complete_fn=_llm_must_not_run)
    assert result.intent is Intent.LIVE_DATA
    assert result.source == "rule"


def test_router_transcript_is_bounded() -> None:
    history = [{"role": "user", "content": f"turn {i} " + "x" * 1000} for i in range(10)]
    content = build_router_messages("why?", history=history)[-1]["content"]
    assert "turn 9" in content and "turn 5" not in content
    assert len(content) < 4 * 320 + 200


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How do I close an alert?", Intent.OPS_DOC),  # how-to: LLM's action label is vetoed
        ("I'd like the warning threshold lowered to 40 NTU", Intent.ACTION_REQUEST),  # no how-to cue
    ],
)
def test_rule_constraints_veto_llm_action_label_on_how_to(question: str, expected: Intent) -> None:
    llm = _mock_llm('{"action_request": true, "need_tools": false, "need_docs": false, "retrieval_query": ""}')
    assert classify_and_rewrite(question, complete_fn=llm).intent is expected


def test_requires_complete_fn_when_rules_abstain() -> None:
    with pytest.raises(ValueError):
        classify_and_rewrite("What is turbidity?")


# --- rule matching discipline -----------------------------------------------


@pytest.mark.parametrize(
    ("text", "signal"),
    [
        ("In the meantime, check the gauge", Signal.DEFINITION),  # "mean" inside "meantime"
        ("I know the site well", Signal.LIVE),  # "now" inside "know"
        ("What was turbidity on 20260517?", Signal.LIVE),  # date, not a site number
        ("Show alerts since 2026-05-17", Signal.LIVE),
    ],
)
def test_rules_do_not_fire_on_substrings_or_dates(text: str, signal: Signal) -> None:
    assert not match_rules(text).has(signal)


def test_site_number_is_live_signal() -> None:
    m = match_rules("turbidity at 12117500")
    assert m.has(Signal.LIVE)
    assert "live.site_no" in m.rule_names


@pytest.mark.parametrize("question", ["How do I close an alert?", "怎么新建站点", "how to delete a site"])
def test_how_to_is_not_an_action_request(question: str) -> None:
    result = route_by_rules(question)
    assert result is None or result.intent is not Intent.ACTION_REQUEST


def test_off_topic_rule_respects_domain_guard() -> None:
    assert route_by_rules("Will it rain at 12117500 and raise turbidity?") is None or (
        route_by_rules("Will it rain at 12117500 and raise turbidity?").intent is not Intent.OFF_TOPIC
    )


# --- canned answers ---------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("create new site", "Stations page"),
        ("Please close alert 42", "Dashboard"),
        ("Set recommend_alert to false", "cannot be overridden"),
        ("把阈值调高一点", "cannot be overridden"),
    ],
)
def test_action_request_answer_points_to_the_right_place(question: str, expected: str) -> None:
    answer = action_request_answer(question)
    assert "read-only" in answer
    assert expected in answer


def test_try_turbidity_sites_list_answer() -> None:
    answer = try_turbidity_sites_list_answer("Which sites have turbidity monitoring?")
    assert answer is not None
    assert "12117500" in answer
    assert try_turbidity_sites_list_answer("What is Phase B?") is None

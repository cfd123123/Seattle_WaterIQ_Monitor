"""Tests for RAG query router (intent + retrieval rewrite)."""

from __future__ import annotations

import pytest

from assistant.llm_client import CompletionResult
from assistant.rag.query_router import Intent, classify_and_rewrite, parse_router_output, try_turbidity_sites_list_answer


def test_parse_router_json_ops_doc() -> None:
    result = parse_router_output(
        '{"intent": "ops_doc", "retrieval_query": "Phase B recommend_alert online alert"}'
    )
    assert result.intent is Intent.OPS_DOC
    assert "Phase B" in (result.retrieval_query or "")


def test_parse_router_line_format() -> None:
    text = "intent: live_data\nretrieval_query:\n"
    result = parse_router_output(text)
    assert result.intent is Intent.LIVE_DATA


def test_fast_path_chitchat_skips_llm() -> None:
    called = False

    def _should_not_run(_messages: list[dict[str, str]]) -> CompletionResult:
        nonlocal called
        called = True
        return CompletionResult(text="{}", model="x", provider="ollama")

    result = classify_and_rewrite("你好", complete_fn=_should_not_run)
    assert result.intent is Intent.CHITCHAT
    assert called is False


def test_fast_path_off_topic_world_cup_skips_llm() -> None:
    called = False

    def _should_not_run(_messages: list[dict[str, str]]) -> CompletionResult:
        nonlocal called
        called = True
        return CompletionResult(text="{}", model="x", provider="ollama")

    result = classify_and_rewrite("Who won the World Cup?", complete_fn=_should_not_run)
    assert result.intent is Intent.OFF_TOPIC
    assert result.retrieval_query is None
    assert called is False


@pytest.mark.parametrize(
    "question",
    [
        "tell me a joke",
        "what is the stock price of Apple?",
        "write me a poem about cats",
        "what's the weather today?",
    ],
)
def test_fast_path_off_topic_examples_skip_llm(question: str) -> None:
    called = False

    def _should_not_run(_messages: list[dict[str, str]]) -> CompletionResult:
        nonlocal called
        called = True
        return CompletionResult(text="{}", model="x", provider="ollama")

    result = classify_and_rewrite(question, complete_fn=_should_not_run)
    assert result.intent is Intent.OFF_TOPIC
    assert called is False


def test_fast_path_create_site_skips_llm() -> None:
    called = False

    def _should_not_run(_messages: list[dict[str, str]]) -> CompletionResult:
        nonlocal called
        called = True
        return CompletionResult(text="{}", model="x", provider="ollama")

    for question in ("create new site", "add a new site", "新建站点"):
        called = False
        result = classify_and_rewrite(question, complete_fn=_should_not_run)
        assert result.intent is Intent.OFF_TOPIC
        assert called is False


def test_try_turbidity_sites_list_answer() -> None:
    answer = try_turbidity_sites_list_answer("Which sites have turbidity monitoring?")
    assert answer is not None
    assert "12117500" in answer
    assert try_turbidity_sites_list_answer("What is Phase B?") is None


def test_fast_path_off_topic_does_not_reject_monitoring_weather() -> None:
    called = False

    def _mock_router(_messages: list[dict[str, str]]) -> CompletionResult:
        nonlocal called
        called = True
        return CompletionResult(
            text='{"intent": "ops_doc", "retrieval_query": "weather turbidity correlation"}',
            model="mock",
            provider="ollama",
        )

    result = classify_and_rewrite(
        "How does weather affect turbidity readings?",
        complete_fn=_mock_router,
    )
    assert result.intent is Intent.OPS_DOC
    assert called is True


def test_classify_chinese_phase_b_fast_path() -> None:
    called = False

    def _should_not_run(_messages: list[dict[str, str]]) -> CompletionResult:
        nonlocal called
        called = True
        return CompletionResult(text="{}", model="x", provider="ollama")

    result = classify_and_rewrite("Phase B 是什么", complete_fn=_should_not_run)
    assert result.intent is Intent.OPS_DOC
    assert result.retrieval_query is not None
    assert "Phase B" in result.retrieval_query
    assert called is False


def test_parse_router_invalid_defaults_clarify() -> None:
    result = parse_router_output("not valid json at all")
    assert result.intent is Intent.CLARIFY


def test_parse_router_low_confidence_clarify() -> None:
    result = parse_router_output(
        '{"intent": "live_data", "retrieval_query": "", "confidence": 0.2}'
    )
    assert result.intent is Intent.CLARIFY
    assert result.confidence == 0.2


def test_parse_router_markdown_fence_json() -> None:
    result = parse_router_output(
        '```json\n{"intent": "ops_doc", "retrieval_query": "Phase B", "confidence": 0.9}\n```'
    )
    assert result.intent is Intent.OPS_DOC
    assert "Phase B" in (result.retrieval_query or "")


def test_fast_path_live_data_skips_llm() -> None:
    called = False

    def _should_not_run(_messages: list[dict[str, str]]) -> CompletionResult:
        nonlocal called
        called = True
        return CompletionResult(text="{}", model="x", provider="ollama")

    result = classify_and_rewrite(
        "What is the 12h risk for site 12117500?",
        complete_fn=_should_not_run,
    )
    assert result.intent is Intent.LIVE_DATA
    assert called is False


def test_weak_why_alert_is_not_forced_hybrid() -> None:
    def _mock_router(_messages: list[dict[str, str]]) -> CompletionResult:
        return CompletionResult(
            text='{"intent": "clarify", "retrieval_query": "", "confidence": 0.3}',
            model="mock",
            provider="ollama",
        )

    result = classify_and_rewrite("why turbidity alert", complete_fn=_mock_router)
    assert result.intent is Intent.CLARIFY


def test_intent_eval_fixture_fast_paths() -> None:
    import json
    from pathlib import Path

    fixture = Path(__file__).resolve().parent / "fixtures" / "intent_eval.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))

    def _fail_if_called(_messages: list[dict[str, str]]) -> CompletionResult:
        raise AssertionError("LLM should not be called for via=fast_path cases")

    for case in cases:
        if case.get("via") != "fast_path":
            continue
        result = classify_and_rewrite(case["question"], complete_fn=_fail_if_called)
        assert result.intent.value == case["expected_intent"], case["question"]


def test_classify_off_topic_mock_llm() -> None:
    def _mock_router(_messages: list[dict[str, str]]) -> CompletionResult:
        return CompletionResult(
            text='{"intent": "off_topic", "retrieval_query": ""}',
            model="mock",
            provider="ollama",
        )

    # Fast path already handles World Cup; use a monitoring-scoped weather ask for LLM path.
    result = classify_and_rewrite(
        "How does weather affect turbidity readings?",
        complete_fn=_mock_router,
    )
    # Monitoring-scoped weather goes to LLM; mock forces off_topic for this test of parser path.
    # But wait - ops_doc keywords might not match; weather + turbidity is monitoring scoped so not off_topic fast path.
    # Mock returns off_topic - but classify is called with that question and LLM - good.
    assert result.intent is Intent.OFF_TOPIC

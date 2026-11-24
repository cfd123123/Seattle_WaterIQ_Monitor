"""Tests for unified POST /assistant/chat (hybrid + intent routing)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from assistant.llm_client import CompletionResult
from assistant.rag.query_router import Intent, classify_and_rewrite
from assistant.unified_router import answer_unified_question
from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_fast_path_hybrid_intent() -> None:
    result = classify_and_rewrite(
        "Why is recommend_alert true for site 12117500 per Phase B policy?",
    )
    assert result.intent is Intent.HYBRID
    assert result.retrieval_query
    assert "recommend_alert" in result.retrieval_query.lower() or "phase b" in result.retrieval_query.lower()


def test_unified_hybrid_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")

    frozen_tool_result = {
        "ok": True,
        "data": {
            "site_no": "12117500",
            "recommend_alert": True,
            "max_tier_forecast": "HIGH",
            "tier_at_t": "WATCH",
        },
        "source": "python:/turbidity/risk-forecast-12h",
    }

    class FakeHit:
        chunk = type(
            "C",
            (),
            {
                "source_path": "docs/turbidity_operations.md",
                "anchor": "phase-b",
                "heading": "Phase B",
                "text": "Phase B sets recommend_alert from frozen 12h forecast tiers.",
            },
        )()

        def to_source(self) -> dict[str, str]:
            return {
                "type": "doc",
                "ref": "docs/turbidity_operations.md#phase-b",
                "heading": "Phase B",
            }

    phases: list[str] = []

    def mock_classify(_messages: list[dict[str, str]]) -> CompletionResult:
        return CompletionResult(
            text='{"intent": "hybrid", "retrieval_query": "recommend_alert Phase B policy"}',
            model="mock",
            provider="ollama",
        )

    def mock_complete(messages: list[dict[str, Any]]) -> CompletionResult:
        system = messages[0]["content"]
        if "tool router" in system.lower():
            phases.append("select")
            return CompletionResult(
                text=json.dumps(
                    {
                        "tool": "get_turbidity_risk_forecast_12h",
                        "arguments": {"site_no": "12117500"},
                    }
                ),
                model="mock",
                provider="ollama",
            )
        phases.append("synthesize")
        user = messages[-1]["content"]
        assert "Tool result JSON" in user
        assert "Documentation snippets" in user
        return CompletionResult(
            text=(
                "recommend_alert is true with max_tier_forecast HIGH. "
                "Phase B policy ties this to the 12h tier forecast."
            ),
            model="mock",
            provider="ollama",
            usage={"prompt_tokens": 20, "completion_tokens": 15},
        )

    with patch("assistant.unified_router.ensure_rag_index"):
        with patch("assistant.unified_router.search_ops_docs", return_value=[FakeHit()]):
            with patch("assistant.orchestrator.execute_tool", return_value=frozen_tool_result):
                payload = answer_unified_question(
                    "Why is recommend_alert true for site 12117500 per Phase B?",
                    site_no="12117500",
                    classify_fn=mock_classify,
                    complete_fn=mock_complete,
                )

    assert payload["intent"] == "hybrid"
    assert payload["mode"] == "hybrid"
    assert phases == ["select", "synthesize"]
    assert "get_turbidity_risk_forecast_12h" in payload["tool_trace"]
    assert payload["tool_calls"][0]["ok"] is True
    assert any(s["type"] == "api" for s in payload["sources"])
    assert any(s["type"] == "doc" for s in payload["sources"])
    assert "recommend_alert" in payload["answer"].lower()


def test_unified_live_data_delegates_tools_loop() -> None:
    def mock_classify(_messages: list[dict[str, str]]) -> CompletionResult:
        return CompletionResult(
            text='{"intent": "live_data", "retrieval_query": ""}',
            model="mock",
            provider="ollama",
        )

    agent_payload = {
        "answer": "recommend_alert is true.",
        "sources": [{"type": "api", "ref": "python:/turbidity/risk-forecast-12h"}],
        "tool_calls": [{"round": 1, "name": "get_turbidity_risk_forecast_12h", "arguments": {}, "ok": True}],
        "tool_trace": ["get_turbidity_risk_forecast_12h"],
        "mode": "tools",
        "model": "mock",
        "provider": "ollama",
        "usage": None,
        "session_id": None,
    }

    with patch("assistant.unified_router.answer_agent_question", return_value=agent_payload):
        payload = answer_unified_question(
            "What is the 12h turbidity risk for site 12117500?",
            classify_fn=mock_classify,
            complete_fn=lambda _m: CompletionResult(text="x", model="mock", provider="ollama"),
        )

    assert payload["intent"] == "live_data"
    assert payload["mode"] == "tools"
    assert payload["tool_trace"] == ["get_turbidity_risk_forecast_12h"]


def test_unified_chitchat_canned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")

    payload = answer_unified_question("你好")
    assert payload["intent"] == "chitchat"
    assert payload["mode"] == "canned"
    assert payload["tool_calls"] == []
    assert "assistant" in payload["answer"].lower()


def test_unified_query_transform_off_falls_back_live_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "false")

    agent_payload = {
        "answer": "Mock.",
        "sources": [],
        "tool_calls": [],
        "tool_trace": [],
        "mode": "tools",
        "model": "mock",
        "provider": "ollama",
        "usage": None,
        "session_id": None,
    }

    with patch("assistant.unified_router.answer_agent_question", return_value=agent_payload):
        payload = answer_unified_question("hello")

    assert payload["intent"] == "live_data"
    assert payload["mode"] == "tools"


def test_unified_off_topic_canned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")

    payload = answer_unified_question("Who won the World Cup?")
    assert payload["intent"] == "off_topic"
    assert payload["mode"] == "canned"
    assert payload["tool_calls"] == []
    assert "outside turbidity" in payload["answer"].lower()


@pytest.mark.parametrize("use_langgraph", ["true", "false"])
def test_unified_action_request_refused_with_redirect(
    monkeypatch: pytest.MonkeyPatch,
    use_langgraph: str,
) -> None:
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")
    monkeypatch.setenv("ASSISTANT_USE_LANGGRAPH", use_langgraph)

    def no_llm(_messages: list[dict[str, str]]) -> CompletionResult:
        raise AssertionError("write requests are blocked by rules before any LLM call")

    payload = answer_unified_question("create a new site", classify_fn=no_llm, complete_fn=no_llm)
    assert payload["intent"] == "action_request"
    assert payload["mode"] == "canned"
    assert payload["tool_calls"] == []
    assert "Stations page" in payload["answer"]
    if use_langgraph == "true":
        assert payload["route"]["source"] == "rule"
        assert payload["route"]["labels"]["action_request"] is True
        assert "action.imperative_en" in payload["route"]["matched_rules"]


def test_unified_parse_failure_clarify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")

    def mock_classify(_messages: list[dict[str, str]]) -> CompletionResult:
        return CompletionResult(text="garbage not json", model="mock", provider="ollama")

    payload = answer_unified_question(
        "some ambiguous question",
        classify_fn=mock_classify,
        complete_fn=lambda _m: CompletionResult(text="x", model="mock", provider="ollama"),
    )
    assert payload["intent"] == "clarify"
    assert payload["mode"] == "canned"
    assert "rephrase" in payload["answer"].lower()


def test_assistant_chat_hybrid_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "test-key")

    def fake_unified(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "answer": "Hybrid answer with recommend_alert=true and Phase B policy context.",
            "sources": [
                {"type": "api", "ref": "python:/turbidity/risk-forecast-12h"},
                {"type": "doc", "ref": "docs/turbidity_operations.md#phase-b", "heading": "Phase B"},
            ],
            "tool_calls": [
                {
                    "round": 1,
                    "name": "get_turbidity_risk_forecast_12h",
                    "arguments": {"site_no": "12117500"},
                    "ok": True,
                    "source": "python:/turbidity/risk-forecast-12h",
                    "result_preview": {"recommend_alert": True},
                }
            ],
            "tool_trace": ["get_turbidity_risk_forecast_12h"],
            "mode": "hybrid",
            "model": "mock",
            "provider": "openai",
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            "session_id": None,
            "intent": "hybrid",
            "retrieval_query": "recommend_alert Phase B policy",
        }

    with patch("assistant.router.answer_unified_question", side_effect=fake_unified):
        res = client.post(
            "/assistant/chat",
            json={
                "message": "Why is recommend_alert true for site 12117500 per Phase B?",
                "site_no": "12117500",
            },
        )

    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "hybrid"
    assert body["mode"] == "hybrid"
    assert len(body["sources"]) == 2
    assert body["tool_trace"] == ["get_turbidity_risk_forecast_12h"]

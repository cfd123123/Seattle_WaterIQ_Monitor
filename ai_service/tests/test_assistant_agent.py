"""Tests for L3 NL2API agent (POST /assistant/chat)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from assistant.llm_client import CompletionResult, ToolCallSpec
from assistant.orchestrator import answer_agent_question
from assistant.tools.executor import execute_tool, validate_site_no
from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_validate_site_no_accepts_eight_digits() -> None:
    assert validate_site_no("12117500") == "12117500"


def test_validate_site_no_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="8-digit"):
        validate_site_no("abc")


def test_execute_tool_rejects_unknown() -> None:
    result = execute_tool("set_recommend_alert", {"site_no": "12117500"})
    assert result["ok"] is False
    assert result["error_code"] == "TOOL_NOT_ALLOWED"


def test_execute_assistant_health() -> None:
    result = execute_tool("get_assistant_health", {})
    assert result["ok"] is True
    assert result["source"] == "python:/assistant/health"
    assert result["data"]["status"] == "ok"


def test_list_puget_default_sites() -> None:
    result = execute_tool("list_puget_default_sites", {})
    assert result["ok"] is True
    assert result["source"] == "python:/config/puget-default-sites"
    sites = result["data"].get("sites") or []
    assert len(sites) >= 1
    assert any(s.get("site_no") == "12117500" for s in sites)


def test_search_ops_docs_tool() -> None:
    class FakeHit:
        def __init__(self) -> None:
            self.chunk = type(
                "C",
                (),
                {
                    "source_path": "docs/turbidity_operations.md",
                    "anchor": "phase-b",
                    "heading": "Phase B",
                    "text": "Phase B persistence rule for recommend_alert.",
                },
            )()
            self.score = 1.5

    with patch("assistant.rag.search.ensure_rag_index"):
        with patch("assistant.rag.search.search_ops_docs", return_value=[FakeHit()]):
            result = execute_tool("search_ops_docs", {"query": "Phase B recommend_alert"})
    assert result["ok"] is True
    assert result["source"] == "rag:search_ops_docs"
    assert result["data"]["hit_count"] == 1
    assert "Phase B" in result["data"]["hits"][0]["text"]


def test_search_ops_docs_requires_query() -> None:
    result = execute_tool("search_ops_docs", {})
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENT"


def test_execute_state_snapshot_tool() -> None:
    frozen = {
        "site_no": "12117500",
        "alert_tier": "WATCH",
        "state": "Rising",
        "63680": 12.5,
        "is_anomaly": False,
    }
    with patch("models.turbidity_state_monitoring.run_state_snapshot", return_value=frozen):
        result = execute_tool(
            "get_turbidity_state_snapshot",
            {"site_no": "12117500"},
        )
    assert result["ok"] is True
    assert result["data"]["alert_tier"] == "WATCH"
    assert result["source"] == "python:/turbidity/state/snapshot"


def test_registry_includes_new_tools() -> None:
    from assistant.tools.registry import get_tool_names

    names = get_tool_names()
    for expected in (
        "get_turbidity_state_snapshot",
        "list_puget_default_sites",
        "search_ops_docs",
    ):
        assert expected in names


def test_execute_risk_forecast_tool() -> None:
    frozen = {
        "site_no": "12117500",
        "recommend_alert": True,
        "max_tier_forecast": "HIGH",
        "tier_at_t": "WATCH",
    }
    with patch("models.turbidity_risk_forecast_12h.run_risk_forecast_12h", return_value=frozen):
        result = execute_tool(
            "get_turbidity_risk_forecast_12h",
            {"site_no": "12117500"},
        )
    assert result["ok"] is True
    assert result["data"]["recommend_alert"] is True
    assert result["source"] == "python:/turbidity/risk-forecast-12h"


def test_agent_tools_loop_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def mock_complete_with_tools(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> CompletionResult:
        if any(m.get("role") == "tool" for m in messages):
            return CompletionResult(
                text=(
                    "Site 12117500 has recommend_alert=true and max_tier_forecast=HIGH "
                    "per the Phase B API."
                ),
                model="mock",
                provider="ollama",
                usage={"prompt_tokens": 5, "completion_tokens": 10},
            )
        calls.append("tools_round")
        return CompletionResult(
            text="",
            model="mock",
            provider="ollama",
            tool_calls=(
                ToolCallSpec(
                    id="call_1",
                    name="get_turbidity_risk_forecast_12h",
                    arguments=json.dumps({"site_no": "12117500"}),
                ),
            ),
            usage={"prompt_tokens": 3, "completion_tokens": 1},
        )

    frozen = {
        "site_no": "12117500",
        "recommend_alert": True,
        "max_tier_forecast": "HIGH",
        "tier_at_t": "WATCH",
    }

    with patch("assistant.orchestrator.execute_tool", return_value={"ok": True, "data": frozen, "source": "python:/turbidity/risk-forecast-12h"}):
        payload = answer_agent_question(
            "What is the 12h turbidity risk for site 12117500?",
            complete_with_tools_fn=mock_complete_with_tools,
            complete_fn=lambda _m: CompletionResult(text="unused", model="mock", provider="ollama"),
        )

    assert calls == ["tools_round"]
    assert payload["mode"] == "tools"
    assert "get_turbidity_risk_forecast_12h" in payload["tool_trace"]
    assert payload["tool_calls"][0]["ok"] is True
    assert "recommend_alert" in payload["answer"].lower() or "HIGH" in payload["answer"]
    assert any(s["ref"] == "python:/turbidity/risk-forecast-12h" for s in payload["sources"])


def test_agent_lite_fallback_mock() -> None:
    frozen = {
        "site_no": "12117500",
        "recommend_alert": False,
        "max_tier_forecast": "NORMAL",
        "tier_at_t": "NORMAL",
    }
    phases: list[str] = []

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
        phases.append("summarize")
        return CompletionResult(
            text="recommend_alert is false; max_tier_forecast is NORMAL for site 12117500.",
            model="mock",
            provider="ollama",
        )

    with patch("assistant.orchestrator.execute_tool", return_value={"ok": True, "data": frozen, "source": "python:/turbidity/risk-forecast-12h"}):
        payload = answer_agent_question(
            "What is the 12h turbidity risk for site 12117500?",
            complete_fn=mock_complete,
            complete_with_tools_fn=lambda _m, _t: (_ for _ in ()).throw(
                __import__("assistant.llm_client", fromlist=["ToolsNotSupportedError"]).ToolsNotSupportedError(
                    "tools not supported"
                )
            ),
        )

    assert payload["mode"] == "agent_lite"
    assert phases == ["select", "summarize"]
    assert "get_turbidity_risk_forecast_12h" in payload["tool_trace"]
    assert "NORMAL" in payload["answer"]


def test_assistant_chat_endpoint_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "test-key")

    def fake_answer(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "answer": "Mock agent answer with recommend_alert=true.",
            "sources": [{"type": "api", "ref": "python:/turbidity/risk-forecast-12h"}],
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
            "mode": "tools",
            "model": "mock",
            "provider": "openai",
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            "session_id": None,
            "intent": "live_data",
            "retrieval_query": None,
        }

    with patch("assistant.router.answer_unified_question", side_effect=fake_answer):
        res = client.post(
            "/assistant/chat",
            json={"message": "What is the 12h turbidity risk for site 12117500?", "site_no": "12117500"},
        )

    assert res.status_code == 200
    body = res.json()
    assert body["tool_trace"] == ["get_turbidity_risk_forecast_12h"]
    assert body["mode"] == "tools"
    assert "answer" in body


def test_assistant_chat_endpoint_503_when_disabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_ENABLED", "false")
    monkeypatch.delenv("ASSISTANT_LLM_API_KEY", raising=False)
    res = client.post(
        "/assistant/chat",
        json={"message": "hello"},
    )
    assert res.status_code == 503

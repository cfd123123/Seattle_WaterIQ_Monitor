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
        "get_iv_history",
        "get_forecast_series",
    ):
        assert expected in names


def test_execute_iv_history_tool(tmp_path) -> None:
    import pandas as pd

    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)
    csv_path = tmp_path / "iv.csv"
    csv_path.write_text("datetime,site_no,63680\n", encoding="utf-8")

    with patch("models.forecast_engine.load_hourly_series", return_value=series):
        result = execute_tool(
            "get_iv_history",
            {
                "site_no": "12117500",
                "parameter_cd": "63680",
                "history_days": 7,
                "iv_csv_path": str(csv_path),
            },
        )

    assert result["ok"] is True
    assert result["source"] == "python:/iv/history"
    assert result["data"]["parameter_cd"] == "63680"
    assert result["data"]["observed_count"] == 5
    assert result["data"]["latest_value"] == 5.0
    assert len(result["data"]["history_points"]) == 5


def test_agent_lite_multi_tool_forecast_and_history() -> None:
    phases: list[str] = []

    def mock_complete(messages: list[dict[str, Any]]) -> CompletionResult:
        system = messages[0]["content"]
        if "tool router" in system.lower():
            phases.append("select")
            return CompletionResult(
                text=json.dumps(
                    {
                        "tools": [
                            {
                                "tool": "get_forecast_series",
                                "arguments": {
                                    "site_no": "12117500",
                                    "parameter_cd": "63680",
                                    "horizon_hours": 12,
                                    "history_days": 7,
                                },
                            },
                            {
                                "tool": "get_iv_history",
                                "arguments": {
                                    "site_no": "12117500",
                                    "parameter_cd": "63680",
                                    "history_days": 7,
                                },
                            },
                        ]
                    }
                ),
                model="mock",
                provider="ollama",
            )
        phases.append("summarize")
        user = messages[-1]["content"]
        assert "2 tool(s)" in user
        return CompletionResult(
            text=(
                "For site 12117500 turbidity: forecast_available=true with 12h horizon; "
                "history shows latest_value=5.0 NTU over the past week."
            ),
            model="mock",
            provider="ollama",
            usage={"prompt_tokens": 10, "completion_tokens": 20},
        )

    forecast_payload = {
        "ok": True,
        "data": {
            "site_no": "12117500",
            "parameter_cd": "63680",
            "forecast_available": True,
            "horizon_hours": 12,
            "history_days": 7,
            "history_points": [{"timestamp": "t0", "value": 1.0}],
            "forecast_points": [{"timestamp": "t1", "value": 2.0}],
        },
        "source": "python:/forecast/series",
    }
    history_payload = {
        "ok": True,
        "data": {
            "site_no": "12117500",
            "parameter_cd": "63680",
            "latest_value": 5.0,
            "observed_count": 5,
        },
        "source": "python:/iv/history",
    }

    def fake_execute(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name == "get_forecast_series":
            return forecast_payload
        if name == "get_iv_history":
            return history_payload
        return {"ok": False, "error_code": "UNEXPECTED", "message": name}

    from assistant.llm_client import ToolsNotSupportedError

    def refuse_tools(_messages: list[dict[str, Any]], _tools: list[dict[str, Any]]) -> CompletionResult:
        raise ToolsNotSupportedError("tools not supported in test")

    with patch("assistant.orchestrator.execute_tool", side_effect=fake_execute):
        payload = answer_agent_question(
            "Forecast turbidity for 12117500 and also return recent history.",
            site_no="12117500",
            complete_fn=mock_complete,
            complete_with_tools_fn=refuse_tools,
        )

    assert payload["mode"] == "agent_lite"
    assert phases == ["select", "summarize"]
    assert payload["tool_trace"] == ["get_forecast_series", "get_iv_history"]
    assert "12117500" in payload["answer"]
    assert len(payload["tool_calls"]) == 2


def test_selections_from_router_payload_legacy_and_multi() -> None:
    from assistant.orchestrator import _selections_from_router_payload

    legacy = _selections_from_router_payload(
        {"tool": "get_iv_history", "arguments": {"parameter_cd": "63680"}},
        site_no="12117500",
    )
    assert legacy == [("get_iv_history", {"parameter_cd": "63680", "site_no": "12117500"})]

    multi = _selections_from_router_payload(
        {
            "tools": [
                {"tool": "get_forecast_series", "arguments": {"parameter_cd": "63680", "horizon_hours": 12}},
                {"name": "get_iv_history", "args": {"parameter_cd": "63680"}},
            ]
        },
        site_no="12117500",
    )
    assert [name for name, _ in multi] == ["get_forecast_series", "get_iv_history"]
    assert multi[0][1]["site_no"] == "12117500"


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

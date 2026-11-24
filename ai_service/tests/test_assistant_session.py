"""Tests for in-memory session memory and history passthrough."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from assistant.orchestrator import answer_agent_question
from assistant.session_memory import SessionStore, looks_like_follow_up, should_reuse_cached_tools
from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_looks_like_follow_up_short_question() -> None:
    history = [{"role": "user", "content": "forecast?"}, {"role": "assistant", "content": "NORMAL tier."}]
    assert looks_like_follow_up("What does recommend_alert mean?", history) is True
    assert looks_like_follow_up("refresh the forecast now", history) is False


def test_session_store_merge_and_cache() -> None:
    store = SessionStore(max_sessions=10, max_turns=6, cache_ttl=600)
    sid = store.resolve_session_id(None)
    assert sid

    store.append_turn(sid, "user", "first question")
    store.append_turn(sid, "assistant", "first answer")
    merged = store.merge_history(sid, [{"role": "user", "content": "client only"}])
    assert merged[-1]["content"] == "first answer"

    audit = [{"name": "get_turbidity_risk_forecast_12h", "ok": True, "result_preview": {"recommend_alert": False}}]
    store.cache_tool_result(sid, "12117500", audit, [{"ok": True, "data": {"recommend_alert": False}}])
    cached = store.get_cached_tools(sid, "12117500")
    assert cached is not None
    assert cached[0][0]["name"] == "get_turbidity_risk_forecast_12h"


def test_agent_question_reuses_cached_tools_on_follow_up(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionStore(max_sessions=10, max_turns=6, cache_ttl=600)
    sid = "test-session-follow-up"
    audit = [
        {
            "name": "get_turbidity_risk_forecast_12h",
            "ok": True,
            "source": "python:/turbidity/risk-forecast-12h",
            "result_preview": {"recommend_alert": False, "max_tier_forecast": "NORMAL"},
        }
    ]
    store.cache_tool_result(sid, "12117500", audit, [{"ok": True, "data": {"recommend_alert": False}}])
    history = [
        {"role": "user", "content": "12h risk for 12117500"},
        {"role": "assistant", "content": "recommend_alert is false."},
    ]

    calls: list[str] = []

    def mock_complete(msgs: list[dict[str, Any]]) -> Any:
        calls.append("complete")
        from assistant.llm_client import CompletionResult

        return CompletionResult(
            text="recommend_alert is false because max_tier_forecast is NORMAL.",
            model="mock",
            provider="ollama",
        )

    with patch("assistant.orchestrator.session_store", store):
        payload = answer_agent_question(
            "Explain recommend_alert in more detail",
            site_no="12117500",
            session_id=sid,
            history=history,
            complete_fn=mock_complete,
            complete_with_tools_fn=lambda _m, _t: (_ for _ in ()).throw(
                RuntimeError("tools should not run")
            ),
        )

    assert payload["mode"] == "agent_lite"
    assert payload["tool_trace"] == ["get_turbidity_risk_forecast_12h"]
    assert payload["tool_calls"] == []
    assert calls == ["complete"]


def test_assistant_chat_accepts_history_and_session_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "test-key")

    captured: dict[str, Any] = {}

    def fake_answer(*_a: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "answer": "Follow-up answer.",
            "sources": [],
            "tool_calls": [],
            "tool_trace": [],
            "mode": "agent_lite",
            "model": "mock",
            "provider": "openai",
            "usage": None,
            "session_id": kwargs.get("session_id"),
            "intent": "live_data",
            "retrieval_query": None,
        }

    with patch("assistant.router.answer_unified_question", side_effect=fake_answer):
        res = client.post(
            "/assistant/chat",
            json={
                "message": "Tell me more",
                "site_no": "12117500",
                "session_id": "sess-abc",
                "history": [
                    {"role": "user", "content": "prior q"},
                    {"role": "assistant", "content": "prior a"},
                ],
            },
        )

    assert res.status_code == 200
    assert captured.get("session_id") == "sess-abc"
    assert captured.get("history") == [
        {"role": "user", "content": "prior q"},
        {"role": "assistant", "content": "prior a"},
    ]
    assert res.json()["session_id"] == "sess-abc"


def test_unified_router_persists_session_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "false")

    store = SessionStore(max_sessions=10, max_turns=6, cache_ttl=600)

    def mock_complete(msgs: list[dict[str, Any]]) -> Any:
        from assistant.llm_client import CompletionResult

        return CompletionResult(text="Tool summary.", model="mock", provider="ollama")

    frozen_audit = [
        {
            "round": 1,
            "name": "get_turbidity_risk_forecast_12h",
            "arguments": {"site_no": "12117500"},
            "ok": True,
            "source": "python:/turbidity/risk-forecast-12h",
            "result_preview": {"recommend_alert": True},
        }
    ]

    with patch("assistant.unified_router.session_store", store):
        with patch(
            "assistant.orchestrator._run_tools_loop",
            return_value=("Tool summary.", frozen_audit, None, None),
        ):
            from assistant.unified_router import answer_unified_question

            out = answer_unified_question(
                "12h risk?",
                site_no="12117500",
                session_id="persist-test",
                complete_fn=mock_complete,
            )

    assert out["session_id"] == "persist-test"
    merged = store.merge_history("persist-test", None)
    assert merged[-1]["role"] == "assistant"
    assert "Tool summary" in merged[-1]["content"]
    cached = store.get_cached_tools("persist-test", "12117500")
    assert cached is not None


_CACHED_RISK_AUDIT = [
    {
        "ok": True,
        "name": "get_turbidity_risk_forecast_12h",
        "arguments": {"site_no": "12117500"},
        "result_preview": {"site_no": "12117500", "max_tier_forecast": "NORMAL"},
    }
]
_RISK_HISTORY = [
    {"role": "user", "content": "What is the 12h risk for 12117500?"},
    {"role": "assistant", "content": "Site 12117500: recommend_alert false, tier NORMAL."},
]


@pytest.mark.parametrize(
    "message",
    [
        "What is the 12h risk for 12147600?",  # different site
        "那 12147600 呢？",  # different site, Chinese follow-up form
        "12147600 现在浊度多少",  # Chinese used to always count as a follow-up
        "What is the current discharge at 12117500?",  # same site, different parameter
        "why is it high now?",  # asks for the present value
        "Show the flow history",  # "show" contains "how"
    ],
)
def test_cached_tools_not_reused_for_new_data(message: str) -> None:
    assert should_reuse_cached_tools(message, _RISK_HISTORY, _CACHED_RISK_AUDIT) is False


@pytest.mark.parametrize(
    "message",
    ["why?", "为什么是 NORMAL？", "what does that mean for 12117500?", "why is turbidity NORMAL there?"],
)
def test_cached_tools_reused_for_follow_up_on_same_data(message: str) -> None:
    assert should_reuse_cached_tools(message, _RISK_HISTORY, _CACHED_RISK_AUDIT) is True


def test_client_history_keeps_user_turns_only() -> None:
    store = SessionStore()
    merged = store.merge_history(
        "fresh-session",
        [
            {"role": "user", "content": "12h risk for 12117500"},
            {"role": "assistant", "content": "recommend_alert is true."},
        ],
    )
    assert merged == [{"role": "user", "content": "12h risk for 12117500"}]

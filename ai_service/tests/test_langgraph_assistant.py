"""Tests for LangChain tool wrappers and LangGraph routing."""

from __future__ import annotations

import json

from assistant.config import load_assistant_config
from assistant.graph import AssistantGraphDeps, invoke_assistant_graph
from assistant.lc.tools import build_readonly_langchain_tools, get_tool_by_name
from assistant.llm_client import CompletionResult
from assistant.rag.query_router import Intent, classify_and_rewrite, try_turbidity_sites_list_answer
from assistant.session_memory import looks_like_follow_up, session_store


def test_langchain_readonly_tools_cover_whitelist() -> None:
    tools = build_readonly_langchain_tools()
    names = {t.name for t in tools}
    assert "get_assistant_health" in names
    assert "get_turbidity_risk_forecast_12h" in names
    assert "search_ops_docs" in names
    assert "set_recommend_alert" not in names


def test_langchain_health_tool_runs() -> None:
    tool = get_tool_by_name("get_assistant_health")
    assert tool is not None
    raw = tool.invoke({})
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["data"]["status"] == "ok"


def test_langgraph_chitchat_canned(monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")
    monkeypatch.setenv("ASSISTANT_USE_LANGGRAPH", "true")
    cfg = load_assistant_config()

    deps = AssistantGraphDeps(
        cfg=cfg,
        complete_fn=lambda _m: CompletionResult(text="x", model="mock", provider="ollama"),
        classify_and_rewrite=classify_and_rewrite,
        answer_agent_question=lambda *_a, **_k: {"answer": "should-not-run"},
        answer_ops_doc_question=lambda *_a, **_k: {"answer": "should-not-run"},
        select_and_execute_tool=lambda *_a, **_k: ([], None, CompletionResult(text="{}", model="m", provider="ollama")),
        try_turbidity_sites_list_answer=try_turbidity_sites_list_answer,
        ensure_rag_index=lambda: None,
        search_ops_docs=lambda *_a, **_k: [],
        session_store=session_store,
        looks_like_follow_up=looks_like_follow_up,
        build_hybrid_messages=lambda *_a, **_k: [],
        canned_chitchat="Hello from water quality assistant.",
        canned_off_topic="Outside turbidity monitoring scope.",
        canned_clarify="Please rephrase with a clearer ops question.",
    )
    payload = invoke_assistant_graph(deps, message="你好")
    assert payload["intent"] == Intent.CHITCHAT.value
    assert payload["mode"] == "canned"
    assert "assistant" in payload["answer"].lower()


def test_langgraph_reflect_blocks_ungrounded_tool_answer(monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")
    monkeypatch.setenv("ASSISTANT_USE_LANGGRAPH", "true")
    monkeypatch.setenv("ASSISTANT_REFLECT", "true")
    cfg = load_assistant_config()

    def fake_agent(*_a, **_k):
        return {
            "answer": "Turbidity spiked to 88.2 NTU with no tool support for that number.",
            "sources": [{"type": "api", "ref": "python:/turbidity/risk-forecast-12h"}],
            "tool_calls": [
                {
                    "round": 1,
                    "name": "get_turbidity_risk_forecast_12h",
                    "arguments": {"site_no": "12117500"},
                    "ok": True,
                    "source": "python:/turbidity/risk-forecast-12h",
                    "result_preview": {
                        "site_no": "12117500",
                        "recommend_alert": False,
                        "max_tier_forecast": "NORMAL",
                    },
                }
            ],
            "tool_trace": ["get_turbidity_risk_forecast_12h"],
            "mode": "tools",
            "model": "mock",
            "provider": "ollama",
            "usage": None,
            "session_id": None,
        }

    deps = AssistantGraphDeps(
        cfg=cfg,
        complete_fn=lambda _m: CompletionResult(
            text="Site 12117500 recommend_alert is false; max_tier_forecast is NORMAL.",
            model="mock",
            provider="ollama",
        ),
        classify_and_rewrite=lambda *_a, **_k: type(
            "R",
            (),
            {"intent": Intent.LIVE_DATA, "retrieval_query": None},
        )(),
        answer_agent_question=fake_agent,
        answer_ops_doc_question=lambda *_a, **_k: {"answer": "docs"},
        select_and_execute_tool=lambda *_a, **_k: (
            [],
            None,
            CompletionResult(text="{}", model="m", provider="ollama"),
        ),
        try_turbidity_sites_list_answer=try_turbidity_sites_list_answer,
        ensure_rag_index=lambda: None,
        search_ops_docs=lambda *_a, **_k: [],
        session_store=session_store,
        looks_like_follow_up=looks_like_follow_up,
        build_hybrid_messages=lambda *_a, **_k: [],
        canned_chitchat="Hello from water quality assistant.",
        canned_off_topic="Outside turbidity monitoring scope.",
        canned_clarify="Please rephrase with a clearer ops question.",
    )
    payload = invoke_assistant_graph(
        deps,
        message="What is the 12h turbidity risk for site 12117500?",
        site_no="12117500",
    )
    assert "88.2" not in payload["answer"]

"""Tests for deterministic ask-back when the user has not named a site."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from assistant.llm_client import CompletionResult, ToolCallSpec
from assistant.orchestrator import _user_provided_sites, answer_agent_question

_RISK_OK = {"ok": True, "data": {"site_no": "12117500", "recommend_alert": False}, "source": "python:/risk"}


def _tool_round(name: str, args: dict[str, Any]) -> CompletionResult:
    return CompletionResult(
        text="",
        model="mock",
        provider="ollama",
        tool_calls=(ToolCallSpec(id="call_1", name=name, arguments=json.dumps(args)),),
    )


def _final(text: str) -> CompletionResult:
    return CompletionResult(text=text, model="mock", provider="ollama")


def _unused_complete(_messages: list[dict[str, Any]]) -> CompletionResult:
    raise AssertionError("plain completion should not be called")


def test_user_provided_sites_from_id_name_context_and_history() -> None:
    assert _user_provided_sites("risk for 12145500?", None) == {"12145500"}
    assert "12117500" in _user_provided_sites("turbidity on the Cedar River", None)
    assert _user_provided_sites("current risk", "12117500") == {"12117500"}
    history = [{"role": "user", "content": "show 12117000"}]
    assert _user_provided_sites("and its forecast?", None, history) == {"12117000"}
    assert _user_provided_sites("what is the current turbidity?", None) == set()


def test_guessed_site_is_blocked_and_user_is_asked() -> None:
    def complete_with_tools(messages: list[dict[str, Any]], _tools: list[dict[str, Any]]) -> CompletionResult:
        if any(m.get("role") == "tool" for m in messages):
            return _final("Turbidity at 12117500 is 3.2 NTU.")
        return _tool_round("get_turbidity_risk_forecast_12h", {"site_no": "12117500"})

    execute = MagicMock(return_value=_RISK_OK)
    with patch("assistant.orchestrator.execute_tool", execute):
        payload = answer_agent_question(
            "What is the current turbidity risk?",
            complete_with_tools_fn=complete_with_tools,
            complete_fn=_unused_complete,
        )

    execute.assert_not_called()
    assert payload["mode"] == "canned"
    assert payload["answer"].startswith("Which site do you mean?")
    assert "3.2" not in payload["answer"]
    assert payload["tool_calls"][0]["error_code"] == "SITE_NOT_SPECIFIED"


def test_named_river_counts_as_provided_site() -> None:
    def complete_with_tools(messages: list[dict[str, Any]], _tools: list[dict[str, Any]]) -> CompletionResult:
        if any(m.get("role") == "tool" for m in messages):
            return _final("recommend_alert is false for 12117500.")
        return _tool_round("get_turbidity_risk_forecast_12h", {"site_no": "12117500"})

    with patch("assistant.orchestrator.execute_tool", return_value=_RISK_OK) as execute:
        payload = answer_agent_question(
            "What is the 12h risk on the Cedar River?",
            complete_with_tools_fn=complete_with_tools,
            complete_fn=_unused_complete,
        )

    execute.assert_called_once()
    assert payload["mode"] == "tools"


def test_site_returned_by_earlier_tool_is_allowed() -> None:
    rounds = iter(
        [
            _tool_round("list_puget_default_sites", {}),
            _tool_round("get_turbidity_risk_forecast_12h", {"site_no": "12117500"}),
            _final("Checked the first default site: recommend_alert is false."),
        ]
    )

    def fake_execute(name: str, _args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_puget_default_sites":
            return {"ok": True, "data": {"sites": [{"site_no": "12117500"}]}, "source": "config"}
        return _RISK_OK

    with patch("assistant.orchestrator.execute_tool", side_effect=fake_execute):
        payload = answer_agent_question(
            "Check the risk at the first default site",
            complete_with_tools_fn=lambda _m, _t: next(rounds),
            complete_fn=_unused_complete,
        )

    assert [e["ok"] for e in payload["tool_calls"]] == [True, True]
    assert payload["mode"] == "tools"


def test_agent_lite_guessed_site_asks_without_summarize() -> None:
    phases: list[str] = []

    def complete(messages: list[dict[str, Any]]) -> CompletionResult:
        phases.append("select")
        assert "tool router" in messages[0]["content"].lower()
        return _final(json.dumps({"tools": [{"tool": "get_turbidity_risk_forecast_12h", "arguments": {"site_no": "12117500"}}]}))

    with patch("assistant.orchestrator.execute_tool") as execute:
        payload = answer_agent_question(
            "What is the turbidity risk right now?",
            complete_with_tools_fn=lambda _m, _t: _final(""),
            complete_fn=complete,
        )

    execute.assert_not_called()
    assert phases == ["select"]
    assert payload["mode"] == "canned"
    assert payload["answer"].startswith("Which site do you mean?")


def test_single_user_site_overrides_model_hallucinated_site() -> None:
    def complete_with_tools(messages: list[dict[str, Any]], _tools: list[dict[str, Any]]) -> CompletionResult:
        if any(m.get("role") == "tool" for m in messages):
            return _final("recommend_alert is false for 12117500.")
        return _tool_round("get_turbidity_risk_forecast_12h", {"site_no": "12060400"})

    with patch("assistant.orchestrator.execute_tool", return_value=_RISK_OK) as execute:
        payload = answer_agent_question(
            "What is the 12h turbidity risk on the Cedar River?",
            complete_with_tools_fn=complete_with_tools,
            complete_fn=_unused_complete,
        )

    assert execute.call_args.args[1]["site_no"] == "12117500"
    assert payload["tool_calls"][0]["arguments"]["site_no"] == "12117500"
    assert payload["mode"] == "tools"

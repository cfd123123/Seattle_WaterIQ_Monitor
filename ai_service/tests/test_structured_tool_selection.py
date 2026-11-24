"""Tests for schema-constrained agent-lite tool selection."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import BadRequestError

from assistant.config import load_assistant_config
from assistant.llm_client import CompletionResult, build_complete_fn
from assistant.orchestrator import _complete_tool_selection
from assistant.tools.registry import get_tool_names, get_tool_selection_schema


def _variants() -> list[dict[str, Any]]:
    return get_tool_selection_schema()["properties"]["tools"]["items"]["anyOf"]


def test_selection_schema_has_one_branch_per_whitelisted_tool() -> None:
    names = [v["properties"]["tool"]["const"] for v in _variants()]
    assert sorted(names) == sorted(get_tool_names())


def test_selection_schema_constrains_argument_values() -> None:
    by_name = {v["properties"]["tool"]["const"]: v["properties"]["arguments"] for v in _variants()}
    history_args = by_name["get_iv_history"]
    assert history_args["additionalProperties"] is False
    assert history_args["properties"]["site_no"]["pattern"] == r"^[0-9]{8}$"
    assert history_args["properties"]["parameter_cd"]["enum"] == ["00060", "63680"]


def test_tool_selection_uses_structured_when_available() -> None:
    calls: list[dict[str, Any]] = []

    def plain(_messages: list[dict[str, Any]]) -> CompletionResult:
        raise AssertionError("plain completion should not be used")

    def structured(_messages: list[dict[str, Any]], response_format: dict[str, Any]) -> CompletionResult:
        calls.append(response_format)
        return CompletionResult(text='{"tools": []}', model="mock", provider="ollama")

    plain.structured = structured  # type: ignore[attr-defined]
    result = _complete_tool_selection([{"role": "user", "content": "hi"}], plain)

    assert json.loads(result.text) == {"tools": []}
    assert calls[0]["type"] == "json_schema"
    assert calls[0]["json_schema"]["schema"] == get_tool_selection_schema()


def test_tool_selection_without_structured_uses_plain_completion() -> None:
    def plain(_messages: list[dict[str, Any]]) -> CompletionResult:
        return CompletionResult(text='{"tools": []}', model="mock", provider="ollama")

    assert _complete_tool_selection([], plain).text == '{"tools": []}'


def _bad_request() -> BadRequestError:
    request = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")
    response = httpx.Response(400, request=request)
    return BadRequestError("response_format not supported", response=response, body=None)


def test_build_complete_fn_falls_back_when_response_format_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_STRUCTURED_OUTPUT", "true")
    complete_fn = build_complete_fn(load_assistant_config())

    ok = CompletionResult(text='{"tools": []}', model="mock", provider="ollama")
    create = MagicMock(side_effect=[_bad_request(), ok])
    with patch("assistant.llm_client.LLMClient._create_completion", create):
        result = complete_fn.structured([], {"type": "json_schema"})  # type: ignore[attr-defined]

    assert result is ok
    assert create.call_args_list[0].kwargs["response_format"] == {"type": "json_schema"}
    assert create.call_args_list[1].kwargs["response_format"] is None


def test_build_complete_fn_without_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_STRUCTURED_OUTPUT", "false")
    assert not hasattr(build_complete_fn(load_assistant_config()), "structured")

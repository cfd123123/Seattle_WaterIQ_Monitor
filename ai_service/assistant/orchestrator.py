"""L3 NL2API agent orchestrator — OpenAI tools loop with agent-lite fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from assistant.agent_prompts import (
    AGENT_LITE_SUMMARIZE_PROMPT,
    AGENT_LITE_TOOL_SELECT_PROMPT,
    AGENT_SYSTEM_PROMPT,
)
from assistant.config import AssistantConfig, load_assistant_config
from assistant.llm_client import CompletionResult, LLMClient, ToolsNotSupportedError, _merge_usage
from assistant.session_memory import (
    format_cached_tool_context,
    looks_like_follow_up,
    session_store,
)
from assistant.tools.executor import execute_tool
from assistant.tools.registry import get_openai_tools

logger = logging.getLogger(__name__)

ToolAuditEntry = dict[str, Any]
CompleteFn = Callable[[list[dict[str, Any]]], CompletionResult]
CompleteWithToolsFn = Callable[[list[dict[str, Any]], list[dict[str, Any]]], CompletionResult]


def _build_user_message(message: str, site_no: str | None) -> str:
    parts = [message.strip()]
    if site_no:
        parts.append(f"\n[Context: focus_site_no={site_no}]")
    return "".join(parts)


def _build_agent_messages(
    message: str,
    site_no: str | None,
    *,
    history: list[dict[str, str]] | None = None,
    cached_tool_context: str | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    if cached_tool_context:
        messages.append({"role": "system", "content": cached_tool_context})
    if history:
        for turn in history:
            role = turn.get("role")
            content = str(turn.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": _build_user_message(message, site_no)})
    return messages


def _sources_from_audit(audit: list[ToolAuditEntry]) -> list[dict[str, str]]:
    seen: set[str] = set()
    sources: list[dict[str, str]] = []
    for entry in audit:
        if not entry.get("ok"):
            continue
        ref = str(entry.get("source", ""))
        if not ref or ref in seen:
            continue
        seen.add(ref)
        sources.append({"type": "api", "ref": ref})
    return sources


def _parse_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def _run_tool_call(
    name: str,
    arguments: dict[str, Any],
    *,
    round_no: int,
    audit: list[ToolAuditEntry],
) -> dict[str, Any]:
    result = execute_tool(name, arguments)
    audit.append(
        {
            "round": round_no,
            "name": name,
            "arguments": arguments,
            "ok": bool(result.get("ok")),
            "source": result.get("source"),
            "error_code": result.get("error_code"),
            "message": result.get("message"),
            "result_preview": _preview_result(result),
        }
    )
    return result


def _preview_result(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        return {"error": result.get("message")}
    data = result.get("data")
    if not isinstance(data, dict):
        return {"data": data}
    preview_keys = (
        "site_no",
        "recommend_alert",
        "max_tier_forecast",
        "tier_at_t",
        "alert_tier",
        "state",
        "63680",
        "alert_12h_forecast",
        "forecast_available",
        "parameter_cd",
        "horizon_hours",
        "history_days",
        "point_count",
        "observed_count",
        "latest_value",
        "mean_value",
        "returned_points",
        "status",
        "enabled",
        "region_label",
        "hit_count",
    )
    preview = {k: data[k] for k in preview_keys if k in data}
    # Compact series previews (avoid dumping full IV tails into session cache).
    for series_key in ("history_points", "forecast_points"):
        points = data.get(series_key)
        if isinstance(points, list) and points:
            preview[series_key] = {
                "count": len(points),
                "first": points[0],
                "last": points[-1],
            }
    return preview


def _tool_trace(audit: list[ToolAuditEntry]) -> list[str]:
    return [str(e["name"]) for e in audit if e.get("name")]


def _selections_from_router_payload(
    payload: dict[str, Any] | None,
    *,
    site_no: str | None,
    max_tools: int = 3,
) -> list[tuple[str, dict[str, Any]]]:
    """Parse agent-lite JSON into ordered (tool_name, args) pairs (multi-tool aware)."""
    if not payload:
        return []

    selections: list[tuple[str, dict[str, Any]]] = []
    raw_tools = payload.get("tools")
    if isinstance(raw_tools, list):
        for item in raw_tools:
            if not isinstance(item, dict):
                continue
            raw_name = item.get("tool") or item.get("name")
            if raw_name is None or str(raw_name).lower() == "null":
                continue
            name = str(raw_name).strip()
            if not name:
                continue
            raw_args = item.get("arguments") or item.get("args") or {}
            args = dict(raw_args) if isinstance(raw_args, dict) else {}
            if site_no and "site_no" not in args:
                args["site_no"] = site_no
            selections.append((name, args))
            if len(selections) >= max_tools:
                break
        return selections

    raw_tool = payload.get("tool")
    if raw_tool is None or str(raw_tool).lower() == "null":
        return []
    name = str(raw_tool).strip()
    if not name:
        return []
    raw_args = payload.get("arguments")
    args = dict(raw_args) if isinstance(raw_args, dict) else {}
    if site_no and "site_no" not in args:
        args["site_no"] = site_no
    return [(name, args)]


def _run_tool_selections(
    selections: list[tuple[str, dict[str, Any]]],
    *,
    audit: list[ToolAuditEntry],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for idx, (name, args) in enumerate(selections, start=1):
        payloads.append(_run_tool_call(name, args, round_no=idx, audit=audit))
    return payloads


def _run_tools_loop(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    max_rounds: int,
    complete_with_tools_fn: CompleteWithToolsFn,
) -> tuple[str, list[ToolAuditEntry], CompletionResult | None, dict[str, Any] | None]:
    audit: list[ToolAuditEntry] = []
    usage_acc: dict[str, Any] | None = None
    last_result: CompletionResult | None = None
    working = list(messages)

    for round_no in range(1, max_rounds + 1):
        last_result = complete_with_tools_fn(working, tools)
        usage_acc = _merge_usage(usage_acc, last_result.usage)

        if not last_result.tool_calls:
            return last_result.text, audit, last_result, usage_acc

        # Append assistant message with tool calls for the next round.
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": last_result.text or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in last_result.tool_calls
            ],
        }
        working.append(assistant_msg)

        for tc in last_result.tool_calls:
            try:
                args = json.loads(tc.arguments) if tc.arguments.strip() else {}
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            tool_result = _run_tool_call(tc.name, args, round_no=round_no, audit=audit)
            working.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, default=str),
                }
            )

    # Max rounds reached — ask for a final answer without more tools.
    working.append(
        {
            "role": "user",
            "content": "Summarize the tool results above in English. Do not call more tools.",
        }
    )
    final = complete_with_tools_fn(working, [])
    usage_acc = _merge_usage(usage_acc, final.usage)
    return final.text, audit, final, usage_acc


def _run_agent_lite(
    message: str,
    site_no: str | None,
    *,
    complete_fn: CompleteFn,
) -> tuple[str, list[ToolAuditEntry], CompletionResult, dict[str, Any] | None]:
    audit: list[ToolAuditEntry] = []
    select_messages: list[dict[str, str]] = [
        {"role": "system", "content": AGENT_LITE_TOOL_SELECT_PROMPT},
        {"role": "user", "content": _build_user_message(message, site_no)},
    ]
    selection = complete_fn(select_messages)
    usage_acc = selection.usage

    payload = _parse_json_object(selection.text)
    selections = _selections_from_router_payload(payload, site_no=site_no)
    tool_payloads = _run_tool_selections(selections, audit=audit)

    summarize_user_parts = [
        f"User question: {message.strip()}",
    ]
    if site_no:
        summarize_user_parts.append(f"Context site_no: {site_no}")
    if tool_payloads:
        summarize_user_parts.append(
            f"Tool result JSON ({len(tool_payloads)} tool(s)):\n"
            f"{json.dumps(tool_payloads, default=str)}"
        )
    else:
        summarize_user_parts.append("No tool was executed.")

    summarize_messages: list[dict[str, str]] = [
        {"role": "system", "content": AGENT_LITE_SUMMARIZE_PROMPT},
        {"role": "user", "content": "\n\n".join(summarize_user_parts)},
    ]
    summary = complete_fn(summarize_messages)
    usage_acc = _merge_usage(usage_acc, summary.usage)
    return summary.text, audit, summary, usage_acc


def select_and_execute_tool(
    message: str,
    site_no: str | None,
    *,
    complete_fn: CompleteFn,
) -> tuple[list[ToolAuditEntry], dict[str, Any] | None, CompletionResult]:
    """
    One-round tool pick + execute (agent-lite selection without summarize).

    Used by hybrid unified routing before RAG + synthesis.
    If the router returns multiple tools, execute all and return the first payload
    as the primary hybrid context (others remain in the audit trail).
    """
    audit: list[ToolAuditEntry] = []
    select_messages: list[dict[str, str]] = [
        {"role": "system", "content": AGENT_LITE_TOOL_SELECT_PROMPT},
        {"role": "user", "content": _build_user_message(message, site_no)},
    ]
    selection = complete_fn(select_messages)

    payload = _parse_json_object(selection.text)
    selections = _selections_from_router_payload(payload, site_no=site_no)
    tool_payloads = _run_tool_selections(selections, audit=audit)
    tool_payload = tool_payloads[0] if tool_payloads else None
    return audit, tool_payload, selection


def _answer_from_cached_tools(
    message: str,
    site_no: str | None,
    *,
    history: list[dict[str, str]] | None,
    audit: list[ToolAuditEntry],
    payloads: list[dict[str, Any]],
    complete_fn: CompleteFn,
) -> tuple[str, list[ToolAuditEntry], CompletionResult, dict[str, Any] | None]:
    """Answer a follow-up using cached tool JSON without re-executing tools."""
    cached_context = format_cached_tool_context(audit, payloads)
    messages = _build_agent_messages(
        message,
        site_no,
        history=history,
        cached_tool_context=cached_context,
    )
    messages[0] = {
        "role": "system",
        "content": (
            AGENT_SYSTEM_PROMPT
            + "\n11. The user is asking a follow-up about data already fetched in this session. "
            "Use the cached tool results below; do not invent new numbers."
        ),
    }
    summary = complete_fn(messages)
    return summary.text, [], summary, summary.usage


def answer_agent_question(
    message: str,
    *,
    site_no: str | None = None,
    session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    max_tool_rounds: int | None = None,
    config: AssistantConfig | None = None,
    complete_fn: CompleteFn | None = None,
    complete_with_tools_fn: CompleteWithToolsFn | None = None,
) -> dict[str, Any]:
    """
    Run the L3 read-only agent: tools loop (or agent-lite fallback) then English answer.

    Does not modify recommend_alert or any write APIs.
    """
    cfg = config if config is not None else load_assistant_config()
    max_rounds = max_tool_rounds if max_tool_rounds is not None else cfg.max_tool_rounds
    max_rounds = max(1, min(5, int(max_rounds)))

    tools = get_openai_tools()
    resolved_history = history or []

    if complete_fn is None:

        def _complete_fn(msgs: list[dict[str, Any]]) -> CompletionResult:
            client = LLMClient(cfg)
            return client.complete(msgs, max_tokens=768)

        complete_fn = _complete_fn

    if complete_with_tools_fn is None:

        def _complete_with_tools_fn(
            msgs: list[dict[str, Any]],
            tool_defs: list[dict[str, Any]],
        ) -> CompletionResult:
            client = LLMClient(cfg)
            if tool_defs:
                return client.complete_with_tools(msgs, tool_defs, max_tokens=768)
            return client.complete(msgs, max_tokens=768)

        complete_with_tools_fn = _complete_with_tools_fn

    mode = "tools"
    audit: list[ToolAuditEntry] = []
    answer = ""
    model: str | None = cfg.model
    provider = cfg.provider
    usage_acc: dict[str, Any] | None = None

    cached = None
    if session_id:
        cached = session_store.get_cached_tools(session_id, site_no)

    if cached and looks_like_follow_up(message, resolved_history):
        cached_audit, cached_payloads = cached
        answer, audit, last, usage_acc = _answer_from_cached_tools(
            message,
            site_no,
            history=resolved_history,
            audit=cached_audit,
            payloads=cached_payloads,
            complete_fn=complete_fn,
        )
        mode = "agent_lite"
        model = last.model
        provider = last.provider
        return {
            "answer": answer,
            "sources": _sources_from_audit(cached_audit),
            "tool_calls": [],
            "tool_trace": _tool_trace(cached_audit),
            "mode": mode,
            "model": model,
            "provider": provider,
            "usage": usage_acc,
            "session_id": session_id,
        }

    base_messages = _build_agent_messages(message, site_no, history=resolved_history)

    try:
        answer, audit, last, usage_acc = _run_tools_loop(
            base_messages,
            tools,
            max_rounds=max_rounds,
            complete_with_tools_fn=complete_with_tools_fn,
        )
        if last is not None:
            model = last.model
            provider = last.provider
        # Ollama / small models may ignore tools — fall back when no tools ran.
        if not audit and _should_try_agent_lite(message, answer):
            logger.info("No tool calls in tools loop; falling back to agent-lite")
            answer, audit, last, usage_acc = _run_agent_lite(
                message,
                site_no,
                complete_fn=complete_fn,
            )
            mode = "agent_lite"
            model = last.model
            provider = last.provider
    except ToolsNotSupportedError:
        logger.info("Provider does not support tools API; using agent-lite fallback")
        answer, audit, last, usage_acc = _run_agent_lite(
            message,
            site_no,
            complete_fn=complete_fn,
        )
        mode = "agent_lite"
        model = last.model
        provider = last.provider

    return {
        "answer": answer,
        "sources": _sources_from_audit(audit),
        "tool_calls": audit,
        "tool_trace": _tool_trace(audit),
        "mode": mode,
        "model": model,
        "provider": provider,
        "usage": usage_acc,
        "session_id": session_id,
    }


def _should_try_agent_lite(message: str, answer: str) -> bool:
    """Heuristic: data questions with no tool audit should retry agent-lite."""
    lowered = message.lower()
    data_keywords = (
        "risk",
        "forecast",
        "turbidity",
        "recommend_alert",
        "alert",
        "flow",
        "discharge",
        "63680",
        "00060",
        "12h",
        "12 h",
        "site",
        "snapshot",
        "tier",
        "puget",
        "anomal",
    )
    if any(k in lowered for k in data_keywords):
        return True
    if re.search(r"\b\d{8}\b", message):
        return True
    return not answer.strip()

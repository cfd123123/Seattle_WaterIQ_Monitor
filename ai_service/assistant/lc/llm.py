"""LangChain ChatModel factory and CompletionResult bridge."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from assistant.config import AssistantConfig
from assistant.llm_client import CompletionResult, ToolCallSpec, resolve_api_key, sanitize_usage


def build_chat_model(
    config: AssistantConfig,
    *,
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> ChatOpenAI:
    """Build an OpenAI-compatible ChatOpenAI (works with Ollama via base_url)."""
    return ChatOpenAI(
        model=config.model,
        api_key=resolve_api_key(config),
        base_url=config.base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=60.0,
        max_retries=1,
    )


def _to_lc_messages(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for msg in messages:
        role = str(msg.get("role", "")).strip().lower()
        content = msg.get("content")
        text = "" if content is None else str(content)
        if role == "system":
            out.append(SystemMessage(content=text))
        elif role == "user":
            out.append(HumanMessage(content=text))
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                formatted = []
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    formatted.append(
                        {
                            "id": str(tc.get("id") or ""),
                            "name": str(fn.get("name") or ""),
                            "args": fn.get("arguments") or {},
                        }
                    )
                # ChatOpenAI expects args as dict; if string JSON, leave for model layer.
                normalized = []
                for item in formatted:
                    args = item["args"]
                    if isinstance(args, str):
                        normalized.append(
                            {"id": item["id"], "name": item["name"], "args": {"_raw": args}}
                        )
                    else:
                        normalized.append(item)
                out.append(AIMessage(content=text, tool_calls=normalized))
            else:
                out.append(AIMessage(content=text))
        elif role == "tool":
            out.append(
                ToolMessage(
                    content=text,
                    tool_call_id=str(msg.get("tool_call_id") or "tool"),
                )
            )
        else:
            out.append(HumanMessage(content=text))
    return out


def _usage_from_response(response: AIMessage) -> dict[str, Any] | None:
    meta = getattr(response, "usage_metadata", None) or {}
    if not isinstance(meta, dict):
        return None
    raw = {
        "prompt_tokens": meta.get("input_tokens"),
        "completion_tokens": meta.get("output_tokens"),
        "total_tokens": meta.get("total_tokens"),
    }
    return sanitize_usage(raw)


def _tool_calls_from_response(response: AIMessage) -> tuple[ToolCallSpec, ...]:
    raw = getattr(response, "tool_calls", None) or []
    parsed: list[ToolCallSpec] = []
    for idx, call in enumerate(raw):
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "")
        if not name:
            continue
        call_id = str(call.get("id") or f"call_{idx}")
        args = call.get("args")
        if isinstance(args, dict) and set(args.keys()) == {"_raw"}:
            arguments = str(args["_raw"])
        elif isinstance(args, dict):
            import json

            arguments = json.dumps(args)
        else:
            arguments = str(args or "{}")
        parsed.append(ToolCallSpec(id=call_id, name=name, arguments=arguments))
    return tuple(parsed)


def complete_messages(
    messages: list[dict[str, Any]],
    *,
    config: AssistantConfig,
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> CompletionResult:
    """Run a LangChain chat completion and return the assistant CompletionResult shape."""
    model = build_chat_model(config, temperature=temperature, max_tokens=max_tokens)
    response = model.invoke(_to_lc_messages(messages))
    if not isinstance(response, AIMessage):
        text = str(response)
        return CompletionResult(
            text=text.strip(),
            model=config.model,
            provider=config.provider,
            usage=None,
        )
    text = (response.content or "") if isinstance(response.content, str) else str(response.content or "")
    return CompletionResult(
        text=text.strip(),
        model=config.model,
        provider=config.provider,
        usage=_usage_from_response(response),
        tool_calls=_tool_calls_from_response(response),
    )

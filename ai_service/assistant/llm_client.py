"""Thin OpenAI-compatible client for assistant completions (OpenAI + Ollama)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from assistant.config import AssistantConfig, is_ollama_base_url

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 60.0
MAX_RETRIES = 1

_USAGE_TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _extract_usage_dict(usage: Any) -> dict[str, Any] | None:
    """Normalize OpenAI/Ollama usage payloads (Pydantic model or plain dict)."""
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    return None


def sanitize_usage(raw: dict[str, Any] | None) -> dict[str, int | float] | None:
    """Keep only flat token counts for API responses (Ollama may return nested nulls)."""
    if not raw:
        return None
    out: dict[str, int | float] = {}
    for key in _USAGE_TOKEN_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out[key] = value
        elif isinstance(value, float) and value.is_integer():
            out[key] = int(value)
        elif isinstance(value, float):
            out[key] = value
    return out or None


@dataclass(frozen=True)
class ToolCallSpec:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class CompletionResult:
    text: str
    model: str
    provider: str
    usage: dict[str, Any] | None = None
    tool_calls: tuple[ToolCallSpec, ...] = ()
    finish_reason: str | None = None


def resolve_api_key(config: AssistantConfig) -> str:
    """Return API key; Ollama accepts a placeholder when no real key is configured."""
    if config.api_key:
        return config.api_key
    if config.provider == "ollama" or is_ollama_base_url(config.base_url):
        return "ollama"
    return ""


def _parse_tool_calls(choice_message: Any) -> tuple[ToolCallSpec, ...]:
    raw_calls = getattr(choice_message, "tool_calls", None) or []
    parsed: list[ToolCallSpec] = []
    for call in raw_calls:
        fn = getattr(call, "function", None)
        if fn is None:
            continue
        name = getattr(fn, "name", None) or ""
        arguments = getattr(fn, "arguments", None) or "{}"
        call_id = getattr(call, "id", None) or f"call_{len(parsed)}"
        if name:
            parsed.append(ToolCallSpec(id=str(call_id), name=str(name), arguments=str(arguments)))
    return tuple(parsed)


def _merge_usage(
    acc: dict[str, Any] | None,
    addition: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not addition:
        return acc
    if not acc:
        return dict(addition)
    merged = dict(acc)
    for key in _USAGE_TOKEN_KEYS:
        a = merged.get(key)
        b = addition.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            merged[key] = a + b
        elif b is not None and a is None:
            merged[key] = b
    return merged


class ToolsNotSupportedError(RuntimeError):
    """Raised when the provider rejects or ignores OpenAI-style tool calling."""


class LLMClient:
    """OpenAI SDK wrapper with timeout and a single retry."""

    def __init__(self, config: AssistantConfig, *, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> None:
        self._config = config
        self._timeout_sec = timeout_sec
        api_key = resolve_api_key(config)
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=timeout_sec,
            max_retries=0,
        )

    def _create_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> CompletionResult:
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message
        text = (message.content or "").strip()
        usage = sanitize_usage(_extract_usage_dict(response.usage))
        return CompletionResult(
            text=text,
            model=response.model or self._config.model,
            provider=self._config.provider,
            usage=usage,
            tool_calls=_parse_tool_calls(message),
            finish_reason=getattr(choice, "finish_reason", None),
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> CompletionResult:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self._create_completion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    logger.warning("LLM completion failed (attempt %s), retrying: %s", attempt + 1, exc)
                    time.sleep(0.5)
                    continue
                raise RuntimeError(f"LLM completion failed after {MAX_RETRIES + 1} attempt(s)") from last_error
        raise RuntimeError("LLM completion failed")  # unreachable

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 768,
    ) -> CompletionResult:
        """Chat completion with OpenAI function-calling tools."""
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self._create_completion(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                msg = str(exc).lower()
                if "tool" in msg or "function" in msg or "unsupported" in msg:
                    raise ToolsNotSupportedError(str(exc)) from exc
                last_error = exc
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "LLM tool completion failed (attempt %s), retrying: %s",
                        attempt + 1,
                        exc,
                    )
                    time.sleep(0.5)
                    continue
                raise RuntimeError(
                    f"LLM tool completion failed after {MAX_RETRIES + 1} attempt(s)"
                ) from last_error
        raise RuntimeError("LLM tool completion failed")  # unreachable

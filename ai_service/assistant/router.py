"""FastAPI routes for the water-quality LLM assistant."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from assistant.health import build_health_payload
from assistant.unified_router import answer_unified_question

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantHealthResponse(BaseModel):
    status: Literal["ok"]
    enabled: bool
    assistant_enabled: bool
    provider: Literal["openai", "ollama", "none"]
    model: str
    configured: bool = Field(description="True when an API key or Ollama base URL is set.")
    llm_configured: bool
    llm_reachable: bool = Field(
        description="M1: always false; live reachability probe deferred to MVP-1+.",
    )
    rag_index_ready: bool = Field(
        description="True when the ops-doc RAG index is built and has chunks.",
    )


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)


class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Natural-language operator question.")
    site_no: str | None = Field(
        default=None,
        description="Optional USGS 8-digit site number used as tool-call context.",
    )
    session_id: str | None = Field(
        default=None,
        description="Client session id; server persists last N turns in memory when provided.",
    )
    history: list[HistoryMessage] | None = Field(
        default=None,
        description="Optional prior turns from the client; fallback when the server store is empty, user turns only.",
    )
    max_tool_rounds: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Tool loop cap (default from ASSISTANT_MAX_TOOL_ROUNDS, max 5).",
    )


class AssistantSource(BaseModel):
    type: Literal["api", "doc"] = "api"
    ref: str
    heading: str | None = None


class ToolCallAudit(BaseModel):
    round: int
    name: str
    arguments: dict[str, Any]
    ok: bool
    source: str | None = None
    error_code: str | None = None
    message: str | None = None
    result_preview: dict[str, Any] | None = None


class RouteInfo(BaseModel):
    source: Literal["rule", "llm", "fallback"]
    labels: dict[str, bool] | None = None
    matched_rules: list[str] = Field(default_factory=list)


class AssistantChatResponse(BaseModel):
    answer: str
    sources: list[AssistantSource]
    tool_calls: list[ToolCallAudit]
    tool_trace: list[str]
    mode: Literal["tools", "agent_lite", "hybrid", "rag", "canned"]
    model: str | None = None
    provider: Literal["openai", "ollama", "none"]
    usage: dict[str, int | float] | None = None
    session_id: str | None = None
    intent: Literal[
        "ops_doc", "live_data", "hybrid", "chitchat", "off_topic", "action_request", "clarify"
    ] | None = None
    retrieval_query: str | None = None
    route: RouteInfo | None = Field(
        default=None,
        description="How the intent was decided: rule vs LLM, predicted labels, rules that fired.",
    )


@router.get("/health", response_model=AssistantHealthResponse)
def assistant_health() -> AssistantHealthResponse:
    """Report assistant module status and LLM configuration (no completion call in M1)."""
    return AssistantHealthResponse(**build_health_payload())


@router.post("/chat", response_model=AssistantChatResponse)
def assistant_chat(body: AssistantChatRequest) -> dict[str, Any]:
    """Unified assistant entry — intent routing, tools loop, RAG, and hybrid synthesis."""
    from assistant.config import load_assistant_config

    cfg = load_assistant_config()
    if not cfg.enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "assistant_disabled",
                "message": "Assistant is disabled or LLM is not configured.",
                "assistant_enabled": cfg.master_enabled,
                "llm_configured": cfg.llm_configured,
            },
        )

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must not be empty")

    client_history = (
        [{"role": h.role, "content": h.content.strip()} for h in body.history]
        if body.history
        else None
    )

    try:
        payload = answer_unified_question(
            message,
            site_no=body.site_no,
            session_id=body.session_id,
            history=client_history,
            max_tool_rounds=body.max_tool_rounds,
            config=cfg,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail={"error": "llm_failed", "message": str(exc)}) from exc
    except Exception as exc:
        logger.exception("Assistant agent chat failed unexpectedly")
        raise HTTPException(
            status_code=502,
            detail={"error": "agent_internal_error", "message": str(exc)},
        ) from exc

    try:
        return AssistantChatResponse.model_validate(payload).model_dump()
    except ValidationError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": "invalid_agent_response", "message": str(exc)},
        ) from exc

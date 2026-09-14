"""POST /copilot/chat — ops-doc RAG copilot (MVP-2)."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from pydantic import BaseModel, Field

from assistant import copilot as copilot_module
from assistant.config import load_assistant_config

logger = logging.getLogger(__name__)

copilot_router = APIRouter(prefix="/copilot", tags=["copilot"])


class CopilotChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Operator question in natural language.")
    site_no: str | None = Field(
        default=None,
        description="Optional USGS site number for context (does not fetch live data in MVP-2).",
    )


class CopilotSource(BaseModel):
    type: Literal["doc"] = "doc"
    ref: str
    heading: str | None = None


class CopilotChatResponse(BaseModel):
    answer: str
    sources: list[CopilotSource]
    model: str | None = None
    provider: Literal["openai", "ollama", "none"]
    usage: dict[str, int | float] | None = None
    intent: Literal["ops_doc", "live_data", "hybrid", "chitchat", "off_topic", "clarify"] | None = None
    retrieval_query: str | None = None


@copilot_router.post("/chat", response_model=CopilotChatResponse)
def copilot_chat(body: CopilotChatRequest) -> dict[str, Any]:
    """Answer ops questions from indexed documentation (read-only RAG)."""
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

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")

    try:
        payload = copilot_module.answer_copilot_question(question, site_no=body.site_no, config=cfg)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail={"error": "llm_failed", "message": str(exc)}) from exc
    except (ImportError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "rag_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Copilot chat failed unexpectedly")
        raise HTTPException(
            status_code=502,
            detail={"error": "copilot_internal_error", "message": str(exc)},
        ) from exc

    try:
        return CopilotChatResponse.model_validate(payload).model_dump()
    except ValidationError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": "invalid_copilot_response", "message": str(exc)},
        ) from exc

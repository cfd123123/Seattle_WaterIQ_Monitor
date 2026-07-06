"""Assistant health payload — configuration and RAG index readiness."""

from __future__ import annotations

from typing import Any, Literal

from assistant.config import AssistantConfig, load_assistant_config
from assistant.rag.search import is_rag_index_ready

AssistantHealthStatus = Literal["ok"]


def build_health_payload(config: AssistantConfig | None = None) -> dict[str, Any]:
    """
    Build GET /assistant/health JSON.

    ``rag_index_ready`` is true when the persisted or in-memory RAG index has chunks.
    """
    cfg = config if config is not None else load_assistant_config()
    return {
        "status": "ok",
        "enabled": cfg.enabled,
        "assistant_enabled": cfg.enabled,
        "provider": cfg.provider,
        "model": cfg.model,
        "configured": cfg.llm_configured,
        "llm_configured": cfg.llm_configured,
        "llm_reachable": False,
        "rag_index_ready": is_rag_index_ready(),
    }

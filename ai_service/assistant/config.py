"""Assistant LLM configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AssistantProvider = Literal["openai", "ollama", "none"]

DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip()


def _env_optional_str(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    return str(raw).strip()


def is_ollama_base_url(base_url: str) -> bool:
    """Heuristic: local Ollama or explicit ollama host does not require an API key."""
    lowered = base_url.lower()
    return "11434" in lowered or "ollama" in lowered


def detect_provider(*, api_key: str | None, base_url: str) -> AssistantProvider:
    if api_key:
        return "ollama" if is_ollama_base_url(base_url) else "openai"
    if is_ollama_base_url(base_url):
        return "ollama"
    return "none"


def is_llm_configured(*, api_key: str | None, base_url: str) -> bool:
    return bool(api_key) or is_ollama_base_url(base_url)


DEFAULT_MAX_TOOL_ROUNDS = 5


@dataclass(frozen=True)
class AssistantConfig:
    """Resolved assistant settings for health checks and future LLM calls."""

    master_enabled: bool
    api_key: str | None
    base_url: str
    model: str
    provider: AssistantProvider
    llm_configured: bool
    enabled: bool
    max_tool_rounds: int
    query_transform: bool

    @classmethod
    def from_environ(cls) -> AssistantConfig:
        master_enabled = _env_bool("ASSISTANT_ENABLED", default=True)
        api_key = _env_optional_str("ASSISTANT_LLM_API_KEY")
        base_url = _env_str("ASSISTANT_LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
        model = _env_str("ASSISTANT_LLM_MODEL", DEFAULT_LLM_MODEL)
        provider = detect_provider(api_key=api_key, base_url=base_url)
        llm_configured = is_llm_configured(api_key=api_key, base_url=base_url)
        enabled = master_enabled and llm_configured
        max_rounds_raw = os.environ.get("ASSISTANT_MAX_TOOL_ROUNDS")
        if max_rounds_raw and str(max_rounds_raw).strip().isdigit():
            max_tool_rounds = max(1, min(5, int(str(max_rounds_raw).strip())))
        else:
            max_tool_rounds = DEFAULT_MAX_TOOL_ROUNDS
        query_transform = _env_bool("ASSISTANT_QUERY_TRANSFORM", default=True)
        return cls(
            master_enabled=master_enabled,
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider=provider,
            llm_configured=llm_configured,
            enabled=enabled,
            max_tool_rounds=max_tool_rounds,
            query_transform=query_transform,
        )


def load_assistant_config() -> AssistantConfig:
    """Load assistant config from the current process environment."""
    return AssistantConfig.from_environ()


def ai_service_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ai_service_root() -> Path:
    return ai_service_root()


# Markdown sources indexed by MVP-2 RAG (paths relative to ai_service/).
# Public/minimal repos gitignore ai_service/plan/; rebuild index after clone:
#   python -m assistant.rag.indexer --rebuild
DEFAULT_RAG_DOC_REL_PATHS: tuple[str, ...] = (
    "docs/turbidity_operations.md",
)


@dataclass(frozen=True)
class RagConfig:
    """RAG index settings for the ops-doc copilot."""

    index_dir: Path
    top_k: int
    doc_paths: tuple[Path, ...]

    @classmethod
    def from_environ(cls) -> RagConfig:
        root = _ai_service_root()
        index_rel = _env_str("ASSISTANT_RAG_INDEX_DIR", "assistant/rag/store")
        index_dir = Path(index_rel)
        if not index_dir.is_absolute():
            index_dir = root / index_dir
        top_k_raw = os.environ.get("ASSISTANT_RAG_TOP_K")
        top_k = int(top_k_raw.strip()) if top_k_raw and str(top_k_raw).strip() else 5
        doc_paths = tuple(root / rel for rel in DEFAULT_RAG_DOC_REL_PATHS)
        return cls(index_dir=index_dir, top_k=top_k, doc_paths=doc_paths)


def load_rag_config() -> RagConfig:
    """Load RAG index configuration from the current process environment."""
    return RagConfig.from_environ()

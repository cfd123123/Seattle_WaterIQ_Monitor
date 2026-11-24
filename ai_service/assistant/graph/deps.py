"""Shared deps injected into the assistant LangGraph (keeps tests patch-friendly)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from assistant.config import AssistantConfig
from assistant.llm_client import CompletionResult
from assistant.rag.query_router import RouterResult, action_request_answer
from assistant.rag.search import SearchHit

CompleteFn = Callable[[list[dict[str, Any]]], CompletionResult]
CompleteWithToolsFn = Callable[[list[dict[str, Any]], list[dict[str, Any]]], CompletionResult]
ClassifyFn = Callable[[list[dict[str, str]]], CompletionResult]
ClassifyAndRewriteFn = Callable[..., RouterResult]
AgentAnswerFn = Callable[..., dict[str, Any]]
OpsDocAnswerFn = Callable[..., dict[str, Any]]
SelectToolFn = Callable[..., tuple[list[dict[str, Any]], dict[str, Any] | None, CompletionResult]]
SearchFn = Callable[..., list[SearchHit]]


@dataclass
class AssistantGraphDeps:
    """Callables resolved at invoke-time so unittest patches on unified_router still apply."""

    cfg: AssistantConfig
    complete_fn: CompleteFn
    classify_and_rewrite: ClassifyAndRewriteFn
    answer_agent_question: AgentAnswerFn
    answer_ops_doc_question: OpsDocAnswerFn
    select_and_execute_tool: SelectToolFn
    try_turbidity_sites_list_answer: Callable[[str], str | None]
    ensure_rag_index: Callable[..., Any]
    search_ops_docs: SearchFn
    session_store: Any
    should_reuse_cached_tools: Callable[..., bool]
    build_hybrid_messages: Callable[..., list[dict[str, Any]]]
    canned_chitchat: str
    canned_off_topic: str
    canned_clarify: str
    complete_with_tools_fn: CompleteWithToolsFn | None = None
    classify_fn: ClassifyFn | None = None
    max_tool_rounds: int | None = None
    top_k: int | None = None
    action_request_answer: Callable[[str], str] = action_request_answer

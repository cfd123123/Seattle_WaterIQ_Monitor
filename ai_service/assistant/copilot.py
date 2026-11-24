"""L2 ops-doc RAG copilot — retrieve docs and generate an English answer."""

from __future__ import annotations

from typing import Any, Callable

from assistant.config import AssistantConfig, load_assistant_config
from assistant.copilot_prompts import (
    CHITCHAT_ANSWER,
    CLARIFY_ANSWER,
    HYBRID_ANSWER,
    LIVE_DATA_ANSWER,
    LOW_CONFIDENCE_ANSWER,
    OFF_TOPIC_ANSWER,
    build_copilot_messages,
)
from assistant.llm_client import CompletionResult, LLMClient, build_complete_fn, sanitize_usage
from assistant.rag.query_router import (
    ROUTER_MAX_TOKENS,
    Intent,
    action_request_answer,
    classify_and_rewrite,
)
from assistant.rag.search import SearchHit, ensure_rag_index, search_ops_docs


def _dedupe_sources(hits: list[SearchHit]) -> list[dict[str, str]]:
    seen: set[str] = set()
    sources: list[dict[str, str]] = []
    for hit in hits:
        source = hit.to_source()
        ref = source["ref"]
        if ref in seen:
            continue
        seen.add(ref)
        sources.append(source)
    return sources


def _canned_response(
    *,
    answer: str,
    intent: Intent,
    retrieval_query: str | None,
    cfg: AssistantConfig,
) -> dict[str, Any]:
    return {
        "answer": answer,
        "sources": [],
        "model": cfg.model,
        "provider": cfg.provider,
        "usage": None,
        "intent": intent.value,
        "retrieval_query": retrieval_query,
    }


def _answer_ops_doc(
    question: str,
    *,
    retrieval_query: str,
    site_no: str | None,
    cfg: AssistantConfig,
    complete_fn: Callable[[list[dict[str, str]]], CompletionResult] | None,
    top_k: int | None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    ensure_rag_index()
    hits = search_ops_docs(retrieval_query, top_k=top_k)
    if not hits:
        return _canned_response(
            answer=LOW_CONFIDENCE_ANSWER,
            intent=Intent.OPS_DOC,
            retrieval_query=retrieval_query,
            cfg=cfg,
        )

    messages = build_copilot_messages(question, hits=hits, site_no=site_no, history=history)
    if complete_fn is not None:
        result = complete_fn(messages)
    else:
        client = LLMClient(cfg)
        result = client.complete(messages, max_tokens=768)

    return {
        "answer": result.text,
        "sources": _dedupe_sources(hits),
        "model": result.model,
        "provider": result.provider,
        "usage": sanitize_usage(result.usage),
        "intent": Intent.OPS_DOC.value,
        "retrieval_query": retrieval_query,
    }


def answer_copilot_question(
    question: str,
    *,
    site_no: str | None = None,
    config: AssistantConfig | None = None,
    complete_fn: Callable[[list[dict[str, str]]], CompletionResult] | None = None,
    classify_fn: Callable[[list[dict[str, str]]], CompletionResult] | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """
    Retrieve ops docs and call the LLM to produce an answer with sources.

    When query_transform is enabled (default), classifies intent and rewrites the
    BM25 query before retrieval. Read-only: does not call write APIs.
    """
    cfg = config if config is not None else load_assistant_config()

    if not cfg.query_transform:
        ensure_rag_index()
        hits = search_ops_docs(question, top_k=top_k)
        messages = build_copilot_messages(question, hits=hits, site_no=site_no)
        if complete_fn is not None:
            result = complete_fn(messages)
        else:
            client = LLMClient(cfg)
            result = client.complete(messages, max_tokens=768)
        return {
            "answer": result.text,
            "sources": _dedupe_sources(hits),
            "model": result.model,
            "provider": result.provider,
            "usage": sanitize_usage(result.usage),
        }

    router = classify_and_rewrite(
        question,
        site_no=site_no,
        complete_fn=classify_fn
        or build_complete_fn(cfg, max_tokens=ROUTER_MAX_TOKENS, temperature=0.0),
    )

    if router.intent is Intent.CHITCHAT:
        return _canned_response(
            answer=CHITCHAT_ANSWER,
            intent=Intent.CHITCHAT,
            retrieval_query=router.retrieval_query,
            cfg=cfg,
        )
    if router.intent is Intent.OFF_TOPIC:
        return _canned_response(
            answer=OFF_TOPIC_ANSWER,
            intent=Intent.OFF_TOPIC,
            retrieval_query=router.retrieval_query,
            cfg=cfg,
        )
    if router.intent is Intent.ACTION_REQUEST:
        return _canned_response(
            answer=action_request_answer(question),
            intent=Intent.ACTION_REQUEST,
            retrieval_query=None,
            cfg=cfg,
        )
    if router.intent is Intent.CLARIFY:
        return _canned_response(
            answer=CLARIFY_ANSWER,
            intent=Intent.CLARIFY,
            retrieval_query=router.retrieval_query,
            cfg=cfg,
        )
    if router.intent is Intent.LIVE_DATA:
        return _canned_response(
            answer=LIVE_DATA_ANSWER,
            intent=Intent.LIVE_DATA,
            retrieval_query=router.retrieval_query,
            cfg=cfg,
        )
    if router.intent is Intent.HYBRID:
        return _canned_response(
            answer=HYBRID_ANSWER,
            intent=Intent.HYBRID,
            retrieval_query=router.retrieval_query,
            cfg=cfg,
        )

    retrieval_query = (router.retrieval_query or question).strip()
    return _answer_ops_doc(
        question,
        retrieval_query=retrieval_query,
        site_no=site_no,
        cfg=cfg,
        complete_fn=complete_fn,
        top_k=top_k,
    )


def answer_ops_doc_question(
    question: str,
    *,
    retrieval_query: str | None = None,
    site_no: str | None = None,
    history: list[dict[str, str]] | None = None,
    config: AssistantConfig | None = None,
    complete_fn: Callable[[list[dict[str, str]]], CompletionResult] | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Ops-doc RAG answer without intent routing (shared by unified assistant entry)."""
    cfg = config if config is not None else load_assistant_config()
    rq = (retrieval_query or question).strip()
    return _answer_ops_doc(
        question,
        retrieval_query=rq,
        site_no=site_no,
        cfg=cfg,
        complete_fn=complete_fn,
        top_k=top_k,
        history=history,
    )

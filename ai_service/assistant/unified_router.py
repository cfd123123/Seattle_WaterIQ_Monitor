"""Unified assistant entry — intent routing for POST /assistant/chat."""

from __future__ import annotations

from typing import Any, Callable

from assistant.config import AssistantConfig, load_assistant_config
from assistant.copilot import answer_ops_doc_question
from assistant.copilot_prompts import (
    CHITCHAT_ANSWER,
    OFF_TOPIC_ANSWER,
    build_hybrid_messages,
)
from assistant.llm_client import CompletionResult, LLMClient, _merge_usage, sanitize_usage
from assistant.orchestrator import (
    _sources_from_audit,
    _tool_trace,
    answer_agent_question,
    select_and_execute_tool,
)
from assistant.rag.query_router import Intent, classify_and_rewrite, try_turbidity_sites_list_answer
from assistant.rag.search import SearchHit, ensure_rag_index, search_ops_docs
from assistant.session_memory import (
    looks_like_follow_up,
    session_store,
)


CompleteFn = Callable[[list[dict[str, Any]]], CompletionResult]


def _dedupe_doc_sources(hits: list[SearchHit]) -> list[dict[str, str]]:
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


def _merge_sources(
    api_sources: list[dict[str, str]],
    doc_sources: list[dict[str, str]],
) -> list[dict[str, str]]:
    seen: set[str] = set()
    merged: list[dict[str, str]] = []
    for source in api_sources + doc_sources:
        ref = source.get("ref", "")
        key = f"{source.get('type')}:{ref}"
        if not ref or key in seen:
            continue
        seen.add(key)
        merged.append(source)
    return merged


def _canned_unified(
    *,
    answer: str,
    intent: Intent,
    retrieval_query: str | None,
    cfg: AssistantConfig,
) -> dict[str, Any]:
    return {
        "answer": answer,
        "sources": [],
        "tool_calls": [],
        "tool_trace": [],
        "mode": "canned",
        "model": cfg.model,
        "provider": cfg.provider,
        "usage": None,
        "session_id": None,
        "intent": intent.value,
        "retrieval_query": retrieval_query,
    }


def _persist_session_turns(
    session_id: str,
    message: str,
    payload: dict[str, Any],
    *,
    site_no: str | None,
) -> None:
    """Append user/assistant turns and cache successful tool results."""
    answer = str(payload.get("answer", "")).strip()
    if answer:
        session_store.append_turn(session_id, "user", message)
        session_store.append_turn(session_id, "assistant", answer)
    audit = payload.get("tool_calls") or []
    if audit:
        payloads = [
            {
                "ok": e.get("ok"),
                "data": e.get("result_preview"),
                "source": e.get("source"),
                "name": e.get("name"),
            }
            for e in audit
            if e.get("ok")
        ]
        session_store.cache_tool_result(session_id, site_no, audit, payloads)


def _answer_hybrid(
    message: str,
    *,
    site_no: str | None,
    retrieval_query: str | None,
    cfg: AssistantConfig,
    complete_fn: CompleteFn,
    session_id: str | None,
    history: list[dict[str, str]] | None,
    top_k: int | None,
) -> dict[str, Any]:
    cached = session_store.get_cached_tools(session_id, site_no) if session_id else None
    reuse_cache = bool(cached and looks_like_follow_up(message, history or []))
    audit: list[dict[str, Any]] = []
    tool_payload: dict[str, Any] | None = None
    selection_usage = None

    if reuse_cache and cached is not None:
        audit, cached_payloads = cached
        if cached_payloads:
            tool_payload = cached_payloads[0]
    else:
        audit, tool_payload, selection = select_and_execute_tool(
            message,
            site_no,
            complete_fn=complete_fn,
        )
        selection_usage = selection.usage

    rq = (retrieval_query or "recommend_alert Phase B alert policy").strip()
    ensure_rag_index()
    hits = search_ops_docs(rq, top_k=top_k)
    doc_sources = _dedupe_doc_sources(hits)

    messages = build_hybrid_messages(
        message,
        tool_payload=tool_payload,
        hits=hits,
        site_no=site_no,
        history=history,
    )
    synthesis = complete_fn(messages)
    usage_acc = _merge_usage(selection_usage, synthesis.usage)

    api_sources = _sources_from_audit(audit)
    return {
        "answer": synthesis.text,
        "sources": _merge_sources(api_sources, doc_sources),
        "tool_calls": [] if reuse_cache else audit,
        "tool_trace": _tool_trace(audit),
        "mode": "hybrid",
        "model": synthesis.model,
        "provider": synthesis.provider,
        "usage": sanitize_usage(usage_acc),
        "session_id": session_id,
        "intent": Intent.HYBRID.value,
        "retrieval_query": rq,
    }


def answer_unified_question(
    message: str,
    *,
    site_no: str | None = None,
    session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    max_tool_rounds: int | None = None,
    config: AssistantConfig | None = None,
    complete_fn: CompleteFn | None = None,
    complete_with_tools_fn: Callable[..., CompletionResult] | None = None,
    classify_fn: Callable[[list[dict[str, str]]], CompletionResult] | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """
    Unified POST /assistant/chat orchestration: classify intent then route.

    Intents: chitchat, off_topic, ops_doc, live_data, hybrid.
    When query_transform is disabled, falls back to live_data (tools loop only).
    """
    cfg = config if config is not None else load_assistant_config()
    resolved_session = session_store.resolve_session_id(session_id)
    merged_history = session_store.merge_history(resolved_session, history)

    sites_answer = try_turbidity_sites_list_answer(message)
    if sites_answer is not None:
        out = _canned_unified(
            answer=sites_answer,
            intent=Intent.OPS_DOC,
            retrieval_query=None,
            cfg=cfg,
        )
        out["session_id"] = resolved_session
        _persist_session_turns(resolved_session, message, out, site_no=site_no)
        return out

    if complete_fn is None:

        def _complete_fn(msgs: list[dict[str, Any]]) -> CompletionResult:
            client = LLMClient(cfg)
            return client.complete(msgs, max_tokens=768)

        complete_fn = _complete_fn

    if not cfg.query_transform:
        payload = answer_agent_question(
            message,
            site_no=site_no,
            session_id=resolved_session,
            history=merged_history,
            max_tool_rounds=max_tool_rounds,
            config=cfg,
            complete_fn=complete_fn,
            complete_with_tools_fn=complete_with_tools_fn,
        )
        payload["intent"] = Intent.LIVE_DATA.value
        payload["retrieval_query"] = None
        payload["session_id"] = resolved_session
        _persist_session_turns(resolved_session, message, payload, site_no=site_no)
        return payload

    if classify_fn is not None:
        router = classify_and_rewrite(message, site_no=site_no, complete_fn=classify_fn)
    else:

        def _lazy_classify(msgs: list[dict[str, str]]) -> CompletionResult:
            client = LLMClient(cfg)
            return client.complete(msgs, temperature=0.0, max_tokens=128)

        router = classify_and_rewrite(message, site_no=site_no, complete_fn=_lazy_classify)

    if router.intent is Intent.CHITCHAT:
        out = _canned_unified(
            answer=CHITCHAT_ANSWER,
            intent=Intent.CHITCHAT,
            retrieval_query=router.retrieval_query,
            cfg=cfg,
        )
        out["session_id"] = resolved_session
        _persist_session_turns(resolved_session, message, out, site_no=site_no)
        return out

    if router.intent is Intent.OFF_TOPIC:
        out = _canned_unified(
            answer=OFF_TOPIC_ANSWER,
            intent=Intent.OFF_TOPIC,
            retrieval_query=router.retrieval_query,
            cfg=cfg,
        )
        out["session_id"] = resolved_session
        _persist_session_turns(resolved_session, message, out, site_no=site_no)
        return out

    if router.intent is Intent.OPS_DOC:
        payload = answer_ops_doc_question(
            message,
            retrieval_query=router.retrieval_query,
            site_no=site_no,
            history=merged_history,
            config=cfg,
            complete_fn=complete_fn,
            top_k=top_k,
        )
        payload["tool_calls"] = []
        payload["tool_trace"] = []
        payload["mode"] = "rag"
        payload["session_id"] = resolved_session
        _persist_session_turns(resolved_session, message, payload, site_no=site_no)
        return payload

    if router.intent is Intent.HYBRID:
        payload = _answer_hybrid(
            message,
            site_no=site_no,
            retrieval_query=router.retrieval_query,
            cfg=cfg,
            complete_fn=complete_fn,
            session_id=resolved_session,
            history=merged_history,
            top_k=top_k,
        )
        _persist_session_turns(resolved_session, message, payload, site_no=site_no)
        return payload

    # live_data (default agent tools loop)
    payload = answer_agent_question(
        message,
        site_no=site_no,
        session_id=resolved_session,
        history=merged_history,
        max_tool_rounds=max_tool_rounds,
        config=cfg,
        complete_fn=complete_fn,
        complete_with_tools_fn=complete_with_tools_fn,
    )
    payload["intent"] = Intent.LIVE_DATA.value
    payload["retrieval_query"] = router.retrieval_query
    payload["session_id"] = resolved_session
    _persist_session_turns(resolved_session, message, payload, site_no=site_no)
    return payload

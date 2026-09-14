"""Build and invoke the unified assistant LangGraph."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from assistant.graph.deps import AssistantGraphDeps
from assistant.graph.state import AssistantState
from assistant.llm_client import CompletionResult, LLMClient, _merge_usage, sanitize_usage
from assistant.rag.query_router import Intent
from assistant.reflect import revise_answer, run_reflection


def _dedupe_doc_sources(hits: list[Any]) -> list[dict[str, str]]:
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


def _sources_from_audit(audit: list[dict[str, Any]]) -> list[dict[str, str]]:
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


def _tool_trace(audit: list[dict[str, Any]]) -> list[str]:
    return [str(e["name"]) for e in audit if e.get("name")]


def _canned_payload(
    *,
    answer: str,
    intent: Intent,
    retrieval_query: str | None,
    cfg: Any,
    session_id: str | None,
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
        "session_id": session_id,
        "intent": intent.value,
        "retrieval_query": retrieval_query,
    }


def _apply_payload(
    state: AssistantState,
    payload: dict[str, Any],
    *,
    skip_reflect: bool = False,
) -> dict[str, Any]:
    return {
        "answer": str(payload.get("answer", "")),
        "sources": list(payload.get("sources") or []),
        "tool_calls": list(payload.get("tool_calls") or []),
        "tool_trace": list(payload.get("tool_trace") or []),
        "mode": str(payload.get("mode") or "canned"),
        "model": payload.get("model"),
        "provider": str(payload.get("provider") or state.get("provider") or "none"),
        "usage": payload.get("usage"),
        "session_id": payload.get("session_id", state.get("session_id")),
        "intent": payload.get("intent", state.get("intent")),
        "retrieval_query": payload.get("retrieval_query", state.get("retrieval_query")),
        "done": True,
        "skip_reflect": skip_reflect,
        "reflect_count": int(state.get("reflect_count") or 0),
        "reflect_issues": list(state.get("reflect_issues") or []),
        "reflect_action": state.get("reflect_action"),
    }


def build_assistant_graph(deps: AssistantGraphDeps):
    """Compile intent-routing graph; nodes close over deps for patch compatibility."""

    def resolve_session(state: AssistantState) -> dict[str, Any]:
        resolved = deps.session_store.resolve_session_id(state.get("session_id"))
        merged = deps.session_store.merge_history(resolved, state.get("history"))
        return {
            "session_id": resolved,
            "history": merged,
            "provider": deps.cfg.provider,
            "model": deps.cfg.model,
            "done": False,
            "skip_classify": False,
            "skip_reflect": False,
            "reflect_count": 0,
            "reflect_issues": [],
            "reflect_action": None,
        }

    def special_canned(state: AssistantState) -> dict[str, Any]:
        sites_answer = deps.try_turbidity_sites_list_answer(state["message"])
        if sites_answer is None:
            return {"done": False}
        payload = _canned_payload(
            answer=sites_answer,
            intent=Intent.OPS_DOC,
            retrieval_query=None,
            cfg=deps.cfg,
            session_id=state.get("session_id"),
        )
        return _apply_payload(state, payload, skip_reflect=True)

    def classify(state: AssistantState) -> dict[str, Any]:
        if not deps.cfg.query_transform:
            return {
                "intent": Intent.LIVE_DATA.value,
                "retrieval_query": None,
                "skip_classify": True,
            }

        if deps.classify_fn is not None:
            router = deps.classify_and_rewrite(
                state["message"],
                site_no=state.get("site_no"),
                complete_fn=deps.classify_fn,
            )
        else:

            def _lazy_classify(msgs: list[dict[str, str]]) -> CompletionResult:
                client = LLMClient(deps.cfg)
                return client.complete(msgs, temperature=0.0, max_tokens=128)

            router = deps.classify_and_rewrite(
                state["message"],
                site_no=state.get("site_no"),
                complete_fn=_lazy_classify,
            )
        return {
            "intent": router.intent.value,
            "retrieval_query": router.retrieval_query,
        }

    def canned_reply(state: AssistantState) -> dict[str, Any]:
        intent_raw = state.get("intent") or Intent.CLARIFY.value
        intent = Intent(intent_raw) if intent_raw in {i.value for i in Intent} else Intent.CLARIFY
        if intent is Intent.CHITCHAT:
            answer = deps.canned_chitchat
        elif intent is Intent.OFF_TOPIC:
            answer = deps.canned_off_topic
        else:
            answer = deps.canned_clarify
            intent = Intent.CLARIFY
        payload = _canned_payload(
            answer=answer,
            intent=intent,
            retrieval_query=state.get("retrieval_query"),
            cfg=deps.cfg,
            session_id=state.get("session_id"),
        )
        return _apply_payload(state, payload, skip_reflect=True)

    def rag_answer(state: AssistantState) -> dict[str, Any]:
        payload = deps.answer_ops_doc_question(
            state["message"],
            retrieval_query=state.get("retrieval_query"),
            site_no=state.get("site_no"),
            history=state.get("history"),
            config=deps.cfg,
            complete_fn=deps.complete_fn,
            top_k=deps.top_k,
        )
        payload["tool_calls"] = []
        payload["tool_trace"] = []
        payload["mode"] = "rag"
        payload["session_id"] = state.get("session_id")
        payload["intent"] = Intent.OPS_DOC.value
        payload["retrieval_query"] = state.get("retrieval_query")
        return _apply_payload(state, payload)

    def live_data(state: AssistantState) -> dict[str, Any]:
        payload = deps.answer_agent_question(
            state["message"],
            site_no=state.get("site_no"),
            session_id=state.get("session_id"),
            history=state.get("history"),
            max_tool_rounds=deps.max_tool_rounds,
            config=deps.cfg,
            complete_fn=deps.complete_fn,
            complete_with_tools_fn=deps.complete_with_tools_fn,
        )
        payload["intent"] = Intent.LIVE_DATA.value
        payload["retrieval_query"] = (
            None if not deps.cfg.query_transform else state.get("retrieval_query")
        )
        payload["session_id"] = state.get("session_id")
        return _apply_payload(state, payload)

    def hybrid(state: AssistantState) -> dict[str, Any]:
        message = state["message"]
        site_no = state.get("site_no")
        session_id = state.get("session_id")
        history = state.get("history") or []
        retrieval_query = state.get("retrieval_query")

        cached = deps.session_store.get_cached_tools(session_id, site_no) if session_id else None
        reuse_cache = bool(cached and deps.looks_like_follow_up(message, history))
        audit: list[dict[str, Any]] = []
        tool_payload: dict[str, Any] | None = None
        selection_usage = None

        if reuse_cache and cached is not None:
            audit, cached_payloads = cached
            if cached_payloads:
                tool_payload = cached_payloads[0]
        else:
            audit, tool_payload, selection = deps.select_and_execute_tool(
                message,
                site_no,
                complete_fn=deps.complete_fn,
            )
            selection_usage = selection.usage

        rq = (retrieval_query or "recommend_alert online turbidity alert policy").strip()
        deps.ensure_rag_index()
        hits = deps.search_ops_docs(rq, top_k=deps.top_k)
        doc_sources = _dedupe_doc_sources(hits)

        messages = deps.build_hybrid_messages(
            message,
            tool_payload=tool_payload,
            hits=hits,
            site_no=site_no,
            history=history,
        )
        synthesis = deps.complete_fn(messages)
        usage_acc = _merge_usage(selection_usage, synthesis.usage)

        payload = {
            "answer": synthesis.text,
            "sources": _merge_sources(_sources_from_audit(audit), doc_sources),
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
        return _apply_payload(state, payload)

    def reflect(state: AssistantState) -> dict[str, Any]:
        """Rule-first reflection after rag/tools/hybrid; optional one revise or clarify."""
        if not deps.cfg.reflect_enabled or state.get("skip_reflect"):
            return {}
        mode = str(state.get("mode") or "")
        if mode == "canned":
            return {"skip_reflect": True}

        answer = str(state.get("answer") or "")
        tool_calls = list(state.get("tool_calls") or [])
        count = int(state.get("reflect_count") or 0)
        max_retries = int(deps.cfg.reflect_max_retries)

        result = run_reflection(
            answer=answer,
            mode=mode,
            tool_calls=tool_calls,
            site_no=state.get("site_no"),
            use_llm=bool(deps.cfg.reflect_use_llm),
            complete_fn=deps.complete_fn if deps.cfg.reflect_use_llm else None,
        )
        if result.ok:
            return {
                "reflect_count": count,
                "reflect_issues": [],
                "reflect_action": "pass",
                "skip_reflect": True,
            }

        updates: dict[str, Any] = {
            "reflect_count": count + 1,
            "reflect_issues": list(result.issues),
            "reflect_action": result.action,
        }

        if result.action == "clarify" or count >= max_retries:
            updates["answer"] = deps.canned_clarify
            updates["intent"] = Intent.CLARIFY.value
            updates["mode"] = "canned"
            updates["skip_reflect"] = True
            return updates

        if result.action == "revise_answer" and count < max_retries:
            revised = revise_answer(
                message=state["message"],
                draft_answer=answer,
                issues=result.issues,
                tool_calls=tool_calls,
                complete_fn=deps.complete_fn,
            )
            updates["answer"] = revised
            # Re-check once after revise without another LLM round-trip beyond revise.
            again = run_reflection(
                answer=revised,
                mode=mode,
                tool_calls=tool_calls,
                site_no=state.get("site_no"),
                use_llm=False,
                complete_fn=None,
            )
            if not again.ok:
                updates["answer"] = deps.canned_clarify
                updates["intent"] = Intent.CLARIFY.value
                updates["mode"] = "canned"
                updates["reflect_issues"] = list(result.issues) + list(again.issues)
                updates["reflect_action"] = "clarify"
            updates["skip_reflect"] = True
            return updates

        updates["skip_reflect"] = True
        return updates

    def persist(state: AssistantState) -> dict[str, Any]:
        session_id = state.get("session_id")
        if not session_id:
            return {}
        answer = str(state.get("answer") or "").strip()
        if answer:
            deps.session_store.append_turn(session_id, "user", state["message"])
            deps.session_store.append_turn(session_id, "assistant", answer)
        audit = state.get("tool_calls") or []
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
            deps.session_store.cache_tool_result(session_id, state.get("site_no"), audit, payloads)
        return {}

    def after_special(state: AssistantState) -> Literal["persist", "live_data", "classify"]:
        if state.get("done"):
            return "persist"
        if not deps.cfg.query_transform:
            return "live_data"
        return "classify"

    def after_classify(
        state: AssistantState,
    ) -> Literal["canned_reply", "rag_answer", "live_data", "hybrid"]:
        intent = state.get("intent")
        if intent in {
            Intent.CHITCHAT.value,
            Intent.OFF_TOPIC.value,
            Intent.CLARIFY.value,
        }:
            return "canned_reply"
        if intent == Intent.OPS_DOC.value:
            return "rag_answer"
        if intent == Intent.HYBRID.value:
            return "hybrid"
        return "live_data"

    graph = StateGraph(AssistantState)
    graph.add_node("resolve_session", resolve_session)
    graph.add_node("special_canned", special_canned)
    graph.add_node("classify", classify)
    graph.add_node("canned_reply", canned_reply)
    graph.add_node("rag_answer", rag_answer)
    graph.add_node("live_data", live_data)
    graph.add_node("hybrid", hybrid)
    graph.add_node("reflect", reflect)
    graph.add_node("persist", persist)

    graph.add_edge(START, "resolve_session")
    graph.add_edge("resolve_session", "special_canned")
    graph.add_conditional_edges(
        "special_canned",
        after_special,
        {
            "persist": "persist",
            "live_data": "live_data",
            "classify": "classify",
        },
    )
    graph.add_conditional_edges(
        "classify",
        after_classify,
        {
            "canned_reply": "canned_reply",
            "rag_answer": "rag_answer",
            "live_data": "live_data",
            "hybrid": "hybrid",
        },
    )
    graph.add_edge("canned_reply", "persist")
    graph.add_edge("rag_answer", "reflect")
    graph.add_edge("live_data", "reflect")
    graph.add_edge("hybrid", "reflect")
    graph.add_edge("reflect", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def invoke_assistant_graph(
    deps: AssistantGraphDeps,
    *,
    message: str,
    site_no: str | None = None,
    session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run the compiled graph and return the public assistant chat payload."""
    compiled = build_assistant_graph(deps)
    final: AssistantState = compiled.invoke(
        {
            "message": message,
            "site_no": site_no,
            "session_id": session_id,
            "history": history or [],
        }
    )
    return {
        "answer": str(final.get("answer") or ""),
        "sources": list(final.get("sources") or []),
        "tool_calls": list(final.get("tool_calls") or []),
        "tool_trace": list(final.get("tool_trace") or []),
        "mode": str(final.get("mode") or "canned"),
        "model": final.get("model"),
        "provider": final.get("provider") or deps.cfg.provider,
        "usage": final.get("usage"),
        "session_id": final.get("session_id"),
        "intent": final.get("intent"),
        "retrieval_query": final.get("retrieval_query"),
    }

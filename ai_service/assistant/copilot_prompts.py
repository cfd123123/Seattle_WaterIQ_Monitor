"""Prompt templates for ops-doc RAG copilot (MVP-2)."""

from __future__ import annotations

import json
from typing import Any

ROUTER_SYSTEM_PROMPT = """\
You route operator questions for a READ-ONLY USGS Puget Sound turbidity/flow monitoring assistant.
Answer five independent yes/no labels about the LATEST question. Do not pick a single category.

- in_scope: true if the question concerns this monitoring product — USGS turbidity (63680) or flow (00060) \
at Puget Sound sites, alerts, recommend_alert, Phase A / Phase B, R7 / R7a / R7b, monitoring states, \
forecasts, runbooks, or how to use this assistant (greetings count as in scope). \
False for unrelated topics: sports, stocks, recipes, general coding, news, general weather not tied to a site.
- chitchat: a greeting, thanks, or small talk with no real question.
- action_request: the operator asks you to CHANGE something — create/edit/delete a site, acknowledge or \
close an alert, change thresholds, tiers, or recommend_alert. Asking HOW to do it is NOT an action request \
(that is need_docs).
- need_tools: answering needs live read-only data — current readings, forecasts, 12h risk, alert tier, \
state snapshot, or any present value at a specific site.
- need_docs: answering needs documentation — definitions, policies, rules, runbooks, or why something happens.

Tie-breaking:
- Unsure whether data or docs are needed → set BOTH need_tools and need_docs to true.
- Unsure whether the question is in scope → set in_scope to true.

retrieval_query: when need_docs is true, a short English keyword phrase for BM25 search \
(English even if the question is Chinese; keep product terms like Phase B, recommend_alert, R7a). \
Otherwise an empty string.

Use "Conversation so far" only to resolve follow-ups such as "why?", "what about the other site?", "那上游呢".

Reply with ONLY one JSON object, no markdown:
{"in_scope": true, "chitchat": false, "action_request": false, "need_tools": false, "need_docs": false, \
"retrieval_query": ""}

Examples:
Latest question: 你好
{"in_scope": true, "chitchat": true, "action_request": false, "need_tools": false, "need_docs": false, "retrieval_query": ""}

Latest question: Who won the World Cup?
{"in_scope": false, "chitchat": false, "action_request": false, "need_tools": false, "need_docs": false, "retrieval_query": ""}

Latest question: Phase B 是什么
{"in_scope": true, "chitchat": false, "action_request": false, "need_tools": false, "need_docs": true, "retrieval_query": "Phase B online alert recommend_alert"}

Latest question: What is turbidity at site 12117500 right now?
{"in_scope": true, "chitchat": false, "action_request": false, "need_tools": true, "need_docs": false, "retrieval_query": ""}

Latest question: Why is recommend_alert true for site 12117500 and what does Phase B say?
{"in_scope": true, "chitchat": false, "action_request": false, "need_tools": true, "need_docs": true, "retrieval_query": "recommend_alert Phase B alert policy"}

Latest question: Please close alert 42
{"in_scope": true, "chitchat": false, "action_request": true, "need_tools": false, "need_docs": false, "retrieval_query": ""}

Latest question: How do I close an alert?
{"in_scope": true, "chitchat": false, "action_request": false, "need_tools": false, "need_docs": true, "retrieval_query": "acknowledge close alert procedure"}

Conversation so far:
user: What is the current turbidity at 12117500?
assistant: Turbidity at 12117500 is 62 NTU, alert tier HIGH.
Latest question: why so high?
{"in_scope": true, "chitchat": false, "action_request": false, "need_tools": true, "need_docs": true, "retrieval_query": "turbidity high alert tier cause"}
"""

# Router context window: last N turns, each truncated (assistant answers can be long).
ROUTER_HISTORY_TURNS = 4
ROUTER_HISTORY_CHARS = 300

COPILOT_SYSTEM_PROMPT = """\
You are a water-quality operations copilot for USGS turbidity monitoring.

You answer questions using ONLY the retrieved documentation snippets provided in the user message.
Respond in English only.

Hard rules:
- Default length: 2–3 short sentences. Only go longer if the operator explicitly asks for detail.
- Use plain everyday English. Avoid jargon where a simpler word works.
- Do NOT include file paths, markdown links, anchors, section numbers, or [plan/...#...] style citations \
in your answer. The API attaches sources separately.
- If the operator greets you or asks a non-ops question (e.g. "hello", "你好"), reply briefly in English: \
introduce yourself as the turbidity ops copilot and invite ops questions.
- If the snippets do not contain enough information, say "I don't know" and suggest checking the \
official ops docs or on-call runbook.
- NEVER invent numeric thresholds, site readings, or alert decisions.
- NEVER claim you can change recommend_alert, alert tiers, or any automated decision fields.
- Decision values (recommend_alert, tiers, NTU) always come from deterministic Python/Java APIs, \
not from the LLM.
- Use short paragraphs or one simple list only when it clearly helps readability.
"""

LOW_CONFIDENCE_ANSWER = (
    "I could not find a close match in the indexed ops docs for that question. "
    "Try rephrasing with terms like Phase B, recommend_alert, or monitoring state, "
    "or check the turbidity operations runbook."
)

CHITCHAT_ANSWER = (
    "Hello! I'm the turbidity monitoring assistant. "
    "Ask about Phase B alerts, live site readings, 12h risk forecasts, "
    "or other turbidity and flow ops topics."
)

OFF_TOPIC_ANSWER = (
    "That question is outside turbidity monitoring and ops documentation. "
    "I can help with alerts, site readings, monitoring states, and runbook topics for this product."
)

CLARIFY_ANSWER = (
    "I'm not sure what you need yet. Please rephrase using one clear ask: "
    "(1) docs — e.g. What is the online turbidity alert policy?; "
    "(2) live data — e.g. 12h turbidity risk for site 12117500; "
    "(3) both — e.g. why is recommend_alert true for 12117500 according to the alert rules?"
)

ACTION_REQUEST_ANSWER = (
    "I can't make changes — this assistant is read-only. {hint} "
    "I can still look up current readings and forecasts, or explain the alert rules."
)
ACTION_REQUEST_SITE_HINT = (
    "To register or edit a monitoring site, use the Stations page (USGS site numbers are verified on save)."
)
ACTION_REQUEST_ALERT_HINT = "To acknowledge or close an alert, use the alert list on the Dashboard page."
ACTION_REQUEST_RULE_HINT = (
    "Thresholds, tiers, and recommend_alert come from deterministic rules and server configuration "
    "owned by admins; they cannot be overridden from chat."
)
ACTION_REQUEST_GENERIC_HINT = "Please make changes from the monitoring dashboard."

LIVE_DATA_ANSWER = (
    "Live site readings and forecasts are not available in documentation mode. "
    "Switch to Agent mode (POST /assistant/chat) to query current turbidity, risk forecast, "
    "or use the forecast page in the monitoring dashboard."
)

HYBRID_ANSWER = (
    "This question needs both live forecast data and ops policy context. "
    "Use POST /assistant/chat (unified assistant entry) which runs read-only tools "
    "and retrieves relevant documentation in one answer."
)

HYBRID_SYNTHESIZE_PROMPT = """\
You are the Water Quality Operations Assistant (unified hybrid mode).

The operator asked a question that requires BOTH:
1. Live read-only API tool results (frozen decision fields — authoritative numbers and flags)
2. Retrieved ops documentation snippets (policy context)

Rules:
- Answer in English only.
- Default length: 2–4 short sentences unless the operator asks for detail.
- Use plain everyday English; avoid jargon where a simpler word works.
- All numeric values, tiers, and recommend_alert MUST match the tool JSON exactly — never invent NTU, tiers, or alert flags.
- Use documentation snippets to explain why or policy context; do not let docs override tool decision fields.
- Do NOT include file paths, markdown links, anchors, or [plan/...#...] style citations in your answer. \
The API attaches sources separately.
- NEVER claim you can change recommend_alert or any automated decision field.
- If tool data is missing or errored, say so; still use docs for general policy if helpful.
"""


def build_router_messages(
    question: str,
    *,
    site_no: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build messages for label classification + retrieval query rewrite.

    History goes into the user message as a transcript (not as chat turns), so the
    router classifies the latest question instead of continuing the conversation.
    """
    site_line = f"Operator focus site: {site_no}\n" if site_no else ""
    transcript = ""
    if history:
        lines = [
            f"{turn.get('role', 'user')}: {str(turn.get('content', ''))[:ROUTER_HISTORY_CHARS]}"
            for turn in history[-ROUTER_HISTORY_TURNS:]
        ]
        transcript = "Conversation so far:\n" + "\n".join(lines) + "\n"
    user_content = f"{site_line}{transcript}Latest question: {question}"
    return [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_copilot_messages(
    question: str,
    *,
    hits: list[Any],
    site_no: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build chat messages with retrieved doc context and optional prior turns."""
    context_blocks: list[str] = []
    for idx, hit in enumerate(hits, start=1):
        chunk = hit.chunk if hasattr(hit, "chunk") else hit
        ref = f"{chunk.source_path}#{chunk.anchor}"
        context_blocks.append(f"[{idx}] Source: {ref}\n{chunk.text}")

    context_text = "\n\n---\n\n".join(context_blocks) if context_blocks else "(no snippets retrieved)"
    site_line = f"Operator focus site: {site_no}\n" if site_no else ""
    user_content = (
        f"{site_line}"
        "Use the documentation snippets below to answer the operator question.\n"
        "If snippets are insufficient, say you don't know.\n\n"
        f"Question: {question}\n\n"
        f"Documentation snippets:\n{context_text}"
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": COPILOT_SYSTEM_PROMPT},
    ]
    if history:
        for turn in history:
            role = turn.get("role")
            content = str(turn.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_content})
    return messages


def build_hybrid_messages(
    question: str,
    *,
    tool_payload: dict[str, Any] | None,
    hits: list[Any],
    site_no: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build chat messages for hybrid synthesis (tool JSON + doc snippets)."""
    context_blocks: list[str] = []
    for idx, hit in enumerate(hits, start=1):
        chunk = hit.chunk if hasattr(hit, "chunk") else hit
        ref = f"{chunk.source_path}#{chunk.anchor}"
        context_blocks.append(f"[{idx}] Source: {ref}\n{chunk.text}")

    context_text = "\n\n---\n\n".join(context_blocks) if context_blocks else "(no documentation snippets retrieved)"
    site_line = f"Operator focus site: {site_no}\n" if site_no else ""

    if tool_payload is not None:
        tool_section = f"Tool result JSON:\n{json.dumps(tool_payload, default=str)}"
    else:
        tool_section = "Tool result: (no tool was executed)"

    user_content = (
        f"{site_line}"
        "Synthesize an English answer using the tool result and documentation snippets below.\n"
        "Decision fields in the tool JSON are frozen and authoritative.\n\n"
        f"Question: {question}\n\n"
        f"{tool_section}\n\n"
        f"Documentation snippets:\n{context_text}"
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": HYBRID_SYNTHESIZE_PROMPT},
    ]
    if history:
        for turn in history:
            role = turn.get("role")
            content = str(turn.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_content})
    return messages

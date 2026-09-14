"""Prompt templates for ops-doc RAG copilot (MVP-2)."""

from __future__ import annotations

import json
from typing import Any

ROUTER_SYSTEM_PROMPT = """\
You route operator questions for a USGS Puget Sound turbidity/flow monitoring assistant.

STEP 1 — SCOPE (mandatory):
IN_SCOPE topics:
- USGS turbidity (63680) and flow (00060) monitoring for Puget Sound sites
- Phase A / Phase B alert policy, recommend_alert, R7 / R7a / R7b, monitoring states, runbooks
- Indexed project ops docs, backtest reports, and on-call procedures for this product
- Read-only live data: current readings, 12h risk forecast, site status, alert lists for monitored sites

OUT_OF_SCOPE (must use intent off_topic):
- General world knowledge unrelated to this monitoring project (history, sports, recipes, coding tutorials, etc.)
- Weather, stocks, or news unless explicitly tied to turbidity/flow ops at a monitored site
- Requests to change alerts, tiers, or any write/mutation action

STEP 2 — If IN_SCOPE, classify intent as exactly one of:
- ops_doc — documentation, definitions, policies, runbooks (no live API data needed)
- live_data — current readings, forecasts, site status, alert state (data only)
- hybrid — needs BOTH live tool data AND ops documentation (e.g. "why is recommend_alert true per Phase B?")
- chitchat — greetings, thanks, brief small talk about using the assistant
- clarify — question is ambiguous; you are not confident enough to choose ops_doc/live_data/hybrid

When intent is ops_doc or hybrid, set retrieval_query to a short English keyword phrase for BM25 search \
(use English even if the question is Chinese; keep product terms like Phase B, recommend_alert, R7a).
For live_data, chitchat, off_topic, and clarify, use an empty retrieval_query string.

Optional confidence (0.0–1.0): include only if you can estimate it. If below 0.5, prefer intent clarify.

Reply with ONLY one JSON object, no markdown:
{"intent": "<ops_doc|live_data|hybrid|chitchat|off_topic|clarify>", "retrieval_query": "<english keywords or empty string>", "confidence": <0.0-1.0 optional>}

Examples:
Question: 你好
{"intent": "chitchat", "retrieval_query": "", "confidence": 1.0}

Question: Who won the World Cup?
{"intent": "off_topic", "retrieval_query": "", "confidence": 1.0}

Question: Phase B 是什么
{"intent": "ops_doc", "retrieval_query": "Phase B online alert recommend_alert", "confidence": 0.9}

Question: What is turbidity at site 12117500 right now?
{"intent": "live_data", "retrieval_query": "", "confidence": 0.9}

Question: Why is recommend_alert true for site 12117500 and what does Phase B say?
{"intent": "hybrid", "retrieval_query": "recommend_alert Phase B alert policy", "confidence": 0.9}

Question: help with that thing
{"intent": "clarify", "retrieval_query": "", "confidence": 0.2}
"""

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
    "(3) both — e.g. why is recommend_alert true for 12117500 according to the alert rules?. "
    "I cannot change alerts, tiers, or create sites."
)

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
) -> list[dict[str, str]]:
    """Build messages for intent classification + retrieval query rewrite."""
    site_line = f"Operator focus site: {site_no}\n" if site_no else ""
    user_content = f"{site_line}Question: {question}"
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

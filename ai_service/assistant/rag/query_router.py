"""Intent classification and retrieval query rewriting for RAG copilot (v2)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from assistant.copilot_prompts import build_router_messages
from assistant.llm_client import CompletionResult, LLMClient

_CHITCHAT_FAST_PATH = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "你好",
        "嗨",
        "谢谢",
    }
)


class Intent(str, Enum):
    OPS_DOC = "ops_doc"
    LIVE_DATA = "live_data"
    HYBRID = "hybrid"
    CHITCHAT = "chitchat"
    OFF_TOPIC = "off_topic"


@dataclass(frozen=True)
class RouterResult:
    intent: Intent
    retrieval_query: str | None = None


def _normalize_intent(raw: str) -> Intent | None:
    cleaned = raw.strip().lower().replace("-", "_")
    for intent in Intent:
        if cleaned == intent.value:
            return intent
    aliases = {
        "ops": Intent.OPS_DOC,
        "doc": Intent.OPS_DOC,
        "documentation": Intent.OPS_DOC,
        "live": Intent.LIVE_DATA,
        "data": Intent.LIVE_DATA,
        "agent": Intent.LIVE_DATA,
        "mixed": Intent.HYBRID,
        "hybrid_data_doc": Intent.HYBRID,
        "chat": Intent.CHITCHAT,
        "greeting": Intent.CHITCHAT,
        "offtopic": Intent.OFF_TOPIC,
        "other": Intent.OFF_TOPIC,
    }
    return aliases.get(cleaned)


def _extract_json_object(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]*\}", text, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _parse_line_format(text: str) -> RouterResult | None:
    intent_raw: str | None = None
    retrieval_query: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("intent:"):
            intent_raw = stripped.split(":", 1)[1].strip()
        elif lower.startswith("retrieval_query:"):
            retrieval_query = stripped.split(":", 1)[1].strip()
    if not intent_raw:
        return None
    intent = _normalize_intent(intent_raw)
    if intent is None:
        return None
    if intent is Intent.OPS_DOC and not retrieval_query:
        retrieval_query = None
    return RouterResult(intent=intent, retrieval_query=retrieval_query or None)


def parse_router_output(text: str) -> RouterResult:
    """Parse LLM router output (JSON preferred, line format fallback)."""
    payload = _extract_json_object(text)
    if payload:
        intent_raw = payload.get("intent")
        if isinstance(intent_raw, str):
            intent = _normalize_intent(intent_raw)
            if intent is not None:
                rq = payload.get("retrieval_query")
                retrieval_query = rq.strip() if isinstance(rq, str) and rq.strip() else None
                return RouterResult(intent=intent, retrieval_query=retrieval_query)

    line_result = _parse_line_format(text)
    if line_result is not None:
        return line_result

    # Parse failure: reject rather than defaulting to doc search (avoids hallucination on garbage input).
    return RouterResult(intent=Intent.OFF_TOPIC, retrieval_query=None)


_HYBRID_DATA_KEYWORDS = (
    "risk",
    "forecast",
    "turbidity",
    "recommend_alert",
    "alert",
    "12h",
    "12 h",
    "63680",
    "00060",
    "flow",
    "discharge",
    "site",
)

_HYBRID_DOC_KEYWORDS = (
    "why",
    "explain",
    "policy",
    "phase b",
    "phase a",
    "rule",
    "r7",
    "r7a",
    "r7b",
    "mean",
    "meaning",
    "according to",
    "runbook",
    "documentation",
)


def _default_hybrid_retrieval_query(question: str) -> str:
    lowered = question.lower()
    if "recommend_alert" in lowered or "recommend alert" in lowered:
        return "recommend_alert Phase B alert policy rules"
    if "phase b" in lowered:
        return "Phase B recommend_alert online alert policy"
    if "r7" in lowered:
        return "R7 R7a R7b recommend_alert escalation policy"
    return "recommend_alert Phase B turbidity alert policy"


def _fast_path_chitchat(question: str) -> RouterResult | None:
    normalized = question.strip().lower().rstrip("!.?")
    if normalized in _CHITCHAT_FAST_PATH:
        return RouterResult(intent=Intent.CHITCHAT, retrieval_query=None)
    return None


def _fast_path_hybrid(question: str) -> RouterResult | None:
    """Heuristic: live-data cues plus policy/explain cues → hybrid."""
    lowered = question.lower()
    has_data = any(k in lowered for k in _HYBRID_DATA_KEYWORDS) or bool(
        re.search(r"\b\d{8}\b", question)
    )
    has_doc = any(k in lowered for k in _HYBRID_DOC_KEYWORDS)
    if has_data and has_doc:
        return RouterResult(
            intent=Intent.HYBRID,
            retrieval_query=_default_hybrid_retrieval_query(question),
        )
    return None


# Guard: skip off_topic fast path when the question may be monitoring-related.
_MONITORING_SCOPE_KEYWORDS = (
    "turbidity",
    "flow",
    "discharge",
    "usgs",
    "site",
    "63680",
    "00060",
    "phase a",
    "phase b",
    "recommend_alert",
    "recommend alert",
    "r7",
    "r7a",
    "r7b",
    "alert",
    "monitoring",
    "runbook",
    "ntu",
    "puget",
    "forecast",
    "wqi",
    "water quality",
)

# Obvious OUT_OF_SCOPE phrases from ROUTER_SYSTEM_PROMPT examples (sports, weather, etc.).
_OFF_TOPIC_KEYWORDS = (
    "world cup",
    "super bowl",
    "basketball",
    "nba",
    "nfl",
    "mlb",
    "olympics",
    "soccer",
    "champions league",
    "weather forecast",
    "will it rain",
    "temperature tomorrow",
    "what's the weather",
    "what is the weather",
    "weather today",
    "weather tomorrow",
    "recipe for",
    "how to cook",
    "how to bake",
    "write a poem",
    "write me a poem",
    "stock price",
    "stock market",
    "nasdaq",
    "dow jones",
    "share price",
    "tell me a joke",
    "knock knock",
    "coding tutorial",
    "learn javascript",
    "learn python",
    "latest news",
    "breaking news",
)

_OFF_TOPIC_REGEXES = (
    re.compile(r"\bwho\s+won\b", re.IGNORECASE),
    re.compile(r"\bfootball\s+(game|match|score)\b", re.IGNORECASE),
)

_CREATE_SITE_PHRASES = (
    "create new site",
    "create a new site",
    "create a site",
    "add new site",
    "add a new site",
    "register new site",
    "register a site",
    "新建站点",
    "新建站",
    "添加站点",
    "新增站点",
)

_CREATE_SITE_REGEXES = (
    re.compile(r"\b(create|add|register)\s+(a\s+)?new\s+site\b", re.IGNORECASE),
    re.compile(r"(新建|添加|新增).{0,4}站", re.IGNORECASE),
)

_TURBIDITY_SITES_CANNED = (
    "Turbidity (63680) monitoring is wired for these Puget Sound sites: "
    "12117500 (Cedar River near Landsburg, WA); "
    "12147600 (South Fork Tolt River near Index, WA). "
    "Other registered sites may lack 63680 in IV. "
    "Enter an 8-digit USGS site number or set the site on the forecast page."
)

_WHICH_TURBIDITY_SITES_REGEXES = (
    re.compile(
        r"\b(which|what)\s+sites?\s+(have|with|monitor|track)\s+turbidity\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bsites?\s+with\s+turbidity\b", re.IGNORECASE),
    re.compile(r"list.*turbidity.*sites?", re.IGNORECASE),
    re.compile(r"哪些.*(站|站点).*(浊度|63680)"),
    re.compile(r"浊度.*(哪些|哪几个).*(站|站点)"),
)


def _looks_in_monitoring_scope(question: str) -> bool:
    lowered = question.lower()
    if any(k in lowered for k in _MONITORING_SCOPE_KEYWORDS):
        return True
    return bool(re.search(r"\b\d{8}\b", question))


def _fast_path_create_site(question: str) -> RouterResult | None:
    """Heuristic: site registration / creation requests are out of scope."""
    lowered = question.lower()
    if any(p in lowered for p in _CREATE_SITE_PHRASES):
        return RouterResult(intent=Intent.OFF_TOPIC, retrieval_query=None)
    if any(p.search(question) for p in _CREATE_SITE_REGEXES):
        return RouterResult(intent=Intent.OFF_TOPIC, retrieval_query=None)
    return None


def try_turbidity_sites_list_answer(question: str) -> str | None:
    """Return canned English answer when the operator asks which sites have turbidity."""
    if any(p.search(question) for p in _WHICH_TURBIDITY_SITES_REGEXES):
        return _TURBIDITY_SITES_CANNED
    return None


def _fast_path_off_topic(question: str) -> RouterResult | None:
    """Heuristic: clearly non-monitoring questions → off_topic without LLM."""
    if _looks_in_monitoring_scope(question):
        return None
    lowered = question.lower()
    if any(k in lowered for k in _OFF_TOPIC_KEYWORDS):
        return RouterResult(intent=Intent.OFF_TOPIC, retrieval_query=None)
    if any(p.search(question) for p in _OFF_TOPIC_REGEXES):
        return RouterResult(intent=Intent.OFF_TOPIC, retrieval_query=None)
    return None


def classify_and_rewrite(
    question: str,
    *,
    site_no: str | None = None,
    llm_client: LLMClient | None = None,
    complete_fn: Callable[[list[dict[str, str]]], CompletionResult] | None = None,
) -> RouterResult:
    """
    Classify operator intent and rewrite the BM25 query in one LLM call.

    Short greetings, obvious off-topic, and some hybrid patterns may skip the LLM.
    """
    fast = _fast_path_chitchat(question)
    if fast is not None:
        return fast

    create_site = _fast_path_create_site(question)
    if create_site is not None:
        return create_site

    hybrid = _fast_path_hybrid(question)
    if hybrid is not None:
        return hybrid

    off_topic = _fast_path_off_topic(question)
    if off_topic is not None:
        return off_topic

    messages = build_router_messages(question, site_no=site_no)
    if complete_fn is not None:
        result = complete_fn(messages)
    elif llm_client is not None:
        result = llm_client.complete(messages, temperature=0.0, max_tokens=128)
    else:
        raise ValueError("classify_and_rewrite requires llm_client or complete_fn")

    return parse_router_output(result.text)

"""Intent classification and retrieval query rewriting for RAG copilot (v2).

Layered routing: deterministic fast paths first, then LLM with schema validation.
Parse failure / low confidence → clarify (ask the operator to rephrase), not a guessed path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from assistant.copilot_prompts import build_router_messages
from assistant.llm_client import CompletionResult, LLMClient

# Below this optional confidence, treat LLM classification as unreliable.
_MIN_CONFIDENCE = 0.5

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
    CLARIFY = "clarify"


@dataclass(frozen=True)
class RouterResult:
    intent: Intent
    retrieval_query: str | None = None
    confidence: float | None = None


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
        "unclear": Intent.CLARIFY,
        "unknown": Intent.CLARIFY,
        "ambiguous": Intent.CLARIFY,
        "need_clarify": Intent.CLARIFY,
        "need_clarification": Intent.CLARIFY,
    }
    return aliases.get(cleaned)


def _extract_json_object(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    # Strip common markdown fences from small models.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
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


def _parse_confidence(raw: object) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        if 0.0 <= value <= 1.0:
            return value
        return None
    if isinstance(raw, str) and raw.strip():
        try:
            value = float(raw.strip())
        except ValueError:
            return None
        if 0.0 <= value <= 1.0:
            return value
    return None


def _parse_line_format(text: str) -> RouterResult | None:
    intent_raw: str | None = None
    retrieval_query: str | None = None
    confidence: float | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("intent:"):
            intent_raw = stripped.split(":", 1)[1].strip()
        elif lower.startswith("retrieval_query:"):
            retrieval_query = stripped.split(":", 1)[1].strip()
        elif lower.startswith("confidence:"):
            confidence = _parse_confidence(stripped.split(":", 1)[1].strip())
    if not intent_raw:
        return None
    intent = _normalize_intent(intent_raw)
    if intent is None:
        return None
    return _validated_router_result(
        intent=intent,
        retrieval_query=retrieval_query or None,
        confidence=confidence,
    )


def _validated_router_result(
    *,
    intent: Intent,
    retrieval_query: str | None,
    confidence: float | None = None,
) -> RouterResult:
    """Schema/confidence gate: invalid or low-confidence → ask the operator to clarify."""
    if confidence is not None and confidence < _MIN_CONFIDENCE:
        return RouterResult(intent=Intent.CLARIFY, retrieval_query=None, confidence=confidence)

    rq = retrieval_query.strip() if isinstance(retrieval_query, str) and retrieval_query.strip() else None
    if intent in {Intent.LIVE_DATA, Intent.CHITCHAT, Intent.OFF_TOPIC, Intent.CLARIFY}:
        rq = None
    return RouterResult(intent=intent, retrieval_query=rq, confidence=confidence)


def parse_router_output(text: str) -> RouterResult:
    """Parse LLM router output (JSON preferred, line format fallback).

    Invalid / unparseable output → clarify (return a tip), not a guessed ops/live path.
    """
    payload = _extract_json_object(text)
    if payload:
        intent_raw = payload.get("intent")
        if isinstance(intent_raw, str):
            intent = _normalize_intent(intent_raw)
            if intent is not None:
                rq = payload.get("retrieval_query")
                retrieval_query = rq.strip() if isinstance(rq, str) and rq.strip() else None
                confidence = _parse_confidence(payload.get("confidence"))
                return _validated_router_result(
                    intent=intent,
                    retrieval_query=retrieval_query,
                    confidence=confidence,
                )

    line_result = _parse_line_format(text)
    if line_result is not None:
        return line_result

    return RouterResult(intent=Intent.CLARIFY, retrieval_query=None)


# Strong live-data signals only (avoid treating every "alert" mention as live).
_LIVE_DATA_KEYWORDS = (
    "recommend_alert",
    "recommend alert",
    "12h risk",
    "12 h risk",
    "12-hour risk",
    "risk forecast",
    "right now",
    "current reading",
    "current turbidity",
    "current ntu",
    "live reading",
    "state snapshot",
    "alert tier",
)

_LIVE_DATA_REGEXES = (
    re.compile(r"\b\d{8}\b"),
    re.compile(r"\b(what|show|get|fetch)\b.{0,40}\b(risk|forecast|reading|ntu|tier)\b", re.I),
    re.compile(r"\b(is|was)\s+recommend[_\s]?alert\b", re.I),
)

# Policy / docs signals for hybrid (must pair with a live signal).
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
    "per phase",
    "什么意思",
    "为什么",
    "依据",
    "政策",
)

_OPS_DOC_TOPIC_KEYWORDS = (
    "phase b",
    "phase a",
    "runbook",
    "r7a",
    "r7b",
    "r7 ",
    "recommend_alert",
    "recommend alert",
    "monitoring state",
    "alert tier",
    "turbidity operations",
    "是什么",
    "什么是",
    "文档",
)

_OPS_DOC_QUESTION_CUES = (
    "what is",
    "what's",
    "define",
    "definition",
    "explain",
    "mean",
    "meaning",
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


def _has_live_data_cue(question: str) -> bool:
    lowered = question.lower()
    if any(k in lowered for k in _LIVE_DATA_KEYWORDS):
        return True
    return any(p.search(question) for p in _LIVE_DATA_REGEXES)


def _has_policy_cue(question: str) -> bool:
    lowered = question.lower()
    return any(k in lowered for k in _HYBRID_DOC_KEYWORDS)


def _fast_path_chitchat(question: str) -> RouterResult | None:
    normalized = question.strip().lower().rstrip("!.?")
    if normalized in _CHITCHAT_FAST_PATH:
        return RouterResult(intent=Intent.CHITCHAT, retrieval_query=None)
    return None


def _fast_path_hybrid(question: str) -> RouterResult | None:
    """Require BOTH a strong live-data cue and a policy/explain cue."""
    if _has_live_data_cue(question) and _has_policy_cue(question):
        return RouterResult(
            intent=Intent.HYBRID,
            retrieval_query=_default_hybrid_retrieval_query(question),
        )
    return None


def _fast_path_live_data(question: str) -> RouterResult | None:
    """Clear live-only asks (no policy/why overlay)."""
    if not _has_live_data_cue(question):
        return None
    if _has_policy_cue(question):
        return None
    return RouterResult(intent=Intent.LIVE_DATA, retrieval_query=None)


def _fast_path_ops_doc(question: str) -> RouterResult | None:
    """Clear docs-only asks: product topic + (optional) definition cue; no live-data cues."""
    if _has_live_data_cue(question):
        return None
    lowered = question.lower()
    has_topic = any(k in lowered for k in _OPS_DOC_TOPIC_KEYWORDS)
    if not has_topic:
        return None
    # Chinese definition forms already listed as topics; English needs a question cue
    # unless the topic phrase alone is clearly a definition ask (Phase B / R7*).
    strong_alone = any(
        k in lowered
        for k in ("phase b", "phase a", "r7a", "r7b", "runbook", "是什么", "什么是")
    )
    has_question_cue = any(k in lowered for k in _OPS_DOC_QUESTION_CUES)
    if not (strong_alone or has_question_cue):
        return None

    rq = None
    if "phase b" in lowered:
        rq = "Phase B online alert recommend_alert"
    elif "phase a" in lowered:
        rq = "Phase A turbidity monitoring"
    elif "r7" in lowered:
        rq = "R7 R7a R7b recommend_alert escalation policy"
    return RouterResult(intent=Intent.OPS_DOC, retrieval_query=rq)


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
    "浊度",
    "流量",
    "告警",
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

    Order: chitchat → create-site → hybrid → live_data → ops_doc → off_topic → LLM.
    LLM parse failure or low confidence → clarify (tip), not a guessed route.
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

    live = _fast_path_live_data(question)
    if live is not None:
        return live

    ops = _fast_path_ops_doc(question)
    if ops is not None:
        return ops

    messages = build_router_messages(question, site_no=site_no)
    if complete_fn is not None:
        result = complete_fn(messages)
    elif llm_client is not None:
        result = llm_client.complete(messages, temperature=0.0, max_tokens=128)
    else:
        raise ValueError("classify_and_rewrite requires llm_client or complete_fn")

    return parse_router_output(result.text)

"""Intent routing and retrieval query rewriting for the assistant (v3, multi-label).

The router predicts independent labels — ``in_scope``, ``chitchat``, ``action_request``,
``need_tools``, ``need_docs`` — and derives the graph branch from them, so ``hybrid`` is
simply ``need_tools and need_docs`` instead of a class of its own.

Layers:
1. L0 rules (``route_rules``): high-precision fast paths; abstain when unsure.
2. L2 LLM: schema-constrained JSON labels, with the recent conversation as context.
Parse failure → clarify (ask the operator to rephrase), never a guessed path.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any, Callable, Literal

from pydantic import BaseModel, ValidationError

from assistant.copilot_prompts import (
    ACTION_REQUEST_ALERT_HINT,
    ACTION_REQUEST_ANSWER,
    ACTION_REQUEST_GENERIC_HINT,
    ACTION_REQUEST_RULE_HINT,
    ACTION_REQUEST_SITE_HINT,
    build_router_messages,
)
from assistant.llm_client import CompletionResult
from assistant.rag.route_rules import Signal, match_rules

# Router replies are a small JSON object; this caps cost and latency of the classify call.
ROUTER_MAX_TOKENS = 160

# With history, messages this short ("why?", "那上游呢") are treated as follow-ups.
_SHORT_FOLLOW_UP_CHARS = 12

RouteSource = Literal["rule", "llm", "fallback"]


class Intent(str, Enum):
    OPS_DOC = "ops_doc"
    LIVE_DATA = "live_data"
    HYBRID = "hybrid"
    CHITCHAT = "chitchat"
    OFF_TOPIC = "off_topic"
    ACTION_REQUEST = "action_request"
    CLARIFY = "clarify"


@dataclass(frozen=True)
class RouteLabels:
    """Independent routing labels; ``to_intent`` maps them onto a graph branch."""

    in_scope: bool = True
    chitchat: bool = False
    action_request: bool = False
    need_tools: bool = False
    need_docs: bool = False

    def to_intent(self) -> Intent:
        # Precedence: a write request is refused before anything else runs; scope gates the rest.
        if self.action_request:
            return Intent.ACTION_REQUEST
        if not self.in_scope:
            return Intent.OFF_TOPIC
        if self.need_tools and self.need_docs:
            return Intent.HYBRID
        if self.need_tools:
            return Intent.LIVE_DATA
        if self.need_docs:
            return Intent.OPS_DOC
        if self.chitchat:
            return Intent.CHITCHAT
        return Intent.CLARIFY


@dataclass(frozen=True)
class RouterResult:
    intent: Intent
    retrieval_query: str | None = None
    labels: RouteLabels | None = None
    source: RouteSource = "llm"
    matched_rules: tuple[str, ...] = ()

    @classmethod
    def from_labels(
        cls,
        labels: RouteLabels,
        *,
        source: RouteSource,
        retrieval_query: str | None = None,
        matched_rules: tuple[str, ...] = (),
    ) -> RouterResult:
        intent = labels.to_intent()
        rq = retrieval_query.strip() if isinstance(retrieval_query, str) else None
        if intent not in {Intent.OPS_DOC, Intent.HYBRID} or not rq:
            rq = None
        return cls(
            intent=intent,
            retrieval_query=rq,
            labels=labels,
            source=source,
            matched_rules=matched_rules,
        )

    def route_info(self) -> dict[str, Any]:
        """Routing trace for the API response and offline eval."""
        return {
            "source": self.source,
            "labels": asdict(self.labels) if self.labels is not None else None,
            "matched_rules": list(self.matched_rules),
        }


_CLARIFY_FALLBACK = RouterResult(intent=Intent.CLARIFY, labels=RouteLabels(), source="fallback")


# ---------------------------------------------------------------------------
# L2 LLM output: JSON schema (constrained decoding) + validation
# ---------------------------------------------------------------------------

ROUTER_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "route_labels",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "in_scope": {"type": "boolean"},
                "chitchat": {"type": "boolean"},
                "action_request": {"type": "boolean"},
                "need_tools": {"type": "boolean"},
                "need_docs": {"type": "boolean"},
                "retrieval_query": {"type": "string"},
            },
            "required": [
                "in_scope",
                "chitchat",
                "action_request",
                "need_tools",
                "need_docs",
                "retrieval_query",
            ],
            "additionalProperties": False,
        },
    },
}


class _RouterOutput(BaseModel):
    """Validates the LLM reply even when the provider ignored ``response_format``."""

    in_scope: bool = True
    chitchat: bool = False
    action_request: bool = False
    need_tools: bool = False
    need_docs: bool = False
    retrieval_query: str = ""


_LABEL_KEYS = frozenset(_RouterOutput.model_fields) - {"retrieval_query"}

# Single-class replies (older prompt, or a model that ignores the schema) mapped onto labels.
_INTENT_LABELS: dict[Intent, RouteLabels] = {
    Intent.OPS_DOC: RouteLabels(need_docs=True),
    Intent.LIVE_DATA: RouteLabels(need_tools=True),
    Intent.HYBRID: RouteLabels(need_tools=True, need_docs=True),
    Intent.CHITCHAT: RouteLabels(chitchat=True),
    Intent.OFF_TOPIC: RouteLabels(in_scope=False),
    Intent.ACTION_REQUEST: RouteLabels(action_request=True),
    Intent.CLARIFY: RouteLabels(),
}

_INTENT_ALIASES = {
    "ops": Intent.OPS_DOC,
    "doc": Intent.OPS_DOC,
    "documentation": Intent.OPS_DOC,
    "live": Intent.LIVE_DATA,
    "data": Intent.LIVE_DATA,
    "agent": Intent.LIVE_DATA,
    "mixed": Intent.HYBRID,
    "chat": Intent.CHITCHAT,
    "greeting": Intent.CHITCHAT,
    "offtopic": Intent.OFF_TOPIC,
    "other": Intent.OFF_TOPIC,
    "action": Intent.ACTION_REQUEST,
    "write": Intent.ACTION_REQUEST,
    "unclear": Intent.CLARIFY,
    "unknown": Intent.CLARIFY,
    "ambiguous": Intent.CLARIFY,
}


def _normalize_intent(raw: str) -> Intent | None:
    cleaned = raw.strip().lower().replace("-", "_")
    for intent in Intent:
        if cleaned == intent.value:
            return intent
    return _INTENT_ALIASES.get(cleaned)


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


def parse_router_output(text: str) -> RouterResult:
    """Parse the LLM router reply into labels; anything invalid → clarify fallback."""
    payload = _extract_json_object(text)
    if not payload:
        return _CLARIFY_FALLBACK

    if _LABEL_KEYS & payload.keys():
        try:
            out = _RouterOutput.model_validate(payload)
        except ValidationError:
            return _CLARIFY_FALLBACK
        labels = RouteLabels(**out.model_dump(exclude={"retrieval_query"}))
        return RouterResult.from_labels(labels, source="llm", retrieval_query=out.retrieval_query)

    intent_raw = payload.get("intent")
    intent = _normalize_intent(intent_raw) if isinstance(intent_raw, str) else None
    if intent is None:
        return _CLARIFY_FALLBACK
    rq = payload.get("retrieval_query")
    return RouterResult.from_labels(
        _INTENT_LABELS[intent],
        source="llm",
        retrieval_query=rq if isinstance(rq, str) else None,
    )


# ---------------------------------------------------------------------------
# L0 rules: combine signals, abstain unless the case is unambiguous
# ---------------------------------------------------------------------------

# Ordered: the first matching hint becomes the BM25 query for rule-routed doc/hybrid asks.
_RETRIEVAL_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"recommend[_\s]alert", re.I), "recommend_alert Phase B alert policy rules"),
    (re.compile(r"\bphase\s+b\b", re.I), "Phase B online alert recommend_alert"),
    (re.compile(r"\bphase\s+a\b", re.I), "Phase A turbidity monitoring"),
    (re.compile(r"\br7[ab]?\b", re.I), "R7 R7a R7b recommend_alert escalation policy"),
    (re.compile(r"alert\s+tiers?|告警等级", re.I), "alert tier NORMAL WATCH HIGH CRITICAL"),
    (re.compile(r"monitoring\s+states?|four[-\s]state|监测状态|四态", re.I), "monitoring state four-state turbidity"),
    (re.compile(r"\brunbook\b|on[-\s]call|值班|运维手册", re.I), "turbidity operations runbook on-call"),
)

_DEFAULT_HYBRID_QUERY = "recommend_alert Phase B turbidity alert policy"


def _rule_retrieval_query(question: str) -> str | None:
    for pattern, query in _RETRIEVAL_HINTS:
        if pattern.search(question):
            return query
    return None


def route_by_rules(question: str, *, has_history: bool = False) -> RouterResult | None:
    """
    L0 fast path. Precedence: chitchat → action → (defer follow-ups) → off_topic → hybrid
    → live_data → ops_doc. Returns ``None`` (abstain) when no high-precision case applies.
    """
    m = match_rules(question)

    def decided(labels: RouteLabels, retrieval_query: str | None = None) -> RouterResult:
        return RouterResult.from_labels(
            labels,
            source="rule",
            retrieval_query=retrieval_query,
            matched_rules=m.rule_names,
        )

    if m.has(Signal.CHITCHAT):
        return decided(RouteLabels(chitchat=True))
    # Deterministic write-request block: never depends on the LLM noticing it.
    if m.has(Signal.ACTION) and not m.has(Signal.HOW_TO):
        return decided(RouteLabels(action_request=True))
    # Follow-ups need the conversation to be understood — that is the LLM's job.
    if has_history and (m.has(Signal.CONTEXT_REF) or len(question.strip()) <= _SHORT_FOLLOW_UP_CHARS):
        return None
    if m.has(Signal.OFF_TOPIC) and not m.has(Signal.DOMAIN):
        return decided(RouteLabels(in_scope=False))
    if m.has(Signal.LIVE) and m.has(Signal.POLICY):
        return decided(
            RouteLabels(need_tools=True, need_docs=True),
            _rule_retrieval_query(question) or _DEFAULT_HYBRID_QUERY,
        )
    if m.has(Signal.LIVE):
        return decided(RouteLabels(need_tools=True))
    if m.has(Signal.DOC_TOPIC) and (m.has(Signal.DEFINITION) or m.has(Signal.POLICY)):
        return decided(RouteLabels(need_docs=True), _rule_retrieval_query(question))
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

CompleteFn = Callable[[list[dict[str, Any]]], CompletionResult]


def _complete_router(messages: list[dict[str, str]], complete_fn: CompleteFn) -> CompletionResult:
    """Router call; schema-constrained when the callable supports it."""
    structured = getattr(complete_fn, "structured", None)
    if structured is None:
        return complete_fn(messages)
    return structured(messages, ROUTER_RESPONSE_FORMAT)


def classify_and_rewrite(
    question: str,
    *,
    site_no: str | None = None,
    history: list[dict[str, str]] | None = None,
    complete_fn: CompleteFn | None = None,
) -> RouterResult:
    """
    Predict routing labels and the BM25 retrieval query.

    Rules first (no LLM call); otherwise one LLM call that sees the recent conversation,
    so follow-ups like "why?" are classified in context.
    """
    ruled = route_by_rules(question, has_history=bool(history))
    if ruled is not None:
        return ruled
    if complete_fn is None:
        raise ValueError("classify_and_rewrite requires complete_fn when rules abstain")
    messages = build_router_messages(question, site_no=site_no, history=history)
    return _apply_rule_constraints(question, parse_router_output(_complete_router(messages, complete_fn).text))


def _apply_rule_constraints(question: str, result: RouterResult) -> RouterResult:
    """
    Deterministic vetoes on LLM labels. Small models flag "how do I close an alert?" as a
    write request even when the prompt says otherwise; a how-to is a docs question (same
    precedence as ``route_by_rules``), so the rule layer overrides that label.
    """
    labels = result.labels
    if labels is None or not labels.action_request:
        return result
    m = match_rules(question)
    if m.has(Signal.HOW_TO):
        fixed = replace(labels, action_request=False, need_docs=True)
        return RouterResult.from_labels(
            fixed,
            source=result.source,
            retrieval_query=result.retrieval_query,
            matched_rules=m.rule_names,
        )
    return result


# ---------------------------------------------------------------------------
# Canned answers that bypass the graph branches
# ---------------------------------------------------------------------------

_ALERT_OBJECT = re.compile(r"\b(?:alerts?|alarms?)\b|告警|报警|预警", re.IGNORECASE)
_SITE_OBJECT = re.compile(r"\b(?:sites?|stations?)\b|站", re.IGNORECASE)
_RULE_OBJECT = re.compile(r"\b(?:thresholds?|tiers?|rules?|recommend_alert)\b|阈值|规则|等级", re.IGNORECASE)


def action_request_answer(question: str) -> str:
    """Refuse a write request and point the operator to the page that can do it."""
    if _RULE_OBJECT.search(question):
        hint = ACTION_REQUEST_RULE_HINT
    elif _ALERT_OBJECT.search(question):
        hint = ACTION_REQUEST_ALERT_HINT
    elif _SITE_OBJECT.search(question):
        hint = ACTION_REQUEST_SITE_HINT
    else:
        hint = ACTION_REQUEST_GENERIC_HINT
    return ACTION_REQUEST_ANSWER.format(hint=hint)


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


def try_turbidity_sites_list_answer(question: str) -> str | None:
    """Return canned English answer when the operator asks which sites have turbidity."""
    if any(p.search(question) for p in _WHICH_TURBIDITY_SITES_REGEXES):
        return _TURBIDITY_SITES_CANNED
    return None

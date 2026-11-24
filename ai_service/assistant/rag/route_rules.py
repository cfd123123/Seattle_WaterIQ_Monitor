"""Declarative L0 routing rules for the assistant intent router.

Rules emit *signals*, never a final intent. ``route_by_rules`` in ``query_router``
combines signals with a fixed precedence and abstains (returns ``None``) whenever
the combination is not a high-precision case, leaving it to the LLM router.

Matching discipline:
- English phrases are wrapped in ``\\b`` word boundaries, so "mean" never hits "meantime"
  and "now" never hits "know".
- Chinese has no word boundaries; Chinese rules list whole terms only.
- Every rule has a stable ``name``; matched names are returned for logging and eval,
  so a misroute can be traced to the exact rule that fired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable


class Signal(str, Enum):
    CHITCHAT = "chitchat"  # whole message is a greeting / thanks
    ACTION = "action"  # imperative write request (create / close / modify ...)
    HOW_TO = "how_to"  # asks HOW to do something — a docs question, not a request
    OFF_TOPIC = "off_topic"  # clearly unrelated subject
    DOMAIN = "domain"  # monitoring vocabulary; guards against off_topic false positives
    LIVE = "live"  # needs current or site-specific data
    POLICY = "policy"  # why / rule / policy explanation
    DEFINITION = "definition"  # what is / define / meaning
    DOC_TOPIC = "doc_topic"  # named product concept covered by the ops docs
    CONTEXT_REF = "context_ref"  # only makes sense with earlier turns (it / that / what about ...)


@dataclass(frozen=True)
class Rule:
    name: str
    signal: Signal
    pattern: re.Pattern[str]
    accept: Callable[[re.Match[str]], bool] | None = None

    def matches(self, text: str) -> bool:
        for match in self.pattern.finditer(text):
            if self.accept is None or self.accept(match):
                return True
        return False


@dataclass(frozen=True)
class RuleMatch:
    signals: frozenset[Signal]
    rule_names: tuple[str, ...]

    def has(self, signal: Signal) -> bool:
        return signal in self.signals


def _en(*fragments: str) -> re.Pattern[str]:
    """Alternation of English regex fragments, bounded by word boundaries."""
    return re.compile(r"\b(?:" + "|".join(fragments) + r")\b", re.IGNORECASE)


def _zh(*terms: str) -> re.Pattern[str]:
    return re.compile("|".join(terms))


def _is_site_number(match: re.Match[str]) -> bool:
    """8-digit USGS site number, but not a YYYYMMDD date such as 20260517."""
    text = match.group(0)
    try:
        parsed = datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return True
    return not 1900 <= parsed.year <= 2100


_SITE_NO = re.compile(r"(?<!\d)\d{8}(?!\d)")

_WRITE_VERBS_EN = (
    r"create|add|register|delete|remove|update(?!\s+me\b)|modify|edit|change|set|reset|close|"
    r"acknowledge|ack|dismiss|resolve|disable|enable|mute|silence|override|lower|raise"
)
_WRITE_OBJECTS_EN = r"sites?|stations?|alerts?|thresholds?|tiers?|recommend_alert|rules?"
_REQUEST_PREFIX_EN = (
    r"(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|help\s+me\s+|"
    r"i\s+(?:want|need)\s+to\s+|go\s+ahead\s+and\s+)?"
)

RULES: tuple[Rule, ...] = (
    # --- chitchat: the whole message must be a greeting, not merely start with one ---
    Rule(
        "chitchat.greeting_en",
        Signal.CHITCHAT,
        re.compile(
            r"^\s*(?:hi|hello|hey|thanks|thank\s+you|good\s+(?:morning|afternoon|evening))\s*[!.?]*\s*$",
            re.IGNORECASE,
        ),
    ),
    Rule("chitchat.greeting_zh", Signal.CHITCHAT, re.compile(r"^\s*(?:你好|您好|嗨|谢谢|多谢)\s*[!！。?？]*\s*$")),
    # --- write requests: imperative verb + business object, verb at the start of the ask ---
    Rule(
        "action.imperative_en",
        Signal.ACTION,
        re.compile(
            rf"^\s*{_REQUEST_PREFIX_EN}(?:{_WRITE_VERBS_EN})\b.{{0,40}}?\b(?:{_WRITE_OBJECTS_EN})\b",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "action.imperative_zh",
        Signal.ACTION,
        _zh(
            r"(?:新建|新增|添加|创建|注册|删除|移除|修改|更改|编辑|关闭|关掉|消除|设置|调整|调低|调高|屏蔽|禁用|启用)"
            r".{0,6}?(?:站点|监测站|站|告警|报警|预警|阈值|规则|等级)"
        ),
    ),
    # 把-construction puts the object before the verb: 把这个告警关掉 / 把阈值调高.
    Rule(
        "action.ba_zh",
        Signal.ACTION,
        _zh(
            r"把.{0,8}?(?:站点|站|告警|报警|预警|阈值|规则|等级).{0,4}?"
            r"(?:关掉|关闭|删除|删掉|调高|调低|修改|改成|改为|屏蔽|禁用)"
        ),
    ),
    Rule(
        "how_to.en",
        Signal.HOW_TO,
        _en(
            r"how\s+(?:do|can|should|would)\s+(?:i|we|you|operators?)",
            r"how\s+to",
            r"what\s+happens\s+(?:if|when)",
            r"steps\s+to",
        ),
    ),
    Rule("how_to.zh", Signal.HOW_TO, _zh("怎么", "怎样", "如何", "步骤", "流程")),
    # --- off topic ---
    Rule(
        "off_topic.sports_en",
        Signal.OFF_TOPIC,
        _en(
            r"world\s+cup", r"super\s+bowl", "nba", "nfl", "mlb", "olympics", "soccer",
            r"champions\s+league", "basketball", r"who\s+won", r"football\s+(?:game|match|score)",
        ),
    ),
    Rule(
        "off_topic.finance_en",
        Signal.OFF_TOPIC,
        _en(r"stock\s+(?:price|market)", "nasdaq", r"dow\s+jones", r"share\s+price", "bitcoin", "crypto"),
    ),
    Rule(
        "off_topic.weather_en",
        Signal.OFF_TOPIC,
        _en(
            r"weather\s+(?:forecast|today|tomorrow)", r"will\s+it\s+rain",
            r"what(?:'s|\s+is)\s+the\s+weather", r"temperature\s+tomorrow",
        ),
    ),
    Rule(
        "off_topic.creative_en",
        Signal.OFF_TOPIC,
        _en(
            r"write\s+(?:me\s+)?a\s+(?:poem|story|song)", r"tell\s+me\s+a\s+joke", r"knock\s+knock",
            r"recipe\s+for", r"how\s+to\s+(?:cook|bake)",
        ),
    ),
    Rule(
        "off_topic.general_en",
        Signal.OFF_TOPIC,
        _en(r"coding\s+tutorial", r"learn\s+(?:javascript|python)", r"(?:latest|breaking)\s+news"),
    ),
    Rule(
        "off_topic.zh",
        Signal.OFF_TOPIC,
        _zh("世界杯", "股票", "股价", "比特币", "讲个笑话", "写一首诗", "写首诗", "菜谱", "做饭", "新闻", "天气预报", "明天天气", "会下雨吗"),
    ),
    # --- domain vocabulary (scope guard only; never routes on its own) ---
    Rule(
        "domain.en",
        Signal.DOMAIN,
        _en(
            "turbidity", "flow", "discharge", "usgs", "sites?", "stations?", "gauges?", "gages?",
            "63680", "00060", r"phase\s+[ab]", "recommend_alert", r"recommend\s+alert", "r7[ab]?",
            "alerts?", "alarms?", "monitoring", "runbook", "ntu", "puget", "forecasts?", "wqi",
            r"water\s+quality", "rivers?", "streams?", "sensors?",
        ),
    ),
    Rule("domain.zh", Signal.DOMAIN, _zh("浊度", "流量", "告警", "报警", "预警", "站点", "监测", "水质", "河", "传感器", "预测")),
    Rule("domain.site_no", Signal.DOMAIN, _SITE_NO, accept=_is_site_number),
    # --- live data ---
    Rule("live.site_no", Signal.LIVE, _SITE_NO, accept=_is_site_number),
    Rule(
        "live.temporal_en",
        Signal.LIVE,
        _en(
            r"right\s+now", "now", "current(?:ly)?", "latest", "today", r"at\s+the\s+moment",
            "live", r"real[-\s]?time", r"this\s+(?:morning|hour)",
        ),
    ),
    Rule(
        "live.data_request_en",
        Signal.LIVE,
        re.compile(
            r"\b(?:show|get|fetch|pull|give\s+me)\b.{0,40}?"
            r"\b(?:readings?|forecasts?|risk|ntu|tiers?|snapshot|series|history|data)\b",
            re.IGNORECASE,
        ),
    ),
    Rule("live.risk_en", Signal.LIVE, _en(r"12\s*-?\s*h(?:our)?\s+risk", r"risk\s+forecast", r"state\s+snapshot")),
    Rule("live.zh", Signal.LIVE, _zh("现在", "当前", "目前", "实时", "最新", "今天", "此刻")),
    # --- docs: policy / definition / named topics ---
    Rule(
        "policy.en",
        Signal.POLICY,
        _en(
            "why", "explain", "explanation", "polic(?:y|ies)", "rules?", "reasons?", r"according\s+to",
            r"per\s+(?:the\s+)?(?:policy|phase\s+[ab]|runbook|docs?)", "runbook", "documentation",
        ),
    ),
    Rule("policy.zh", Signal.POLICY, _zh("为什么", "原因", "依据", "规则", "政策", "根据", "文档", "解释")),
    Rule(
        "definition.en",
        Signal.DEFINITION,
        _en(r"what\s+(?:is|are|does)", r"what's", "define", "definition", "meaning", "means?", r"stands?\s+for"),
    ),
    Rule("definition.zh", Signal.DEFINITION, _zh("是什么", "什么是", "什么意思", "含义", "定义", "指什么")),
    Rule(
        "doc_topic.en",
        Signal.DOC_TOPIC,
        _en(
            r"phase\s+[ab]", "recommend_alert", r"recommend\s+alert", "r7[ab]?", "runbook",
            r"alert\s+tiers?", r"monitoring\s+states?", r"four[-\s]state", r"persistence\s+(?:rule|alert)",
            r"turbidity\s+operations", r"on[-\s]call",
        ),
    ),
    Rule("doc_topic.zh", Signal.DOC_TOPIC, _zh("告警等级", "监测状态", "四态", "值班", "运维手册")),
    # --- context dependence (used only when there is history) ---
    Rule(
        "context_ref.en",
        Signal.CONTEXT_REF,
        re.compile(
            r"^\s*(?:and|so|then|also|but|what\s+about|how\s+about)\b"
            r"|\b(?:it|that|this|those|these|them|the\s+other(?:\s+one)?|same)\b",
            re.IGNORECASE,
        ),
    ),
    Rule("context_ref.zh", Signal.CONTEXT_REF, _zh("那", "这个", "它", "另一个", "上一个", "刚才", "呢")),
)


def extract_site_numbers(text: str) -> set[str]:
    """8-digit USGS site numbers mentioned in the text (YYYYMMDD dates excluded)."""
    return {m.group(0) for m in _SITE_NO.finditer(text) if _is_site_number(m)}


def match_rules(text: str, rules: tuple[Rule, ...] = RULES) -> RuleMatch:
    """Evaluate every rule; return the set of signals and the names of rules that fired."""
    names = tuple(rule.name for rule in rules if rule.matches(text))
    signals = frozenset(rule.signal for rule in rules if rule.name in names)
    return RuleMatch(signals=signals, rule_names=names)

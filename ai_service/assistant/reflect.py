"""Post-answer reflection (rule-first, optional LLM) for tool/RAG/hybrid paths."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from assistant.llm_client import CompletionResult

ReflectAction = Literal["pass", "revise_answer", "clarify"]

_FORBIDDEN_CLAIM_PATTERNS = (
    re.compile(r"\b(changed|updated|set|modified|overwrote)\b.{0,40}\brecommend[_\s]?alert\b", re.I),
    re.compile(r"\brecommend[_\s]?alert\b.{0,40}\b(changed|updated|set|to true|to false)\b", re.I),
    re.compile(r"\b(i have|i've|we have)\s+(changed|updated|set)\b.{0,30}\balert\b", re.I),
    re.compile(r"(已修改|已更改|已经改|把).{0,10}(告警|recommend)", re.I),
)

# Numbers that often appear in prose without being tool facts (years, horizons in the question).
_IGNORE_NUMBERS = frozenset({"12", "24", "36", "48", "7", "30", "90", "168", "1", "2", "3", "4", "5", "6", "8", "10"})

_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)(?![A-Za-z0-9_])")

# Alert-tier vocabulary emitted by turbidity state monitoring and the 12h risk forecast.
_TIER_WORDS = frozenset({"NORMAL", "WATCH", "HIGH", "CRITICAL", "SENSOR_GAP", "DATA_STALE", "UNKNOWN"})
_TIER_ALT = "|".join(sorted(_TIER_WORDS))

# Policy prose ("recommend_alert is true when the tier is HIGH") states a rule, not a reading:
# sentences with a conditional are skipped before claims are extracted. Trade-off: a real
# reading inside a conditional sentence goes unchecked.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？;；])\s*|\n+")
_CONDITIONAL = re.compile(r"\b(?:when|whenever|if|unless|once)\b|如果|假如|当.{0,12}时", re.I)

# A tier claim binds a tier word to a tier field: "max_tier_forecast is HIGH", "tier: WATCH",
# "HIGH tier". Plural "tiers range from NORMAL to CRITICAL" is not a claim.
_TIER_CLAIM_PATTERNS = (
    re.compile(
        r"\b(?:max_tier_forecast|tier_at_t|alert_tier|tier)\b"
        r"(?:\s+(?:is|was|of|at|now|currently|forecast|reached|reaches|will\s+be))*"
        rf"\s*[:=]?\s*[*`'\"]*({_TIER_ALT})\b",
        re.I,
    ),
    re.compile(rf"\b({_TIER_ALT})\s+(?:alert\s+)?tier\b", re.I),
)

# Negative forms are matched (and removed) first so "no alert is recommended" never reads as true.
_ALERT_FALSE_PATTERNS = (
    re.compile(r"\brecommend[_\s]?alert\b\W{0,3}(?:is|was|=|:)?\s*[*`'\"]*false\b", re.I),
    re.compile(r"\bno\s+alert\s+(?:is\s+|was\s+)?recommended\b", re.I),
    re.compile(r"\balert\s+(?:is|was)\s+not\s+recommended\b", re.I),
    re.compile(r"\b(?:does|did)\s+not\s+recommend\s+(?:an?\s+)?alert\b", re.I),
    re.compile(r"\bnot\s+recommending\s+(?:an?\s+)?alert\b", re.I),
    re.compile(r"不建议告警|无需告警|不需要告警"),
)
_ALERT_TRUE_PATTERNS = (
    re.compile(r"\brecommend[_\s]?alert\b\W{0,3}(?:is|was|=|:)?\s*[*`'\"]*true\b", re.I),
    re.compile(r"\balert\s+(?:is|was)\s+recommended\b", re.I),
    re.compile(r"\brecommends?\s+(?:an?\s+)?alert\b", re.I),
    re.compile(r"\balert\s+(?:should|will|must)\s+be\s+(?:raised|issued|sent|triggered|recommended)\b", re.I),
    re.compile(r"\b(?:raise|issue|trigger)\s+an?\s+alert\b", re.I),
    re.compile(r"建议告警|需要告警"),
)

# A positive alert phrase negated earlier in the same clause ("there is no need to recommend an
# alert", "no alert should be raised") asserts false. Commas end the window, so "not low, so an
# alert is recommended" stays positive.
_NEGATION_BEFORE = re.compile(r"(?:\b(?:no|not|never|without|nor)\b|n't|不|无需|无须|没有)[^.,;!?。，；]{0,25}$", re.I)

# Bare upper-case tier word ("It's at HIGH right now") — tools-only answers, where tier words
# are readings. Skipped after comparison words: "from NORMAL to CRITICAL", "not HIGH", "reach WATCH".
_BARE_TIER = re.compile(rf"\b({_TIER_ALT})\b")
_TIER_NOT_CLAIMED_AFTER = re.compile(
    r"\b(?:not|below|above|than|from|to|reach(?:es|ed)?|exceeds?|exceeded|between|or|nor)\s*$",
    re.I,
)

REFLECT_SYSTEM_PROMPT = """\
You are a strict verifier for a read-only water-quality assistant.
Given the draft answer and tool JSON (may be empty for docs-only answers), reply with ONLY JSON:
{"ok": true|false, "issues": ["..."], "action": "pass"|"revise_answer"|"clarify"}

Fail when:
- The answer invents numeric readings/tiers/alert flags not present in tool JSON
- The answer claims it changed alerts or decision fields
- Live-data questions were answered without usable tool results

Prefer action revise_answer for wording fixes; clarify when a site_no or target is missing.
"""


@dataclass
class ReflectResult:
    ok: bool
    action: ReflectAction = "pass"
    issues: list[str] = field(default_factory=list)


def _tool_payloads_from_audit(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for entry in tool_calls:
        if not entry.get("ok"):
            continue
        preview = entry.get("result_preview")
        if isinstance(preview, dict):
            payloads.append(preview)
        data = entry.get("data")
        if isinstance(data, dict):
            payloads.append(data)
    return payloads


def _flatten_numbers(obj: Any, out: set[str]) -> None:
    if obj is None or isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        if isinstance(obj, float) and obj.is_integer():
            out.add(str(int(obj)))
        out.add(str(obj))
        # Also keep a short rounded form for floats like 12.50 → 12.5
        if isinstance(obj, float):
            out.add(f"{obj:.4f}".rstrip("0").rstrip("."))
        return
    if isinstance(obj, str):
        for match in _NUMBER_RE.findall(obj):
            out.add(match)
            if "." in match:
                out.add(match.rstrip("0").rstrip("."))
        return
    if isinstance(obj, dict):
        for value in obj.values():
            _flatten_numbers(value, out)
        return
    if isinstance(obj, (list, tuple)):
        for value in obj:
            _flatten_numbers(value, out)


def _numbers_in_text(text: str) -> set[str]:
    found: set[str] = set()
    for match in _NUMBER_RE.findall(text):
        found.add(match)
        if "." in match:
            found.add(match.rstrip("0").rstrip("."))
    return found


def _assertive_text(text: str) -> str:
    return " ".join(s for s in _SENTENCE_SPLIT.split(text) if s and not _CONDITIONAL.search(s))


def _claimed_tiers(text: str, *, bare: bool = False) -> set[str]:
    assertive = _assertive_text(text)
    claims = {m.upper() for pattern in _TIER_CLAIM_PATTERNS for m in pattern.findall(assertive)}
    if bare:
        claims |= {
            m.group(1)
            for m in _BARE_TIER.finditer(assertive)
            if not _TIER_NOT_CLAIMED_AFTER.search(assertive[: m.start()])
        }
    return claims


def _claimed_alert(text: str) -> set[bool]:
    """Polarities the answer asserts for recommend_alert (empty when it makes no claim)."""
    claims: set[bool] = set()
    remaining = _assertive_text(text)
    for pattern in _ALERT_FALSE_PATTERNS:
        if pattern.search(remaining):
            claims.add(False)
            remaining = pattern.sub(" ", remaining)
    for pattern in _ALERT_TRUE_PATTERNS:
        for match in pattern.finditer(remaining):
            claims.add(not _NEGATION_BEFORE.search(remaining[: match.start()]))
    return claims


def _tool_tiers(obj: Any, out: set[str]) -> None:
    if isinstance(obj, str):
        if obj.upper() in _TIER_WORDS:
            out.add(obj.upper())
    elif isinstance(obj, dict):
        for value in obj.values():
            _tool_tiers(value, out)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _tool_tiers(value, out)


def _decision_field_issues(text: str, payloads: list[dict[str, Any]], *, strict: bool) -> list[str]:
    """
    Check categorical decision claims (tier, recommend_alert) against tool JSON.

    Number checks alone miss the most dangerous error: "tier HIGH, alert recommended"
    when the API said NORMAL / false. ``strict`` (tools-only answers) also flags claims the
    tools never returned; hybrid answers may cite tiers from docs, so they are only
    checked when the tools did return that field.
    """
    issues: list[str] = []
    tool_tiers: set[str] = set()
    _tool_tiers(payloads, tool_tiers)
    if strict or tool_tiers:
        claimed = _claimed_tiers(text, bare=strict)
        issues += [f"ungrounded_tier:{tier}" for tier in sorted(claimed - tool_tiers)]

    tool_alert = {p["recommend_alert"] for p in payloads if isinstance(p.get("recommend_alert"), bool)}
    if strict or tool_alert:
        issues += [
            f"ungrounded_recommend_alert:{str(claim).lower()}"
            for claim in sorted(_claimed_alert(text) - tool_alert)
        ]
    return issues


def reflect_rules(
    *,
    answer: str,
    mode: str,
    tool_calls: list[dict[str, Any]] | None,
    site_no: str | None = None,
) -> ReflectResult:
    """Deterministic checks — primary reflection path."""
    issues: list[str] = []
    text = (answer or "").strip()
    if not text:
        return ReflectResult(ok=False, action="revise_answer", issues=["empty_answer"])

    audit = tool_calls or []
    ok_tools = [e for e in audit if e.get("ok")]
    mode_l = (mode or "").lower()

    if mode_l in {"tools", "agent_lite", "hybrid"}:
        payloads = _tool_payloads_from_audit(audit)
        allowed: set[str] = set()
        _flatten_numbers(payloads, allowed)
        if site_no:
            allowed.add(str(site_no).strip())
        allowed |= _IGNORE_NUMBERS

        answer_nums = _numbers_in_text(text) - allowed

        if not ok_tools and mode_l in {"tools", "agent_lite"}:
            # Only fail hard when the answer asserts facts (numbers, tiers, alert flags) without tools.
            asserts_facts = answer_nums or _claimed_tiers(text, bare=True) or _claimed_alert(text)
            if asserts_facts or any(p.search(text) for p in _FORBIDDEN_CLAIM_PATTERNS):
                issues.append("missing_tool_results")
        elif payloads:
            for num in answer_nums:
                if len(num) == 8 and num.isdigit():
                    issues.append(f"ungrounded_site:{num}")
                    continue
                if "." in num or len(num) >= 2:
                    issues.append(f"ungrounded_number:{num}")
                    break
            issues += _decision_field_issues(text, payloads, strict=mode_l != "hybrid")

    if any(p.search(text) for p in _FORBIDDEN_CLAIM_PATTERNS):
        if "forbidden_write_claim" not in issues:
            issues.append("forbidden_write_claim")

    if issues:
        action: ReflectAction = "clarify" if "missing_tool_results" in issues else "revise_answer"
        if "forbidden_write_claim" in issues:
            action = "revise_answer"
        return ReflectResult(ok=False, action=action, issues=issues)
    return ReflectResult(ok=True, action="pass", issues=[])


def _parse_reflect_llm(text: str) -> ReflectResult | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    ok = bool(payload.get("ok"))
    raw_action = str(payload.get("action") or ("pass" if ok else "revise_answer")).strip().lower()
    action: ReflectAction
    if raw_action in {"pass", "revise_answer", "clarify"}:
        action = raw_action  # type: ignore[assignment]
    else:
        action = "pass" if ok else "revise_answer"
    issues_raw = payload.get("issues") or []
    issues = [str(x) for x in issues_raw] if isinstance(issues_raw, list) else []
    return ReflectResult(ok=ok, action=action, issues=issues)


def reflect_with_llm(
    *,
    answer: str,
    mode: str,
    tool_calls: list[dict[str, Any]] | None,
    complete_fn: Callable[[list[dict[str, Any]]], CompletionResult],
) -> ReflectResult:
    payloads = _tool_payloads_from_audit(tool_calls or [])
    user = (
        f"mode: {mode}\n"
        f"draft_answer:\n{answer}\n\n"
        f"tool_json:\n{json.dumps(payloads, default=str)[:4000]}\n"
    )
    result = complete_fn(
        [
            {"role": "system", "content": REFLECT_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
    )
    parsed = _parse_reflect_llm(result.text)
    if parsed is None:
        return ReflectResult(ok=True, action="pass", issues=["reflect_llm_parse_failed"])
    return parsed


def run_reflection(
    *,
    answer: str,
    mode: str,
    tool_calls: list[dict[str, Any]] | None,
    site_no: str | None = None,
    use_llm: bool = False,
    complete_fn: Callable[[list[dict[str, Any]]], CompletionResult] | None = None,
) -> ReflectResult:
    """Rule checks first; optional LLM only if rules passed (catches soft issues)."""
    rules = reflect_rules(answer=answer, mode=mode, tool_calls=tool_calls, site_no=site_no)
    if not rules.ok:
        return rules
    if use_llm and complete_fn is not None and mode in {"tools", "agent_lite", "hybrid", "rag"}:
        return reflect_with_llm(
            answer=answer,
            mode=mode,
            tool_calls=tool_calls,
            complete_fn=complete_fn,
        )
    return rules


REVISE_SYSTEM_PROMPT = """\
You revise an assistant draft for a read-only water-quality monitoring product.
Rules:
- English only.
- Every numeric value, tier, and recommend_alert flag MUST match the tool JSON exactly.
- Never claim you changed alerts or decision fields.
- If tool JSON is missing required facts, say what is missing and ask for a site number if needed.
- Keep the answer concise (2–4 sentences).
"""


def revise_answer(
    *,
    message: str,
    draft_answer: str,
    issues: list[str],
    tool_calls: list[dict[str, Any]] | None,
    complete_fn: Callable[[list[dict[str, Any]]], CompletionResult],
) -> str:
    payloads = _tool_payloads_from_audit(tool_calls or [])
    user = (
        f"User question: {message}\n"
        f"Issues found: {', '.join(issues) or 'ungrounded_or_unsafe'}\n"
        f"Draft answer:\n{draft_answer}\n\n"
        f"Tool JSON:\n{json.dumps(payloads, default=str)[:4000]}\n"
    )
    result = complete_fn(
        [
            {"role": "system", "content": REVISE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
    )
    text = (result.text or "").strip()
    return text or draft_answer


# Decision and reading fields rendered verbatim when the LLM wording cannot be verified.
_FACT_KEYS = (
    "recommend_alert",
    "max_tier_forecast",
    "tier_at_t",
    "alert_tier",
    "state",
    "parameter_cd",
    "latest_value",
    "mean_value",
    "horizon_hours",
    "forecast_available",
)

FACTS_FALLBACK_INTRO = (
    "I couldn't verify my written summary against the data, "
    "so here are the values returned by the monitoring API:"
)


def _format_fact(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def render_tool_facts(tool_calls: list[dict[str, Any]] | None) -> str | None:
    """
    Deterministic fallback answer: tool values rendered by code, no LLM wording.

    Used when reflection still fails after a revise — the operator gets correct data
    instead of a generic "please rephrase". Returns ``None`` when no tool succeeded.
    """
    lines: list[str] = []
    for entry in tool_calls or []:
        preview = entry.get("result_preview")
        if not entry.get("ok") or not isinstance(preview, dict):
            continue
        fields = [f"{key}={_format_fact(preview[key])}" for key in _FACT_KEYS if key in preview]
        if not fields:
            continue
        site = preview.get("site_no")
        label = f"Site {site}" if site else "Result"
        lines.append(f"- {label} ({entry.get('name', 'tool')}): " + ", ".join(fields))
    if not lines:
        return None
    return FACTS_FALLBACK_INTRO + "\n" + "\n".join(lines)

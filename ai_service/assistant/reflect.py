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

_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])(\d+\.?\d*)(?![A-Za-z0-9_])")

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
            # Only fail hard when the answer asserts numeric facts without tools.
            if answer_nums or any(p.search(text) for p in _FORBIDDEN_CLAIM_PATTERNS):
                issues.append("missing_tool_results")
        elif payloads:
            for num in answer_nums:
                if len(num) == 8 and num.isdigit():
                    issues.append(f"ungrounded_site:{num}")
                    continue
                if "." in num or len(num) >= 2:
                    issues.append(f"ungrounded_number:{num}")
                    break

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

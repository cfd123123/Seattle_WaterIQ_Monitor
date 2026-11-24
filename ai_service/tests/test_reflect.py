"""Tests for post-answer reflection."""

from __future__ import annotations

import pytest

from assistant.reflect import reflect_rules, run_reflection


def test_reflect_passes_grounded_tool_answer() -> None:
    audit = [
        {
            "ok": True,
            "name": "get_turbidity_risk_forecast_12h",
            "result_preview": {
                "site_no": "12117500",
                "recommend_alert": True,
                "max_tier_forecast": "HIGH",
            },
        }
    ]
    result = reflect_rules(
        answer=(
            "For site 12117500, recommend_alert is true and max_tier_forecast is HIGH "
            "over the next 12 hours."
        ),
        mode="tools",
        tool_calls=audit,
        site_no="12117500",
    )
    assert result.ok is True
    assert result.action == "pass"


def test_reflect_flags_ungrounded_number() -> None:
    audit = [
        {
            "ok": True,
            "name": "get_turbidity_risk_forecast_12h",
            "result_preview": {"site_no": "12117500", "recommend_alert": False},
        }
    ]
    result = reflect_rules(
        answer="Turbidity is 99.7 NTU right now for this site.",
        mode="tools",
        tool_calls=audit,
        site_no="12117500",
    )
    assert result.ok is False
    assert any(i.startswith("ungrounded_number") for i in result.issues)


def test_reflect_flags_forbidden_write_claim() -> None:
    result = reflect_rules(
        answer="I have changed recommend_alert to false for you.",
        mode="tools",
        tool_calls=[
            {
                "ok": True,
                "result_preview": {"recommend_alert": True, "site_no": "12117500"},
            }
        ],
        site_no="12117500",
    )
    assert result.ok is False
    assert "forbidden_write_claim" in result.issues


def test_reflect_tools_without_results_clarify() -> None:
    result = reflect_rules(
        answer="Turbidity will reach 42.5 NTU based on my estimate.",
        mode="tools",
        tool_calls=[],
        site_no=None,
    )
    assert result.ok is False
    assert "missing_tool_results" in result.issues
    assert result.action == "clarify"


def test_reflect_tools_without_results_ok_if_no_numeric_claims() -> None:
    result = reflect_rules(
        answer="Mock.",
        mode="tools",
        tool_calls=[],
        site_no=None,
    )
    assert result.ok is True
    assert result.action == "pass"


def test_run_reflection_rules_only_by_default() -> None:
    result = run_reflection(
        answer="Hello from docs.",
        mode="rag",
        tool_calls=[],
        use_llm=False,
    )
    assert result.ok is True


_RISK_AUDIT = [
    {
        "ok": True,
        "name": "get_turbidity_risk_forecast_12h",
        "result_preview": {
            "site_no": "12117500",
            "recommend_alert": False,
            "max_tier_forecast": "NORMAL",
            "tier_at_t": "NORMAL",
        },
    }
]


def _check(answer: str, *, mode: str = "tools", audit=_RISK_AUDIT):
    return reflect_rules(answer=answer, mode=mode, tool_calls=audit, site_no="12117500")


def test_reflect_flags_contradicted_tier_and_alert() -> None:
    result = _check("Turbidity at 12117500 is tier HIGH, an alert IS recommended.")
    assert result.ok is False
    assert result.action == "revise_answer"
    assert "ungrounded_tier:HIGH" in result.issues
    assert "ungrounded_recommend_alert:true" in result.issues


def test_reflect_passes_matching_negative_alert_claim() -> None:
    result = _check("Site 12117500 is at tier NORMAL and no alert is recommended.")
    assert result.ok is True


def test_reflect_flags_recommend_alert_field_contradiction() -> None:
    result = _check("For 12117500, recommend_alert: true and max_tier_forecast is NORMAL.")
    assert "ungrounded_recommend_alert:true" in result.issues
    assert not any(i.startswith("ungrounded_tier") for i in result.issues)


def test_reflect_ignores_policy_prose_in_hybrid() -> None:
    result = _check(
        "Site 12117500 is NORMAL with no alert recommended. Per Phase B, recommend_alert is true "
        "when the tier is HIGH, and tiers range from NORMAL to CRITICAL.",
        mode="hybrid",
    )
    assert result.ok is True, result.issues


def test_reflect_hybrid_skips_tier_check_when_tools_return_no_tier() -> None:
    audit = [{"ok": True, "name": "get_forecast_series", "result_preview": {"site_no": "12117500", "parameter_cd": "63680"}}]
    result = _check("The HIGH tier means sustained turbidity above the watch level.", mode="hybrid", audit=audit)
    assert result.ok is True, result.issues


def test_reflect_tier_claim_without_tools_is_missing_results() -> None:
    result = reflect_rules(answer="The alert tier is CRITICAL right now.", mode="tools", tool_calls=[])
    assert "missing_tool_results" in result.issues
    assert result.action == "clarify"


def test_render_tool_facts_uses_tool_values_verbatim() -> None:
    from assistant.reflect import FACTS_FALLBACK_INTRO, render_tool_facts

    facts = render_tool_facts(_RISK_AUDIT)
    assert facts is not None and facts.startswith(FACTS_FALLBACK_INTRO)
    assert "Site 12117500" in facts
    assert "recommend_alert=false" in facts
    assert "max_tier_forecast=NORMAL" in facts
    assert render_tool_facts([{"ok": False, "name": "x"}]) is None
    assert render_tool_facts([]) is None


@pytest.mark.parametrize(
    "answer",
    [
        "It's at HIGH right now.",
        "An alert should be raised for 12117500.",
        "Turbidity is not low, so an alert is recommended.",
        "浊度等级为 HIGH，建议告警。",
    ],
)
def test_reflect_flags_contradictions_in_loose_wording(answer: str) -> None:
    result = _check(answer)
    assert result.ok is False
    assert any(i.startswith(("ungrounded_tier", "ungrounded_recommend_alert")) for i in result.issues)


@pytest.mark.parametrize(
    "answer",
    [
        "Turbidity is normal at 12117500.",
        "Tier NORMAL. There is no need to recommend an alert.",
        "No alert should be raised for 12117500; tier NORMAL.",
        "Tiers go from NORMAL to CRITICAL; 12117500 is NORMAL.",
        "No alert is recommended; the tier would need to reach WATCH.",
    ],
)
def test_reflect_passes_consistent_answers(answer: str) -> None:
    result = _check(answer)
    assert result.ok is True, result.issues

"""Tests for post-answer reflection."""

from __future__ import annotations

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

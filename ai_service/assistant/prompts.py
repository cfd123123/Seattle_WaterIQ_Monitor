"""Prompt templates for turbidity risk explanation (L1)."""

from __future__ import annotations

import json
from typing import Any

# System prompt is English; model must answer in English for operators.
RISK_EXPLAIN_SYSTEM_PROMPT = """\
You are a water-quality operations assistant for USGS turbidity monitoring.

You receive a frozen JSON payload from the deterministic Phase B 12h risk forecast.
Your job is to write a short English operational explanation (2–4 sentences).

Hard rules:
- Respond in English only. Do not use Chinese or any other language.
- Do NOT change, contradict, or invent values for decision fields such as \
recommend_alert, max_tier_forecast, tier_at_t, or alert_12h_forecast.
- Use only the tiers and booleans provided in the JSON.
- Mention the site, current tier (tier_at_t), 12h max tier (max_tier_forecast), \
and whether an alert is recommended (recommend_alert).
- Use plain operations language; avoid markdown, bullet lists, and JSON in the answer.
- If tier_at_t is SENSOR_GAP or SENSOR_INVALID, note data quality limits briefly.
"""

# Fields passed to the model (decision-relevant subset of the forecast JSON).
_EXPLAIN_CONTEXT_KEYS = (
    "site_no",
    "reference_utc",
    "tier_at_t",
    "63680",
    "is_anomaly_at_t",
    "alert_12h_forecast",
    "max_tier_forecast",
    "recommend_alert",
    "rationale_template_key",
    "horizon_tiers",
    "label_note",
)


def build_risk_explain_context(frozen: dict[str, Any]) -> dict[str, Any]:
    """Extract read-only decision context for the LLM user message."""
    return {key: frozen[key] for key in _EXPLAIN_CONTEXT_KEYS if key in frozen}


def build_risk_explain_messages(frozen: dict[str, Any]) -> list[dict[str, str]]:
    """Build chat messages for turbidity 12h risk explanation."""
    context = build_risk_explain_context(frozen)
    user_payload = json.dumps(context, ensure_ascii=False, indent=2)
    user_content = (
        "Explain the following frozen turbidity 12h risk forecast for on-call operators.\n"
        "Respond in English only, in 2–4 operational sentences.\n\n"
        f"{user_payload}"
    )
    return [
        {"role": "system", "content": RISK_EXPLAIN_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

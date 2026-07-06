"""L1 turbidity 12h risk explanation — append explanation_text to frozen forecast JSON."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from assistant.config import AssistantConfig, load_assistant_config
from assistant.llm_client import CompletionResult, LLMClient
from assistant.prompts import build_risk_explain_messages

# Decision fields that must never be overwritten by the explain layer.
_FROZEN_DECISION_KEYS = frozenset(
    {
        "site_no",
        "model_version",
        "phase_b_model",
        "phase_b_max_tier_model",
        "reference_utc",
        "features_csv",
        "thresholds_path",
        "tier_at_t",
        "63680",
        "is_anomaly_at_t",
        "alert_12h_forecast",
        "max_tier_forecast",
        "recommend_alert",
        "rationale_template_key",
        "horizon_tiers",
        "exog_policy",
        "label_note",
    }
)

SOURCE_REF = "python:/turbidity/risk-forecast-12h"


def merge_explanation_into_forecast(
    frozen: dict[str, Any],
    explanation: dict[str, Any],
) -> dict[str, Any]:
    """
    Return forecast JSON with explanation fields appended.

    Decision keys from ``frozen`` are always preserved; LLM output cannot override them.
    """
    merged = dict(frozen)
    for key in _FROZEN_DECISION_KEYS:
        if key in frozen:
            merged[key] = frozen[key]
    merged.update(explanation)
    for key in _FROZEN_DECISION_KEYS:
        if key in frozen:
            merged[key] = frozen[key]
    merged.setdefault(
        "sources",
        [{"type": "api", "ref": SOURCE_REF}],
    )
    return merged


def build_explanation_meta(
    result: CompletionResult,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    ts = generated_at or datetime.now(timezone.utc)
    return {
        "explanation_text": result.text,
        "explanation_model": result.model,
        "explanation_provider": result.provider,
        "explanation_generated_at": ts.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def generate_risk_explanation(
    frozen: dict[str, Any],
    *,
    config: AssistantConfig | None = None,
    complete_fn: Callable[[list[dict[str, str]]], CompletionResult] | None = None,
) -> dict[str, Any]:
    """
    Call the LLM to produce ``explanation_text`` for a frozen Phase B forecast.

    Does not mutate ``frozen`` decision fields.
    """
    cfg = config if config is not None else load_assistant_config()
    messages = build_risk_explain_messages(frozen)
    if complete_fn is not None:
        result = complete_fn(messages)
    else:
        client = LLMClient(cfg)
        result = client.complete(messages)
    meta = build_explanation_meta(result)
    return merge_explanation_into_forecast(frozen, meta)

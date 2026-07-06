"""Unit tests for R7a escalate_12h backtest."""

from __future__ import annotations

from models.turbidity_risk_escalate_backtest import (
    _predict_escalate_baseline,
    annotate_escalate_label,
    filter_normal_rows,
    is_normal_quality_cutoff,
    tuning_sample_weights,
)


def test_filter_normal_only() -> None:
    rows = [
        {"tier_at_T": "NORMAL", "alert_12h": 1},
        {"tier_at_T": "WATCH", "alert_12h": 1},
        {"tier_at_T": "NORMAL", "alert_12h": 0},
    ]
    out = filter_normal_rows(rows)
    assert len(out) == 2
    assert out[0]["escalate_12h"] == 1
    assert out[1]["escalate_12h"] == 0


def test_persistence_escalate_always_zero() -> None:
    rows = annotate_escalate_label(
        [{"tier_at_T": "NORMAL", "alert_12h": 1}]
    )
    pred, _ = _predict_escalate_baseline("persistence_escalate", rows)
    assert list(pred) == [0]


def test_tuning_weights_flood_and_positive() -> None:
    rows = [
        {
            "tier_at_T": "NORMAL",
            "escalate_12h": 1,
            "cutoff_utc": "2025-12-10 12:00:00+00:00",
        },
        {
            "tier_at_T": "NORMAL",
            "escalate_12h": 0,
            "cutoff_utc": "2025-06-01 00:00:00+00:00",
        },
    ]
    w = tuning_sample_weights(rows, flood_weight=5.0)
    assert w[0] == 5.0
    assert w[1] == 1.0


def test_is_normal_quality() -> None:
    assert is_normal_quality_cutoff({"tier_at_T": "NORMAL"})
    assert not is_normal_quality_cutoff({"tier_at_T": "WATCH"})

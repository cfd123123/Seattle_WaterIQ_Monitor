"""Unit tests for event-window turbidity risk metrics."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from models.turbidity_risk_event_eval import (
    filter_rows,
    is_y_rise_event,
    metrics_for_population,
    population_filters,
    run_event_metrics_eval,
)
from models.turbidity_state_monitoring import build_tier_rules_metadata, label_alert_tier


def test_metrics_for_population_counts() -> None:
    rows = [
        {"alert_12h": 1},
        {"alert_12h": 0},
        {"alert_12h": 1},
    ]
    pred = np.array([1, 1, 0], dtype=int)
    m = metrics_for_population(rows, pred)
    assert m["tp"] == 1
    assert m["fp"] == 1
    assert m["fn"] == 1
    assert m["tn"] == 0


def test_is_y_rise_event() -> None:
    idx = pd.date_range("2024-01-01", periods=20, freq="h", tz="UTC")
    y = pd.Series(np.ones(20), index=idx)
    y.iloc[10:14] = 5.0
    row = {"tier_at_T": "NORMAL", "cutoff_ix": 8, "cutoff_utc": str(idx[8])}
    assert is_y_rise_event(row, y, delta_up_1h=2.0)
    assert not is_y_rise_event(row, y, delta_up_1h=10.0)


def test_run_event_metrics_eval_synthetic(tmp_path: Path) -> None:
    n = 500
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    y = np.ones(n) * 1.0
    y[350:370] = 8.0
    csv = tmp_path / "feat.csv"
    pd.DataFrame(
        {
            "datetime_utc": idx,
            "63680": y,
            "precipitation_mm": np.zeros(n),
            "upstream_discharge_cfs_12116400": np.linspace(100, 200, n),
        }
    ).to_csv(csv, index=False)
    thr_path = tmp_path / "thr.json"
    thr_path.write_text(
        json.dumps(
            {
                "model_version": "test",
                "split_index": 350,
                "site_no": "12117500",
                "features_csv": str(csv),
                "tier_rules": build_tier_rules_metadata(
                    {
                        "theta_low": 1.0,
                        "theta_high": 2.0,
                        "delta_up_1h": 0.5,
                        "y_tuning_p90": 2.0,
                        "y_tuning_p95": 4.0,
                        "y_tuning_p99": 10.0,
                        "delta_up_P90": 0.3,
                        "absolute_ntu_critical": 50.0,
                    }
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "report"
    result = run_event_metrics_eval(
        features_csv=csv,
        thresholds_json=thr_path,
        report_dir=out,
        holdout_step=12,
        with_if_features=False,
        tune_alert_threshold=False,
        write_md=True,
    )
    assert (out / "risk_class_event_metrics.json").is_file()
    assert "persistence_alert" in result["by_model_variant"]
    assert "full_holdout" in result["population_counts"]

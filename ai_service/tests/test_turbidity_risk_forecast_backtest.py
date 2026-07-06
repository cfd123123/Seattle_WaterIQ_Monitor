"""Unit tests for turbidity 12h risk forecast backtest."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from models.turbidity_risk_forecast_backtest import (
    _tier_accuracy,
    format_risk_forecast_md,
    max_quality_tier,
    recommend_alert_from_max_tier,
    run_risk_forecast_backtest,
    tier_from_predicted_ntu,
    walk_forward_direct_ridge_risk,
)
from models.turbidity_state_monitoring import build_tier_rules_metadata, compute_thresholds, label_alert_tier


def _synthetic_features_csv(path: Path, n: int = 500) -> None:
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    y = np.ones(n) * 1.0
    y[350:370] = 8.0
    y[450:460] = 20.0
    df = pd.DataFrame(
        {
            "datetime_utc": idx,
            "63680": y,
            "precipitation_mm": np.linspace(0, 2, n),
            "upstream_discharge_cfs_12116400": np.linspace(100, 300, n),
        }
    )
    df.to_csv(path, index=False)


def _minimal_thresholds(split_ix: int, csv: Path) -> dict:
    return {
        "model_version": "turbidity-state-v2.1-test",
        "split_index": split_ix,
        "site_no": "12117500",
        "features_csv": str(csv.resolve()),
        "tier_rules": build_tier_rules_metadata(
            {
                "theta_low": 1.0,
                "theta_high": 2.0,
                "delta_up_1h": 0.1,
                "y_tuning_p90": 2.0,
                "y_tuning_p95": 4.0,
                "y_tuning_p99": 10.0,
                "delta_up_P90": 0.3,
                "absolute_ntu_critical": 50.0,
            }
        ),
    }


def test_tier_from_predicted_ntu_critical() -> None:
    thr = _minimal_thresholds(200, Path("x.csv"))
    tier = tier_from_predicted_ntu(55.0, 1.0, thr)
    assert tier == "CRITICAL"


def test_max_quality_tier_and_recommend_alert() -> None:
    assert max_quality_tier(["NORMAL", "WATCH"]) == "WATCH"
    assert recommend_alert_from_max_tier("WATCH") is True
    assert recommend_alert_from_max_tier("NORMAL") is False


def test_tier_accuracy_skips_gaps() -> None:
    out = _tier_accuracy(["WATCH", "NORMAL"], ["WATCH", "SENSOR_GAP"])
    assert out["n_finite_actual"] == 1
    assert out["accuracy"] == 1.0


def test_walk_forward_direct_ridge_risk_synthetic() -> None:
    idx = pd.date_range("2024-01-01", periods=400, freq="h", tz="UTC")
    y = pd.Series(np.linspace(1, 3, 400), index=idx)
    prec = pd.Series(np.zeros(400), index=idx)
    q = pd.Series(np.linspace(50, 150, 400), index=idx)
    wf = walk_forward_direct_ridge_risk(
        y,
        prec,
        q,
        1,
        exog_mode="persistence",
        lag=12,
        step=12,
        split_ix=300,
        ridge_alpha=1.0,
        history_window_hours=200,
        holdout_only=True,
    )
    assert len(wf["records"]) > 0
    assert wf["exog_mode"] == "persistence"


def test_run_risk_forecast_backtest_synthetic(tmp_path: Path) -> None:
    csv = tmp_path / "feat.csv"
    thr_path = tmp_path / "state_thresholds.json"
    out = tmp_path / "report"
    _synthetic_features_csv(csv, n=500)
    thr = _minimal_thresholds(350, csv)
    thr_path.write_text(json.dumps(thr, indent=2), encoding="utf-8")

    result = run_risk_forecast_backtest(
        features_csv=csv,
        thresholds_json=thr_path,
        report_dir=out,
        horizons=[1, 2, 3],
        holdout_step=12,
        ridge_alpha=1.0,
        history_window_hours=200,
        write_md=True,
    )
    assert (out / "risk_forecast_holdout.json").is_file()
    assert (out / "risk_forecast_holdout.md").is_file()
    assert "oracle" in result["by_exog_mode"]
    assert "persistence" in result["by_exog_mode"]
    h1 = result["by_exog_mode"]["oracle"]["per_horizon"]["1"]
    assert h1["tier"]["n_finite_actual"] > 0
    md = format_risk_forecast_md(result)
    assert "recommend_alert" in md

"""Unit tests for turbidity holdout tier evaluation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from models.turbidity_holdout_eval import (
    _flood_window_tier_summary,
    _monthly_tier_rates_holdout,
    _resolve_holdout_tiers,
    _tier_counts_and_rates,
    format_holdout_eval_summary,
    run_holdout_eval,
)
from models.turbidity_state_monitoring import (
    GAP_TIERS,
    build_tier_rules_metadata,
    compute_thresholds,
    label_alert_tier,
)


def _synthetic_features_csv(path: Path, n: int = 1200) -> None:
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    y = np.ones(n) * 1.0
    y[900:920] = 6.0
    y[1100:1110] = 15.0
    df = pd.DataFrame(
        {
            "datetime_utc": idx,
            "63680": y,
            "precipitation_mm": np.zeros(n),
            "upstream_discharge_cfs_12116400": np.linspace(100, 200, n),
        }
    )
    df.to_csv(path, index=False)


def test_tier_counts_and_rates() -> None:
    idx = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    tiers = pd.Series(["NORMAL", "WATCH", "WATCH", "CRITICAL"], index=idx)
    out = _tier_counts_and_rates(tiers)
    assert out["tier_counts"]["WATCH"] == 2
    assert out["tier_rates"]["NORMAL"] == pytest.approx(0.25)


def test_flood_window_tier_summary() -> None:
    idx = pd.date_range("2025-12-09", periods=24 * 9, freq="h", tz="UTC")
    y = pd.Series(3.0, index=idx)
    y.iloc[10] = 20.0
    tiers = pd.Series(["WATCH"] * len(idx), index=idx)
    tiers.iloc[10] = "CRITICAL"
    out = _flood_window_tier_summary(tiers, y)
    assert out["n_grid_hours"] == len(idx)
    assert out["y_max"] == pytest.approx(20.0)
    assert out["tier_counts"]["CRITICAL"] == 1


def test_monthly_tier_rates_holdout() -> None:
    idx = pd.date_range("2025-07-01", periods=48, freq="h", tz="UTC")
    tiers = pd.Series(["NORMAL", "WATCH"] * 24, index=idx)
    rows = _monthly_tier_rates_holdout(tiers)
    assert len(rows) == 1
    assert rows[0]["tier_rates"]["WATCH"] == pytest.approx(0.5)


def test_tier_counts_separates_gap_from_normal() -> None:
    idx = pd.date_range("2024-01-01", periods=6, freq="h", tz="UTC")
    tiers = pd.Series(["NORMAL", "SENSOR_GAP", "SENSOR_GAP", "WATCH", "DATA_STALE", "CRITICAL"], index=idx)
    out = _tier_counts_and_rates(tiers)
    assert out["n_gap_hours"] == 3
    assert out["tier_counts"]["NORMAL"] == 1
    assert out["quality_tier_rates"]["NORMAL"] == pytest.approx(0.333333, rel=1e-4)


def test_run_holdout_eval_synthetic(tmp_path: Path) -> None:
    csv = tmp_path / "feat.csv"
    out = tmp_path / "report"
    out.mkdir()
    _synthetic_features_csv(csv, n=1200)

    from models.turbidity_state_monitoring import load_features

    df = load_features(csv)
    y = df["63680"]
    tuning = pd.Series(True, index=y.index)
    tuning.iloc[800:] = False
    thr = compute_thresholds(y, None, None, tuning, recovery_window_hours=48)
    thr["split_index"] = 800
    thr["split_time_utc"] = str(y.index[800])
    thr["features_csv"] = str(csv.resolve())
    thr["site_no"] = "12117500"
    (out / "state_thresholds.json").write_text(json.dumps(thr, indent=2), encoding="utf-8")

    tiers = label_alert_tier(y, thr)
    hourly = df.copy()
    hourly["alert_tier"] = tiers
    hourly.reset_index().to_csv(out / "hourly_states.csv", index=False)

    result = run_holdout_eval(out, write_md=True)
    assert (out / "holdout_eval.json").is_file()
    assert (out / "holdout_eval.md").is_file()
    assert result["n_grid_hours"] == 400
    assert sum(result["tier_counts"].values()) == result["n_grid_hours"]
    assert "WATCH" in result["tier_rates"]
    assert "flood_window_dec_2025" in result
    md = format_holdout_eval_summary(result)
    assert "Holdout tier rates" in md


def test_resolve_holdout_tiers_recomputes_without_hourly() -> None:
    idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
    y = pd.Series([1.0] * 10, index=idx)
    thr = {
        "theta_low": 2.0,
        "theta_high": 5.0,
        "y_tuning_p90": 5.0,
        "y_tuning_p95": 8.0,
        "y_tuning_p99": 12.0,
        "delta_up_1h": 0.1,
        "delta_up_P90": 0.3,
        "tier_rules": build_tier_rules_metadata(
            {
                "theta_low": 2.0,
                "theta_high": 5.0,
                "y_tuning_p90": 5.0,
                "y_tuning_p95": 8.0,
                "y_tuning_p99": 12.0,
                "delta_up_1h": 0.1,
                "delta_up_P90": 0.3,
            }
        ),
    }
    holdout = pd.Series([False] * 5 + [True] * 5, index=idx)
    tiers, src = _resolve_holdout_tiers(y, thr, holdout, None)
    assert src == "recomputed_from_thresholds"
    assert len(tiers) == 5

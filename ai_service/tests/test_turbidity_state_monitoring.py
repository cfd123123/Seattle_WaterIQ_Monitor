"""Unit tests for turbidity state monitoring and alert tiers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from models.turbidity_state_monitoring import (
    ALERT_TIERS,
    CALIBRATION_MIN_MONTH_VALID_RATE,
    GAP_TIERS,
    MIN_DELTA_WATCH_1H,
    _alert_tier_at,
    _gap_tier_at,
    build_calibration_mask,
    build_tier_rules_metadata,
    compute_thresholds,
    diff_1h_from_previous_valid,
    evaluate_never_alert_baseline,
    label_alert_tier,
    label_states,
    load_features,
    rule_warning_high_at_T,
    run_state_monitoring,
    snapshot_at_reference,
    tier_is_anomaly,
)


def _synthetic_features_csv(path: Path, n: int = 500) -> None:
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    y = np.ones(n) * 1.0
    y[400:410] = 5.0
    y[410:420] = 3.0
    df = pd.DataFrame(
        {
            "datetime_utc": idx,
            "63680": y,
            "precipitation_mm": np.zeros(n),
            "upstream_discharge_cfs_12116400": np.linspace(100, 200, n),
        }
    )
    df.to_csv(path, index=False)


def _tier_thr() -> dict:
    return {
        "theta_low": 2.0,
        "theta_high": 5.0,
        "y_tuning_p90": 5.0,
        "y_tuning_p95": 8.0,
        "y_tuning_p99": 12.0,
        "delta_up_1h": 0.1,
        "delta_up_P90": 0.3,
        "absolute_ntu_critical": 50.0,
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


def test_label_states_priority() -> None:
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    y = pd.Series([1.0, 1.0, 10.0, 9.0, 8.0], index=idx)
    thr = {
        "theta_low": 2.0,
        "theta_high": 5.0,
        "delta_up_1h": 0.1,
        "recovery_window_hours": 48,
    }
    states = label_states(y, thr)
    assert states.iloc[2] == "High"
    assert states.iloc[3] == "High"

    idx2 = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    y2 = pd.Series([1.0, 10.0, 4.0, 3.5], index=idx2)
    states2 = label_states(y2, thr)
    assert states2.iloc[1] == "High"
    assert states2.iloc[2] == "Recovering"


def test_alert_tier_priority_critical_over_high() -> None:
    tier = _alert_tier_at(
        13.0,
        0.0,
        p75=2.0,
        p90=5.0,
        p95=8.0,
        p99=12.0,
        delta_watch=0.1,
        delta_high=0.3,
        absolute_ntu_critical=50.0,
    )
    assert tier == "CRITICAL"


def test_alert_tier_absolute_critical() -> None:
    tier = _alert_tier_at(
        55.0,
        np.nan,
        p75=2.0,
        p90=5.0,
        p95=8.0,
        p99=12.0,
        delta_watch=0.1,
        delta_high=0.3,
        absolute_ntu_critical=50.0,
    )
    assert tier == "CRITICAL"


def test_alert_tier_normal_below_p90() -> None:
    tier = _alert_tier_at(
        0.6,
        0.05,
        p75=1.275,
        p90=2.9,
        p95=4.4,
        p99=12.588,
        delta_watch=0.1,
        delta_high=0.266667,
        absolute_ntu_critical=50.0,
    )
    assert tier == "NORMAL"


def test_alert_tier_watch_at_p90() -> None:
    tier = _alert_tier_at(
        2.9,
        np.nan,
        p75=1.275,
        p90=2.9,
        p95=4.4,
        p99=12.588,
        delta_watch=0.1,
        delta_high=0.266667,
        absolute_ntu_critical=50.0,
    )
    assert tier == "WATCH"


def test_alert_tier_watch_p75_with_rise() -> None:
    tier = _alert_tier_at(
        1.5,
        0.15,
        p75=1.275,
        p90=2.9,
        p95=4.4,
        p99=12.588,
        delta_watch=0.1,
        delta_high=0.266667,
        absolute_ntu_critical=50.0,
    )
    assert tier == "WATCH"


def test_alert_tier_high_p95() -> None:
    tier = _alert_tier_at(
        4.5,
        np.nan,
        p75=1.275,
        p90=2.9,
        p95=4.4,
        p99=12.588,
        delta_watch=0.1,
        delta_high=0.266667,
        absolute_ntu_critical=50.0,
    )
    assert tier == "HIGH"


def test_alert_tier_high_p90_with_fast_rise() -> None:
    tier = _alert_tier_at(
        3.0,
        0.3,
        p75=1.275,
        p90=2.9,
        p95=4.4,
        p99=12.588,
        delta_watch=0.1,
        delta_high=0.266667,
        absolute_ntu_critical=50.0,
    )
    assert tier == "HIGH"


def test_diff_1h_skips_gap_and_nan() -> None:
    idx = pd.date_range("2024-01-01", periods=6, freq="h", tz="UTC")
    y = pd.Series([1.0, np.nan, 2.0, 3.0, np.nan, 5.0], index=idx)
    d = diff_1h_from_previous_valid(y)
    assert np.isnan(d.iloc[0])
    assert np.isnan(d.iloc[2])
    assert d.iloc[3] == pytest.approx(1.0)
    assert np.isnan(d.iloc[5])


def test_label_alert_tier_series() -> None:
    idx = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    y = pd.Series([0.6, 1.0, 3.0, 13.0], index=idx)
    tiers = label_alert_tier(y, _tier_thr())
    assert tiers.iloc[0] == "NORMAL"
    assert tiers.iloc[2] in ("WATCH", "HIGH")
    assert tiers.iloc[3] == "CRITICAL"


def test_gap_tier_at_semantics() -> None:
    assert _gap_tier_at(None) == "UNKNOWN"
    assert _gap_tier_at(1.0) == "SENSOR_GAP"
    assert _gap_tier_at(3.0) == "SENSOR_GAP"
    assert _gap_tier_at(4.0) == "DATA_STALE"


def test_label_alert_tier_missing_y_not_normal() -> None:
    idx = pd.date_range("2024-01-01", periods=8, freq="h", tz="UTC")
    y = pd.Series([1.0, np.nan, np.nan, np.nan, np.nan, 2.0, np.nan, 3.0], index=idx)
    tiers = label_alert_tier(y, _tier_thr())
    assert tiers.iloc[0] == "NORMAL"
    assert tiers.iloc[1] == "SENSOR_GAP"
    assert tiers.iloc[2] in GAP_TIERS
    assert tiers.iloc[4] == "DATA_STALE"
    assert tiers.iloc[5] == "NORMAL"
    assert not tiers.isin(["NORMAL"]).iloc[1:5].all()
    assert tiers.iloc[0] not in GAP_TIERS


def test_tier_is_anomaly_only_quality_alerts() -> None:
    assert not tier_is_anomaly("NORMAL")
    assert tier_is_anomaly("WATCH")
    assert not tier_is_anomaly("SENSOR_GAP")
    assert not tier_is_anomaly("DATA_STALE")
    assert not tier_is_anomaly("UNKNOWN")


def test_snapshot_gap_hour_is_not_anomaly() -> None:
    idx = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    y = pd.Series([1.0, np.nan, 3.0, 13.0], index=idx)
    df = pd.DataFrame({"63680": y}, index=idx)
    thr = _tier_thr()
    states = label_states(y, {**thr, "recovery_window_hours": 48})
    snap = snapshot_at_reference(df, thr, states, y, None, None, ref_utc_hour=idx[1])
    assert snap["alert_tier"] == "SENSOR_GAP"
    assert snap["is_anomaly"] is False


def test_compute_thresholds_delta_watch_floor() -> None:
    idx = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    y = pd.Series(1.0, index=idx)
    tuning = pd.Series(True, index=idx)
    thr = compute_thresholds(y, None, None, tuning, recovery_window_hours=48)
    assert thr["delta_up_1h"] >= MIN_DELTA_WATCH_1H
    assert thr["tier_rules"]["delta_watch_1h"] >= MIN_DELTA_WATCH_1H


def test_compute_thresholds_includes_tier_rules() -> None:
    idx = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    y = pd.Series(np.linspace(1.0, 3.0, 200), index=idx)
    tuning = pd.Series(True, index=idx)
    thr = compute_thresholds(y, None, None, tuning, recovery_window_hours=48)
    assert "tier_rules" in thr
    assert thr["tier_rules"]["p75"] == thr["theta_low"]
    assert thr["tier_rules"]["p90"] == thr["y_tuning_p90"]


def test_compute_thresholds_eda_quantiles() -> None:
    idx = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    y = pd.Series(np.linspace(1.0, 3.0, 200), index=idx)
    tuning = pd.Series(True, index=idx)
    thr = compute_thresholds(y, None, None, tuning, recovery_window_hours=48)
    assert thr["theta_low"] == thr["y_tuning_p75"]
    assert thr["theta_high"] == thr["y_tuning_p90"]
    assert thr["y_tuning_p50"] == thr["baseline_median"]
    assert thr["y_tuning_iqr"] == round(thr["y_tuning_p75"] - thr["y_tuning_p25"], 6)
    assert thr["y_tuning_p95"] >= thr["y_tuning_p90"]
    assert thr["y_tuning_p99"] >= thr["y_tuning_p95"]
    assert "delta_up_P90" in thr
    assert thr["tuning_n_hours"] == thr["tuning_hours"] == 200
    assert thr["y_valid_n"] == 200
    assert thr["y_missing_n"] == 0
    assert thr["y_missing_rate"] == 0.0
    assert thr["tuning_start_utc"] == str(idx[0])
    assert thr["tuning_end_utc"] == str(idx[-1])


def test_build_calibration_mask_excludes_low_validity_months() -> None:
    idx = pd.date_range("2024-01-01", periods=24 * 31 * 3, freq="h", tz="UTC")
    y = pd.Series(1.0, index=idx)
    y.loc["2024-02"] = np.nan
    y.loc["2024-02-15":"2024-02-16"] = 2.0
    tuning = pd.Series(True, index=idx)
    cal_mask, meta = build_calibration_mask(tuning, y)
    assert "2024-02" in meta["calibration_months_excluded"]
    assert "2024-01" in meta["calibration_months_included"]
    assert "2024-03" in meta["calibration_months_included"]
    assert not cal_mask.loc["2024-02-01 00:00:00+00:00"]
    assert cal_mask.loc["2024-01-01 00:00:00+00:00"]
    assert meta["tuning_n_hours"] == len(idx)
    assert meta["calibration_hours_after_month_filter"] == int(cal_mask.sum())


def test_compute_thresholds_excludes_sparse_month_from_quantiles() -> None:
    idx = pd.date_range("2024-01-01", periods=24 * 62, freq="h", tz="UTC")
    y = pd.Series(1.0, index=idx)
    y.loc["2024-02"] = np.nan
    y.iloc[31 * 24 : 31 * 24 + 10] = 100.0
    tuning = pd.Series(True, index=idx)
    thr_sparse = compute_thresholds(y, None, None, tuning, recovery_window_hours=48)
    y_jan_mar = y.copy()
    y_jan_mar.loc["2024-02"] = np.nan
    thr_ref = compute_thresholds(y_jan_mar, None, None, tuning, recovery_window_hours=48)
    assert thr_sparse["calibration_months_excluded"] == ["2024-02"]
    assert thr_sparse["theta_low"] == thr_ref["theta_low"]
    assert thr_sparse["calibration_hours_after_month_filter"] < thr_sparse["tuning_n_hours"]


def test_compute_thresholds_tuning_validity_with_missing_y() -> None:
    idx = pd.date_range("2024-01-01", periods=120, freq="h", tz="UTC")
    y = pd.Series(np.linspace(1.0, 2.0, 120), index=idx)
    y.iloc[10:20] = np.nan
    prec = pd.Series(np.arange(120, dtype=float), index=idx)
    prec.iloc[5:8] = np.nan
    q_up = pd.Series(np.linspace(50.0, 150.0, 120), index=idx)
    tuning = pd.Series(True, index=idx)
    thr = compute_thresholds(y, prec, q_up, tuning, recovery_window_hours=48)
    assert thr["tuning_n_hours"] == 120
    assert thr["calibration_hours_after_month_filter"] == thr["tuning_n_hours"]
    assert thr["calibration_min_month_valid_rate"] == CALIBRATION_MIN_MONTH_VALID_RATE
    assert thr["y_valid_n"] == 110
    assert thr["y_missing_n"] == 10
    assert thr["y_missing_rate"] == round(10 / 120, 6)
    assert thr["precip_valid_n"] == 117
    assert thr["upstream_q_valid_n"] == 120


def test_never_alert_recall_zero_on_synthetic() -> None:
    with tempfile.TemporaryDirectory() as td:
        csv = Path(td) / "feat.csv"
        _synthetic_features_csv(csv, n=800)
        df = load_features(csv)
        y = df["63680"]
        tuning = pd.Series(True, index=y.index)
        thr = compute_thresholds(y, None, None, tuning, recovery_window_hours=48)
        states = label_states(y, thr)
        holdout = pd.Series(False, index=y.index)
        holdout.iloc[600:] = True
        base = evaluate_never_alert_baseline(y, states, holdout, horizons=(6,))
        assert base["6"]["recall"] == 0.0


def test_run_state_monitoring_writes_artifacts() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        csv = td_path / "feat.csv"
        out = td_path / "out"
        _synthetic_features_csv(csv, n=1200)
        summary = run_state_monitoring(csv, out_dir=out, write_plot=False)
        assert (out / "hourly_states.csv").is_file()
        assert (out / "state_thresholds.json").is_file()
        assert (out / "summary.json").is_file()
        assert "warning_vs_never_alert" in summary
        assert summary["warning_vs_never_alert"]["6"]["rule_beats_never_alert"] is True
        assert "tier_counts_all" in summary
        assert "SENSOR_GAP" in summary["alert_tiers"]
        assert set(ALERT_TIERS).issubset(summary["alert_tiers"])
        hourly = pd.read_csv(out / "hourly_states.csv")
        assert "alert_tier" in hourly.columns
        thr_json = json.loads((out / "state_thresholds.json").read_text(encoding="utf-8"))
        assert "tier_rules" in thr_json


def test_rule_warning_rising_fires() -> None:
    idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
    y = pd.Series([1.0, 2.0, 3.0, 3.5, 3.6, 3.7, 3.8, 3.9, 4.0, 4.1], index=idx)
    thr = {
        "theta_low": 2.0,
        "theta_high": 10.0,
        "delta_up_1h": 0.1,
        "recovery_window_hours": 48,
    }
    states = label_states(y, thr)
    assert rule_warning_high_at_T(2, y, states, None, None, thr, 6) is True

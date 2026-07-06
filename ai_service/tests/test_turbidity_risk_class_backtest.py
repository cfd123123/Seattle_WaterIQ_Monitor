"""Unit tests for turbidity 12h risk classification backtest."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from models.turbidity_risk_class_backtest import (
    _labels_12h_at_cutoff,
    alert_proba_to_binary,
    build_exog_policy,
    build_labeled_cutoffs,
    compare_risk_class_to_baseline,
    evaluate_model_on_rows,
    evaluate_upgrade_lead_time,
    format_risk_class_md,
    run_risk_class_backtest,
    sweep_ml_alert_threshold,
)
from models.turbidity_state_monitoring import build_tier_rules_metadata, label_alert_tier


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


def test_labels_12h_insufficient_future() -> None:
    idx = pd.date_range("2024-01-01", periods=80, freq="h", tz="UTC")
    y = pd.Series(np.ones(80), index=idx)
    tiers = label_alert_tier(y, _minimal_thresholds(40, Path("x.csv")))
    # Near end: fewer than 6 valid future hours possible when many NaN — all finite here
    lab = _labels_12h_at_cutoff(tiers, y, 75, min_valid_future_hours=6)
    assert lab is None


def test_labels_12h_alert_on_spike() -> None:
    idx = pd.date_range("2024-01-01", periods=50, freq="h", tz="UTC")
    y = pd.Series(np.ones(50), index=idx)
    y.iloc[10:14] = 15.0
    thr = _minimal_thresholds(25, Path("x.csv"))
    tiers = label_alert_tier(y, thr)
    lab = _labels_12h_at_cutoff(tiers, y, 8, min_valid_future_hours=3)
    assert lab is not None
    assert lab["alert_12h"] == 1


def test_build_labeled_cutoffs_synthetic() -> None:
    idx = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    y = pd.Series(np.linspace(1, 4, 200), index=idx)
    prec = pd.Series(np.zeros(200), index=idx)
    q = pd.Series(np.linspace(50, 150, 200), index=idx)
    thr = _minimal_thresholds(120, Path("x.csv"))
    tiers = label_alert_tier(y, thr)
    rows = build_labeled_cutoffs(
        y, prec, q, tiers, lag=12, min_valid_future_hours=6, idx_start=50, idx_end=180, step=6
    )
    assert len(rows) > 0
    assert rows[0]["features"].shape[0] == 12 * 3


def test_evaluate_persistence_baseline() -> None:
    rows = [
        {"tier_at_T": "WATCH", "alert_12h": 1, "max_tier_12h": "HIGH"},
        {"tier_at_T": "NORMAL", "alert_12h": 0, "max_tier_12h": "NORMAL"},
    ]
    out = evaluate_model_on_rows("persistence_alert", rows, rows)
    assert out["n_eval"] == 2
    assert out["alert_12h"]["tp"] >= 0


def test_build_exog_policy_precip_no_ffill() -> None:
    pol = build_exog_policy(
        use_exog_ffill=True,
        use_precip_ffill=False,
        use_upstream_ffill=True,
    )
    assert pol["use_precip_ffill"] is False
    assert pol["use_upstream_ffill"] is True
    assert "interval" in pol["precip_no_ffill_rationale"].lower()


def test_compare_risk_class_to_baseline() -> None:
    base = {
        "n_tuning_labeled_cutoffs": 100,
        "n_holdout_labeled_cutoffs": 10,
        "by_model": {
            "logistic_regression": {"alert_12h": {"f1": 0.5}},
        },
    }
    cur = {
        "n_tuning_labeled_cutoffs": 98,
        "n_holdout_labeled_cutoffs": 9,
        "by_model": {
            "logistic_regression": {"alert_12h": {"f1": 0.55}},
        },
    }
    cmp = compare_risk_class_to_baseline(cur, base)
    assert cmp["n_holdout_labeled_cutoffs_delta"] == -1
    assert cmp["alert_12h_f1_delta"]["logistic_regression"] == pytest.approx(0.05)


def test_evaluate_upgrade_lead_time_event_local_window() -> None:
    """Lead time uses [T, upgrade) only, not earlier holdout cutoffs."""
    idx = pd.date_range("2024-01-01", periods=120, freq="h", tz="UTC")
    tiers = pd.Series(["NORMAL"] * 120, index=idx)
    tiers.iloc[50:56] = "WATCH"  # first upgrade at ix 50 from event T=45 (future h=5)
    y = pd.Series(np.ones(120), index=idx)
    y.iloc[50:56] = 8.0

    eval_rows = [
        {
            "cutoff_ix": 10,
            "cutoff_utc": str(idx[10]),
            "tier_at_T": "NORMAL",
            "alert_12h": 0,
        },
        {
            "cutoff_ix": 45,
            "cutoff_utc": str(idx[45]),
            "tier_at_T": "NORMAL",
            "alert_12h": 1,
        },
        {
            "cutoff_ix": 48,
            "cutoff_utc": str(idx[48]),
            "tier_at_T": "NORMAL",
            "alert_12h": 1,
        },
    ]
    # Alert at ix=10 (far before event) must NOT affect event at T=45.
    alert_pred = np.array([1, 0, 1], dtype=int)
    out = evaluate_upgrade_lead_time(
        tiers, y, eval_rows, alert_pred, model_name="test"
    )
    assert out["n_upgrade_events"] == 2  # T=45 and T=48 both NORMAL + future WATCH+
    leads = [e["lead_hours"] for e in out["events_sample"] if e.get("has_lead")]
    assert leads
    assert max(leads) <= 12
    # Event at T=48: pred at 48, upgrade at 50 -> lead 2
    ev48 = next(e for e in out["events_sample"] if e["event_cutoff_ix"] == 48)
    assert ev48["lead_hours"] == 2


def test_alert_proba_to_binary_threshold() -> None:
    proba = np.array([0.1, 0.5, 0.9])
    assert list(alert_proba_to_binary(proba, 0.5)) == [0, 1, 1]
    assert list(alert_proba_to_binary(proba, 0.6)) == [0, 0, 1]


def test_sweep_ml_alert_threshold_fp_guardrail() -> None:
    idx = pd.date_range("2024-01-01", periods=80, freq="h", tz="UTC")
    tiers = pd.Series(["NORMAL"] * 80, index=idx)
    tiers.iloc[40:44] = "WATCH"
    y = pd.Series(np.ones(80), index=idx)
    rows = [
        {
            "cutoff_ix": i,
            "cutoff_utc": str(idx[i]),
            "tier_at_T": str(tiers.iloc[i]),
            "alert_12h": 1 if i == 38 else 0,
        }
        for i in range(30, 50)
    ]
    proba = np.linspace(0.0, 1.0, len(rows))
    out = sweep_ml_alert_threshold(
        tiers,
        y,
        rows,
        proba,
        model_key="logistic_regression",
        persistence_fp_rate=0.2,
        fp_guardrail_ratio=1.05,
        threshold_grid=(0.3, 0.5, 0.9),
    )
    assert "selected_threshold" in out
    assert out["selected_threshold"] in (0.3, 0.5, 0.9)
    assert len(out["sweep"]) == 3


def test_run_risk_class_backtest_synthetic(tmp_path: Path) -> None:
    csv = tmp_path / "feat.csv"
    thr_path = tmp_path / "state_thresholds.json"
    out = tmp_path / "report"
    _synthetic_features_csv(csv, n=500)
    thr = _minimal_thresholds(350, csv)
    thr_path.write_text(json.dumps(thr, indent=2), encoding="utf-8")

    result = run_risk_class_backtest(
        features_csv=csv,
        thresholds_json=thr_path,
        report_dir=out,
        holdout_step=12,
        lag=12,
        min_valid_future_hours=4,
        write_md=True,
    )
    assert (out / "risk_class_holdout.json").is_file()
    assert (out / "risk_class_holdout.md").is_file()
    assert "lightgbm" in result["by_model"]
    md = format_risk_class_md(result)
    assert "alert_12h" in md

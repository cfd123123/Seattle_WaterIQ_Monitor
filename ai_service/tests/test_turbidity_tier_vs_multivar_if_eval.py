"""Unit tests for turbidity tier vs univariate vs multivariate IF holdout comparison."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from models.turbidity_state_monitoring import compute_thresholds, label_alert_tier, load_features
from models.turbidity_tier_vs_multivar_if_eval import (
    MULTIVAR_FEATURE_COLS,
    build_multivar_matrix,
    compute_exog_complete_case_counts,
    fit_multivar_if_is_anomaly,
    run_tier_vs_univariate_vs_multivar_eval,
    score_multivar_if_on_holdout_hours,
)


def _synthetic_features_csv(path: Path, n: int = 400, *, gap_precip: bool = False) -> None:
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    y = np.ones(n) * 1.0
    y[200:210] = 25.0
    prec = np.zeros(n)
    if gap_precip:
        prec[100:120] = np.nan
    df = pd.DataFrame(
        {
            "datetime_utc": idx,
            "63680": y,
            "precipitation_mm": prec,
            "upstream_discharge_cfs_12116400": np.linspace(100, 200, n),
        }
    )
    df.to_csv(path, index=False)


def test_load_features_use_exog_ffill_false(tmp_path: Path) -> None:
    csv = tmp_path / "f.csv"
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "datetime_utc": idx,
            "63680": [1.0, 2.0, 3.0, 4.0, 5.0],
            "precipitation_mm": [np.nan, 1.0, np.nan, 2.0, np.nan],
            "upstream_discharge_cfs_12116400": [np.nan, 100.0, np.nan, 120.0, np.nan],
        }
    )
    df.to_csv(csv, index=False)
    filled = load_features(csv, use_exog_ffill=True)
    raw = load_features(csv, use_exog_ffill=False)
    assert filled["precipitation_mm"].iloc[1:].notna().all()
    assert filled["precipitation_mm"].iloc[2] == pytest.approx(1.0)
    assert raw["precipitation_mm"].isna().sum() == 3

    split = load_features(csv, use_precip_ffill=False, use_upstream_ffill=True)
    assert split["precipitation_mm"].isna().sum() == 3
    assert split["upstream_discharge_cfs_12116400"].iloc[2] == pytest.approx(100.0)


def test_fit_multivar_if_insufficient() -> None:
    w = np.ones((10, 3))
    is_anom, meta = fit_multivar_if_is_anomaly(w)
    assert is_anom is None
    assert meta["reason"] == "insufficient_history"


def test_fit_multivar_if_spike() -> None:
    base = np.column_stack([np.ones(200), np.zeros(200), np.linspace(1, 2, 200)])
    spike = np.array([[80.0, 0.0, 2.0]])
    w = np.vstack([base, spike])
    is_anom, meta = fit_multivar_if_is_anomaly(w)
    assert meta["samples_used"] <= 201
    assert is_anom is True


def test_compute_exog_complete_case_counts() -> None:
    n = 100
    x = np.ones((n, 3))
    x[10:20, 1] = np.nan
    tuning = pd.Series([True] * 60 + [False] * 40)
    holdout = ~tuning
    out = compute_exog_complete_case_counts(x, tuning, holdout)
    assert out["tuning"]["n_multivar_ready"] == 50
    assert out["holdout"]["n_multivar_ready"] == 40


def test_score_multivar_if_on_holdout_hours_small() -> None:
    idx = pd.date_range("2024-01-01", periods=300, freq="h", tz="UTC")
    x = np.column_stack([np.ones(300), np.zeros(300), np.linspace(1, 2, 300)])
    x[-1, 0] = 50.0
    eval_ix = idx[-5:]
    scored = score_multivar_if_on_holdout_hours(x, eval_ix, idx, progress_every=0)
    assert len(scored) == 5
    assert scored["mif_available"].all()


def test_run_tier_vs_univariate_vs_multivar_eval_synthetic(tmp_path: Path) -> None:
    csv = tmp_path / "feat.csv"
    out = tmp_path / "report"
    out.mkdir()
    _synthetic_features_csv(csv, n=400)

    df = load_features(csv, use_exog_ffill=False)
    y = df["63680"]
    tuning = pd.Series(True, index=y.index)
    tuning.iloc[250:] = False
    thr = compute_thresholds(y, None, None, tuning, recovery_window_hours=48)
    thr["split_index"] = 250
    thr["split_time_utc"] = str(y.index[250])
    thr["features_csv"] = str(csv.resolve())
    thr["site_no"] = "12117500"
    (out / "state_thresholds.json").write_text(json.dumps(thr, indent=2), encoding="utf-8")

    tiers = label_alert_tier(y, thr)
    hourly = df.copy()
    hourly["alert_tier"] = tiers
    hourly.reset_index().to_csv(out / "hourly_states.csv", index=False)

    result = run_tier_vs_univariate_vs_multivar_eval(out, progress_every=0, write_md=True)
    assert (out / "exog_complete_case_counts.json").is_file()
    assert (out / "tier_vs_univariate_vs_multivar_holdout.json").is_file()
    assert (out / "tier_vs_univariate_vs_multivar_holdout.md").is_file()
    three = result["three_way_hours"]
    assert three["n_hours"] > 0
    for key in ("tier_vs_univariate", "tier_vs_multivariate", "univariate_vs_multivariate"):
        c = three[key]
        assert c["n_hours"] == c["both_alert_n"] + c["tier_only_n"] + c["if_only_n"] + c["neither_n"]


def test_build_multivar_matrix_columns(tmp_path: Path) -> None:
    csv = tmp_path / "f.csv"
    _synthetic_features_csv(csv, n=10)
    df = load_features(csv, use_exog_ffill=False)
    m = build_multivar_matrix(df)
    assert m.shape == (10, len(MULTIVAR_FEATURE_COLS))

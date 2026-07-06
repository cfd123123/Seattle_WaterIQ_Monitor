"""Unit tests for turbidity tier vs IsolationForest holdout comparison."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from models.turbidity_tier_vs_if_eval import (
    _contingency_block,
    build_calendar_y_series,
    fit_if_is_anomaly,
    format_tier_vs_if_md,
    run_tier_vs_if_eval,
    score_if_on_holdout_hours,
    tier_is_alert,
)
from models.turbidity_state_monitoring import (
    compute_thresholds,
    label_alert_tier,
    load_features,
)


def _synthetic_features_csv(path: Path, n: int = 400) -> None:
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    y = np.ones(n) * 1.0
    y[200:210] = 25.0
    y[350:355] = 40.0
    df = pd.DataFrame(
        {
            "datetime_utc": idx,
            "63680": y,
            "precipitation_mm": np.zeros(n),
            "upstream_discharge_cfs_12116400": np.linspace(100, 200, n),
        }
    )
    df.to_csv(path, index=False)


def test_tier_is_alert() -> None:
    assert tier_is_alert("WATCH")
    assert tier_is_alert("critical")
    assert not tier_is_alert("NORMAL")
    assert not tier_is_alert("SENSOR_GAP")


def test_fit_if_is_anomaly_insufficient() -> None:
    is_anom, meta = fit_if_is_anomaly(np.ones(10))
    assert is_anom is None
    assert meta["reason"] == "insufficient_history"


def test_fit_if_is_anomaly_spike() -> None:
    window = np.concatenate([np.ones(200) * 1.0, np.array([80.0])])
    is_anom, meta = fit_if_is_anomaly(window)
    assert meta["samples_used"] <= 201
    assert is_anom is True


def test_contingency_block() -> None:
    tier = pd.Series([True, True, False, False])
    if_a = pd.Series([True, False, True, False])
    out = _contingency_block(tier, if_a)
    assert out["both_alert_n"] == 1
    assert out["tier_only_n"] == 1
    assert out["if_only_n"] == 1
    assert out["neither_n"] == 1
    assert out["agreement_rate"] == pytest.approx(0.5)


def test_score_if_on_holdout_hours_small() -> None:
    idx = pd.date_range("2024-01-01", periods=300, freq="h", tz="UTC")
    y = pd.Series(1.0, index=idx)
    y.iloc[-1] = 50.0
    eval_ix = idx[-5:]
    scored = score_if_on_holdout_hours(y, eval_ix, progress_every=0)
    assert len(scored) == 5
    assert scored["if_available"].all()
    assert scored["if_is_anomaly"].dtype == object or scored["if_is_anomaly"].notna().all()


def test_run_tier_vs_if_eval_synthetic(tmp_path: Path) -> None:
    csv = tmp_path / "feat.csv"
    out = tmp_path / "report"
    out.mkdir()
    _synthetic_features_csv(csv, n=400)

    df = load_features(csv)
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

    result = run_tier_vs_if_eval(out, progress_every=0, write_md=True)
    assert (out / "tier_vs_if_holdout.json").is_file()
    assert (out / "tier_vs_if_holdout.md").is_file()
    q = result["quality_hours"]["contingency"]
    assert q["n_hours"] > 0
    assert q["n_hours"] == q["both_alert_n"] + q["tier_only_n"] + q["if_only_n"] + q["neither_n"]
    md = format_tier_vs_if_md(result)
    assert "2×2 contingency" in md


def test_build_calendar_y_series(tmp_path: Path) -> None:
    csv = tmp_path / "f.csv"
    _synthetic_features_csv(csv, n=50)
    s = build_calendar_y_series(features_csv=csv, iv_csv=None, site_no="12117500")
    assert len(s) == 50

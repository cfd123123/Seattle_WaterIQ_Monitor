"""Unit tests for live 12h turbidity risk forecast (Phase B)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from models.turbidity_risk_forecast_12h import (
    rationale_template_key,
    run_risk_forecast_12h,
)
from models.turbidity_state_monitoring import build_tier_rules_metadata, label_alert_tier


def _synthetic_features_csv(path: Path, n: int = 200) -> None:
    idx = pd.date_range("2024-06-01", periods=n, freq="h", tz="UTC")
    y = np.ones(n) * 0.5
    y[150:160] = 12.0
    df = pd.DataFrame(
        {
            "datetime_utc": idx,
            "63680": y,
            "precipitation_mm": np.zeros(n),
            "upstream_discharge_cfs_12116400": np.linspace(100, 200, n),
        }
    )
    df.to_csv(path, index=False)


def _thresholds_json(path: Path, csv: Path) -> None:
    thr = {
        "model_version": "turbidity-state-v2.1-test",
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
    path.write_text(json.dumps(thr), encoding="utf-8")


def test_run_risk_forecast_12h_normal(tmp_path: Path) -> None:
    csv = tmp_path / "feat.csv"
    thr = tmp_path / "thr.json"
    _synthetic_features_csv(csv)
    _thresholds_json(thr, csv)
    out = run_risk_forecast_12h(
        features_csv=csv,
        thresholds_json=thr,
        reference_utc="2024-06-01T05:00:00+00:00",
    )
    assert out["tier_at_t"] == "NORMAL"
    assert out["alert_12h_forecast"] == 0
    assert out["recommend_alert"] is False
    assert out["max_tier_forecast"] == "NORMAL"
    assert len(out["horizon_tiers"]) == 12
    assert out["rationale_template_key"] == "forecast.turbidityRisk.rationale.persistenceNormal"


def test_run_risk_forecast_12h_elevated(tmp_path: Path) -> None:
    csv = tmp_path / "feat.csv"
    thr = tmp_path / "thr.json"
    _synthetic_features_csv(csv)
    _thresholds_json(thr, csv)
    df = pd.read_csv(csv)
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True)
    y = df.set_index("datetime_utc")["63680"]
    tiers = label_alert_tier(y, json.loads(thr.read_text()))
    ref = "2024-06-07T16:00:00+00:00"
    ix = y.index.get_indexer([pd.Timestamp(ref)], method="pad")[0]
    if str(tiers.iloc[ix]) not in ("WATCH", "HIGH", "CRITICAL"):
        pytest.skip("synthetic hour not elevated under test thresholds")
    out = run_risk_forecast_12h(
        features_csv=csv,
        thresholds_json=thr,
        reference_utc=ref,
    )
    assert out["alert_12h_forecast"] == 1
    assert out["recommend_alert"] is True
    assert out["max_tier_forecast"] == str(tiers.iloc[ix])


def test_rationale_gap() -> None:
    key = rationale_template_key(
        tier_at_t="SENSOR_GAP",
        recommend_alert=False,
        alert_12h_forecast=0,
    )
    assert key == "forecast.turbidityRisk.rationale.gap"


def test_wrong_site_raises(tmp_path: Path) -> None:
    csv = tmp_path / "feat.csv"
    thr = tmp_path / "thr.json"
    _synthetic_features_csv(csv)
    _thresholds_json(thr, csv)
    with pytest.raises(ValueError, match="12117500"):
        run_risk_forecast_12h(site_no="99999999", features_csv=csv, thresholds_json=thr)

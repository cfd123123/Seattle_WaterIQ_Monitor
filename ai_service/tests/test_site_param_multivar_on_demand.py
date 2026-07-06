"""Smoke test for on-demand multivariate IF snapshot."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from models.site_param_multivar_anomaly_on_demand import site_param_multivar_anomaly_from_features


def test_site_param_multivar_anomaly_synthetic(tmp_path: Path) -> None:
    n = 80
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "datetime_utc": idx,
            "63680": np.linspace(1.0, 2.0, n),
            "precipitation_mm": np.zeros(n),
            "upstream_discharge_cfs_12116400": np.linspace(100.0, 200.0, n),
        }
    )
    csv = tmp_path / "feat.csv"
    df.to_csv(csv, index=False)
    out = site_param_multivar_anomaly_from_features(csv, site_no="12117500")
    assert out["site_no"] == "12117500"
    assert out["model_version"] == "site-param-iforest-multivar-ondemand-v1"
    assert out["anomaly_available"] is True
    assert isinstance(out["is_anomaly"], bool)

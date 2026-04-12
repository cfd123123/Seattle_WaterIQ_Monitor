"""
On-demand univariate anomaly detection per site and USGS parameter_cd (00060 discharge / 63680 turbidity)
from IV hourly series.

Uses RobustScaler + IsolationForest, fit in-request on the window, score the **last valid hourly point**.
Cold start: insufficient hourly points -> anomaly_available=false with a reason code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

from forecast_engine import load_hourly_series

ALLOWED_PARAMETERS: Final[tuple[str, ...]] = ("00060", "63680")
MODEL_VERSION = "site-param-iforest-ondemand-v1"
MIN_HOURLY_POINTS = 72
MAX_TRAIN_POINTS = 2500


def site_param_anomaly_from_iv_csv(
    csv_path: Path,
    *,
    site_no: str,
    parameter_cd: str,
) -> dict[str, Any]:
    site_no = str(site_no).strip()
    parameter_cd = str(parameter_cd).strip()

    if parameter_cd not in ALLOWED_PARAMETERS:
        return {
            "site_no": site_no,
            "parameter_cd": parameter_cd,
            "anomaly_available": False,
            "reason": "unsupported_parameter_cd",
            "samples_used": 0,
            "sample_timestamp": None,
            "model_version": MODEL_VERSION,
            "anomaly_score": None,
            "threshold": None,
            "is_anomaly": None,
        }

    s = load_hourly_series(csv_path, site_no, parameter_cd)
    if s.empty:
        return {
            "site_no": site_no,
            "parameter_cd": parameter_cd,
            "anomaly_available": False,
            "reason": "no_series_or_column",
            "samples_used": 0,
            "sample_timestamp": None,
            "model_version": MODEL_VERSION,
            "anomaly_score": None,
            "threshold": None,
            "is_anomaly": None,
        }

    y = s.values.astype(float)
    n = len(y)
    if n < MIN_HOURLY_POINTS:
        return {
            "site_no": site_no,
            "parameter_cd": parameter_cd,
            "anomaly_available": False,
            "reason": "insufficient_history",
            "samples_used": n,
            "sample_timestamp": s.index[-1].isoformat(),
            "model_version": MODEL_VERSION,
            "anomaly_score": None,
            "threshold": None,
            "is_anomaly": None,
        }

    window = y[-MAX_TRAIN_POINTS:]
    ts_window = s.index[-MAX_TRAIN_POINTS :]
    X = window.reshape(-1, 1)

    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X)

    max_samples = min(256, len(X_scaled))
    iso = IsolationForest(
        n_estimators=200,
        max_samples=max_samples,
        contamination=0.05,
        random_state=42,
    )
    iso.fit(X_scaled)

    last = X_scaled[-1:]
    pred_label = int(iso.predict(last)[0])
    raw = float((-iso.score_samples(last))[0])
    train_scores = -iso.score_samples(X_scaled)
    thresh = float(np.percentile(train_scores, 95))

    sample_ts = ts_window[-1].isoformat()
    is_anomaly = pred_label == -1

    return {
        "site_no": site_no,
        "parameter_cd": parameter_cd,
        "anomaly_available": True,
        "reason": None,
        "samples_used": len(window),
        "sample_timestamp": sample_ts,
        "model_version": MODEL_VERSION,
        "anomaly_score": round(raw, 6),
        "threshold": round(thresh, 6),
        "is_anomaly": is_anomaly,
    }

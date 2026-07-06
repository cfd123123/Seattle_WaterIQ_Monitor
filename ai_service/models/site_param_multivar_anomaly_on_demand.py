"""
On-demand multivariate IsolationForest for turbidity (63680 + precipitation + upstream discharge).

Uses the same feature columns and hyperparameters as ``turbidity_tier_vs_multivar_if_eval``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .turbidity_state_monitoring import _resolve_cutoff_index, load_features
from .turbidity_tier_vs_multivar_if_eval import (
    MULTIVAR_MODEL_VERSION,
    _row_all_finite,
    _score_multivar_if_one_hour,
    build_multivar_matrix,
)


def site_param_multivar_anomaly_from_features(
    features_csv: Path,
    *,
    site_no: str,
    reference_utc: str | None = None,
) -> dict[str, Any]:
    """
    Score one hour on the hourly features grid with rolling multivariate IF (no exog ffill).

    Returns HTTP-friendly dict with ``anomaly_available=false`` when exog is incomplete at t
    or history is insufficient.
    """
    csv_path = Path(features_csv)
    if not csv_path.is_file():
        raise FileNotFoundError(f"features CSV not found: {csv_path}")

    df = load_features(csv_path, use_exog_ffill=False)
    y = df["63680"]
    ref_ts: pd.Timestamp | None = None
    if reference_utc and reference_utc.strip():
        ref_ts = pd.Timestamp(reference_utc.strip())

    try:
        ix = _resolve_cutoff_index(y, ref_ts)
    except ValueError as e:
        return {
            "site_no": site_no.strip(),
            "anomaly_available": False,
            "reason": "timestamp_not_on_grid",
            "samples_used": 0,
            "sample_timestamp": ref_ts.isoformat() if ref_ts is not None else None,
            "model_version": MULTIVAR_MODEL_VERSION,
            "is_anomaly": None,
        }

    t = y.index[ix]
    x_num = build_multivar_matrix(df)
    multivar_pos = np.flatnonzero(_row_all_finite(x_num))
    scored = _score_multivar_if_one_hour(x_num, multivar_pos, ix)

    return {
        "site_no": site_no.strip(),
        "anomaly_available": bool(scored["mif_available"]),
        "reason": scored["mif_reason"],
        "samples_used": int(scored["mif_samples_used"] or 0),
        "sample_timestamp": t.isoformat(),
        "model_version": MULTIVAR_MODEL_VERSION,
        "is_anomaly": scored["mif_is_anomaly"],
    }

"""
Live 12h turbidity RISK forecast (Phase B) for site 12117500.

Uses frozen ``state_thresholds.json`` (v2.1 tiers) and hourly features CSV with
``use_precip_ffill=False``, ``use_upstream_ffill=True`` (same as Phase A' backtest).

Primary model: ``persistence_alert`` / ``persistence_max_tier`` from
``turbidity_risk_class_backtest`` (no NTU regression curve).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest_turbidity_exog_ridge_lgbm import UPSTREAM_DISCHARGE_COL
from .turbidity_risk_forecast_backtest import DEFAULT_THRESHOLDS_JSON, recommend_alert_from_max_tier
from .turbidity_state_monitoring import (
    DEFAULT_FEATURES_CSV,
    DEFAULT_SITE_NO,
    MODEL_VERSION,
    _resolve_cutoff_index,
    is_gap_tier,
    is_quality_alert_tier,
    label_alert_tier,
    load_features,
    tier_is_anomaly,
)

PHASE_B_MODEL_KEY = "persistence_alert"
PHASE_B_MAX_TIER_MODEL_KEY = "persistence_max_tier"
HORIZONS = list(range(1, 13))


def _persistence_predictions(tier_at_t: str) -> tuple[int, str]:
    """Mirror ``_predict_baseline`` in ``turbidity_risk_class_backtest`` for one cutoff."""
    t_now = str(tier_at_t)
    if is_quality_alert_tier(t_now):
        max_tier = t_now
        alert_12h = 1
    else:
        max_tier = "NORMAL"
        alert_12h = 0
    return alert_12h, max_tier


def rationale_template_key(
    *,
    tier_at_t: str,
    recommend_alert: bool,
    alert_12h_forecast: int,
) -> str:
    """i18n key for one-line rationale (frontend ``messages.ts``)."""
    if is_gap_tier(tier_at_t):
        return "forecast.turbidityRisk.rationale.gap"
    if recommend_alert or alert_12h_forecast == 1:
        if tier_at_t == "CRITICAL":
            return "forecast.turbidityRisk.rationale.persistenceCritical"
        if tier_at_t == "HIGH":
            return "forecast.turbidityRisk.rationale.persistenceHigh"
        return "forecast.turbidityRisk.rationale.persistenceElevated"
    return "forecast.turbidityRisk.rationale.persistenceNormal"


def horizon_tier_strip(max_tier: str) -> list[dict[str, Any]]:
    """Simplified 1..12h strip: persistence repeats the same predicted tier each hour."""
    tier = max_tier if is_quality_alert_tier(max_tier) else "NORMAL"
    return [{"horizon_h": h, "tier": tier} for h in HORIZONS]


def run_risk_forecast_12h(
    *,
    site_no: str = DEFAULT_SITE_NO,
    features_csv: Path = DEFAULT_FEATURES_CSV,
    thresholds_json: Path = DEFAULT_THRESHOLDS_JSON,
    reference_utc: str | None = None,
) -> dict[str, Any]:
    """
    Point forecast of 12h alert risk at reference hour ``T`` (default: latest in CSV).

    Returns alert probability semantics as binary persistence flags, max tier, and
  ``recommend_alert`` (max tier in 1..12h is WATCH+ under persistence).
    """
    site = site_no.strip()
    if site != DEFAULT_SITE_NO:
        raise ValueError(f"Phase B risk forecast is only wired for site {DEFAULT_SITE_NO}")

    csv_path = Path(features_csv)
    if not csv_path.is_file():
        raise FileNotFoundError(f"features CSV not found: {csv_path}")

    thr_path = Path(thresholds_json)
    if not thr_path.is_file():
        raise FileNotFoundError(f"thresholds JSON not found: {thr_path}")

    thresholds = json.loads(thr_path.read_text(encoding="utf-8"))
    df = load_features(
        csv_path,
        use_exog_ffill=False,
        use_precip_ffill=False,
        use_upstream_ffill=True,
    )
    y = df["63680"]
    alert_tiers = label_alert_tier(y, thresholds)

    ref_ts: pd.Timestamp | None = None
    if reference_utc and str(reference_utc).strip():
        ref_ts = pd.Timestamp(reference_utc.strip())
    ix = _resolve_cutoff_index(y, ref_ts)
    tier_at_t = str(alert_tiers.iloc[ix])

    alert_12h, max_tier = _persistence_predictions(tier_at_t)
    recommend = recommend_alert_from_max_tier(max_tier)
    rationale_key = rationale_template_key(
        tier_at_t=tier_at_t,
        recommend_alert=recommend,
        alert_12h_forecast=alert_12h,
    )

    y_val = float(y.iloc[ix]) if np.isfinite(y.iloc[ix]) else None
    return {
        "site_no": site,
        "model_version": MODEL_VERSION,
        "phase_b_model": PHASE_B_MODEL_KEY,
        "phase_b_max_tier_model": PHASE_B_MAX_TIER_MODEL_KEY,
        "reference_utc": y.index[ix].isoformat(),
        "features_csv": str(csv_path.resolve()),
        "thresholds_path": str(thr_path.resolve()),
        "tier_at_t": tier_at_t,
        "63680": round(y_val, 6) if y_val is not None else None,
        "is_anomaly_at_t": tier_is_anomaly(tier_at_t),
        "alert_12h_forecast": int(alert_12h),
        "max_tier_forecast": max_tier,
        "recommend_alert": bool(recommend),
        "rationale_template_key": rationale_key,
        "horizon_tiers": horizon_tier_strip(max_tier),
        "exog_policy": {
            "use_precip_ffill": False,
            "use_upstream_ffill": True,
            "upstream_ffill_limit_hours": 24,
        },
        "label_note": (
            "Persistence: if current quality tier is WATCH/HIGH/CRITICAL, "
            "forecast assumes the same through h=1..12 (no NTU regression)."
        ),
    }

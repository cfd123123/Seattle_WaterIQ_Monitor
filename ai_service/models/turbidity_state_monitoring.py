"""
Turbidity (63680) monitoring: alert tiers (v2) and legacy four-state labels (v1 rules).

Spec: plan/turbidity_state_monitoring.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest_turbidity_exog_ridge_lgbm import (
    UPSTREAM_DISCHARGE_COL,
    _causal_fill_series,
    _split_index_for_holdout,
)

STATES = ("Normal", "Rising", "High", "Recovering")
# Water-quality alert tiers (finite 63680 only).
ALERT_TIERS = ("NORMAL", "WATCH", "HIGH", "CRITICAL")
# Missing / unreliable observation tiers (never treated as NORMAL or is_anomaly).
GAP_TIERS = ("SENSOR_GAP", "DATA_STALE", "UNKNOWN")
ALL_ALERT_TIERS = ALERT_TIERS + GAP_TIERS
WARNING_HORIZONS = (6, 12)
MODEL_VERSION = "turbidity-state-v2.1"
DEFAULT_DATA_STALE_HOURS = 3
DEFAULT_ABSOLUTE_NTU_CRITICAL = 50.0
MIN_DELTA_WATCH_1H = 0.1
MIN_DELTA_HIGH_1H = 0.266667
# Calibration (threshold quantiles) uses only UTC months with >= this valid 63680 rate on the tuning grid.
CALIBRATION_MIN_MONTH_VALID_RATE = 0.70
DEFAULT_SITE_NO = "12117500"
DEFAULT_FEATURES_CSV = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "features_12117500_63680_openmeteo_upstream_2022.csv"
)
# Max hours to forward-fill upstream discharge gaps (USGS IV can be sparse).
UPSTREAM_FFILL_LIMIT_HOURS = 24


def load_features(
    csv_path: Path,
    *,
    use_exog_ffill: bool = True,
    use_precip_ffill: bool | None = None,
    use_upstream_ffill: bool | None = None,
    upstream_ffill_limit: int = UPSTREAM_FFILL_LIMIT_HOURS,
) -> pd.DataFrame:
    """
    Load site feature CSV with optional causal exogenous fills.

    ``use_precip_ffill`` / ``use_upstream_ffill`` default to ``use_exog_ffill`` when unset.
    Preferred risk-class policy: ``use_precip_ffill=False``, ``use_upstream_ffill=True`` —
    hourly precipitation is an interval amount (not a level), so forward-fill would imply
    rain continued into dry hours and distort lag sums; upstream discharge may be ffilled
    briefly because IV gaps are sensor timing, not physical absence of flow.
    """
    precip_ffill = use_exog_ffill if use_precip_ffill is None else use_precip_ffill
    upstream_ffill = use_exog_ffill if use_upstream_ffill is None else use_upstream_ffill

    df = pd.read_csv(csv_path)
    if "datetime_utc" not in df.columns:
        raise ValueError("features CSV must contain datetime_utc")
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["datetime_utc"]).sort_values("datetime_utc")
    df = df.drop_duplicates(subset=["datetime_utc"], keep="last")
    df = df.set_index("datetime_utc")
    if "63680" not in df.columns:
        raise ValueError("missing column 63680")
    out = df.copy()
    out["63680"] = pd.to_numeric(out["63680"], errors="coerce")
    if "precipitation_mm" in out.columns:
        prec = pd.to_numeric(out["precipitation_mm"], errors="coerce")
        if precip_ffill:
            out["precipitation_mm"] = _causal_fill_series(prec, limit=upstream_ffill_limit)
        else:
            # Keep NaN between observed hourly amounts; do not carry rain into dry hours.
            out["precipitation_mm"] = prec
    if UPSTREAM_DISCHARGE_COL in out.columns:
        q_up = pd.to_numeric(out[UPSTREAM_DISCHARGE_COL], errors="coerce")
        if upstream_ffill:
            out[UPSTREAM_DISCHARGE_COL] = _causal_fill_series(q_up, limit=upstream_ffill_limit)
        else:
            out[UPSTREAM_DISCHARGE_COL] = q_up
    return out


def _monthly_valid_rates_within_mask(y: pd.Series, mask: pd.Series) -> pd.DataFrame:
    """Per UTC year-month valid 63680 rate on hours where ``mask`` is True."""
    sub = y[mask].astype(float)
    rows: list[dict[str, Any]] = []
    for ym, grp in sub.groupby(sub.index.strftime("%Y-%m"), sort=True):
        grid_n = len(grp)
        valid_n = int(np.isfinite(grp.to_numpy(dtype=float, copy=False)).sum())
        rows.append(
            {
                "year_month": ym,
                "grid_hours": grid_n,
                "y_valid_n": valid_n,
                "y_valid_rate": round(valid_n / grid_n, 6) if grid_n else None,
            }
        )
    return pd.DataFrame(rows)


def build_calibration_mask(
    tuning_mask: pd.Series,
    y: pd.Series,
    *,
    min_month_valid_rate: float = CALIBRATION_MIN_MONTH_VALID_RATE,
) -> tuple[pd.Series, dict[str, Any]]:
    """
    Restrict calibration hours to tuning months with sufficient 63680 coverage.

    Months with y_valid_rate < ``min_month_valid_rate`` on the tuning hour grid are excluded
    from threshold estimation (all hours in that UTC year-month within tuning are dropped).
    """
    monthly = _monthly_valid_rates_within_mask(y, tuning_mask)
    excluded: list[str] = []
    included: list[str] = []
    for row in monthly.itertuples(index=False):
        ym = str(row.year_month)
        rate = row.y_valid_rate
        if rate is None or rate < min_month_valid_rate:
            excluded.append(ym)
        else:
            included.append(ym)

    month_labels = pd.Series(y.index.strftime("%Y-%m"), index=y.index)
    cal_mask = tuning_mask & ~month_labels.isin(excluded)

    meta: dict[str, Any] = {
        "calibration_min_month_valid_rate": min_month_valid_rate,
        "calibration_months_excluded": excluded,
        "calibration_months_included": included,
        "calibration_months_included_n": len(included),
        "calibration_months_excluded_n": len(excluded),
        "tuning_n_hours": int(tuning_mask.sum()),
        "calibration_hours_after_month_filter": int(cal_mask.sum()),
    }
    return cal_mask, meta


def _tuning_validity_counts(
    tuning_mask: pd.Series,
    y: pd.Series,
    prec: pd.Series | None,
    q_up: pd.Series | None,
) -> dict[str, Any]:
    """Non-null / finite counts on the calibration hour grid (mask True rows)."""
    tuning_n = int(tuning_mask.sum())
    y_tuning = y[tuning_mask].astype(float)
    y_valid_n = int(np.isfinite(y_tuning).sum())
    y_missing_n = tuning_n - y_valid_n
    # Denominator is all tuning rows, not y_valid_n (quantiles use only valid 63680).
    y_missing_rate = round(y_missing_n / tuning_n, 6) if tuning_n else None
    out: dict[str, Any] = {
        "y_valid_n": y_valid_n,
        "y_missing_n": y_missing_n,
        "y_missing_rate": y_missing_rate,
    }
    if prec is not None:
        prec_t = prec[tuning_mask].astype(float)
        out["precip_valid_n"] = int(np.isfinite(prec_t).sum())
    if q_up is not None:
        q_t = q_up[tuning_mask].astype(float)
        out["upstream_q_valid_n"] = int(np.isfinite(q_t).sum())
    return out


def compute_thresholds(
    y: pd.Series,
    prec: pd.Series | None,
    q_up: pd.Series | None,
    tuning_mask: pd.Series,
    *,
    recovery_window_hours: int,
    min_month_valid_rate: float = CALIBRATION_MIN_MONTH_VALID_RATE,
    absolute_ntu_critical: float = DEFAULT_ABSOLUTE_NTU_CRITICAL,
) -> dict[str, Any]:
    calibration_mask, month_meta = build_calibration_mask(
        tuning_mask, y, min_month_valid_rate=min_month_valid_rate
    )
    validity = _tuning_validity_counts(calibration_mask, y, prec, q_up)
    tuning_n = int(tuning_mask.sum())
    calibration_n = int(calibration_mask.sum())
    tuning_ix = y.index[calibration_mask]

    yt = y[calibration_mask].astype(float)
    yt = yt[np.isfinite(yt)]
    if len(yt) < 100:
        raise ValueError("too few tuning hours for threshold estimation")
    dy = yt.diff().dropna()
    dy_pos = dy[dy > 0]
    p25 = float(np.nanquantile(yt, 0.25))
    p50 = float(np.nanquantile(yt, 0.50))
    theta_low = float(np.nanquantile(yt, 0.75))
    theta_high = float(np.nanquantile(yt, 0.90))
    p95 = float(np.nanquantile(yt, 0.95))
    p99 = float(np.nanquantile(yt, 0.99))
    iqr = float(theta_low - p25)
    delta_up = float(
        max(MIN_DELTA_WATCH_1H, np.nanquantile(dy_pos, 0.75) if len(dy_pos) > 10 else MIN_DELTA_WATCH_1H)
    )
    delta_up_p90 = float(np.nanquantile(dy_pos, 0.90) if len(dy_pos) > 10 else 0.1)

    thr: dict[str, Any] = {
        "theta_low": round(theta_low, 6),
        "theta_high": round(theta_high, 6),
        "delta_up_1h": round(delta_up, 6),
        "recovery_window_hours": int(recovery_window_hours),
        "tuning_hours": tuning_n,
        "tuning_n_hours": tuning_n,
        "calibration_hours_after_month_filter": calibration_n,
        **month_meta,
        **validity,
        "tuning_start_utc": str(tuning_ix.min()) if calibration_n else None,
        "tuning_end_utc": str(tuning_ix.max()) if calibration_n else None,
        "y_tuning_p25": round(p25, 6),
        "y_tuning_p50": round(p50, 6),
        "baseline_median": round(p50, 6),
        "y_tuning_p75": round(theta_low, 6),
        "y_tuning_p90": round(theta_high, 6),
        "y_tuning_p95": round(p95, 6),
        "y_tuning_p99": round(p99, 6),
        "y_tuning_iqr": round(iqr, 6),
        "delta_up_P90": round(delta_up_p90, 6),
        "absolute_ntu_critical": round(float(absolute_ntu_critical), 6),
        "model_version": MODEL_VERSION,
    }
    if prec is not None:
        p6: list[float] = []
        idx = prec.index[calibration_mask]
        for t in idx:
            sl = prec.loc[:t].iloc[-6:]
            if len(sl):
                p6.append(float(sl.sum()))
        if p6:
            thr["precip_6h_mm_p90_tuning"] = round(float(np.nanquantile(p6, 0.90)), 6)
    if q_up is not None:
        qu = q_up[calibration_mask].astype(float)
        qu = qu[np.isfinite(qu)]
        if len(qu) > 50:
            thr["upstream_q_p90_tuning"] = round(float(np.nanquantile(qu, 0.90)), 4)
    thr["tier_rules"] = build_tier_rules_metadata(thr)
    return thr


def _resolve_delta_high(thresholds: dict[str, Any]) -> float:
    raw = thresholds.get("delta_up_P90", MIN_DELTA_HIGH_1H)
    return float(max(MIN_DELTA_HIGH_1H, float(raw)))


def build_tier_rules_metadata(
    thresholds: dict[str, Any],
    *,
    absolute_ntu_critical: float | None = None,
) -> dict[str, Any]:
    """Serializable tier rule thresholds for ``state_thresholds.json``."""
    abs_crit = (
        float(absolute_ntu_critical)
        if absolute_ntu_critical is not None
        else float(thresholds.get("absolute_ntu_critical", DEFAULT_ABSOLUTE_NTU_CRITICAL))
    )
    p75 = float(thresholds["theta_low"])
    p90 = float(thresholds.get("y_tuning_p90", thresholds["theta_high"]))
    p95 = float(thresholds["y_tuning_p95"])
    p99 = float(thresholds["y_tuning_p99"])
    delta_watch = float(thresholds["delta_up_1h"])
    delta_high = _resolve_delta_high(thresholds)
    return {
        "priority": list(ALERT_TIERS),
        "p75": round(p75, 6),
        "p90": round(p90, 6),
        "p95": round(p95, 6),
        "p99": round(p99, 6),
        "delta_watch_1h": round(delta_watch, 6),
        "delta_high_1h": round(delta_high, 6),
        "absolute_ntu_critical": round(abs_crit, 6),
        "rules": {
            "NORMAL": "finite 63680 and current < P90",
            "WATCH": "finite 63680; current >= P90 OR (current >= P75 AND diff_1h >= delta_watch)",
            "HIGH": "finite 63680; current >= P95 OR (current >= P90 AND diff_1h >= delta_high)",
            "CRITICAL": "finite 63680; current >= P99 OR current >= absolute_ntu_critical",
            "SENSOR_GAP": "current hour invalid (NaN/non-finite); last valid <= stale_hours ago",
            "DATA_STALE": "current hour invalid; last valid observation > stale_hours before index",
            "UNKNOWN": "current hour invalid; no prior valid 63680 on series",
        },
        "data_stale_hours": DEFAULT_DATA_STALE_HOURS,
        "gap_tiers": list(GAP_TIERS),
        "model_version_note": (
            "v2.1: missing 63680 hours use SENSOR_GAP / DATA_STALE / UNKNOWN; "
            "is_anomaly is true only for WATCH/HIGH/CRITICAL"
        ),
    }


def diff_1h_from_previous_valid(y: pd.Series) -> pd.Series:
    """
    Hour-over-hour change using only the immediately prior **valid** hour.

    NaN when the previous valid hour is missing or more than one hour before ``t``.
    """
    yv = y.astype(float)
    out = pd.Series(np.nan, index=y.index, dtype=float)
    last_t: pd.Timestamp | None = None
    last_val: float | None = None
    for t in y.index:
        val = yv.loc[t]
        if not np.isfinite(val):
            continue
        if last_t is not None and last_val is not None:
            gap_h = (t - last_t) / pd.Timedelta(hours=1)
            if gap_h == 1:
                out.loc[t] = float(val) - last_val
        last_t = t
        last_val = float(val)
    return out


def is_gap_tier(tier: str) -> bool:
    return str(tier) in GAP_TIERS


def is_quality_alert_tier(tier: str) -> bool:
    """True for WATCH/HIGH/CRITICAL (actionable water-quality alerts)."""
    return str(tier) in ("WATCH", "HIGH", "CRITICAL")


def tier_is_anomaly(tier: str) -> bool:
    """Gaps are not alerts; only elevated quality tiers count as anomaly."""
    return is_quality_alert_tier(tier)


def _gap_tier_at(hours_since_last_valid: float | None, *, stale_hours: float = DEFAULT_DATA_STALE_HOURS) -> str:
    """
    Label a missing-y hour.

    SENSOR_GAP: invalid 63680; last valid within ``stale_hours``.
    DATA_STALE: invalid; last valid more than ``stale_hours`` before this index.
    UNKNOWN: invalid; no prior finite 63680 in the series.
    """
    if hours_since_last_valid is None:
        return "UNKNOWN"
    if hours_since_last_valid > stale_hours:
        return "DATA_STALE"
    return "SENSOR_GAP"


def _alert_tier_at(
    current: float,
    diff_1h: float,
    *,
    p75: float,
    p90: float,
    p95: float,
    p99: float,
    delta_watch: float,
    delta_high: float,
    absolute_ntu_critical: float,
) -> str:
    if current >= p99 or current >= absolute_ntu_critical:
        return "CRITICAL"
    diff_ok = np.isfinite(diff_1h)
    if current >= p95 or (current >= p90 and diff_ok and diff_1h >= delta_high):
        return "HIGH"
    if current >= p90 or (current >= p75 and diff_ok and diff_1h >= delta_watch):
        return "WATCH"
    return "NORMAL"


def label_alert_tier(
    y: pd.Series,
    thresholds: dict[str, Any],
    *,
    data_stale_hours: float | None = None,
) -> pd.Series:
    """
    Alert tier per hour.

    Finite 63680: CRITICAL > HIGH > WATCH > NORMAL (quantile rules).
    Missing 63680: SENSOR_GAP / DATA_STALE / UNKNOWN (never NORMAL).
    """
    tier_meta = thresholds.get("tier_rules") or build_tier_rules_metadata(thresholds)
    stale_h = float(
        data_stale_hours
        if data_stale_hours is not None
        else tier_meta.get("data_stale_hours", DEFAULT_DATA_STALE_HOURS)
    )
    p75 = float(tier_meta["p75"])
    p90 = float(tier_meta["p90"])
    p95 = float(tier_meta["p95"])
    p99 = float(tier_meta["p99"])
    delta_watch = float(tier_meta["delta_watch_1h"])
    delta_high = float(tier_meta["delta_high_1h"])
    abs_crit = float(tier_meta["absolute_ntu_critical"])

    yv = y.astype(float)
    diff = diff_1h_from_previous_valid(y)
    tiers: list[str] = []
    last_t: pd.Timestamp | None = None
    for t in y.index:
        val = yv.loc[t]
        if not np.isfinite(val):
            hours_since: float | None = None
            if last_t is not None:
                hours_since = (t - last_t) / pd.Timedelta(hours=1)
            tiers.append(_gap_tier_at(hours_since, stale_hours=stale_h))
            continue
        d1 = float(diff.loc[t]) if np.isfinite(diff.loc[t]) else np.nan
        tiers.append(
            _alert_tier_at(
                float(val),
                d1,
                p75=p75,
                p90=p90,
                p95=p95,
                p99=p99,
                delta_watch=delta_watch,
                delta_high=delta_high,
                absolute_ntu_critical=abs_crit,
            )
        )
        last_t = t
    return pd.Series(tiers, index=y.index, dtype=object)


def label_states(y: pd.Series, thresholds: dict[str, Any]) -> pd.Series:
    theta_low = float(thresholds["theta_low"])
    theta_high = float(thresholds["theta_high"])
    delta_up = float(thresholds["delta_up_1h"])
    w_rec = int(thresholds["recovery_window_hours"])

    yv = y.astype(float)
    dy = yv.diff()
    states: list[str] = []
    last_high_i = -10**9
    arr = yv.to_numpy()
    for i in range(len(arr)):
        val = arr[i]
        if not np.isfinite(val):
            states.append("Normal")
            continue
        d1 = float(dy.iloc[i]) if i > 0 and np.isfinite(dy.iloc[i]) else 0.0
        if val >= theta_high:
            states.append("High")
            last_high_i = i
        elif val >= theta_low and d1 > delta_up:
            states.append("Rising")
        elif (i - last_high_i) <= w_rec and val < theta_high and d1 < 0:
            states.append("Recovering")
        else:
            states.append("Normal")
    return pd.Series(states, index=y.index, dtype=object)


def rule_warning_high_at_T(
    T_ix: int,
    y: pd.Series,
    states: pd.Series,
    prec: pd.Series | None,
    q_up: pd.Series | None,
    thresholds: dict[str, Any],
    horizon: int,
) -> bool:
    """True if rule predicts High within the next ``horizon`` hours (evaluation uses actual window)."""
    n = len(y)
    h = int(horizon)
    if T_ix + h >= n:
        return False
    st = str(states.iloc[T_ix])
    if st in ("High", "Rising"):
        return True
    if st == "Recovering":
        return False
    y_t = float(y.iloc[T_ix]) if np.isfinite(y.iloc[T_ix]) else np.nan
    if np.isfinite(y_t) and y_t >= float(thresholds["theta_low"]):
        if prec is not None and "precip_6h_mm_p90_tuning" in thresholds:
            p6 = float(prec.iloc[max(0, T_ix - 5) : T_ix + 1].sum())
            if p6 >= float(thresholds["precip_6h_mm_p90_tuning"]):
                return True
        if q_up is not None and "upstream_q_p90_tuning" in thresholds:
            qu = float(q_up.iloc[T_ix])
            if np.isfinite(qu) and qu >= float(thresholds["upstream_q_p90_tuning"]):
                return True
    return False


def _confusion(pred: bool, actual: bool) -> str:
    if pred and actual:
        return "tp"
    if pred and not actual:
        return "fp"
    if not pred and actual:
        return "fn"
    return "tn"


def _metrics_from_counts(tp: int, fp: int, fn: int, tn: int) -> dict[str, Any]:
    prec_score = tp / (tp + fp) if (tp + fp) else None
    rec_score = tp / (tp + fn) if (tp + fn) else None
    f1 = None
    if prec_score is not None and rec_score is not None and (prec_score + rec_score) > 0:
        f1 = 2 * prec_score * rec_score / (prec_score + rec_score)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(prec_score, 4) if prec_score is not None else None,
        "recall": round(rec_score, 4) if rec_score is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "n_cutoffs": int(tp + fp + fn + tn),
    }


def _first_high_lead_hours(states: pd.Series, i: int, h: int) -> int | None:
    for k in range(1, h + 1):
        if states.iloc[i + k] == "High":
            return k
    return None


def evaluate_warning_holdout(
    y: pd.Series,
    states: pd.Series,
    prec: pd.Series | None,
    q_up: pd.Series | None,
    thresholds: dict[str, Any],
    holdout_mask: pd.Series,
    horizons: tuple[int, ...] = WARNING_HORIZONS,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    idx = np.where(holdout_mask.to_numpy())[0]
    for h in horizons:
        tp = fp = fn = tn = 0
        lead_hours: list[int] = []
        for i in idx:
            if i + h >= len(y):
                continue
            pred = rule_warning_high_at_T(i, y, states, prec, q_up, thresholds, h)
            actual = bool((states.iloc[i + 1 : i + h + 1] == "High").any())
            bucket = _confusion(pred, actual)
            if bucket == "tp":
                tp += 1
                lh = _first_high_lead_hours(states, i, h)
                if lh is not None:
                    lead_hours.append(lh)
            elif bucket == "fp":
                fp += 1
            elif bucket == "fn":
                fn += 1
            else:
                tn += 1
        block = _metrics_from_counts(tp, fp, fn, tn)
        if lead_hours:
            arr = np.asarray(lead_hours, dtype=float)
            block["lead_time_hours"] = {
                "n_tp": len(lead_hours),
                "mean": round(float(arr.mean()), 4),
                "median": round(float(np.median(arr)), 4),
                "p25": round(float(np.quantile(arr, 0.25)), 4),
                "p75": round(float(np.quantile(arr, 0.75)), 4),
            }
        else:
            block["lead_time_hours"] = None
        out[str(h)] = block
    return out


def evaluate_never_alert_baseline(
    y: pd.Series,
    states: pd.Series,
    holdout_mask: pd.Series,
    horizons: tuple[int, ...] = WARNING_HORIZONS,
) -> dict[str, Any]:
    """Baseline that never fires a warning (spec success criterion comparison)."""
    out: dict[str, Any] = {}
    idx = np.where(holdout_mask.to_numpy())[0]
    for h in horizons:
        tp = fp = fn = tn = 0
        for i in idx:
            if i + h >= len(y):
                continue
            pred = False
            actual = bool((states.iloc[i + 1 : i + h + 1] == "High").any())
            bucket = _confusion(pred, actual)
            if bucket == "tp":
                tp += 1
            elif bucket == "fp":
                fp += 1
            elif bucket == "fn":
                fn += 1
            else:
                tn += 1
        out[str(h)] = _metrics_from_counts(tp, fp, fn, tn)
    return out


def holdout_state_fractions(states: pd.Series, holdout_mask: pd.Series) -> dict[str, Any]:
    sub = states[holdout_mask]
    n = int(len(sub))
    if n == 0:
        return {"n_hours": 0, "fractions": {s: None for s in STATES}}
    counts = {s: int((sub == s).sum()) for s in STATES}
    return {
        "n_hours": n,
        "counts": counts,
        "fractions": {s: round(counts[s] / n, 6) for s in STATES},
    }


def holdout_tier_fractions(tiers: pd.Series, holdout_mask: pd.Series) -> dict[str, Any]:
    sub = tiers[holdout_mask]
    n = int(len(sub))
    if n == 0:
        return {"n_hours": 0, "counts": {t: 0 for t in ALL_ALERT_TIERS}, "fractions": {t: None for t in ALL_ALERT_TIERS}}
    counts = {t: int((sub == t).sum()) for t in ALL_ALERT_TIERS}
    return {
        "n_hours": n,
        "counts": counts,
        "fractions": {t: round(counts[t] / n, 6) for t in ALL_ALERT_TIERS},
    }


def _episodes_high(states: pd.Series) -> list[dict[str, Any]]:
    eps: list[dict[str, Any]] = []
    in_ep = False
    start = None
    for t, s in states.items():
        if s == "High" and not in_ep:
            in_ep = True
            start = t
        elif s != "High" and in_ep:
            eps.append(
                {
                    "start_utc": str(start),
                    "end_utc": str(t),
                    "hours": int((t - start) / pd.Timedelta(hours=1)),
                }
            )
            in_ep = False
            start = None
    if in_ep and start is not None:
        t = states.index[-1]
        eps.append(
            {
                "start_utc": str(start),
                "end_utc": str(t),
                "hours": int((t - start) / pd.Timedelta(hours=1)) + 1,
            }
        )
    return eps


def maybe_plot(
    states: pd.Series,
    y: pd.Series,
    out_path: Path,
    split_time: pd.Timestamp | None,
    *,
    site_no: str = DEFAULT_SITE_NO,
) -> bool:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(14, 3))
    ax.plot(y.index, y.values, color="#1f77b4", lw=0.35, alpha=0.8)
    for st, c in zip(STATES, ["#95a5a6", "#f39c12", "#e74c3c", "#27ae60"]):
        m = states == st
        if m.any():
            ax.scatter(y.index[m], y.values[m], s=4, c=c, label=st, alpha=0.6)
    if split_time is not None:
        ax.axvline(split_time, color="black", ls=":", lw=1, label="holdout start")
    ax.set_ylabel("63680")
    ax.set_title(f"Turbidity states — {site_no}")
    ax.legend(loc="upper right", fontsize=6, ncol=5)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return True


def _resolve_cutoff_index(y: pd.Series, ref_utc_hour: pd.Timestamp | None) -> int:
    if ref_utc_hour is None:
        return len(y) - 1
    ref = ref_utc_hour
    if ref.tzinfo is None:
        ref = ref.tz_localize("UTC")
    else:
        ref = ref.tz_convert("UTC")
    ref = ref.floor("h")
    loc = y.index.get_indexer([ref], method="pad")
    if loc.size == 0 or loc[0] < 0:
        raise ValueError("reference hour not in feature series")
    return int(loc[0])


def snapshot_at_reference(
    df: pd.DataFrame,
    thresholds: dict[str, Any],
    states: pd.Series,
    y: pd.Series,
    prec: pd.Series | None,
    q_up: pd.Series | None,
    *,
    alert_tiers: pd.Series | None = None,
    ref_utc_hour: pd.Timestamp | None = None,
    site_no: str = DEFAULT_SITE_NO,
) -> dict[str, Any]:
    """Current legacy state, alert tier, and rule warnings at one cutoff (for API / ops)."""
    ix = _resolve_cutoff_index(y, ref_utc_hour)
    t = y.index[ix]
    st = str(states.iloc[ix])
    if alert_tiers is None:
        alert_tiers = label_alert_tier(y, thresholds)
    tier = str(alert_tiers.iloc[ix])
    y_val = float(y.iloc[ix]) if np.isfinite(y.iloc[ix]) else None
    diff_s = diff_1h_from_previous_valid(y)
    d1 = float(diff_s.iloc[ix]) if np.isfinite(diff_s.iloc[ix]) else None
    warnings: dict[str, Any] = {}
    for h in WARNING_HORIZONS:
        fire = rule_warning_high_at_T(ix, y, states, prec, q_up, thresholds, h)
        future_high = False
        if ix + h < len(y):
            future_high = bool((states.iloc[ix + 1 : ix + h + 1] == "High").any())
        warnings[str(h)] = {
            "rule_fires": fire,
            "future_high_in_window": future_high if ix + h < len(y) else None,
        }
    tier_meta = thresholds.get("tier_rules") or build_tier_rules_metadata(thresholds)
    return {
        "site_no": site_no,
        "model_version": MODEL_VERSION,
        "reference_utc": t.isoformat(),
        "63680": round(y_val, 6) if y_val is not None else None,
        "state": st,
        "alert_tier": tier,
        "diff_1h": round(d1, 6) if d1 is not None else None,
        "is_anomaly": tier_is_anomaly(tier),
        "warning_horizons": warnings,
        "thresholds": {
            "theta_low": thresholds.get("theta_low"),
            "theta_high": thresholds.get("theta_high"),
            "tier_rules": tier_meta,
        },
    }


def run_state_monitoring(
    features_csv: Path,
    *,
    site_no: str = DEFAULT_SITE_NO,
    holdout_fraction: float = 0.2,
    holdout_min_hours: int = 336,
    recovery_window_hours: int = 48,
    out_dir: Path | None = None,
    write_plot: bool = True,
    thresholds_json: Path | None = None,
    absolute_ntu_critical: float = DEFAULT_ABSOLUTE_NTU_CRITICAL,
) -> dict[str, Any]:
    """
    Full pipeline: thresholds (tuning), labels, holdout metrics, optional artifacts.

    Returns summary dict (also written to ``out_dir/summary.json`` when ``out_dir`` set).
    """
    csv_path = Path(features_csv)
    if not csv_path.is_file():
        raise FileNotFoundError(f"features CSV not found: {csv_path}")

    df = load_features(csv_path)
    y = df["63680"]
    prec = df["precipitation_mm"] if "precipitation_mm" in df.columns else None
    q_up = df[UPSTREAM_DISCHARGE_COL] if UPSTREAM_DISCHARGE_COL in df.columns else None

    n = len(y)
    split_info = _split_index_for_holdout(
        n,
        max_horizon=max(WARNING_HORIZONS),
        holdout_fraction=float(holdout_fraction),
        holdout_min_hours=int(holdout_min_hours),
        min_tuning_hours=2000,
    )
    split_ix = int(split_info["split_index"])
    tuning_mask = pd.Series(y.index < y.index[split_ix], index=y.index)
    holdout_mask = ~tuning_mask

    if thresholds_json is not None and Path(thresholds_json).is_file():
        thresholds = json.loads(Path(thresholds_json).read_text(encoding="utf-8"))
        thresholds.setdefault("recovery_window_hours", recovery_window_hours)
    else:
        thresholds = compute_thresholds(
            y,
            prec,
            q_up,
            tuning_mask,
            recovery_window_hours=int(recovery_window_hours),
            absolute_ntu_critical=float(absolute_ntu_critical),
        )
    thresholds["split_index"] = split_ix
    thresholds["split_time_utc"] = str(y.index[split_ix])
    thresholds["features_csv"] = str(csv_path.resolve())
    thresholds["site_no"] = site_no
    thresholds.setdefault("model_version", MODEL_VERSION)

    if "tier_rules" not in thresholds:
        thresholds["tier_rules"] = build_tier_rules_metadata(
            thresholds, absolute_ntu_critical=absolute_ntu_critical
        )
    thresholds.setdefault("model_version", MODEL_VERSION)

    states = label_states(y, thresholds)
    alert_tiers = label_alert_tier(y, thresholds)
    anomaly = alert_tiers.map(tier_is_anomaly)

    state_counts = {s: int((states == s).sum()) for s in STATES}
    state_counts_holdout = {s: int((states[holdout_mask] == s).sum()) for s in STATES}
    tier_counts = {t: int((alert_tiers == t).sum()) for t in ALL_ALERT_TIERS}
    tier_counts_holdout = {t: int((alert_tiers[holdout_mask] == t).sum()) for t in ALL_ALERT_TIERS}
    fracs = holdout_state_fractions(states, holdout_mask)
    tier_fracs = holdout_tier_fractions(alert_tiers, holdout_mask)

    warning_eval = evaluate_warning_holdout(y, states, prec, q_up, thresholds, holdout_mask)
    never_alert = evaluate_never_alert_baseline(y, states, holdout_mask)
    warning_compare: dict[str, Any] = {}
    for h in WARNING_HORIZONS:
        hs = str(h)
        r_f1 = warning_eval[hs].get("f1")
        n_f1 = never_alert[hs].get("f1")
        warning_compare[hs] = {
            "rule_f1": r_f1,
            "never_alert_f1": n_f1,
            "rule_beats_never_alert": (
                r_f1 is not None and (n_f1 is None or (r_f1 is not None and r_f1 > (n_f1 or 0)))
            ),
        }

    summary: dict[str, Any] = {
        "spec": "plan/turbidity_state_monitoring.md",
        "site_no": site_no,
        "model_version": MODEL_VERSION,
        "states": list(STATES),
        "alert_tiers": list(ALL_ALERT_TIERS),
        "quality_alert_tiers": list(ALERT_TIERS),
        "gap_tiers": list(GAP_TIERS),
        "thresholds": thresholds,
        "state_counts_all": state_counts,
        "state_counts_holdout": state_counts_holdout,
        "tier_counts_all": tier_counts,
        "tier_counts_holdout": tier_counts_holdout,
        "holdout_state_fractions": fracs,
        "holdout_tier_fractions": tier_fracs,
        "anomaly_hours_all": int(anomaly.sum()),
        "anomaly_hours_holdout": int(anomaly[holdout_mask].sum()),
        "high_episodes_all": _episodes_high(states),
        "high_episodes_holdout": _episodes_high(states[holdout_mask]),
        "warning_rule_holdout": warning_eval,
        "warning_never_alert_holdout": never_alert,
        "warning_vs_never_alert": warning_compare,
        "holdout_split": split_info,
        "latest_snapshot": snapshot_at_reference(
            df,
            thresholds,
            states,
            y,
            prec,
            q_up,
            alert_tiers=alert_tiers,
            ref_utc_hour=None,
            site_no=site_no,
        ),
    }

    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        labels = df.copy()
        labels["state"] = states
        labels["alert_tier"] = alert_tiers
        labels["diff_1h"] = diff_1h_from_previous_valid(y)
        labels["is_anomaly"] = anomaly
        labels.reset_index().to_csv(out_path / "hourly_states.csv", index=False)
        (out_path / "state_thresholds.json").write_text(
            json.dumps(thresholds, indent=2), encoding="utf-8"
        )
        (out_path / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if write_plot:
            plotted = maybe_plot(states, y, out_path / "states_timeline.png", y.index[split_ix], site_no=site_no)
            summary["plot_written"] = plotted

    return summary


def _resolve_ai_service_path(p: Path | str | None, default: Path) -> Path:
    if p is None or (isinstance(p, str) and not str(p).strip()):
        return default
    path = Path(p)
    if path.is_absolute():
        return path
    root = Path(__file__).resolve().parent.parent
    return root / path


def run_state_snapshot(
    site_no: str = DEFAULT_SITE_NO,
    *,
    features_csv: Path | str | None = None,
    thresholds_json: Path | str | None = None,
    reference_utc: str | None = None,
    absolute_ntu_critical: float | None = None,
) -> dict[str, Any]:
    """
    Point-in-time alert tier, legacy state, and rule warning flags (same rules as batch monitoring).

    Used by FastAPI ``POST /turbidity/state/snapshot`` and the L3 assistant tool executor.
    """
    features_path = _resolve_ai_service_path(features_csv, DEFAULT_FEATURES_CSV)
    if not features_path.is_file():
        raise FileNotFoundError(f"features CSV not found: {features_path}")

    thr_path: Path | None = None
    if thresholds_json and str(thresholds_json).strip():
        thr_path = _resolve_ai_service_path(thresholds_json, DEFAULT_FEATURES_CSV)

    df = load_features(features_path)
    y = df["63680"]
    prec = df["precipitation_mm"] if "precipitation_mm" in df.columns else None
    q_up = df[UPSTREAM_DISCHARGE_COL] if UPSTREAM_DISCHARGE_COL in df.columns else None
    n = len(y)
    split_info = _split_index_for_holdout(
        n,
        max_horizon=max(WARNING_HORIZONS),
        holdout_fraction=0.2,
        holdout_min_hours=336,
        min_tuning_hours=2000,
    )
    split_ix = int(split_info["split_index"])
    tuning_mask = pd.Series(y.index < y.index[split_ix], index=y.index)
    abs_crit = (
        float(absolute_ntu_critical)
        if absolute_ntu_critical is not None
        else DEFAULT_ABSOLUTE_NTU_CRITICAL
    )
    if thr_path is not None and thr_path.is_file():
        thresholds = json.loads(thr_path.read_text(encoding="utf-8"))
    else:
        thresholds = compute_thresholds(
            y,
            prec,
            q_up,
            tuning_mask,
            recovery_window_hours=48,
            absolute_ntu_critical=abs_crit,
        )
    if "tier_rules" not in thresholds:
        thresholds["tier_rules"] = build_tier_rules_metadata(thresholds)
    states = label_states(y, thresholds)
    alert_tiers = label_alert_tier(y, thresholds)
    ref = None
    if reference_utc and str(reference_utc).strip():
        ref = pd.Timestamp(str(reference_utc).strip())
    return snapshot_at_reference(
        df,
        thresholds,
        states,
        y,
        prec,
        q_up,
        alert_tiers=alert_tiers,
        ref_utc_hour=ref,
        site_no=str(site_no).strip(),
    )

"""
Short-horizon forecast: hourly USGS IV series (UTC) from merged CSV, Ridge 1-step model + recursive
multi-hour rollout on a strict 1-hour calendar grid.

Training rows and walk-forward cutoffs require a full lag window of observed hours and (where
supervised) a non-NaN target at the calendar horizon. Forecast API refuses stale conditioning
relative to UTC hour floor (see MAX_STALENESS_HOURS_DEFAULT).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

FORECAST_MODEL_VERSION = "forecast-ridge-recursive-v2-calendar-grid"
RIDGE_ALPHA_DEFAULT = 2.0
MIN_HOURLY_POINTS = 48
MAX_HORIZON_HOURS = 168
MAX_LAG = 36
# Max hours between UTC forecast reference (hour floor) and last conditioning hour on the grid.
MAX_STALENESS_HOURS_DEFAULT = 2.0
_HOUR = pd.Timedelta(hours=1)

# USGS NWIS commonly uses -999999 (sometimes -99999) for missing / not available numeric values.
_NWIS_MISSING_SENTINELS = (-999999.0, -99999.0)


def _mask_usgs_iv_sentinels(s: pd.Series) -> pd.Series:
    """Replace NWIS missing sentinels with NaN so resampling does not corrupt means."""
    v = pd.to_numeric(s, errors="coerce")
    arr = v.to_numpy(dtype=float, copy=True)
    for bad in _NWIS_MISSING_SENTINELS:
        arr = np.where(np.isclose(arr, bad, rtol=0.0, atol=1.0), np.nan, arr)
    return pd.Series(arr, index=v.index, dtype=float)


def load_hourly_series(
    csv_path: Path,
    site_no: str,
    parameter_cd: str,
    *,
    dense: bool = False,
) -> pd.Series:
    """
    Read IV CSV for one site and parameter; resample to 1h mean (UTC index).

    **Default (``dense=False``) — scheme 1 (calendar grid):** keep every UTC hour from first to
    last sample time; missing hours are NaN. Used for forecast, walk-forward backtests, and
    tuning so horizons are **calendar hours**, not “row offsets” after dropping empty hours.

    **``dense=True`` (legacy):** drop hours with no observed value — only for paths that need a
    compact non-NaN vector (e.g. on-demand anomaly / quick EDA), not for strict hourly forecasting.
    """
    if not csv_path.is_file():
        return pd.Series(dtype=float)
    df = pd.read_csv(csv_path)
    if "datetime" not in df.columns or "site_no" not in df.columns:
        return pd.Series(dtype=float)
    if parameter_cd not in df.columns:
        return pd.Series(dtype=float)
    sub = df[df["site_no"].astype(str).str.strip() == str(site_no).strip()].copy()
    if sub.empty:
        return pd.Series(dtype=float)
    sub["datetime"] = pd.to_datetime(sub["datetime"], utc=True, errors="coerce")
    sub = sub.dropna(subset=["datetime"])
    s = _mask_usgs_iv_sentinels(sub.set_index("datetime")[parameter_cd])
    s = s.sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s = s.resample("1h").mean()
    if dense:
        return s.dropna()
    return s


def hourly_grid_continuity_report(
    s: pd.Series,
    *,
    lag: int | None = None,
    horizons: tuple[int, ...] | list[int] = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12),
    walk_forward_step: int = 1,
) -> dict[str, Any]:
    """
    Diagnostics on the **1-hour resampled calendar grid** (same representation as ``dense=False``
    ``load_hourly_series``): validity ratio, NaN/valid runs, gaps between successive observed hours,
    and counts of walk-forward-eligible cutoffs per horizon (full lag window + non-NaN target at T+h).

    Use this **after** 1h resampling to decide whether strict calendar training (scheme 1) is viable.
    """
    step = max(1, int(walk_forward_step))
    out: dict[str, Any] = {
        "grid_rows": 0,
        "valid_hours": 0,
        "na_hours": 0,
        "valid_ratio": 0.0,
        "time_range_utc": None,
        "max_consecutive_na_hours": 0,
        "max_consecutive_valid_hours": 0,
        "gap_hours_between_successive_valid": None,
        "effective_lag": 0,
        "walk_forward_step": step,
        "walk_forward_eligible_cutoffs_by_horizon": {},
        "notes": [],
    }
    if s.empty:
        out["notes"].append("empty_series")
        return out
    if not isinstance(s.index, pd.DatetimeIndex):
        out["notes"].append("index_not_datetime")
        return out

    n = int(len(s))
    valid_mask = s.notna()
    n_valid = int(valid_mask.sum())
    n_na = int(n - n_valid)
    lag_eff = int(lag) if lag is not None else _effective_lag(n, MAX_LAG)
    out.update(
        {
            "grid_rows": n,
            "valid_hours": n_valid,
            "na_hours": n_na,
            "valid_ratio": round(n_valid / n, 6) if n else 0.0,
            "time_range_utc": [s.index[0].isoformat(), s.index[-1].isoformat()],
            "effective_lag": lag_eff,
        }
    )

    has_value = valid_mask.to_numpy(dtype=bool)
    is_na = ~has_value
    max_na = 0
    cur = 0
    for v in is_na:
        if v:
            cur += 1
            max_na = max(max_na, cur)
        else:
            cur = 0
    max_ok = 0
    cur = 0
    for v in has_value:
        if v:
            cur += 1
            max_ok = max(max_ok, cur)
        else:
            cur = 0
    out["max_consecutive_na_hours"] = int(max_na)
    out["max_consecutive_valid_hours"] = int(max_ok)

    ts_valid = s.dropna().index
    if len(ts_valid) >= 2:
        dh = pd.Series(ts_valid).diff().dropna() / _HOUR
        arr = dh.astype(float).to_numpy()
        out["gap_hours_between_successive_valid"] = {
            "count_gaps": int(len(arr)),
            "max": float(np.max(arr)),
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "p90": float(np.quantile(arr, 0.9)),
            "p95": float(np.quantile(arr, 0.95)),
        }
    else:
        out["gap_hours_between_successive_valid"] = {"count_gaps": 0, "note": "fewer_than_two_valid_hours"}

    idx_start_base = max(MIN_HOURLY_POINTS - 1, lag_eff)
    hs = list(horizons)
    for h in hs:
        h = int(h)
        if h < 1 or h > n:
            continue
        idx_start = idx_start_base
        if idx_start >= n - h:
            out["walk_forward_eligible_cutoffs_by_horizon"][str(h)] = {
                "eligible": 0,
                "possible_cutoffs_skipped_range": 0,
            }
            continue
        eligible = 0
        possible = 0
        for idx_T in range(idx_start, n - h, step):
            possible += 1
            if _lag_slice_complete(s, idx_T, lag_eff) and pd.notna(s.iloc[idx_T + h]):
                eligible += 1
        out["walk_forward_eligible_cutoffs_by_horizon"][str(h)] = {
            "eligible": int(eligible),
            "possible_cutoffs_in_step_loop": int(possible),
            "eligible_ratio": round(eligible / possible, 6) if possible else 0.0,
        }

    if n_valid < MIN_HOURLY_POINTS:
        out["notes"].append("valid_hours_below_MIN_HOURLY_POINTS")
    if out["valid_ratio"] < 0.3:
        out["notes"].append("valid_ratio_below_0_3_sparse_grid")
    if max_na >= lag_eff:
        out["notes"].append("max_consecutive_na_hours_gte_effective_lag (full lag windows only inside contiguous valid segments)")
    return out


def _calendar_span_hours(s: pd.Series) -> int:
    return int(len(s.index))


def _effective_lag(n_calendar_hours: int, max_lag: int = MAX_LAG) -> int:
    """Same rule as before, but n is the number of rows on the hourly grid."""
    lag = min(max_lag, n_calendar_hours // 3, n_calendar_hours - 10)
    return max(int(lag), 6)


def _lag_slice_complete(s: pd.Series, idx_end_inclusive: int, lag: int) -> bool:
    """True iff grid rows [idx_end_inclusive-lag+1, idx_end_inclusive] are all non-NaN (lag hours)."""
    if idx_end_inclusive - lag + 1 < 0:
        return False
    w = s.iloc[idx_end_inclusive - lag + 1 : idx_end_inclusive + 1]
    return int(w.shape[0]) == lag and bool(w.notna().all())


def _utc_reference_hour_floor() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc)).floor("h")


def _find_cutoff_index_for_forecast(
    s: pd.Series,
    *,
    lag: int,
    ref_hour: pd.Timestamp,
    max_staleness_hours: float,
) -> tuple[int | None, str | None]:
    """
    Pick the last grid hour index <= ref_hour such that the lag-hour window ending there is
    fully observed, and (ref_hour - that hour) <= max_staleness_hours.
    """
    if s.empty or not isinstance(s.index, pd.DatetimeIndex):
        return None, "no_series_or_column"
    grid_end = min(ref_hour, s.index[-1])
    sub = s.loc[:grid_end]
    if sub.empty:
        return None, "no_series_or_column"

    pos_end = int(s.index.get_loc(sub.index[-1]))
    if isinstance(pos_end, slice):
        pos_end = pos_end.stop - 1

    for idx_T in range(pos_end, lag - 2, -1):
        if not _lag_slice_complete(s, idx_T, lag):
            continue
        t_end = s.index[idx_T]
        stale_h = (ref_hour - t_end) / _HOUR
        if stale_h > max_staleness_hours:
            return None, "staleness_exceeded"
        return idx_T, None
    return None, "no_valid_lag_window"


def _build_lag_dataset(y: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """Dense-array 1-step dataset: X[i]=y[i-lag:i], y[i]=y[i] (legacy / self-test)."""
    n = len(y)
    rows_x: list[np.ndarray] = []
    rows_y: list[float] = []
    for i in range(lag, n):
        rows_x.append(y[i - lag : i])
        rows_y.append(y[i])
    if not rows_y:
        return np.empty((0, lag)), np.empty((0,))
    return np.stack(rows_x, axis=0), np.asarray(rows_y, dtype=float)


def _fit_and_predict_recursive(
    y: np.ndarray,
    horizon: int,
    max_lag: int,
    *,
    ridge_alpha: float | None = None,
) -> tuple[float | None, str | None]:
    """Dense series only: h recursive steps on array positions (self-test / legacy callers)."""
    n = len(y)
    if n < MIN_HOURLY_POINTS:
        return None, "insufficient_history"
    lag = _effective_lag(n, max_lag)
    if n < lag + 5:
        return None, "insufficient_history"

    X, y_tr = _build_lag_dataset(y, lag)
    if X.shape[0] < 20:
        return None, "insufficient_history"

    alpha = float(RIDGE_ALPHA_DEFAULT if ridge_alpha is None else ridge_alpha)
    if alpha <= 0 or not np.isfinite(alpha):
        return None, "invalid_ridge_alpha"

    try:
        model = Ridge(alpha=alpha)
        model.fit(X, y_tr)
    except ValueError:
        return None, "fit_failed"

    window = y[-lag:].astype(float).copy()
    last_pred = float(window[-1])
    for _ in range(horizon):
        pred = float(model.predict(window.reshape(1, -1))[0])
        last_pred = pred
        window = np.append(window[1:], pred)
    return last_pred, None


def _recursive_train_and_predict_at_cutoff(
    s: pd.Series,
    idx_cutoff: int,
    horizon: int,
    lag: int,
    *,
    ridge_alpha: float,
    require_actual_at_horizon: bool = False,
    full_series: pd.Series | None = None,
    full_idx_cutoff: int | None = None,
) -> tuple[float | None, str | None]:
    """
    Train 1-step Ridge on complete (lag -> target) rows with target time index <= idx_cutoff.
    Roll out h calendar hours ahead from idx_cutoff.

    If ``require_actual_at_horizon`` (backtest), require a non-NaN observed value at horizon ``T+h``.
    When ``s`` is truncated, pass ``full_series`` and ``full_idx_cutoff`` so that check uses the full grid.
    """
    h = int(horizon)
    rows_x: list[np.ndarray] = []
    rows_y: list[float] = []
    for i in range(lag, idx_cutoff + 1):
        if not _lag_slice_complete(s, i - 1, lag):
            continue
        if pd.isna(s.iloc[i]):
            continue
        rows_x.append(s.iloc[i - lag : i].to_numpy(dtype=float, copy=False))
        rows_y.append(float(s.iloc[i]))
    if len(rows_y) < 20:
        return None, "insufficient_history"

    X = np.stack(rows_x, axis=0)
    y_tr = np.asarray(rows_y, dtype=float)
    alpha = float(ridge_alpha)
    if alpha <= 0 or not np.isfinite(alpha):
        return None, "invalid_ridge_alpha"
    try:
        model = Ridge(alpha=alpha)
        model.fit(X, y_tr)
    except ValueError:
        return None, "fit_failed"

    if not _lag_slice_complete(s, idx_cutoff, lag):
        return None, "no_valid_lag_window"
    if require_actual_at_horizon:
        if full_series is not None and full_idx_cutoff is not None:
            gi = int(full_idx_cutoff)
            if gi + h >= len(full_series) or gi < 0:
                return None, "horizon_beyond_series"
            if pd.isna(full_series.iloc[gi + h]):
                return None, "missing_future_actual"
        else:
            if idx_cutoff + h >= len(s):
                return None, "horizon_beyond_series"
            if pd.isna(s.iloc[idx_cutoff + h]):
                return None, "missing_future_actual"

    window = s.iloc[idx_cutoff - lag + 1 : idx_cutoff + 1].to_numpy(dtype=float, copy=True)
    for step in range(h):
        pred = float(model.predict(window.reshape(1, -1))[0])
        last_pred = pred
        window = np.append(window[1:], pred)
    return last_pred, None


def ridge_direct_predict_at_cutoff(
    s: pd.Series,
    idx_cutoff: int,
    horizon: int,
    lag: int,
    *,
    ridge_alpha: float,
    full_series: pd.Series | None = None,
    full_idx_cutoff: int | None = None,
) -> tuple[float | None, str | None]:
    """
    Direct horizon-h on calendar grid. Training rows end at o with o+h <= idx_cutoff (no future labels).

    When ``s`` is a truncated slice (e.g. last ``history_window_hours`` ending at cutoff), pass
    ``full_series`` and ``full_idx_cutoff`` so the observed value at horizon ``T+h`` is read from the
    full hourly grid; otherwise ``iloc[idx_cutoff + h]`` on ``s`` is used and may be out of range.
    """
    h = int(horizon)
    rows_x: list[np.ndarray] = []
    rows_y: list[float] = []
    for o in range(lag - 1, idx_cutoff - h + 1):
        if not _lag_slice_complete(s, o, lag):
            continue
        if pd.isna(s.iloc[o + h]):
            continue
        rows_x.append(s.iloc[o - lag + 1 : o + 1].to_numpy(dtype=float, copy=False))
        rows_y.append(float(s.iloc[o + h]))
    if len(rows_y) < 20:
        return None, "insufficient_history"
    if not _lag_slice_complete(s, idx_cutoff, lag):
        return None, "invalid_cutoff"
    if full_series is not None and full_idx_cutoff is not None:
        gi = int(full_idx_cutoff)
        if gi + h >= len(full_series) or gi < 0:
            return None, "horizon_beyond_series"
        if pd.isna(full_series.iloc[gi + h]):
            return None, "missing_future_actual"
    else:
        if idx_cutoff + h >= len(s):
            return None, "horizon_beyond_series"
        if pd.isna(s.iloc[idx_cutoff + h]):
            return None, "missing_future_actual"
    X = np.stack(rows_x, axis=0)
    y_tr = np.asarray(rows_y, dtype=float)
    x_test = s.iloc[idx_cutoff - lag + 1 : idx_cutoff + 1].to_numpy(dtype=float, copy=False).reshape(1, -1)
    try:
        model = Ridge(alpha=float(ridge_alpha))
        model.fit(X, y_tr)
        return float(model.predict(x_test)[0]), None
    except ValueError:
        return None, "fit_failed"


def slice_series_upto_cutoff(
    s: pd.Series,
    idx_cutoff: int,
    history_window_hours: int,
) -> tuple[pd.Series, int]:
    """
    Return ``(sub, local_idx_cutoff)`` ending at the same instant as ``s.index[idx_cutoff]``.

    If ``history_window_hours`` > 0, ``sub`` covers that many consecutive grid hours ending at cutoff.
    """
    if idx_cutoff < 0 or idx_cutoff >= len(s):
        return s.iloc[:0], -1
    t_end = s.index[idx_cutoff]
    if history_window_hours <= 0:
        sub = s.iloc[: idx_cutoff + 1]
        return sub, int(sub.shape[0]) - 1
    t_start = t_end - pd.Timedelta(hours=int(history_window_hours) - 1)
    sub = s.loc[t_start:t_end]
    if sub.empty:
        return sub, -1
    loc = sub.index.get_loc(t_end)
    if isinstance(loc, slice):
        loc = loc.stop - 1
    return sub, int(loc)


def walk_forward_ridge_recursive_calendar(
    s: pd.Series,
    horizon: int,
    *,
    step: int,
    ridge_alpha: float,
    max_lag: int = MAX_LAG,
    history_window_hours: int = 0,
    max_cutoffs: int = 0,
    return_cutoffs: bool = False,
) -> tuple[np.ndarray, np.ndarray, int] | tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    """
    Walk-forward on strict hourly index; compare prediction at T+h to ``s`` at T+h.

    Default (``history_window_hours`` and ``max_cutoffs`` both 0): legacy path — full
    series, lag from ``len(s)``, lag completeness checked on ``s``.

    If either ``history_window_hours > 0`` or ``max_cutoffs > 0``: align with
    ``backtest_model_suite_00060`` — trim ``idx_start`` when ``max_cutoffs > 0``,
    use ``slice_series_upto_cutoff`` + ``_recursive_train_and_predict_at_cutoff`` with
    ``full_series`` / ``full_idx_cutoff`` for horizon targets.
    """
    h = int(horizon)
    step = max(1, int(step))
    n = len(s)
    preds: list[float] = []
    actuals: list[float] = []
    cutoffs: list[int] = []
    skipped = 0
    use_suite = int(history_window_hours) > 0 or int(max_cutoffs) > 0

    if not use_suite:
        lag = _effective_lag(n, max_lag)
        idx_start = max(MIN_HOURLY_POINTS - 1, lag)
        for idx_T in range(idx_start, n - h, step):
            if not _lag_slice_complete(s, idx_T, lag):
                skipped += 1
                continue
            if pd.isna(s.iloc[idx_T + h]):
                skipped += 1
                continue
            p, err = _recursive_train_and_predict_at_cutoff(
                s, idx_T, h, lag, ridge_alpha=ridge_alpha, require_actual_at_horizon=True
            )
            if p is None or err is not None:
                skipped += 1
                continue
            preds.append(p)
            actuals.append(float(s.iloc[idx_T + h]))
            cutoffs.append(int(idx_T))
        out = (np.asarray(preds, dtype=float), np.asarray(actuals, dtype=float), skipped)
        if return_cutoffs:
            return out[0], out[1], out[2], np.asarray(cutoffs, dtype=np.int64)
        return out

    lag_full = _effective_lag(n, max_lag)
    idx_start = max(MIN_HOURLY_POINTS - 1, lag_full)
    if int(max_cutoffs) > 0:
        idx_start = max(idx_start, (n - h) - int(max_cutoffs))
    hw = int(history_window_hours)
    for idx_T in range(idx_start, n - h, step):
        if pd.isna(s.iloc[idx_T + h]):
            skipped += 1
            continue
        sub, loc = slice_series_upto_cutoff(s, idx_T, hw)
        if loc < 0:
            skipped += 1
            continue
        lag = _effective_lag(len(sub), max_lag)
        p, err = _recursive_train_and_predict_at_cutoff(
            sub,
            loc,
            h,
            lag,
            ridge_alpha=ridge_alpha,
            require_actual_at_horizon=True,
            full_series=s,
            full_idx_cutoff=idx_T,
        )
        if p is None or err is not None:
            skipped += 1
            continue
        preds.append(p)
        actuals.append(float(s.iloc[idx_T + h]))
        cutoffs.append(int(idx_T))
    out = (np.asarray(preds, dtype=float), np.asarray(actuals, dtype=float), skipped)
    if return_cutoffs:
        return out[0], out[1], out[2], np.asarray(cutoffs, dtype=np.int64)
    return out


def walk_forward_ridge_direct_calendar(
    s: pd.Series,
    horizon: int,
    *,
    step: int,
    ridge_alpha: float,
    max_lag: int = MAX_LAG,
    history_window_hours: int = 0,
    max_cutoffs: int = 0,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Walk-forward direct Ridge: same calendar rules as ``ridge_direct_predict_at_cutoff`` per cutoff."""
    h = int(horizon)
    step = max(1, int(step))
    n = len(s)
    lag_full = _effective_lag(n, max_lag)
    idx_start = max(MIN_HOURLY_POINTS - 1, lag_full)
    if int(max_cutoffs) > 0:
        idx_start = max(idx_start, (n - h) - int(max_cutoffs))
    preds: list[float] = []
    actuals: list[float] = []
    skipped = 0
    for idx_T in range(idx_start, n - h, step):
        if pd.isna(s.iloc[idx_T + h]):
            skipped += 1
            continue
        sub, loc = slice_series_upto_cutoff(s, idx_T, history_window_hours)
        if loc < 0:
            skipped += 1
            continue
        lag = _effective_lag(len(sub), max_lag)
        p, err = ridge_direct_predict_at_cutoff(
            sub, loc, h, lag, ridge_alpha=ridge_alpha, full_series=s, full_idx_cutoff=idx_T
        )
        if p is None or err is not None:
            skipped += 1
            continue
        preds.append(p)
        actuals.append(float(s.iloc[idx_T + h]))
    return np.asarray(preds, dtype=float), np.asarray(actuals, dtype=float), skipped


def forecast_from_iv_csv(
    csv_path: Path,
    site_no: str,
    parameter_cd: str,
    horizon_hours: int,
    *,
    ref_utc_hour: pd.Timestamp | None = None,
    max_staleness_hours: float = MAX_STALENESS_HOURS_DEFAULT,
) -> dict[str, Any]:
    """
    Recursive Ridge on strict hourly grid. Reference time defaults to current UTC floored to hour.

    Returns ``forecast_condition_end_utc`` (last observed hour in the lag window used) and
    ``staleness_hours`` vs ``forecast_reference_utc``.
    """
    site_no = str(site_no).strip()
    parameter_cd = str(parameter_cd).strip()
    h = int(horizon_hours)
    if h < 1 or h > MAX_HORIZON_HOURS:
        return {
            "site_no": site_no,
            "parameter_cd": parameter_cd,
            "horizon_hours": h,
            "forecast_available": False,
            "forecast_value": None,
            "model_version": FORECAST_MODEL_VERSION,
            "data_points_used": 0,
            "reason": "invalid_horizon",
        }

    s = load_hourly_series(csv_path, site_no, parameter_cd, dense=False)
    if s.empty:
        return {
            "site_no": site_no,
            "parameter_cd": parameter_cd,
            "horizon_hours": h,
            "forecast_available": False,
            "forecast_value": None,
            "model_version": FORECAST_MODEL_VERSION,
            "data_points_used": 0,
            "reason": "no_series_or_column",
        }

    n = len(s)
    ref = ref_utc_hour if ref_utc_hour is not None else _utc_reference_hour_floor()
    lag = _effective_lag(n, MAX_LAG)
    idx_T, err = _find_cutoff_index_for_forecast(
        s, lag=lag, ref_hour=ref, max_staleness_hours=max_staleness_hours
    )
    if idx_T is None:
        return {
            "site_no": site_no,
            "parameter_cd": parameter_cd,
            "horizon_hours": h,
            "forecast_available": False,
            "forecast_value": None,
            "model_version": FORECAST_MODEL_VERSION,
            "data_points_used": n,
            "reason": err or "forecast_unavailable",
            "forecast_reference_utc": ref.isoformat(),
            "series_last_timestamp": s.index[-1].isoformat(),
        }

    pred, fit_err = _recursive_train_and_predict_at_cutoff(
        s, idx_T, h, lag, ridge_alpha=RIDGE_ALPHA_DEFAULT, require_actual_at_horizon=False
    )
    if pred is None:
        return {
            "site_no": site_no,
            "parameter_cd": parameter_cd,
            "horizon_hours": h,
            "forecast_available": False,
            "forecast_value": None,
            "model_version": FORECAST_MODEL_VERSION,
            "data_points_used": n,
            "reason": fit_err or "forecast_unavailable",
            "forecast_reference_utc": ref.isoformat(),
            "forecast_condition_end_utc": s.index[idx_T].isoformat(),
            "series_last_timestamp": s.index[-1].isoformat(),
        }

    t_cond = s.index[idx_T]
    stale_h = float((ref - t_cond) / _HOUR)
    return {
        "site_no": site_no,
        "parameter_cd": parameter_cd,
        "horizon_hours": h,
        "forecast_available": True,
        "forecast_value": round(pred, 4),
        "model_version": FORECAST_MODEL_VERSION,
        "data_points_used": n,
        "reason": None,
        "forecast_reference_utc": ref.isoformat(),
        "forecast_condition_end_utc": t_cond.isoformat(),
        "staleness_hours": round(stale_h, 4),
        "series_last_timestamp": s.index[-1].isoformat(),
    }


def forecast_series_from_iv_csv(
    csv_path: Path,
    site_no: str,
    parameter_cd: str,
    horizon_hours: int,
    history_days: int = 30,
    *,
    ref_utc_hour: pd.Timestamp | None = None,
    max_staleness_hours: float = MAX_STALENESS_HOURS_DEFAULT,
) -> dict[str, Any]:
    """
    History + recursive forecast points on the calendar: each forecast step is one UTC hour.
    """
    base = forecast_from_iv_csv(
        csv_path,
        site_no,
        parameter_cd,
        horizon_hours,
        ref_utc_hour=ref_utc_hour,
        max_staleness_hours=max_staleness_hours,
    )
    site_no = str(site_no).strip()
    parameter_cd = str(parameter_cd).strip()
    h = int(horizon_hours)
    d = int(history_days)
    if d < 1 or d > 90:
        d = 30

    s = load_hourly_series(csv_path, site_no, parameter_cd, dense=False)
    if s.empty:
        base["history_points"] = []
        base["forecast_points"] = []
        base["history_days"] = d
        return base

    ref = ref_utc_hour if ref_utc_hour is not None else _utc_reference_hour_floor()
    lag = _effective_lag(len(s), MAX_LAG)
    idx_T, err = _find_cutoff_index_for_forecast(
        s, lag=lag, ref_hour=ref, max_staleness_hours=max_staleness_hours
    )

    hist = s[s.index >= (ref - pd.Timedelta(days=d))]
    history_points = [
        {"timestamp": ts.isoformat(), "value": (round(float(v), 4) if pd.notna(v) else None)}
        for ts, v in hist.items()
    ]
    base["history_points"] = history_points
    base["history_days"] = d

    if not bool(base.get("forecast_available")) or idx_T is None:
        base["forecast_points"] = []
        return base

    rows_x: list[np.ndarray] = []
    rows_y: list[float] = []
    for i in range(lag, idx_T + 1):
        if not _lag_slice_complete(s, i - 1, lag):
            continue
        if pd.isna(s.iloc[i]):
            continue
        rows_x.append(s.iloc[i - lag : i].to_numpy(dtype=float, copy=False))
        rows_y.append(float(s.iloc[i]))
    if len(rows_y) < 20:
        base["forecast_points"] = []
        return base

    model = Ridge(alpha=RIDGE_ALPHA_DEFAULT)
    model.fit(np.stack(rows_x, axis=0), np.asarray(rows_y, dtype=float))
    window = s.iloc[idx_T - lag + 1 : idx_T + 1].to_numpy(dtype=float, copy=True).copy()
    t_cond = s.index[idx_T]
    pred_points: list[dict[str, Any]] = []
    for step in range(1, h + 1):
        pred = float(model.predict(window.reshape(1, -1))[0])
        window = np.append(window[1:], pred)
        pred_points.append(
            {
                "timestamp": (t_cond + pd.Timedelta(hours=step)).isoformat(),
                "value": round(pred, 4),
            }
        )
    base["forecast_points"] = pred_points
    return base


def _self_test() -> None:
    rng = np.random.default_rng(0)
    t = 120
    x = np.arange(t, dtype=float)
    y = 100 + 0.1 * x + rng.normal(0, 2, size=t)
    p, e = _fit_and_predict_recursive(y, horizon=6, max_lag=24)
    assert e is None and p is not None
    path = Path(__file__).resolve().parent.parent / "data" / "usgs_puget_iv.csv"
    if path.is_file():
        out = forecast_from_iv_csv(path, "12117000", "00060", 12)
        assert "forecast_available" in out


if __name__ == "__main__":
    _self_test()
    print("forecast_engine self-test ok")

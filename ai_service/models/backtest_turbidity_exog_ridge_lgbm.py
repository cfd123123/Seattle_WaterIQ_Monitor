#!/usr/bin/env python3
"""
Walk-forward backtests for turbidity (63680) with Open-Meteo exogenous columns.

Variants (same calendar grid as ``load_hourly_series(..., dense=False)``):

- **direct_ridge / direct_lgbm**: one model per horizon ``h``. Features at end index ``o`` are
  concatenated lags of ``y``, ``precipitation_mm``, ``temperature_2m_c`` using only hours
  ``<= o`` (no future exogenous relative to the training row's end time). Target is ``y[o+h]``.

- **recursive_ridge_exog_hindcast / recursive_lgbm_exog_hindcast**: one-step Ridge or LGBM on
  ``[y_lags | precip_lags | temp_lags]``, then ``h`` recursive rollouts. During rollout at step
  ``k``, precipitation/temperature blocks use **observed** values at ``T+k`` (historical replay
  only — **not** deployable without a weather forecast feed). Hindcast / oracle-weather upper bound.

- **recursive_ridge_univariate**: delegates to ``walk_forward_ridge_recursive_calendar`` (y only).

CLI example::

    .venv/bin/python models/backtest_turbidity_exog_ridge_lgbm.py \\
      --features-csv data/features_12117500_63680_with_openmeteo.csv \\
      --model direct_ridge --horizons 1-12 --step 1 --ridge-alpha 5 \\
      --holdout-fraction 0.2 --holdout-min-hours 336 \\
      --json-out reports/turbidity_exog_direct_ridge.json

JSON includes ``summary_by_eval_window`` (all / tuning / holdout) with model + baselines
(persistence, seasonal lag-24h), tier A/B and h1-12 mean sMAPE/MAE per ``plan/evaluation_contract.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "models"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from evaluation_tiers import ranking_scores_from_horizon_metrics, tier_means_from_by_h
from forecast_engine import (
    MAX_LAG,
    MIN_HOURLY_POINTS,
    _effective_lag,
    walk_forward_ridge_recursive_calendar,
)
from lightgbm import LGBMRegressor

UPSTREAM_DISCHARGE_COL = "upstream_discharge_cfs_12116400"


def _parse_horizons(s: str) -> list[int]:
    s = str(s).strip()
    if s == "1-12":
        return list(range(1, 13))
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _h1_12_means(by_h: dict[int, dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    """Mean sMAPE / MAE over all horizons present (contract-style h=1..12 block)."""
    sms: list[float] = []
    mas: list[float] = []
    for h in horizons:
        r = by_h.get(int(h))
        if not r or r.get("error") or "smape_pct" not in r:
            continue
        sms.append(float(r["smape_pct"]))
        mas.append(float(r["mae"]))
    if not sms:
        return {"h1_12_mean_smape_pct": None, "h1_12_mean_mae": None, "horizons_ok": 0}
    return {
        "h1_12_mean_smape_pct": round(float(np.mean(sms)), 6),
        "h1_12_mean_mae": round(float(np.mean(mas)), 6),
        "horizons_ok": int(len(sms)),
    }


def _split_index_for_holdout(
    n: int,
    max_horizon: int,
    *,
    holdout_fraction: float,
    holdout_min_hours: int,
    min_tuning_hours: int,
) -> dict[str, Any]:
    """
    First cutoff index in the holdout segment: split_index.
    Tuning cutoffs satisfy idx_T < split_index; holdout satisfy idx_T >= split_index.
    """
    hf = max(0.0, min(1.0, float(holdout_fraction)))
    mh = int(max_horizon)
    hmin = int(holdout_min_hours)
    # Do not reserve more tuning than the series can afford after max horizon and min holdout.
    min_tun_capped = min(
        int(min_tuning_hours),
        max(int(MIN_HOURLY_POINTS), n - mh - hmin - 1),
    )
    min_tun_capped = max(min_tun_capped, int(MIN_HOURLY_POINTS))

    holdout_h = max(int(round(hf * n)), hmin)
    max_holdout = n - mh - 1 - int(min_tun_capped)
    max_holdout = max(max_holdout, 1)
    holdout_h = min(holdout_h, max_holdout)
    holdout_h = max(holdout_h, 1)
    split_ix = int(n - holdout_h)
    split_ix = max(split_ix, mh + 1)
    split_ix = min(split_ix, n - 1)
    holdout_h = int(n - split_ix)
    return {
        "split_index": split_ix,
        "holdout_hours": holdout_h,
        "holdout_fraction_requested": hf,
        "holdout_min_hours_requested": hmin,
        "min_tuning_hours_requested": int(min_tuning_hours),
        "min_tuning_hours_effective": int(min_tun_capped),
    }


def _baseline_pairs(
    y: pd.Series,
    cutoffs: np.ndarray,
    h: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Align with model cutoffs. Returns:
      persistence pred/act,
      seasonal pred/act/mask (mask True where seasonal forecast is defined and finite).
    """
    ci = cutoffs.astype(np.int64, copy=False)
    h = int(h)
    pers_p = y.iloc[ci].to_numpy(dtype=float, copy=False)
    pers_a = y.iloc[ci + h].to_numpy(dtype=float, copy=False)
    lag_ix = ci + h - 24
    ok = lag_ix >= 0
    seas_p = np.full(ci.shape[0], np.nan, dtype=float)
    if np.any(ok):
        seas_p[ok] = y.iloc[lag_ix[ok]].to_numpy(dtype=float, copy=False)
    seas_a = pers_a.copy()
    seas_mask = ok & np.isfinite(seas_p) & np.isfinite(seas_a)
    return pers_p, pers_a, seas_p, seas_mask


def _apply_window_mask(
    preds: np.ndarray,
    actuals: np.ndarray,
    cutoffs: np.ndarray,
    pers_p: np.ndarray,
    pers_a: np.ndarray,
    seas_p: np.ndarray,
    seas_mask: np.ndarray,
    window: str,
    split_ix: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if window == "all":
        wm = np.ones(len(cutoffs), dtype=bool)
    elif window == "tuning":
        wm = cutoffs < int(split_ix)
    elif window == "holdout":
        wm = cutoffs >= int(split_ix)
    else:
        raise ValueError(window)
    return (
        preds[wm],
        actuals[wm],
        cutoffs[wm],
        pers_p[wm],
        pers_a[wm],
        seas_p[wm],
        seas_mask[wm],
    )


def _metrics_by_h_for_window(
    horizons: list[int],
    per_h_pack: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    by_m: dict[int, dict[str, Any]] = {}
    by_p: dict[int, dict[str, Any]] = {}
    by_s: dict[int, dict[str, Any]] = {}
    for h in horizons:
        pack = per_h_pack.get(h)
        if not pack:
            continue
        pm, am = pack["model_pred"], pack["model_act"]
        pp, pa = pack["pers_pred"], pack["pers_act"]
        sp, sm = pack["seas_pred"], pack["seas_mask"]
        if len(pm) > 0:
            by_m[h] = _metrics(pm, am)
        else:
            by_m[h] = {"error": "empty_window", "n": 0}
        if len(pp) > 0:
            m = np.isfinite(pp) & np.isfinite(pa)
            by_p[h] = _metrics(pp[m], pa[m]) if m.any() else {"error": "empty_window", "n": 0}
        else:
            by_p[h] = {"error": "empty_window", "n": 0}
        if sm.any():
            by_s[h] = _metrics(sp[sm], am[sm])
        else:
            by_s[h] = {"error": "no_valid_seasonal_pairs", "n": 0}
    tier_m = tier_means_from_by_h(by_m)
    tier_m.update(_h1_12_means(by_m, horizons))
    tier_p = tier_means_from_by_h(by_p)
    tier_p.update(_h1_12_means(by_p, horizons))
    tier_s = tier_means_from_by_h(by_s)
    tier_s.update(_h1_12_means(by_s, horizons))
    return {
        "model": tier_m,
        "baselines": {"persistence": tier_p, "seasonal_lag_24h": tier_s},
        "per_horizon_model": {str(k): v for k, v in by_m.items()},
        "per_horizon_persistence": {str(k): v for k, v in by_p.items()},
        "per_horizon_seasonal_lag_24h": {str(k): v for k, v in by_s.items()},
    }


def _metrics(pred: np.ndarray, actual: np.ndarray) -> dict[str, float | int]:
    pred = pred.astype(float)
    actual = actual.astype(float)
    err = pred - actual
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    denom = (np.abs(actual) + np.abs(pred) + 1e-9) / 2.0
    smape = float(np.mean(np.abs(err) / denom) * 100.0)
    return {"n": int(len(pred)), "mae": round(mae, 6), "rmse": round(rmse, 6), "smape_pct": round(smape, 4)}


def _causal_fill_series(s: pd.Series, limit: int = 24) -> pd.Series:
    return s.ffill(limit=limit)


def load_y_precip_temp_aligned(csv_path: Path) -> tuple[pd.Series, pd.Series, pd.Series]:
    y, p, tc, _, _ = load_features_aligned(csv_path)
    return y, p, tc


def load_features_aligned(
    csv_path: Path,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series | None, dict[str, Any]]:
    df = pd.read_csv(csv_path)
    if "datetime_utc" not in df.columns:
        raise ValueError("features CSV must contain datetime_utc")
    tcol = "datetime_utc"
    df[tcol] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
    df = df.dropna(subset=[tcol])
    df = df.sort_values(tcol).drop_duplicates(subset=[tcol], keep="last")
    df = df.set_index(tcol)
    y = df["63680"].astype(float)
    p = _causal_fill_series(df["precipitation_mm"].astype(float))
    tc = _causal_fill_series(df["temperature_2m_c"].astype(float))
    q_up: pd.Series | None = None
    if UPSTREAM_DISCHARGE_COL in df.columns:
        q_up = _causal_fill_series(df[UPSTREAM_DISCHARGE_COL].astype(float))
    prov_path = csv_path.with_name(csv_path.stem + "_upstream_provenance.json")
    prov: dict[str, Any] = {}
    if prov_path.is_file():
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
    return y, p, tc, q_up, prov


def _exog_blocks_at(
    y: pd.Series,
    prec: pd.Series,
    temp: pd.Series,
    end_ix: int,
    lag: int,
    q_up: pd.Series | None,
) -> np.ndarray | None:
    wy = _lag_matrix_block(y, end_ix, lag)
    wp = _lag_matrix_block(prec, end_ix, lag)
    wt = _lag_matrix_block(temp, end_ix, lag)
    if wy is None or wp is None or wt is None:
        return None
    parts = [wy, wp, wt]
    if q_up is not None:
        wq = _lag_matrix_block(q_up, end_ix, lag)
        if wq is None:
            return None
        parts.append(wq)
    return np.concatenate(parts, axis=0)


def _feat_dim(lag: int, q_up: pd.Series | None) -> int:
    n_blocks = 4 if q_up is not None else 3
    return n_blocks * int(lag)


def _as_lgbm_frame(X: np.ndarray) -> pd.DataFrame:
    """LightGBM sklearn wrapper warns if fit used feature names but predict gets a bare ndarray."""
    cols = [f"f{i}" for i in range(X.shape[1])]
    return pd.DataFrame(X, columns=cols, copy=False)


def _lag_matrix_block(
    s: pd.Series,
    end_ix: int,
    lag: int,
) -> np.ndarray | None:
    """Return shape (lag,) for s[end_ix-lag+1 : end_ix+1] if all finite."""
    if end_ix - lag + 1 < 0:
        return None
    w = s.iloc[end_ix - lag + 1 : end_ix + 1].to_numpy(dtype=float, copy=False)
    if w.shape[0] != lag or not np.isfinite(w).all():
        return None
    return w


def walk_forward_direct_exog(
    y: pd.Series,
    prec: pd.Series,
    temp: pd.Series,
    horizon: int,
    *,
    lag: int,
    step: int,
    max_cutoffs: int,
    history_window_hours: int,
    model_kind: str,
    ridge_alpha: float,
    lgbm_params: dict[str, Any],
    q_up: pd.Series | None = None,
    return_cutoffs: bool = False,
) -> tuple[np.ndarray, np.ndarray, int] | tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    from forecast_engine import slice_series_upto_cutoff

    h = int(horizon)
    step = max(1, int(step))
    n = len(y)
    lag_full = _effective_lag(n, MAX_LAG)
    lag = int(min(lag, lag_full))
    idx_start = max(MIN_HOURLY_POINTS - 1, lag_full)
    if max_cutoffs > 0:
        idx_start = max(idx_start, (n - h) - int(max_cutoffs))
    preds: list[float] = []
    actuals: list[float] = []
    cutoffs_li: list[int] = []
    skipped = 0

    for idx_T in range(idx_start, n - h, step):
        if pd.isna(y.iloc[idx_T + h]):
            skipped += 1
            continue
        sub_y, loc = slice_series_upto_cutoff(y, idx_T, history_window_hours)
        if loc < 0:
            skipped += 1
            continue
        lag_loc = _effective_lag(len(sub_y), MAX_LAG)
        lag_loc = int(min(lag, lag_loc))
        feat_dim = _feat_dim(lag_loc, q_up)
        rows_x: list[np.ndarray] = []
        rows_yy: list[float] = []
        for o in range(lag_loc - 1, loc - h + 1):
            g = idx_T - loc + o
            row = _exog_blocks_at(y, prec, temp, g, lag_loc, q_up)
            if row is None:
                continue
            if pd.isna(y.iloc[g + h]):
                continue
            rows_x.append(row)
            rows_yy.append(float(y.iloc[g + h]))
        if len(rows_yy) < 20:
            skipped += 1
            continue
        x_row = _exog_blocks_at(y, prec, temp, idx_T, lag_loc, q_up)
        if x_row is None:
            skipped += 1
            continue
        x_test = x_row.reshape(1, -1)
        X = np.stack(rows_x, axis=0)
        y_tr = np.asarray(rows_yy, dtype=float)
        if X.shape[1] != feat_dim:
            skipped += 1
            continue
        try:
            if model_kind == "direct_ridge":
                m = Ridge(alpha=float(ridge_alpha))
                m.fit(X, y_tr)
                pred = float(m.predict(x_test)[0])
            else:
                m = LGBMRegressor(
                    objective="regression",
                    random_state=int(lgbm_params.get("random_state", 42)),
                    verbosity=-1,
                    n_jobs=1,
                    **{k: v for k, v in lgbm_params.items() if k != "random_state"},
                )
                X_df = _as_lgbm_frame(X)
                xt_df = _as_lgbm_frame(x_test)
                m.fit(X_df, y_tr)
                pred = float(m.predict(xt_df)[0])
        except ValueError:
            skipped += 1
            continue
        preds.append(pred)
        actuals.append(float(y.iloc[idx_T + h]))
        cutoffs_li.append(int(idx_T))
    out_p = np.asarray(preds, dtype=float)
    out_a = np.asarray(actuals, dtype=float)
    if return_cutoffs:
        return out_p, out_a, skipped, np.asarray(cutoffs_li, dtype=np.int64)
    return out_p, out_a, skipped


def walk_forward_recursive_exog_hindcast(
    y: pd.Series,
    prec: pd.Series,
    temp: pd.Series,
    horizon: int,
    *,
    lag: int,
    step: int,
    max_cutoffs: int,
    history_window_hours: int,
    backend: str,
    ridge_alpha: float,
    lgbm_params: dict[str, Any],
    q_up: pd.Series | None = None,
    return_cutoffs: bool = False,
) -> tuple[np.ndarray, np.ndarray, int] | tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    """One-step regressor (Ridge or LGBM) + recursive rollout; exog uses observed weather/Q at each step (hindcast)."""
    from forecast_engine import slice_series_upto_cutoff

    if backend not in ("ridge", "lgbm"):
        raise ValueError(f"backend must be 'ridge' or 'lgbm', got {backend!r}")

    h = int(horizon)
    step = max(1, int(step))
    n = len(y)
    lag_full = _effective_lag(n, MAX_LAG)
    lag = int(min(lag, lag_full))
    idx_start = max(MIN_HOURLY_POINTS - 1, lag_full)
    if max_cutoffs > 0:
        idx_start = max(idx_start, (n - h) - int(max_cutoffs))
    preds: list[float] = []
    actuals: list[float] = []
    cutoffs_li: list[int] = []
    skipped = 0

    for idx_T in range(idx_start, n - h, step):
        if pd.isna(y.iloc[idx_T + h]):
            skipped += 1
            continue
        sub_y, loc = slice_series_upto_cutoff(y, idx_T, history_window_hours)
        if loc < 0:
            skipped += 1
            continue
        lag_loc = _effective_lag(len(sub_y), MAX_LAG)
        lag_loc = int(min(lag, lag_loc))
        rows_x: list[np.ndarray] = []
        rows_yy: list[float] = []
        for i in range(lag_loc, loc + 1):
            g = idx_T - loc + i
            row = _exog_blocks_at(y, prec, temp, g - 1, lag_loc, q_up)
            if row is None:
                continue
            if pd.isna(y.iloc[g]):
                continue
            rows_x.append(row)
            rows_yy.append(float(y.iloc[g]))
        if len(rows_yy) < 20:
            skipped += 1
            continue
        X = np.stack(rows_x, axis=0)
        y_tr = np.asarray(rows_yy, dtype=float)
        try:
            if backend == "ridge":
                model = Ridge(alpha=float(ridge_alpha))
                model.fit(X, y_tr)
            else:
                model = LGBMRegressor(
                    objective="regression",
                    random_state=int(lgbm_params.get("random_state", 42)),
                    verbosity=-1,
                    n_jobs=1,
                    **{k: v for k, v in lgbm_params.items() if k != "random_state"},
                )
                model.fit(_as_lgbm_frame(X), y_tr)
        except ValueError:
            skipped += 1
            continue
        wy0 = _lag_matrix_block(y, idx_T, lag_loc)
        if wy0 is None:
            skipped += 1
            continue
        y_part = wy0.astype(float, copy=True)
        last_pred: float | None = None
        failed = False
        for k in range(h):
            gi = idx_T + k
            wp_k = _lag_matrix_block(prec, gi, lag_loc)
            wt_k = _lag_matrix_block(temp, gi, lag_loc)
            if wp_k is None or wt_k is None:
                failed = True
                break
            parts = [y_part, wp_k, wt_k]
            if q_up is not None:
                wq_k = _lag_matrix_block(q_up, gi, lag_loc)
                if wq_k is None:
                    failed = True
                    break
                parts.append(wq_k)
            x_row = np.concatenate(parts, axis=0).reshape(1, -1)
            if x_row.shape[1] != _feat_dim(lag_loc, q_up):
                failed = True
                break
            try:
                if backend == "ridge":
                    last_pred = float(model.predict(x_row)[0])
                else:
                    last_pred = float(model.predict(_as_lgbm_frame(x_row))[0])
            except ValueError:
                failed = True
                break
            y_part = np.append(y_part[1:], last_pred)
        if failed or last_pred is None:
            skipped += 1
            continue
        preds.append(last_pred)
        actuals.append(float(y.iloc[idx_T + h]))
        cutoffs_li.append(int(idx_T))
    out_p = np.asarray(preds, dtype=float)
    out_a = np.asarray(actuals, dtype=float)
    if return_cutoffs:
        return out_p, out_a, skipped, np.asarray(cutoffs_li, dtype=np.int64)
    return out_p, out_a, skipped


def walk_forward_recursive_ridge_exog_hindcast(
    y: pd.Series,
    prec: pd.Series,
    temp: pd.Series,
    horizon: int,
    *,
    lag: int,
    step: int,
    max_cutoffs: int,
    history_window_hours: int,
    ridge_alpha: float,
    q_up: pd.Series | None = None,
    return_cutoffs: bool = False,
) -> tuple[np.ndarray, np.ndarray, int] | tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    return walk_forward_recursive_exog_hindcast(
        y,
        prec,
        temp,
        horizon,
        lag=lag,
        step=step,
        max_cutoffs=max_cutoffs,
        history_window_hours=history_window_hours,
        backend="ridge",
        ridge_alpha=ridge_alpha,
        lgbm_params={},
        q_up=q_up,
        return_cutoffs=return_cutoffs,
    )


def walk_forward_recursive_lgbm_exog_hindcast(
    y: pd.Series,
    prec: pd.Series,
    temp: pd.Series,
    horizon: int,
    *,
    lag: int,
    step: int,
    max_cutoffs: int,
    history_window_hours: int,
    lgbm_params: dict[str, Any],
    q_up: pd.Series | None = None,
    return_cutoffs: bool = False,
) -> tuple[np.ndarray, np.ndarray, int] | tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    return walk_forward_recursive_exog_hindcast(
        y,
        prec,
        temp,
        horizon,
        lag=lag,
        step=step,
        max_cutoffs=max_cutoffs,
        history_window_hours=history_window_hours,
        backend="lgbm",
        ridge_alpha=float("nan"),
        lgbm_params=lgbm_params,
        q_up=q_up,
        return_cutoffs=return_cutoffs,
    )


def _precip_6h_sum_at_cutoffs(prec: pd.Series, cutoffs: np.ndarray) -> np.ndarray:
    out: list[float] = []
    for c in cutoffs.astype(int):
        sl = prec.iloc[max(0, int(c) - 5) : int(c) + 1]
        out.append(float(sl.sum()) if len(sl) else float("nan"))
    return np.asarray(out, dtype=float)


def _strata_thresholds_tuning(
    y: pd.Series,
    prec: pd.Series,
    cutoffs: np.ndarray,
    split_ix: int,
    *,
    y_quantile: float = 0.9,
    precip_6h_quantile: float = 0.9,
) -> dict[str, Any]:
    tun = cutoffs[cutoffs < int(split_ix)]
    if len(tun) < 15:
        return {"error": "too_few_tuning_cutoffs", "n": int(len(tun))}
    y_t = y.iloc[tun].astype(float).to_numpy()
    p6 = _precip_6h_sum_at_cutoffs(prec, tun)
    y_thr = float(np.nanquantile(y_t, y_quantile))
    p_thr = float(np.nanquantile(p6[np.isfinite(p6)], precip_6h_quantile)) if np.isfinite(p6).any() else float("nan")
    return {
        "y_at_T_quantile": y_quantile,
        "precip_6h_quantile": precip_6h_quantile,
        "y_at_T_threshold": y_thr,
        "precip_6h_mm_threshold": p_thr,
        "n_tuning_cutoffs": int(len(tun)),
    }


def _summary_strata_holdout(
    horizons: list[int],
    by_h_pack: dict[int, dict[str, Any]],
    y: pd.Series,
    prec: pd.Series,
    split_ix: int,
    strata_thr: dict[str, Any],
) -> dict[str, Any]:
    if strata_thr.get("error"):
        return {"error": strata_thr["error"]}
    y_thr = float(strata_thr["y_at_T_threshold"])
    p_thr = float(strata_thr["precip_6h_mm_threshold"])
    out: dict[str, Any] = {"thresholds": strata_thr, "strata": {}}
    for label, mask_fn in (
        ("all_holdout", lambda c, yv, p6: np.ones(len(c), dtype=bool)),
        ("high_turbidity_at_T", lambda c, yv, p6: yv >= y_thr),
        ("heavy_precip_6h_at_T", lambda c, yv, p6: p6 >= p_thr),
        ("high_turbidity_or_heavy_precip", lambda c, yv, p6: (yv >= y_thr) | (p6 >= p_thr)),
    ):
        per_h: dict[int, dict[str, Any]] = {}
        for h in horizons:
            d = by_h_pack.get(h)
            if not d:
                continue
            pm, am, co, *_ = _apply_window_mask(
                d["preds"],
                d["actuals"],
                d["cutoffs"],
                d["pers_p"],
                d["pers_a"],
                d["seas_p"],
                d["seas_mask"],
                "holdout",
                split_ix,
            )
            if len(co) == 0:
                continue
            yv = y.iloc[co].astype(float).to_numpy()
            p6 = _precip_6h_sum_at_cutoffs(prec, co)
            sm = mask_fn(co, yv, p6) & np.isfinite(yv)
            if not sm.any():
                per_h[h] = {"error": "empty_stratum", "n": 0}
                continue
            per_h[h] = _metrics(pm[sm], am[sm])
            per_h[h]["n"] = int(sm.sum())
        tier_m = tier_means_from_by_h(per_h)
        tier_m.update(_h1_12_means(per_h, horizons))
        out["strata"][label] = {"model": tier_m, "per_horizon": {str(k): v for k, v in per_h.items()}}
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Turbidity walk-forward: Ridge/LGBM with Open-Meteo exog")
    p.add_argument("--features-csv", type=Path, required=True, help="Merged CSV from fetch_open_meteo_archive_hourly --join-*")
    p.add_argument(
        "--model",
        choices=(
            "direct_ridge",
            "direct_lgbm",
            "direct_ridge_upstream",
            "direct_lgbm_upstream",
            "recursive_ridge_exog_hindcast",
            "recursive_lgbm_exog_hindcast",
            "recursive_ridge_exog_upstream_hindcast",
            "recursive_lgbm_exog_upstream_hindcast",
            "recursive_ridge_univariate",
        ),
        required=True,
    )
    p.add_argument("--horizons", type=str, default="1-12")
    p.add_argument("--step", type=int, default=1)
    p.add_argument("--max-cutoffs", type=int, default=720)
    p.add_argument("--history-window-hours", type=int, default=1440)
    p.add_argument("--ridge-alpha", type=float, default=5.0)
    p.add_argument(
        "--holdout-fraction",
        type=float,
        default=0.2,
        help="Fraction of latest hours reserved as holdout segment (see evaluation_contract.md).",
    )
    p.add_argument(
        "--holdout-min-hours",
        type=int,
        default=336,
        help="Minimum holdout length in hours when series is long enough (14 days).",
    )
    p.add_argument(
        "--min-tuning-hours",
        type=int,
        default=2000,
        help="Minimum hours kept for tuning segment when computing split_index.",
    )
    p.add_argument("--json-out", type=Path, default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = Path(args.features_csv)
    if not csv_path.is_file():
        print(f"Missing features CSV: {csv_path}", file=sys.stderr)
        return 2
    y, prec, temp, q_up, upstream_prov = load_features_aligned(csv_path)
    if y.notna().sum() < MIN_HOURLY_POINTS:
        print("Insufficient valid turbidity hours.", file=sys.stderr)
        return 3
    use_upstream = "upstream" in str(args.model)
    if use_upstream and q_up is None:
        print(
            f"Model {args.model!r} requires column {UPSTREAM_DISCHARGE_COL!r} in features CSV.",
            file=sys.stderr,
        )
        return 4
    if use_upstream and q_up is not None and q_up.notna().sum() < MIN_HOURLY_POINTS:
        print("Insufficient valid upstream discharge hours.", file=sys.stderr)
        return 5
    horizons = _parse_horizons(args.horizons)
    lag_eff = _effective_lag(len(y), MAX_LAG)
    max_h = max(horizons)
    split_info = _split_index_for_holdout(
        len(y),
        max_h,
        holdout_fraction=float(args.holdout_fraction),
        holdout_min_hours=int(args.holdout_min_hours),
        min_tuning_hours=int(args.min_tuning_hours),
    )
    split_ix = int(split_info["split_index"])
    try:
        split_info["split_time_utc"] = str(y.index[split_ix])
    except Exception:
        split_info["split_time_utc"] = None

    lgbm_params = {
        "random_state": 42,
        "n_estimators": 200,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": -1,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
    }

    grid: dict[str, Any] = {}
    by_h_arrays: dict[int, dict[str, Any]] = {}

    for h in horizons:
        if args.model == "recursive_ridge_univariate":
            preds, actuals, skipped, cutoffs = walk_forward_ridge_recursive_calendar(
                y,
                h,
                step=int(args.step),
                ridge_alpha=float(args.ridge_alpha),
                max_lag=MAX_LAG,
                history_window_hours=int(args.history_window_hours),
                max_cutoffs=int(args.max_cutoffs),
                return_cutoffs=True,
            )
        elif args.model in ("recursive_ridge_exog_hindcast", "recursive_ridge_exog_upstream_hindcast"):
            preds, actuals, skipped, cutoffs = walk_forward_recursive_ridge_exog_hindcast(
                y,
                prec,
                temp,
                h,
                lag=lag_eff,
                step=int(args.step),
                max_cutoffs=int(args.max_cutoffs),
                history_window_hours=int(args.history_window_hours),
                ridge_alpha=float(args.ridge_alpha),
                q_up=q_up if use_upstream else None,
                return_cutoffs=True,
            )
        elif args.model in ("recursive_lgbm_exog_hindcast", "recursive_lgbm_exog_upstream_hindcast"):
            preds, actuals, skipped, cutoffs = walk_forward_recursive_lgbm_exog_hindcast(
                y,
                prec,
                temp,
                h,
                lag=lag_eff,
                step=int(args.step),
                max_cutoffs=int(args.max_cutoffs),
                history_window_hours=int(args.history_window_hours),
                lgbm_params=lgbm_params,
                q_up=q_up if use_upstream else None,
                return_cutoffs=True,
            )
        elif args.model in (
            "direct_ridge",
            "direct_lgbm",
            "direct_ridge_upstream",
            "direct_lgbm_upstream",
        ):
            kind = "direct_ridge" if "ridge" in str(args.model) else "direct_lgbm"
            preds, actuals, skipped, cutoffs = walk_forward_direct_exog(
                y,
                prec,
                temp,
                h,
                lag=lag_eff,
                step=int(args.step),
                max_cutoffs=int(args.max_cutoffs),
                history_window_hours=int(args.history_window_hours),
                model_kind=kind,
                ridge_alpha=float(args.ridge_alpha),
                lgbm_params=lgbm_params,
                q_up=q_up if use_upstream else None,
                return_cutoffs=True,
            )
        else:
            raise SystemExit(2)
        if len(preds) == 0:
            grid[str(h)] = {"error": "no_valid_predictions", "skipped_cutoffs": skipped}
            continue
        mask = np.isfinite(preds) & np.isfinite(actuals)
        preds = preds[mask]
        actuals = actuals[mask]
        cutoffs = cutoffs[mask]
        if len(preds) == 0:
            grid[str(h)] = {"error": "no_finite_pairs", "skipped_cutoffs": skipped}
            continue
        pers_p, pers_a, seas_p, seas_mask = _baseline_pairs(y, cutoffs, h)
        by_h_arrays[h] = {
            "preds": preds,
            "actuals": actuals,
            "cutoffs": cutoffs,
            "pers_p": pers_p,
            "pers_a": pers_a,
            "seas_p": seas_p,
            "seas_mask": seas_mask,
        }
        m = _metrics(preds, actuals)
        m["skipped_cutoffs"] = skipped
        grid[str(h)] = m

    smape_by_h: dict[int, float] = {}
    mae_by_h: dict[int, float] = {}
    for h in horizons:
        cell = grid.get(str(h), {})
        if "smape_pct" in cell:
            smape_by_h[h] = float(cell["smape_pct"])
            mae_by_h[h] = float(cell["mae"])
    tier = ranking_scores_from_horizon_metrics(list(smape_by_h.keys()), smape_by_h, mae_by_h)

    summary_by_eval_window: dict[str, Any] = {}
    for win in ("all", "tuning", "holdout"):
        per_h_pack: dict[int, dict[str, Any]] = {}
        for h in horizons:
            d = by_h_arrays.get(h)
            if not d:
                continue
            pm, am, _, pp, pa, sp, sm = _apply_window_mask(
                d["preds"],
                d["actuals"],
                d["cutoffs"],
                d["pers_p"],
                d["pers_a"],
                d["seas_p"],
                d["seas_mask"],
                win,
                split_ix,
            )
            per_h_pack[h] = {
                "model_pred": pm,
                "model_act": am,
                "pers_pred": pp,
                "pers_act": pa,
                "seas_pred": sp,
                "seas_mask": sm,
            }
        summary_by_eval_window[win] = _metrics_by_h_for_window(horizons, per_h_pack)

    all_cutoffs = (
        np.unique(np.concatenate([d["cutoffs"] for d in by_h_arrays.values()]))
        if by_h_arrays
        else np.array([], dtype=np.int64)
    )
    strata_thr = _strata_thresholds_tuning(y, prec, all_cutoffs, split_ix)
    summary_strata_holdout = _summary_strata_holdout(horizons, by_h_arrays, y, prec, split_ix, strata_thr)

    tier_means_all = summary_by_eval_window.get("all", {}).get("model", {})
    tier_means_holdout = summary_by_eval_window.get("holdout", {}).get("model", {})

    out_payload = {
        "features_csv": str(csv_path.resolve()),
        "model": args.model,
        "evaluation_contract_ref": "plan/evaluation_contract.md v2",
        "upstream_provenance": upstream_prov,
        "notes": {
            "direct_exog": "Lags of y, precipitation_mm, temperature_2m_c only use hours <= row end; no target-time exog peek.",
            "direct_exog_upstream": (
                f"Adds 4th lag block: {UPSTREAM_DISCHARGE_COL} = USGS 00060 discharge (ft³/s) at site 12116400 "
                "(Cedar Falls), NOT turbidity; see upstream_provenance."
            ),
            "recursive_ridge_exog_hindcast": "During rollout, precip/temp blocks use observed values at simulated hour (historical replay only).",
            "recursive_exog_upstream_hindcast": "Rollout also uses observed upstream discharge at T+k (hindcast).",
            "recursive_lgbm_exog_hindcast": "Same rollout design as recursive_ridge_exog_hindcast; one-step learner is LGBM instead of Ridge.",
            "baselines": "persistence: yhat(T+h)=y(T). seasonal: yhat(T+h)=y(T+h-24) when index valid; evaluated on same cutoffs as the model.",
            "eval_windows": "tuning = cutoffs with idx_T < split_index; holdout = idx_T >= split_index (see holdout_split).",
            "strata": "high_turbidity_at_T and heavy_precip_6h_at_T thresholds frozen from tuning cutoffs (P90).",
        },
        "summary_strata_holdout": summary_strata_holdout,
        "horizons": horizons,
        "step": int(args.step),
        "max_cutoffs": int(args.max_cutoffs),
        "history_window_hours": int(args.history_window_hours),
        "ridge_alpha": float(args.ridge_alpha),
        "effective_lag": int(lag_eff),
        "series_hours": int(len(y)),
        "holdout_split": split_info,
        "tier_ranking": tier,
        "summary_by_eval_window": summary_by_eval_window,
        "tier_means_all_cutoffs": {
            "tier_a_mean_smape_pct": tier_means_all.get("tier_a_mean_smape_pct"),
            "tier_a_mean_mae": tier_means_all.get("tier_a_mean_mae"),
            "tier_b_mean_smape_pct": tier_means_all.get("tier_b_mean_smape_pct"),
            "tier_b_mean_mae": tier_means_all.get("tier_b_mean_mae"),
            "h1_12_mean_smape_pct": tier_means_all.get("h1_12_mean_smape_pct"),
            "h1_12_mean_mae": tier_means_all.get("h1_12_mean_mae"),
        },
        "tier_means_holdout_cutoffs": {
            "tier_a_mean_smape_pct": tier_means_holdout.get("tier_a_mean_smape_pct"),
            "tier_a_mean_mae": tier_means_holdout.get("tier_a_mean_mae"),
            "tier_b_mean_smape_pct": tier_means_holdout.get("tier_b_mean_smape_pct"),
            "tier_b_mean_mae": tier_means_holdout.get("tier_b_mean_mae"),
            "h1_12_mean_smape_pct": tier_means_holdout.get("h1_12_mean_smape_pct"),
            "h1_12_mean_mae": tier_means_holdout.get("h1_12_mean_mae"),
        },
        "per_horizon": grid,
    }
    mean_s = float(np.mean([smape_by_h[h] for h in smape_by_h])) if smape_by_h else float("nan")
    ta = tier_means_all.get("tier_a_mean_smape_pct")
    tha = tier_means_holdout.get("tier_a_mean_smape_pct")
    ta_s = f"{ta:.4f}%" if ta is not None else "na"
    tha_s = f"{tha:.4f}%" if tha is not None else "na"
    print(
        f"model={args.model}  mean_sMAPE_h1_12_all_cutoffs={mean_s:.4f}%  "
        f"tierA_sMAPE_all={ta_s}  tierA_sMAPE_holdout={tha_s}  tier_primary={tier.get('ranking_primary_mean_smape_pct')}"
    )
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(out_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {args.json_out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Extended causal features for 12h turbidity risk classification at cutoff T.

Adds precipitation rolling sums (no precip ffill), upstream discharge derivatives,
and optional on-demand IsolationForest scores (univariate / multivariate) at T.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

from .backtest_turbidity_exog_ridge_lgbm import UPSTREAM_DISCHARGE_COL
from .site_param_anomaly_on_demand import MAX_TRAIN_POINTS, MIN_HOURLY_POINTS
from .turbidity_risk_forecast_backtest import _exog_blocks_no_temp
from .turbidity_tier_vs_if_eval import IF_CONTAMINATION, IF_N_ESTIMATORS, IF_RANDOM_STATE
from .turbidity_tier_vs_multivar_if_eval import MULTIVAR_FEATURE_COLS, fit_multivar_if_is_anomaly

PRECIP_SUM_WINDOWS: Final[tuple[int, ...]] = (6, 12, 24)
UPSTREAM_ROLL_WINDOWS: Final[tuple[int, ...]] = (6, 12, 24)

N_SCALAR_EXOG: Final[int] = len(PRECIP_SUM_WINDOWS) + 1 + len(UPSTREAM_ROLL_WINDOWS)  # 3+1+3=7
N_UNIVARIATE_IF: Final[int] = 2  # is_anomaly, score
N_MULTIVARIATE_IF: Final[int] = 2


def extended_scalar_feature_dim(*, has_upstream: bool) -> int:
    if has_upstream:
        return N_SCALAR_EXOG
    return len(PRECIP_SUM_WINDOWS)


def extended_feature_dim(
    lag: int,
    *,
    has_upstream: bool,
    with_univariate_if: bool,
    with_multivariate_if: bool,
) -> int:
    n_blocks = 3 if has_upstream else 2
    dim = n_blocks * int(lag)
    dim += extended_scalar_feature_dim(has_upstream=has_upstream)
    if with_univariate_if:
        dim += N_UNIVARIATE_IF
    if with_multivariate_if:
        dim += N_MULTIVARIATE_IF
    return dim


def _finite_sum(series: pd.Series, end_ix: int, hours: int) -> float:
    start = max(0, int(end_ix) - int(hours) + 1)
    chunk = series.iloc[start : int(end_ix) + 1].to_numpy(dtype=float, copy=False)
    finite = chunk[np.isfinite(chunk)]
    if finite.size == 0:
        return float("nan")
    return float(finite.sum())


def _rolling_max(series: pd.Series, end_ix: int, hours: int) -> float:
    start = max(0, int(end_ix) - int(hours) + 1)
    chunk = series.iloc[start : int(end_ix) + 1].to_numpy(dtype=float, copy=False)
    finite = chunk[np.isfinite(chunk)]
    if finite.size == 0:
        return float("nan")
    return float(finite.max())


def _upstream_diff_1h(q_up: pd.Series, end_ix: int) -> float:
    if end_ix < 1:
        return float("nan")
    a = float(q_up.iloc[end_ix])
    b = float(q_up.iloc[end_ix - 1])
    if not np.isfinite(a) or not np.isfinite(b):
        return float("nan")
    return float(a - b)


def precip_upstream_scalar_features(
    prec: pd.Series,
    q_up: pd.Series | None,
    *,
    end_ix: int,
) -> np.ndarray:
    parts: list[float] = [_finite_sum(prec, end_ix, w) for w in PRECIP_SUM_WINDOWS]
    if q_up is not None:
        parts.append(_upstream_diff_1h(q_up, end_ix))
        parts.extend(_rolling_max(q_up, end_ix, w) for w in UPSTREAM_ROLL_WINDOWS)
    arr = np.asarray(parts, dtype=float)
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


def _fit_if_score_univariate(window: np.ndarray) -> dict[str, Any]:
    w = np.asarray(window, dtype=float)
    w = w[np.isfinite(w)]
    n = len(w)
    if n < MIN_HOURLY_POINTS:
        return {
            "available": False,
            "is_anomaly": 0.0,
            "score": 0.0,
            "reason": "insufficient_history",
            "samples_used": n,
        }
    tail = w[-MAX_TRAIN_POINTS:]
    X = tail.reshape(-1, 1)
    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X)
    max_samples = min(256, len(X_scaled))
    iso = IsolationForest(
        n_estimators=IF_N_ESTIMATORS,
        max_samples=max_samples,
        contamination=IF_CONTAMINATION,
        random_state=IF_RANDOM_STATE,
    )
    iso.fit(X_scaled)
    last = X_scaled[-1:]
    pred_label = int(iso.predict(last)[0])
    raw = float((-iso.score_samples(last))[0])
    return {
        "available": True,
        "is_anomaly": float(pred_label == -1),
        "score": raw,
        "reason": None,
        "samples_used": len(tail),
    }


def _fit_if_score_multivariate(window: np.ndarray) -> dict[str, Any]:
    is_anom, meta = fit_multivar_if_is_anomaly(window)
    if is_anom is None:
        return {
            "available": False,
            "is_anomaly": 0.0,
            "score": 0.0,
            "reason": meta.get("reason"),
            "samples_used": int(meta.get("samples_used") or 0),
        }
    w = np.asarray(window, dtype=float)
    row_ok = np.all(np.isfinite(w), axis=1)
    w = w[row_ok]
    tail = w[-MAX_TRAIN_POINTS:]
    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(tail)
    max_samples = min(256, len(X_scaled))
    iso = IsolationForest(
        n_estimators=IF_N_ESTIMATORS,
        max_samples=max_samples,
        contamination=IF_CONTAMINATION,
        random_state=IF_RANDOM_STATE,
    )
    iso.fit(X_scaled)
    last = X_scaled[-1:]
    raw = float((-iso.score_samples(last))[0])
    return {
        "available": True,
        "is_anomaly": float(is_anom),
        "score": raw,
        "reason": None,
        "samples_used": len(tail),
    }


class IfScoreCache:
    """Per-cutoff IF scores (fit on trailing history up to T only)."""

    def __init__(
        self,
        y: pd.Series,
        *,
        multivar_matrix: np.ndarray | None = None,
        with_univariate: bool = True,
        with_multivariate: bool = True,
    ) -> None:
        self._y_num = y.to_numpy(dtype=float, copy=False)
        self._valid_y_pos = np.flatnonzero(np.isfinite(self._y_num))
        self._multivar = multivar_matrix
        self._with_uni = with_univariate
        self._with_mvar = with_multivariate and multivar_matrix is not None
        self._uni: dict[int, dict[str, Any]] = {}
        self._mvar: dict[int, dict[str, Any]] = {}

    def _upto_positions(self, idx_T: int) -> np.ndarray:
        return self._valid_y_pos[self._valid_y_pos <= idx_T]

    def univariate_at(self, idx_T: int) -> dict[str, Any]:
        if not self._with_uni:
            return {"available": False, "is_anomaly": 0.0, "score": 0.0}
        if idx_T in self._uni:
            return self._uni[idx_T]
        upto = self._upto_positions(idx_T)
        if len(upto) == 0 or upto[-1] != idx_T:
            out = {
                "available": False,
                "is_anomaly": 0.0,
                "score": 0.0,
                "reason": "y_not_finite_at_t",
            }
        else:
            out = _fit_if_score_univariate(self._y_num[upto])
        self._uni[idx_T] = out
        return out

    def multivariate_at(self, idx_T: int) -> dict[str, Any]:
        if not self._with_mvar or self._multivar is None:
            return {"available": False, "is_anomaly": 0.0, "score": 0.0}
        if idx_T in self._mvar:
            return self._mvar[idx_T]
        row_ok = np.all(np.isfinite(self._multivar), axis=1)
        valid_pos = np.flatnonzero(row_ok)
        upto = valid_pos[valid_pos <= idx_T]
        if len(upto) == 0 or upto[-1] != idx_T:
            out = {
                "available": False,
                "is_anomaly": 0.0,
                "score": 0.0,
                "reason": "multivar_not_finite_at_t",
            }
        else:
            out = _fit_if_score_multivariate(self._multivar[upto])
        self._mvar[idx_T] = out
        return out

    def needs_warm(
        self,
        idx_T: int,
        *,
        with_univariate_if: bool,
        with_multivariate_if: bool,
    ) -> bool:
        """True when at least one requested IF score is not yet cached at idx_T."""
        if with_univariate_if and idx_T not in self._uni:
            return True
        if with_multivariate_if and idx_T not in self._mvar:
            return True
        return False

    def vector_at(
        self,
        idx_T: int,
        *,
        with_univariate_if: bool,
        with_multivariate_if: bool,
    ) -> np.ndarray:
        parts: list[float] = []
        if with_univariate_if:
            u = self.univariate_at(idx_T)
            parts.extend([float(u["is_anomaly"]), float(u["score"])])
        if with_multivariate_if:
            m = self.multivariate_at(idx_T)
            parts.extend([float(m["is_anomaly"]), float(m["score"])])
        return np.asarray(parts, dtype=float)


def build_multivar_matrix_from_df(df: pd.DataFrame) -> np.ndarray:
    missing = [c for c in MULTIVAR_FEATURE_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"features CSV missing multivariate columns: {missing}")
    parts = [
        pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float, copy=False)
        for c in MULTIVAR_FEATURE_COLS
    ]
    return np.column_stack(parts)


def features_at_cutoff_extended(
    y: pd.Series,
    prec: pd.Series,
    q_up: pd.Series | None,
    idx_T: int,
    *,
    lag: int,
    if_cache: IfScoreCache | None = None,
    with_univariate_if: bool = False,
    with_multivariate_if: bool = False,
) -> np.ndarray | None:
    base = _exog_blocks_no_temp(
        y,
        prec,
        q_up,
        end_ix_y=idx_T,
        end_ix_exog=idx_T,
        lag=lag,
    )
    if base is None:
        return None
    scalars = precip_upstream_scalar_features(prec, q_up, end_ix=idx_T)
    chunks = [base, scalars]
    if if_cache is not None and (with_univariate_if or with_multivariate_if):
        chunks.append(
            if_cache.vector_at(
                idx_T,
                with_univariate_if=with_univariate_if,
                with_multivariate_if=with_multivariate_if,
            )
        )
    return np.concatenate(chunks, axis=0)


def warm_if_cache(
    if_cache: IfScoreCache,
    cutoff_indices: list[int],
    *,
    with_univariate_if: bool,
    with_multivariate_if: bool,
    log_every: int = 2000,
) -> None:
    """Pre-score IF at listed cutoffs (cached per index)."""
    pending = [
        ix
        for ix in cutoff_indices
        if if_cache.needs_warm(
            ix,
            with_univariate_if=with_univariate_if,
            with_multivariate_if=with_multivariate_if,
        )
    ]
    skipped = len(cutoff_indices) - len(pending)
    if skipped:
        print(f"  IF cache: skip {skipped} already-warmed cutoffs", flush=True)
    n = len(pending)
    for i, ix in enumerate(pending):
        if with_univariate_if:
            if_cache.univariate_at(ix)
        if with_multivariate_if:
            if_cache.multivariate_at(ix)
        if log_every > 0 and (i + 1) % log_every == 0:
            print(f"  IF cache: {i + 1}/{n} cutoffs", flush=True)

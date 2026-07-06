#!/usr/bin/env python3
"""
Generate linearity / baseline-vs-tree diagnostics for one site + parameter:
- Lag scatter plots (y_t vs y_{t-k})
- Walk-forward 1-step residual series (Ridge vs tree, no leakage)
- Walk-forward multi-horizon backtest (same recursive protocol as forecast_engine Ridge)

Outputs are written under linearity_eval/output/<site>_<parameter>/ by default.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

# Allow imports from ai_service root when run as a script.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from forecast_engine import (  # noqa: E402
    FORECAST_MODEL_VERSION,
    MAX_LAG,
    MIN_HOURLY_POINTS,
    _build_lag_dataset,
    _fit_and_predict_recursive,
    load_hourly_series,
)


def _metrics(pred: np.ndarray, actual: np.ndarray) -> dict[str, float | int]:
    pred = pred.astype(float)
    actual = actual.astype(float)
    err = pred - actual
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    denom = (np.abs(actual) + np.abs(pred) + 1e-9) / 2.0
    smape = float(np.mean(np.abs(err) / denom) * 100.0)
    mask = np.abs(actual) > 1e-6
    mape = float(np.mean(np.abs(err[mask] / actual[mask])) * 100.0) if np.any(mask) else float("nan")
    corr = float("nan")
    if len(pred) >= 2:
        c = np.corrcoef(pred, actual)[0, 1]
        corr = float(c) if not np.isnan(c) else float("nan")
    # Directional accuracy on consecutive evaluation points (same ordering as walk-forward).
    dir_acc = float("nan")
    if len(pred) >= 2:
        dp = np.diff(pred)
        da = np.diff(actual)
        ok = (dp != 0) & (da != 0)
        if np.any(ok):
            dir_acc = float(np.mean(np.sign(dp[ok]) == np.sign(da[ok])) * 100.0)
    return {
        "n": int(len(pred)),
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
        "smape_pct": round(smape, 4),
        "mape_pct": round(mape, 4) if not np.isnan(mape) else float("nan"),
        "pred_actual_corr": round(corr, 6) if not np.isnan(corr) else float("nan"),
        "directional_accuracy_pct": round(dir_acc, 4) if not np.isnan(dir_acc) else float("nan"),
    }


def _adaptive_lag(n: int) -> int:
    lag = min(MAX_LAG, n // 3, n - 10)
    lag = max(lag, 6)
    return int(lag)


def _make_tree_estimator(backend: str, *, max_iter: int, max_depth: int) -> object:
    backend = backend.strip().lower()
    if backend == "lightgbm":
        try:
            import lightgbm as lgb  # type: ignore
        except ImportError as e:
            raise SystemExit(
                "lightgbm is not installed. Install it or use --tree-backend histgb."
            ) from e
        return lgb.LGBMRegressor(
            n_estimators=int(max_iter),
            learning_rate=0.08,
            max_depth=int(max_depth),
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            verbosity=-1,
        )
    if backend == "histgb":
        # Keep this lightweight: walk-forward retrains many times on moderate-length series.
        return HistGradientBoostingRegressor(
            max_depth=int(max_depth),
            learning_rate=0.08,
            max_iter=int(max_iter),
            random_state=42,
        )
    raise ValueError(f"Unknown tree backend: {backend}")


def _fit_and_predict_recursive_tree(
    y: np.ndarray,
    horizon: int,
    max_lag: int,
    tree_estimator: object,
) -> tuple[float | None, str | None]:
    """Same recursive protocol as Ridge in forecast_engine, but with a sklearn-compatible tree model."""
    n = len(y)
    if n < MIN_HOURLY_POINTS:
        return None, "insufficient_history"
    lag = min(max_lag, n // 3, n - 10)
    lag = max(lag, 6)
    if n < lag + 5:
        return None, "insufficient_history"

    X, y_tr = _build_lag_dataset(y, lag)
    if X.shape[0] < 20:
        return None, "insufficient_history"

    model = clone(tree_estimator)
    try:
        model.fit(X, y_tr)
    except ValueError:
        return None, "fit_failed"

    window = y[-lag:].astype(float).copy()
    for _ in range(int(horizon)):
        pred = float(model.predict(window.reshape(1, -1))[0])
        window = np.append(window[1:], pred)
    return float(pred), None


def _walk_forward_multistep(
    y: np.ndarray,
    horizon: int,
    *,
    step: int,
    kind: str,
    tree_estimator: object | None,
) -> tuple[np.ndarray, np.ndarray, int]:
    n = len(y)
    h = int(horizon)
    step = max(1, int(step))
    preds: list[float] = []
    actuals: list[float] = []
    skipped = 0
    t_min = MIN_HOURLY_POINTS - 1
    for t in range(t_min, n - h, step):
        prefix = y[: t + 1].astype(float)
        if kind == "ridge":
            p, err = _fit_and_predict_recursive(prefix, h, MAX_LAG)
        elif kind == "tree":
            assert tree_estimator is not None
            p, err = _fit_and_predict_recursive_tree(prefix, h, MAX_LAG, tree_estimator)
        else:
            raise ValueError(kind)
        if p is None or err is not None:
            skipped += 1
            continue
        preds.append(p)
        actuals.append(float(y[t + h]))
    return np.asarray(preds, dtype=float), np.asarray(actuals, dtype=float), skipped


def _walk_forward_one_step_series(
    index: pd.DatetimeIndex,
    y: np.ndarray,
    *,
    step: int,
    kind: str,
    tree_estimator: object | None,
) -> tuple[list[pd.Timestamp], list[float], list[float], list[float]]:
    """Walk-forward predict y[t+1] using only y[:t+1] for training (true 1-step OOS)."""
    n = len(y)
    step = max(1, int(step))
    times: list[pd.Timestamp] = []
    actuals: list[float] = []
    preds: list[float] = []
    residuals: list[float] = []

    t_min = MIN_HOURLY_POINTS - 1
    for t in range(t_min, n - 1, step):
        train = y[: t + 1].astype(float)
        lag = _adaptive_lag(len(train))
        if len(train) < lag + 5:
            continue
        X_tr, y_tr = _build_lag_dataset(train, lag)
        if X_tr.shape[0] < 20:
            continue
        x_test = y[t + 1 - lag : t + 1].astype(float).reshape(1, -1)
        y_true = float(y[t + 1])
        try:
            if kind == "ridge":
                model = Ridge(alpha=2.0)
                model.fit(X_tr, y_tr)
                y_hat = float(model.predict(x_test)[0])
            elif kind == "tree":
                assert tree_estimator is not None
                model = clone(tree_estimator)
                model.fit(X_tr, y_tr)
                y_hat = float(model.predict(x_test)[0])
            else:
                raise ValueError(kind)
        except ValueError:
            continue

        times.append(index[t + 1])
        actuals.append(y_true)
        preds.append(y_hat)
        residuals.append(y_hat - y_true)

    return times, actuals, preds, residuals


def _plot_lag_scatter(y: np.ndarray, lag: int, out_path: Path, max_points: int) -> None:
    if lag <= 0 or len(y) <= lag:
        return
    x = y[:-lag]
    yy = y[lag:]
    if len(x) > max_points:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(x), size=max_points, replace=False)
        x = x[idx]
        yy = yy[idx]
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(x, yy, s=4, alpha=0.35, color="#1f77b4")
    ax.set_title(f"Lag scatter: y(t) vs y(t-{lag})  (n={len(x)})")
    ax.set_xlabel(f"y(t-{lag})")
    ax.set_ylabel("y(t)")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _plot_residual_series(
    times: list[pd.Timestamp],
    residuals: list[float],
    title: str,
    out_path: Path,
) -> None:
    if not times:
        return
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(times, residuals, linewidth=1.0, color="#d62728")
    ax.axhline(0.0, color="#333333", linewidth=1.0, alpha=0.6)
    ax.set_title(title)
    ax.set_ylabel("residual (pred - actual)")
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Linearity diagnostics + Ridge vs tree walk-forward report")
    p.add_argument("--site-no", required=True)
    p.add_argument("--parameter-cd", required=True)
    p.add_argument(
        "--iv-csv",
        default=str(_ROOT / "data" / "usgs_puget_iv.csv"),
        help="Merged USGS IV CSV path",
    )
    p.add_argument("--step", type=int, default=24, help="Walk-forward stride on time index")
    p.add_argument(
        "--horizons",
        default="1,6,12,24,48,72,168",
        help="Comma-separated horizons (hours)",
    )
    p.add_argument(
        "--tree-backend",
        default="histgb",
        choices=["histgb", "lightgbm"],
        help="Tree model backend for comparison (default avoids extra deps)",
    )
    p.add_argument("--tree-max-iter", type=int, default=120, help="Tree boosting rounds / max_iter (upper bound)")
    p.add_argument("--tree-max-depth", type=int, default=6, help="Tree max depth")
    p.add_argument(
        "--lag-scatter-lags",
        default="1,6,24",
        help="Comma-separated lags for scatter plots",
    )
    p.add_argument(
        "--out-dir",
        default="",
        help="Output directory (default: linearity_eval/output/<site>_<param>)",
    )
    p.add_argument("--max-scatter-points", type=int, default=25_000)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.iv_csv)
    if not csv_path.is_file():
        print(f"Missing IV CSV: {csv_path}", file=sys.stderr)
        raise SystemExit(1)

    site_no = str(args.site_no).strip()
    parameter_cd = str(args.parameter_cd).strip()

    s = load_hourly_series(csv_path, site_no, parameter_cd, dense=True)
    if s.empty:
        print(f"No hourly series for site={site_no} parameter={parameter_cd}", file=sys.stderr)
        raise SystemExit(1)

    y = s.values.astype(float)
    horizons = [int(x.strip()) for x in str(args.horizons).split(",") if x.strip()]
    lag_scatter_lags = [int(x.strip()) for x in str(args.lag_scatter_lags).split(",") if x.strip()]

    out_dir = Path(args.out_dir) if str(args.out_dir).strip() else Path(__file__).resolve().parent / "output" / f"{site_no}_{parameter_cd}"
    out_dir.mkdir(parents=True, exist_ok=True)

    tree_estimator = _make_tree_estimator(
        args.tree_backend,
        max_iter=int(args.tree_max_iter),
        max_depth=int(args.tree_max_depth),
    )

    meta = {
        "ridge_model_version": FORECAST_MODEL_VERSION,
        "tree_backend": args.tree_backend,
        "iv_csv": str(csv_path.resolve()),
        "site_no": site_no,
        "parameter_cd": parameter_cd,
        "series_hours": int(len(y)),
        "time_range_utc": [s.index[0].isoformat(), s.index[-1].isoformat()],
        "walk_forward_step": int(args.step),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Lag scatter plots
    for k in lag_scatter_lags:
        _plot_lag_scatter(y, k, out_dir / f"lag_scatter_lag{k}.png", max_points=int(args.max_scatter_points))

    # 1-step residuals
    t_r, a_r, p_r, e_r = _walk_forward_one_step_series(
        s.index, y, step=args.step, kind="ridge", tree_estimator=None
    )
    t_t, a_t, p_t, e_t = _walk_forward_one_step_series(
        s.index, y, step=args.step, kind="tree", tree_estimator=tree_estimator
    )
    _plot_residual_series(
        t_r,
        e_r,
        title=f"Walk-forward 1-step residuals — Ridge (step={args.step}h)",
        out_path=out_dir / "residuals_1step_ridge.png",
    )
    _plot_residual_series(
        t_t,
        e_t,
        title=f"Walk-forward 1-step residuals — Tree ({args.tree_backend}, step={args.step}h)",
        out_path=out_dir / f"residuals_1step_tree_{args.tree_backend}.png",
    )

    one_step_summary = {
        "ridge": _metrics(np.asarray(p_r, dtype=float), np.asarray(a_r, dtype=float)) if p_r else {"n": 0},
        "tree": _metrics(np.asarray(p_t, dtype=float), np.asarray(a_t, dtype=float)) if p_t else {"n": 0},
    }
    (out_dir / "one_step_summary.json").write_text(
        json.dumps(one_step_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Multi-horizon walk-forward comparison (recursive protocol)
    report: dict[str, object] = {
        **meta,
        "horizons": {},
    }
    for h in horizons:
        pr, ar, sr = _walk_forward_multistep(y, h, step=args.step, kind="ridge", tree_estimator=None)
        pt, at, st = _walk_forward_multistep(y, h, step=args.step, kind="tree", tree_estimator=tree_estimator)
        block: dict[str, object] = {"horizon_hours": int(h), "cutoff_step": int(args.step)}
        if len(pr) == 0:
            block["ridge"] = {"error": "no_valid_predictions", "skipped_cutoffs": sr}
        else:
            m = _metrics(pr, ar)
            m["skipped_cutoffs"] = sr
            block["ridge"] = m
        if len(pt) == 0:
            block["tree"] = {"error": "no_valid_predictions", "skipped_cutoffs": st}
        else:
            m = _metrics(pt, at)
            m["skipped_cutoffs"] = st
            block["tree"] = m
        report["horizons"][str(h)] = block

    (out_dir / "walkforward_recursive_compare.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Wrote report to: {out_dir.resolve()}")


if __name__ == "__main__":
    main()

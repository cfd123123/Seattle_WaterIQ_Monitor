#!/usr/bin/env python3
"""
Random-search tuning for LightGBM direct forecasts (horizons 1..12).

Uses the same walk-forward protocol as backtest_model_suite_00060.py:
lag features -> fit LGBMRegressor -> predict y[t+h] at each cutoff.

Objective (default): minimize mean sMAPE across horizons 1..12 (business-aligned).

Interview takeaway:
- Fix evaluation protocol first (time-series CV / walk-forward), then optimize hyperparameters
  against business KPIs; avoid tuning on the same slice you use for final reporting (holdout).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Allow imports from ai_service when this file lives under ai_service/models/.
_AI_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(_AI_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_SERVICE_ROOT))

# sklearn emits noisy warnings when predicting with ndarray after LightGBM sklearn API stores names.
warnings.filterwarnings(
    "ignore",
    message=".*feature names.*",
    category=UserWarning,
    module="sklearn.utils.validation",
)
from lightgbm import LGBMRegressor

from forecast_engine import (
    MAX_LAG,
    MIN_HOURLY_POINTS,
    _effective_lag,
    load_hourly_series,
    slice_series_upto_cutoff,
)


def _metrics(pred: np.ndarray, actual: np.ndarray) -> dict[str, float]:
    pred = pred.astype(float)
    actual = actual.astype(float)
    err = pred - actual
    denom = (np.abs(actual) + np.abs(pred) + 1e-9) / 2.0
    smape = float(np.mean(np.abs(err) / denom) * 100.0)
    mae = float(np.mean(np.abs(err)))
    return {"smape_pct": smape, "mae": mae}


def _fit_predict_lgbm_direct_calendar(
    sub: pd.Series,
    idx_cutoff: int,
    horizon: int,
    lag: int,
    *,
    params: dict[str, Any],
) -> tuple[float | None, str | None]:
    h = int(horizon)
    rows_x: list[np.ndarray] = []
    rows_y: list[float] = []
    for o in range(lag - 1, idx_cutoff - h + 1):
        w = sub.iloc[o - lag + 1 : o + 1]
        if int(w.shape[0]) != lag or not w.notna().all():
            continue
        if pd.isna(sub.iloc[o + h]):
            continue
        rows_x.append(w.to_numpy(dtype=float, copy=False))
        rows_y.append(float(sub.iloc[o + h]))
    if len(rows_y) < 20:
        return None, "insufficient_history"
    w_test = sub.iloc[idx_cutoff - lag + 1 : idx_cutoff + 1]
    if int(w_test.shape[0]) != lag or not w_test.notna().all():
        return None, "invalid_cutoff"
    # ``sub`` ends at cutoff; horizon target may lie outside ``sub``. Callers (walk-forward)
    # already skip NA using the full series; only validate when the row exists in ``sub``.
    if idx_cutoff + h < len(sub) and pd.isna(sub.iloc[idx_cutoff + h]):
        return None, "invalid_cutoff"
    X = np.stack(rows_x, axis=0)
    y_tr = np.asarray(rows_y, dtype=float)
    x_test = w_test.to_numpy(dtype=float, copy=False).reshape(1, -1)
    model = LGBMRegressor(
        objective="regression",
        random_state=int(params.get("random_state", 42)),
        verbosity=-1,
        n_jobs=1,
        **{k: v for k, v in params.items() if k != "random_state"},
    )
    try:
        model.fit(X, y_tr)
        pred = float(model.predict(x_test)[0])
    except ValueError:
        return None, "fit_failed"
    return pred, None


def _walk_forward(
    s: pd.Series,
    horizon: int,
    *,
    step: int,
    params: dict[str, Any],
    max_cutoffs: int,
    history_window_hours: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    preds: list[float] = []
    actuals: list[float] = []
    skipped = 0
    h = int(horizon)
    n = len(s)
    lag_full = _effective_lag(n, MAX_LAG)
    idx_start = max(MIN_HOURLY_POINTS - 1, lag_full)
    if max_cutoffs > 0:
        idx_start = max(idx_start, (n - h) - int(max_cutoffs))
    for idx_T in range(idx_start, n - h, max(1, int(step))):
        if pd.isna(s.iloc[idx_T + h]):
            skipped += 1
            continue
        sub, loc = slice_series_upto_cutoff(s, idx_T, history_window_hours)
        if loc < 0:
            skipped += 1
            continue
        lag = _effective_lag(len(sub), MAX_LAG)
        p, err = _fit_predict_lgbm_direct_calendar(sub, loc, h, lag, params=params)
        if p is None or err is not None:
            skipped += 1
            continue
        preds.append(p)
        actuals.append(float(s.iloc[idx_T + h]))
    return np.asarray(preds, dtype=float), np.asarray(actuals, dtype=float), skipped


def _mean_smape_across_horizons(
    s: pd.Series,
    horizons: list[int],
    *,
    step: int,
    params: dict[str, Any],
    max_cutoffs: int,
    history_window_hours: int,
) -> tuple[float, int]:
    smapes: list[float] = []
    ok_h = 0
    for h in horizons:
        pred, actual, _ = _walk_forward(
            s,
            h,
            step=step,
            params=params,
            max_cutoffs=max_cutoffs,
            history_window_hours=history_window_hours,
        )
        if len(pred) == 0:
            continue
        m = _metrics(pred, actual)
        smapes.append(m["smape_pct"])
        ok_h += 1
    if not smapes:
        return math.inf, 0
    return float(np.mean(smapes)), ok_h


def _sample_params(rng: random.Random) -> dict[str, Any]:
    """Small search space; expand here as needed."""
    return {
        "n_estimators": rng.choice([40, 80, 120, 200]),   # how many trees to grow
        "learning_rate": rng.choice([0.03, 0.05, 0.08, 0.1]), # how much to shrink the contribution of each tree
        "num_leaves": rng.choice([15, 31, 63, 127]),
        "max_depth": rng.choice([-1, 8, 12]), # -1 means no limit, 8 means 8 levels of depth, 12 means 12 levels of depth
        "subsample": rng.choice([0.7, 0.8, 0.9]),
        "colsample_bytree": rng.choice([0.7, 0.8, 0.9]), # how much of the data to use for each tree
        "min_child_samples": rng.choice([10, 20, 40, 80]), # how many samples are required to split a node
        "reg_lambda": rng.choice([0.0, 0.1, 1.0, 5.0]), # L2 regularization strength
        "reg_alpha": rng.choice([0.0, 0.1, 0.5]),       # L1 regularization strength
        "random_state": 42,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Random search tuner for LightGBM direct (00060)")
    p.add_argument(
        "--iv-csv",
        default=str(_AI_SERVICE_ROOT / "data" / "usgs_puget_iv.csv"),
    )
    p.add_argument("--site-no", required=True)
    p.add_argument("--parameter-cd", default="00060")
    p.add_argument("--horizons", default="1-12")
    p.add_argument("--step", type=int, default=24)
    p.add_argument("--max-cutoffs", type=int, default=720)
    p.add_argument("--history-window-hours", type=int, default=1440)
    p.add_argument("--n-trials", type=int, default=25)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--json-out", default="")
    return p.parse_args()


def _parse_horizons(s: str) -> list[int]:
    s = str(s).strip()
    if s == "1-12":
        return list(range(1, 13))
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def main() -> None:
    args = parse_args()
    csv_path = Path(args.iv_csv)
    if not csv_path.is_file():
        print(f"Missing IV CSV: {csv_path}", file=sys.stderr)
        raise SystemExit(1)

    s = load_hourly_series(csv_path, args.site_no, args.parameter_cd, dense=False)
    if s.empty:
        print(f"No series for site={args.site_no} param={args.parameter_cd}", file=sys.stderr)
        raise SystemExit(1)

    horizons = _parse_horizons(args.horizons)
    rng = random.Random(int(args.seed))

    best_score = math.inf
    best_params: dict[str, Any] | None = None
    trials_out: list[dict[str, Any]] = []

    print(f"site={args.site_no} horizons={horizons} step={args.step} trials={args.n_trials}")
    for trial in range(int(args.n_trials)):
        params = _sample_params(rng)
        score, ok_h = _mean_smape_across_horizons(
            s,
            horizons,
            step=args.step,
            params=params,
            max_cutoffs=int(args.max_cutoffs),
            history_window_hours=int(args.history_window_hours),
        )
        trials_out.append({"trial": trial, "mean_smape_pct": score, "horizons_ok": ok_h, "params": params})
        print(f"  trial {trial + 1}/{args.n_trials} mean_sMAPE={score:.4f}% ok_h={ok_h}")
        if score < best_score:
            best_score = score
            best_params = dict(params)

    print()
    print(f"BEST mean_sMAPE={best_score:.6f}%")
    print(f"BEST params: {json.dumps(best_params, indent=2)}")

    payload = {
        "site_no": args.site_no,
        "parameter_cd": args.parameter_cd,
        "business_objective": "minimize mean sMAPE over horizons (default 1..12)",
        "horizons": horizons,
        "step": int(args.step),
        "max_cutoffs": int(args.max_cutoffs),
        "history_window_hours": int(args.history_window_hours),
        "n_trials": int(args.n_trials),
        "seed": int(args.seed),
        "best_mean_smape_pct": best_score,
        "best_params": best_params,
        "trials": trials_out,
    }

    if args.json_out:
        outp = Path(args.json_out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {outp.resolve()}")


if __name__ == "__main__":
    main()

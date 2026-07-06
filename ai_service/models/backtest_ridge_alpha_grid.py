#!/usr/bin/env python3
"""
Walk-forward Ridge 递归预测：对多个 ridge alpha 与多个 horizon（默认 1..12）做网格评估。

业务含义：评估「当前时刻之后第 1..12 小时」每一步的递归外推误差（与 forecast_engine 一致）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation_tiers import ranking_scores_from_horizon_metrics

from forecast_engine import (
    FORECAST_MODEL_VERSION,
    MAX_LAG,
    MIN_HOURLY_POINTS,
    RIDGE_ALPHA_DEFAULT,
    load_hourly_series,
    walk_forward_ridge_direct_calendar,
    walk_forward_ridge_recursive_calendar,
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
    dir_acc = float("nan")
    if len(pred) >= 2:
        dp = np.diff(pred)
        da = np.diff(actual)
        mask_dir = (dp != 0) & (da != 0)
        if np.any(mask_dir):
            dir_acc = float(np.mean(np.sign(dp[mask_dir]) == np.sign(da[mask_dir])) * 100.0)
    return {
        "n": int(len(pred)),
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
        "smape_pct": round(smape, 4),
        "mape_pct": round(mape, 4) if not np.isnan(mape) else float("nan"),
        "pred_actual_corr": round(corr, 6) if not np.isnan(corr) else float("nan"),
        "directional_accuracy_pct": round(dir_acc, 4) if not np.isnan(dir_acc) else float("nan"),
    }


def walk_forward_backtest(
    s: pd.Series,
    horizon: int,
    *,
    step: int,
    ridge_alpha: float,
    variant: str,
    history_window_hours: int,
    max_cutoffs: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    v = str(variant).strip().lower()
    if v == "recursive":
        return walk_forward_ridge_recursive_calendar(
            s,
            horizon,
            step=step,
            ridge_alpha=ridge_alpha,
            max_lag=MAX_LAG,
            history_window_hours=int(history_window_hours),
            max_cutoffs=int(max_cutoffs),
        )
    if v == "direct":
        return walk_forward_ridge_direct_calendar(
            s,
            horizon,
            step=step,
            ridge_alpha=ridge_alpha,
            max_lag=MAX_LAG,
            history_window_hours=int(history_window_hours),
            max_cutoffs=int(max_cutoffs),
        )
    raise ValueError(f"unsupported variant: {variant!r} (use recursive or direct)")


def _parse_float_list(s: str) -> list[float]:
    out: list[float] = []
    for part in str(s).split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    return out


def _parse_horizons(s: str) -> list[int]:
    s = str(s).strip()
    if s == "1-12":
        return list(range(1, 13))
    out: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ridge alpha grid + multi-horizon walk-forward backtest")
    p.add_argument(
        "--iv-csv",
        default=str(Path(__file__).resolve().parent.parent / "data" / "usgs_puget_iv.csv"),
    )
    p.add_argument("--site-no", required=True)
    p.add_argument("--parameter-cd", required=True)
    p.add_argument(
        "--horizons",
        default="1-12",
        help='e.g. "1-12" or "1,3,6,12"',
    )
    p.add_argument("--step", type=int, default=24)
    p.add_argument(
        "--ridge-alphas",
        default="0.1,0.5,1,2,5,10,20,50",
        help="Comma-separated Ridge alpha values",
    )
    p.add_argument(
        "--variant",
        choices=("recursive", "direct"),
        default="recursive",
        help="Walk-forward Ridge variant (same as model suite).",
    )
    p.add_argument(
        "--max-cutoffs",
        type=int,
        default=0,
        help="If >0, only evaluate the latest N cutoffs per horizon (0 = legacy: use full series).",
    )
    p.add_argument(
        "--history-window-hours",
        type=int,
        default=0,
        help="If >0, truncate history per cutoff like model_suite (0 = use full prefix).",
    )
    p.add_argument("--json-out", default="", help="Write full grid results JSON")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.iv_csv)
    if not csv_path.is_file():
        print(f"错误：找不到 IV CSV：{csv_path}", file=sys.stderr)
        raise SystemExit(1)

    s = load_hourly_series(csv_path, args.site_no, args.parameter_cd, dense=False)
    if s.empty:
        print(
            f"错误：站点 {args.site_no} / 参数 {args.parameter_cd} 无可用小时序列。",
            file=sys.stderr,
        )
        raise SystemExit(1)

    horizons = _parse_horizons(args.horizons)
    alphas = _parse_float_list(args.ridge_alphas)
    if not alphas:
        print("错误：--ridge-alphas 为空", file=sys.stderr)
        raise SystemExit(1)

    print(f"=== Ridge alpha grid (walk-forward {args.variant}) ===")
    print(f"model_version: {FORECAST_MODEL_VERSION}")
    print(f"default_alpha (线上): {RIDGE_ALPHA_DEFAULT}")
    print(f"iv_csv: {csv_path.resolve()}")
    print(f"site_no: {args.site_no}  parameter_cd: {args.parameter_cd}")
    print(f"series_grid_hours: {len(s)}  range: {s.index[0].isoformat()} .. {s.index[-1].isoformat()}")
    print(f"horizons: {horizons}")
    print(f"cutoff_step: {args.step}")
    print(f"max_cutoffs: {args.max_cutoffs}  history_window_hours: {args.history_window_hours}")
    print(f"alphas: {alphas}")
    print()

    grid: dict[str, dict[str, object]] = {}
    ranking: list[dict[str, float | int | str]] = []

    for alpha in alphas:
        key = str(alpha)
        grid[key] = {"ridge_alpha": alpha, "horizons": {}}
        smapes: list[float] = []
        maes: list[float] = []
        for h in horizons:
            preds, actuals, skipped = walk_forward_backtest(
                s,
                h,
                step=args.step,
                ridge_alpha=alpha,
                variant=str(args.variant),
                history_window_hours=int(args.history_window_hours),
                max_cutoffs=int(args.max_cutoffs),
            )
            if len(preds) == 0:
                grid[key]["horizons"][str(h)] = {"error": "no_valid_predictions", "skipped_cutoffs": skipped}
                continue
            m = _metrics(preds, actuals)
            m["skipped_cutoffs"] = skipped
            grid[key]["horizons"][str(h)] = m
            smapes.append(float(m["smape_pct"]))
            maes.append(float(m["mae"]))
        if smapes:
            smape_by_h: dict[int, float] = {}
            mae_by_h: dict[int, float] = {}
            for h in horizons:
                cell = grid[key]["horizons"].get(str(h), {})
                if isinstance(cell, dict) and "error" not in cell and "smape_pct" in cell:
                    smape_by_h[int(h)] = float(cell["smape_pct"])
                    mae_by_h[int(h)] = float(cell["mae"])
            tier_rank = ranking_scores_from_horizon_metrics(
                list(smape_by_h.keys()),
                smape_by_h,
                mae_by_h,
            )
            row = {
                "ridge_alpha": alpha,
                "mean_smape_pct_horizons_mean": round(float(np.mean(smapes)), 6),
                "mean_mae_horizons_mean": round(float(np.mean(maes)), 6),
                "horizons_evaluated": len(smapes),
            }
            row.update(tier_rank)
            ranking.append(row)

    def _sort_key(r: dict[str, object]) -> tuple[float, float, float, float]:
        ps = r.get("ranking_primary_mean_smape_pct")
        tb = r.get("tier_b_mean_smape_pct")
        pm = r.get("ranking_primary_mean_mae")
        return (
            float(ps if ps is not None else 1e30),
            float(tb if tb is not None else 1e30),
            float(pm if pm is not None else 1e30),
            float(r["ridge_alpha"]),  # type: ignore[arg-type]
        )

    ranking.sort(key=_sort_key)

    print("--- Rank by contract primary key (tier A h=1..6 if present, else all horizons) ---")
    for i, row in enumerate(ranking, start=1):
        ta = row.get("tier_a_mean_smape_pct")
        rk = row.get("ranking_primary_key", "")
        print(
            f"  #{i}  alpha={row['ridge_alpha']}  "
            f"primary_sMAPE={row.get('ranking_primary_mean_smape_pct')}% ({rk})  "
            f"mean_all_h={row['mean_smape_pct_horizons_mean']}%  "
            f"tier_a={ta}%  tier_b={row.get('tier_b_mean_smape_pct')}%  "
            f"n_h={row['horizons_evaluated']}"
        )
    if ranking:
        best = ranking[0]
        print()
        print(
            f"Best alpha: {best['ridge_alpha']}  "
            f"(primary mean sMAPE={best.get('ranking_primary_mean_smape_pct')}%, "
            f"key={best.get('ranking_primary_key')})"
        )

    if args.json_out:
        out_path = Path(args.json_out)
        payload = {
            "model_version": FORECAST_MODEL_VERSION,
            "ridge_alpha_default_online": RIDGE_ALPHA_DEFAULT,
            "evaluation_contract_ref": "plan/evaluation_contract.md v2",
            "tier_a_horizons": [1, 2, 3, 4, 5, 6],
            "tier_b_horizons": [7, 8, 9, 10, 11, 12],
            "ranking_policy": "Sort by ranking_primary_mean_smape_pct (tier A intersection if any), "
            "then tier_b_mean_smape_pct, then primary MAE, then alpha.",
            "iv_csv": str(csv_path.resolve()),
            "site_no": str(args.site_no).strip(),
            "parameter_cd": str(args.parameter_cd).strip(),
            "variant": str(args.variant),
            "series_hours": int(len(s)),
            "time_range_utc": [s.index[0].isoformat(), s.index[-1].isoformat()],
            "cutoff_step": int(args.step),
            "max_cutoffs": int(args.max_cutoffs),
            "history_window_hours": int(args.history_window_hours),
            "horizons": horizons,
            "alphas": alphas,
            "grid": grid,
            "ranking_by_contract_primary_then_tier_b": ranking,
            "ranking_by_mean_smape": ranking,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print()
        print(f"已写入 JSON: {out_path.resolve()}")


if __name__ == "__main__":
    main()

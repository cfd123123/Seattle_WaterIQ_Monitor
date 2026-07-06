#!/usr/bin/env python3
"""
对 forecast_engine 中 Ridge 递归预测做 walk-forward 回测（与线上一致：仅用 cutoff 之前的数据拟合并外推）。

在 cutoff 日历整点 T 上：仅当 T 前 lag 小时与 T+h 小时均有观测时，用 T 及以前完整窗训练并递归预测 h 个**日历小时**，与真实 y(T+h) 比较。
输出 MAE、RMSE、sMAPE、有效样本数等；可选 --step 降采样以加快长序列。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from forecast_engine import (
    FORECAST_MODEL_VERSION,
    MAX_LAG,
    MIN_HOURLY_POINTS,
    RIDGE_ALPHA_DEFAULT,
    load_hourly_series,
    walk_forward_ridge_recursive_calendar,
)


def _metrics(pred: np.ndarray, actual: np.ndarray) -> dict[str, float | int]:
    pred = pred.astype(float)
    actual = actual.astype(float)
    err = pred - actual
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    # sMAPE 避免分母过小
    denom = (np.abs(actual) + np.abs(pred) + 1e-9) / 2.0
    smape = float(np.mean(np.abs(err) / denom) * 100.0)
    # 经典 MAPE（仅在 |actual| 足够大时）
    mask = np.abs(actual) > 1e-6
    mape = float(np.mean(np.abs(err[mask] / actual[mask])) * 100.0) if np.any(mask) else float("nan")
    # 相关系数（至少 2 点）
    corr = float("nan")
    if len(pred) >= 2:
        c = np.corrcoef(pred, actual)[0, 1]
        corr = float(c) if not np.isnan(c) else float("nan")
    # 方向准确率：按连续评估点的一阶变化方向是否一致计算
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
) -> tuple[np.ndarray, np.ndarray, int]:
    """Walk-forward on strict hourly grid (same semantics as ``forecast_engine``)."""
    return walk_forward_ridge_recursive_calendar(
        s, horizon, step=step, ridge_alpha=ridge_alpha, max_lag=MAX_LAG
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Walk-forward backtest for forecast_engine Ridge forecast")
    p.add_argument(
        "--iv-csv",
        default=str(Path(__file__).resolve().parent / "data" / "usgs_puget_iv.csv"),
        help="USGS IV 合并 CSV",
    )
    p.add_argument("--site-no", required=True, help="站点号，如 12117000")
    p.add_argument("--parameter-cd", required=True, help="参数码，如 00060 流量")
    p.add_argument(
        "--horizons",
        default="1,6,12,24,48",
        help="逗号分隔的预测步长（小时）",
    )
    p.add_argument(
        "--step",
        type=int,
        default=1,
        help="cutoff 步进（小时索引），大于 1 可加速长序列",
    )
    p.add_argument("--json-out", default="", help="可选：将结果写入 JSON 文件")
    p.add_argument(
        "--ridge-alpha",
        type=float,
        default=RIDGE_ALPHA_DEFAULT,
        help=f"Ridge L2 强度 alpha（默认与线上一致 {RIDGE_ALPHA_DEFAULT}）",
    )
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

    y = s.values.astype(float)
    horizons = [int(x.strip()) for x in str(args.horizons).split(",") if x.strip()]

    print("=== 短时预测回测（walk-forward）===")
    print(f"model_version: {FORECAST_MODEL_VERSION}")
    print(f"ridge_alpha: {float(args.ridge_alpha)}")
    print(f"iv_csv: {csv_path.resolve()}")
    print(f"site_no: {args.site_no}  parameter_cd: {args.parameter_cd}")
    print(f"series_grid_hours: {len(y)}  range: {s.index[0].isoformat()} .. {s.index[-1].isoformat()}")
    print(f"cutoff_step: {args.step}")
    print()

    all_results: dict[str, object] = {
        "model_version": FORECAST_MODEL_VERSION,
        "ridge_alpha": float(args.ridge_alpha),
        "iv_csv": str(csv_path.resolve()),
        "site_no": args.site_no,
        "parameter_cd": args.parameter_cd,
        "series_grid_hours": len(y),
        "cutoff_step": args.step,
        "horizons": {},
    }

    for h in horizons:
        preds, actuals, skipped = walk_forward_backtest(
            s, h, step=args.step, ridge_alpha=float(args.ridge_alpha)
        )
        if len(preds) == 0:
            print(f"horizon={h}h: 无有效预测（可能历史不足或全部被跳过）。skipped_cutoffs={skipped}")
            all_results["horizons"][str(h)] = {"error": "no_valid_predictions", "skipped_cutoffs": skipped}
            continue
        m = _metrics(preds, actuals)
        m["skipped_cutoffs"] = skipped
        all_results["horizons"][str(h)] = m
        print(f"--- horizon {h} h ---")
        print(f"  samples: {m['n']}  skipped_cutoffs: {skipped}")
        print(
            f"  MAE: {m['mae']}  RMSE: {m['rmse']}  sMAPE: {m['smape_pct']}%  "
            f"MAPE: {m['mape_pct']}%  corr: {m['pred_actual_corr']}  "
            f"dir_acc: {m['directional_accuracy_pct']}%"
        )

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
        print()
        print(f"已写入 JSON: {out_path.resolve()}")


if __name__ == "__main__":
    main()

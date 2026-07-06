#!/usr/bin/env python3
"""
Compare Ridge recursive vs direct multi-horizon walk-forward backtest.

Business target:
- Evaluate predictions for next 1..12 hours after current time.
- Keep splitting protocol identical between methods.
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
    MIN_HOURLY_POINTS,
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


def _parse_horizons(s: str) -> list[int]:
    s = str(s).strip()
    if s == "1-12":
        return list(range(1, 13))
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare Ridge recursive vs direct walk-forward backtest")
    p.add_argument(
        "--iv-csv",
        default=str(Path(__file__).resolve().parent.parent / "data" / "usgs_puget_iv.csv"),
    )
    p.add_argument("--site-no", required=True)
    p.add_argument("--parameter-cd", required=True)
    p.add_argument("--horizons", default="1-12")
    p.add_argument("--step", type=int, default=24)
    p.add_argument("--ridge-alpha", type=float, default=50.0)
    p.add_argument("--json-out", default="")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.iv_csv)
    if not csv_path.is_file():
        print(f"错误：找不到 IV CSV：{csv_path}", file=sys.stderr)
        raise SystemExit(1)
    s = load_hourly_series(csv_path, args.site_no, args.parameter_cd, dense=False)
    if s.empty:
        print(f"错误：站点 {args.site_no} / 参数 {args.parameter_cd} 无可用小时序列。", file=sys.stderr)
        raise SystemExit(1)
    horizons = _parse_horizons(args.horizons)

    report: dict[str, object] = {
        "model_version": FORECAST_MODEL_VERSION,
        "site_no": args.site_no,
        "parameter_cd": args.parameter_cd,
        "iv_csv": str(csv_path.resolve()),
        "series_grid_hours": int(len(s)),
        "time_range_utc": [s.index[0].isoformat(), s.index[-1].isoformat()],
        "cutoff_step": int(args.step),
        "ridge_alpha": float(args.ridge_alpha),
        "horizons": {},
    }
    rec_smapes: list[float] = []
    dir_smapes: list[float] = []

    print("=== Direct vs Recursive（walk-forward）===")
    print(f"site={args.site_no} param={args.parameter_cd} step={args.step} alpha={args.ridge_alpha}")
    for h in horizons:
        pr, ar, sr = walk_forward_ridge_recursive_calendar(
            s, h, step=args.step, ridge_alpha=float(args.ridge_alpha)
        )
        pd, ad, sd = walk_forward_ridge_direct_calendar(
            s, h, step=args.step, ridge_alpha=float(args.ridge_alpha)
        )
        block: dict[str, object] = {"horizon_hours": int(h)}
        if len(pr) > 0:
            mr = _metrics(pr, ar)
            mr["skipped_cutoffs"] = sr
            block["recursive"] = mr
            rec_smapes.append(float(mr["smape_pct"]))
        else:
            block["recursive"] = {"error": "no_valid_predictions", "skipped_cutoffs": sr}
        if len(pd) > 0:
            md = _metrics(pd, ad)
            md["skipped_cutoffs"] = sd
            block["direct"] = md
            dir_smapes.append(float(md["smape_pct"]))
        else:
            block["direct"] = {"error": "no_valid_predictions", "skipped_cutoffs": sd}

        if len(pr) > 0 and len(pd) > 0:
            delta = round(float(block["direct"]["smape_pct"]) - float(block["recursive"]["smape_pct"]), 4)  # type: ignore[index]
            print(
                f"h={h:>2}: rec_sMAPE={block['recursive']['smape_pct']}%  dir_sMAPE={block['direct']['smape_pct']}%  "
                f"delta(dir-rec)={delta}%"
            )
        report["horizons"][str(h)] = block

    summary = {
        "recursive_mean_smape_pct": round(float(np.mean(rec_smapes)), 6) if rec_smapes else float("nan"),
        "direct_mean_smape_pct": round(float(np.mean(dir_smapes)), 6) if dir_smapes else float("nan"),
    }
    if rec_smapes and dir_smapes:
        summary["delta_mean_smape_pct_direct_minus_recursive"] = round(
            float(summary["direct_mean_smape_pct"]) - float(summary["recursive_mean_smape_pct"]), 6
        )
    report["summary"] = summary
    print()
    print(f"mean sMAPE: recursive={summary['recursive_mean_smape_pct']}%  direct={summary['direct_mean_smape_pct']}%")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"已写入 JSON: {out.resolve()}")


if __name__ == "__main__":
    main()

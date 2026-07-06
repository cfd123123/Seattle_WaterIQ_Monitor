#!/usr/bin/env python3
"""
Walk-forward baselines for discharge (00060) or turbidity (63680), univariate.

- Persistence: at cutoff T, prediction for horizon h is y(T).
- Seasonal (24h calendar): y_hat(T+h) = y(T+h-24) when that index is valid.

Same cutoff index loop as backtest_model_suite_00060.py (aligned skips).

See plan/evaluation_contract.md (v2) for tier A (h=1..6) vs tier B (h=7..12).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "models"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from evaluation_tiers import tier_means_from_per_horizon_list

from forecast_engine import MAX_LAG, MIN_HOURLY_POINTS, _effective_lag, load_hourly_series


def _parse_horizons(s: str) -> list[int]:
    s = str(s).strip()
    if s == "1-12":
        return list(range(1, 13))
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _load_sites_from_config(config_path: Path, excluded_sites: set[str]) -> list[str]:
    raw = config_path.read_text(encoding="utf-8")
    clean = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("//"))
    clean = re.sub(r",\s*([\]}])", r"\1", clean)
    payload = json.loads(clean)
    rows = payload.get("sites", [])
    sites: list[str] = []
    for row in rows:
        site = str(row.get("site_no", "")).strip()
        if site and site not in excluded_sites:
            sites.append(site)
    return sites


def _metrics(pred: np.ndarray, actual: np.ndarray) -> dict[str, float | int]:
    pred = pred.astype(float)
    actual = actual.astype(float)
    err = pred - actual
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    denom = (np.abs(actual) + np.abs(pred) + 1e-9) / 2.0
    smape = float(np.mean(np.abs(err) / denom) * 100.0)
    return {"n": int(len(pred)), "mae": round(mae, 6), "rmse": round(rmse, 6), "smape_pct": round(smape, 6)}


def _walk_forward_naive_persistence(
    s: pd.Series,
    horizon: int,
    *,
    step: int,
    max_cutoffs: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Pred at T+h is y(T); same idx_T range as backtest _walk_forward (no sub slice)."""
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
        if pd.isna(s.iloc[idx_T]):
            skipped += 1
            continue
        preds.append(float(s.iloc[idx_T]))
        actuals.append(float(s.iloc[idx_T + h]))
    return np.asarray(preds, dtype=float), np.asarray(actuals, dtype=float), skipped


def _walk_forward_seasonal_lag24(
    s: pd.Series,
    horizon: int,
    *,
    step: int,
    max_cutoffs: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Pred at T+h is y(T+h-24); requires index T+h-24 >= 0 and non-NaN."""
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
        j_season = idx_T + h - 24
        if j_season < 0:
            skipped += 1
            continue
        if pd.isna(s.iloc[idx_T + h]):
            skipped += 1
            continue
        if pd.isna(s.iloc[j_season]):
            skipped += 1
            continue
        preds.append(float(s.iloc[j_season]))
        actuals.append(float(s.iloc[idx_T + h]))
    return np.asarray(preds, dtype=float), np.asarray(actuals, dtype=float), skipped


def _mean_metrics_across_horizons(
    s: pd.Series,
    horizons: list[int],
    *,
    step: int,
    max_cutoffs: int,
) -> tuple[float, float, int, list[dict[str, Any]]]:
    smapes: list[float] = []
    maes: list[float] = []
    per_h: list[dict[str, Any]] = []
    ok_h = 0
    for h in horizons:
        pred, actual, skipped = _walk_forward_naive_persistence(s, h, step=step, max_cutoffs=max_cutoffs)
        if len(pred) == 0:
            per_h.append({"h": h, "error": "no_valid_predictions", "skipped_cutoffs": skipped})
            continue
        m = _metrics(pred, actual)
        m["skipped_cutoffs"] = skipped
        per_h.append({"h": h, **m})
        smapes.append(float(m["smape_pct"]))
        maes.append(float(m["mae"]))
        ok_h += 1
    if not smapes:
        return math.inf, math.inf, 0, per_h
    return float(np.mean(smapes)), float(np.mean(maes)), ok_h, per_h


def _mean_metrics_across_horizons_seasonal(
    s: pd.Series,
    horizons: list[int],
    *,
    step: int,
    max_cutoffs: int,
) -> tuple[float, float, int, list[dict[str, Any]]]:
    smapes: list[float] = []
    maes: list[float] = []
    per_h: list[dict[str, Any]] = []
    ok_h = 0
    for h in horizons:
        pred, actual, skipped = _walk_forward_seasonal_lag24(s, h, step=step, max_cutoffs=max_cutoffs)
        if len(pred) == 0:
            per_h.append({"h": h, "error": "no_valid_predictions", "skipped_cutoffs": skipped})
            continue
        m = _metrics(pred, actual)
        m["skipped_cutoffs"] = skipped
        per_h.append({"h": h, **m})
        smapes.append(float(m["smape_pct"]))
        maes.append(float(m["mae"]))
        ok_h += 1
    if not smapes:
        return math.inf, math.inf, 0, per_h
    return float(np.mean(smapes)), float(np.mean(maes)), ok_h, per_h


def _load_ridge_from_summary_csv(csv_path: Path, site_no: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    if not csv_path.is_file():
        return out
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("site_no") != site_no or row.get("parameter_cd") != "00060":
                continue
            mn = str(row.get("model_name", ""))
            if mn not in ("ridge_recursive", "ridge_direct"):
                continue
            out[mn] = {
                "mean_smape_pct": float(row["mean_smape_pct"]),
                "mean_mae": float(row["mean_mae"]),
                "total_eval_points": float(row["total_eval_points"]),
            }
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Walk-forward baselines (persistence + seasonal lag-24) vs optional Ridge CSV; "
        "supports 00060 / 63680 via --parameter-cd."
    )
    p.add_argument("--iv-csv", default=str(_ROOT / "data" / "usgs_puget_iv.csv"))
    p.add_argument("--sites-config", default=str(_ROOT / "config" / "usgs_puget_default_sites.json"))
    p.add_argument(
        "--exclude-sites",
        default="",
        help="Comma-separated site_no to skip when loading from sites-config (default: none).",
    )
    p.add_argument("--parameter-cd", default="00060")
    p.add_argument("--horizons", default="1-12")
    p.add_argument("--step", type=int, default=1)
    p.add_argument("--max-cutoffs", type=int, default=720)
    p.add_argument(
        "--site-no",
        default="",
        help="Comma-separated site numbers to evaluate only (default: all sites from config).",
    )
    p.add_argument(
        "--ridge-summary-csv",
        default=str(_ROOT / "reports" / "model_suite_00060_h1_12_step1" / "summary_by_site_model.csv"),
        help="Optional: compare to Ridge rows from this suite summary CSV.",
    )
    p.add_argument("--json-out", default="", help="If set, write full per-site payload to this path.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = Path(args.iv_csv)
    config_path = Path(args.sites_config)
    ridge_csv = Path(args.ridge_summary_csv)
    if not csv_path.is_file():
        print(f"Missing IV CSV: {csv_path}", file=sys.stderr)
        return 2
    if not config_path.is_file():
        print(f"Missing sites config: {config_path}", file=sys.stderr)
        return 2

    excluded = {x.strip() for x in str(args.exclude_sites).split(",") if x.strip()}
    horizons = _parse_horizons(args.horizons)
    sites = _load_sites_from_config(config_path, excluded)
    only = {x.strip() for x in str(args.site_no).split(",") if x.strip()}
    if only:
        sites = [s for s in sites if s in only]
        missing = sorted(only - set(sites))
        if missing:
            print(f"Warning: requested sites not in config (after exclude): {missing}", file=sys.stderr)

    print("=== Baselines: persistence + seasonal lag-24 (evaluation_contract v2 tiers in JSON) ===")
    print(f"iv_csv={csv_path.resolve()}")
    print(f"parameter_cd={args.parameter_cd}")
    print(f"horizons={horizons} step={args.step} max_cutoffs={args.max_cutoffs}")
    print(f"ridge comparison csv={ridge_csv.resolve()} exists={ridge_csv.is_file()}")
    print()

    report: dict[str, Any] = {
        "sites": {},
        "evaluation_contract_ref": "plan/evaluation_contract.md v2",
        "notes": "Lower sMAPE is better. tier_a = h=1..6, tier_b = h=7..12 (means over horizons that ran). "
        "For ridge_from_csv deltas: (baseline - ridge) sMAPE in percentage points; positive => Ridge lower sMAPE.",
    }

    for site_no in sites:
        s = load_hourly_series(csv_path, site_no, args.parameter_cd, dense=False)
        if s.empty:
            continue
        mean_smape, mean_mae, ok_h, per_h = _mean_metrics_across_horizons(
            s,
            horizons,
            step=int(args.step),
            max_cutoffs=int(args.max_cutoffs),
        )
        mean_smape_s, mean_mae_s, ok_h_s, per_h_s = _mean_metrics_across_horizons_seasonal(
            s,
            horizons,
            step=int(args.step),
            max_cutoffs=int(args.max_cutoffs),
        )
        tier_p = tier_means_from_per_horizon_list(per_h)
        tier_s = tier_means_from_per_horizon_list(per_h_s)
        ridge_rows = _load_ridge_from_summary_csv(ridge_csv, site_no)
        block: dict[str, Any] = {
            "parameter_cd": str(args.parameter_cd).strip(),
            "persistence": {
                "mean_smape_pct_over_horizons": round(mean_smape, 6) if math.isfinite(mean_smape) else None,
                "mean_mae_over_horizons": round(mean_mae, 6) if math.isfinite(mean_mae) else None,
                "horizons_evaluated": ok_h,
                "per_horizon": per_h,
                "tier_summary": tier_p,
            },
            "seasonal_lag24": {
                "mean_smape_pct_over_horizons": round(mean_smape_s, 6) if math.isfinite(mean_smape_s) else None,
                "mean_mae_over_horizons": round(mean_mae_s, 6) if math.isfinite(mean_smape_s) else None,
                "horizons_evaluated": ok_h_s,
                "per_horizon": per_h_s,
                "tier_summary": tier_s,
            },
            "ridge_from_csv": ridge_rows,
            # Backward-compatible aliases (persistence only)
            "mean_smape_pct_naive": round(mean_smape, 6) if math.isfinite(mean_smape) else None,
            "mean_mae_naive": round(mean_mae, 6) if math.isfinite(mean_mae) else None,
            "horizons_evaluated": ok_h,
            "per_horizon": per_h,
        }
        if ridge_rows:
            rr = ridge_rows.get("ridge_recursive", {}).get("mean_smape_pct")
            rd = ridge_rows.get("ridge_direct", {}).get("mean_smape_pct")
            if rr is not None and math.isfinite(mean_smape):
                block["delta_smape_persistence_vs_ridge_recursive_pct"] = round(mean_smape - float(rr), 6)
            if rd is not None and math.isfinite(mean_smape):
                block["delta_smape_persistence_vs_ridge_direct_pct"] = round(mean_smape - float(rd), 6)
            if rr is not None and math.isfinite(mean_smape_s):
                block["delta_smape_seasonal_vs_ridge_recursive_pct"] = round(mean_smape_s - float(rr), 6)
            if rd is not None and math.isfinite(mean_smape_s):
                block["delta_smape_seasonal_vs_ridge_direct_pct"] = round(mean_smape_s - float(rd), 6)
            # Legacy keys (persistence vs Ridge), same as delta_smape_persistence_vs_ridge_*
            if block.get("delta_smape_persistence_vs_ridge_recursive_pct") is not None:
                block["delta_smape_vs_ridge_recursive_pct"] = block["delta_smape_persistence_vs_ridge_recursive_pct"]
            if block.get("delta_smape_persistence_vs_ridge_direct_pct") is not None:
                block["delta_smape_vs_ridge_direct_pct"] = block["delta_smape_persistence_vs_ridge_direct_pct"]
        report["sites"][site_no] = block

        print(f"site={site_no}")
        print(
            f"  persistence mean sMAPE: {mean_smape:.6f}%  MAE: {mean_mae:.6f}  (horizons_ok={ok_h})"
        )
        print(
            f"  seasonal lag-24 mean sMAPE: {mean_smape_s:.6f}%  MAE: {mean_mae_s:.6f}  (horizons_ok={ok_h_s})"
        )
        if tier_p.get("tier_a_mean_smape_pct") is not None:
            print(
                f"  tier A (1-6) persistence mean sMAPE: {tier_p['tier_a_mean_smape_pct']}%  "
                f"(n_h={tier_p.get('tier_a_horizons_ok')})"
            )
        if tier_p.get("tier_b_mean_smape_pct") is not None:
            print(
                f"  tier B (7-12) persistence mean sMAPE: {tier_p['tier_b_mean_smape_pct']}%  "
                f"(n_h={tier_p.get('tier_b_horizons_ok')})"
            )
        if ridge_rows:
            for name in ("ridge_recursive", "ridge_direct"):
                if name in ridge_rows:
                    r = ridge_rows[name]
                    print(
                        f"  {name}: mean sMAPE={r['mean_smape_pct']:.6f}%  "
                        f"mean_MAE={r['mean_mae']:.6f}  n_total={int(r['total_eval_points'])}"
                    )
            if block.get("delta_smape_persistence_vs_ridge_recursive_pct") is not None:
                d = block["delta_smape_persistence_vs_ridge_recursive_pct"]
                print(f"  delta (persistence - ridge_recursive) sMAPE: {d:+.6f} pp  (>0 => Ridge better)")
            if block.get("delta_smape_persistence_vs_ridge_direct_pct") is not None:
                d = block["delta_smape_persistence_vs_ridge_direct_pct"]
                print(f"  delta (persistence - ridge_direct) sMAPE: {d:+.6f} pp  (>0 => Ridge better)")
        print()

    if str(args.json_out).strip():
        outp = Path(args.json_out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {outp.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

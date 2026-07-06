#!/usr/bin/env python3
"""
Exploratory data analysis (EDA) for USGS IV wide-table CSV (e.g. data/usgs_puget_iv.csv).

Sections (each prints a block to stdout; optional PNG figures under --out-dir):
1) Table shape, column list, time span (raw rows).
2) Missingness per numeric/USGS parameter column (raw).
3) Per (site_no, parameter_cd): hourly series via the same resampling as forecast_engine.
4) Hourly series length, implied sampling coverage, simple drift via first vs second half mean.
5) Outlier-like spikes (IQR rule on hourly values).
6) Weak seasonality hints: mean by hour-of-day and by day-of-week.
7) Optional stationarity: Augmented Dickey-Fuller (needs statsmodels).

This is offline analysis only; it does not change production behavior.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from models.forecast_engine import load_hourly_series

DEFAULT_PARAMS = ("00060", "63680", "00010")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EDA for USGS IV CSV (wide table).")
    p.add_argument(
        "--iv-csv",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "usgs_puget_iv.csv",
        help="Path to merged IV CSV.",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="If set, write JSON summary and optional PNG plots here.",
    )
    p.add_argument(
        "--parameters",
        type=str,
        default=",".join(DEFAULT_PARAMS),
        help="Comma-separated parameter_cd list to analyze (must exist as columns after fetch).",
    )
    p.add_argument(
        "--max-sites",
        type=int,
        default=0,
        help="If >0, only analyze first N distinct site_no values (stable order).",
    )
    p.add_argument(
        "--site-nos",
        type=str,
        default="",
        help="Comma-separated site_no to analyze only (default: all sites in CSV, subject to --max-sites).",
    )
    p.add_argument(
        "--skip-plots",
        action="store_true",
        help="Do not write PNG figures (still prints tables).",
    )
    p.add_argument(
        "--skip-adf",
        action="store_true",
        help="Skip Augmented Dickey-Fuller test (avoids statsmodels dependency).",
    )
    return p.parse_args()


def _print_title(title: str) -> None:
    bar = "=" * len(title)
    print(f"\n{bar}\n{title}\n{bar}")


def _iqr_outlier_fraction(values: np.ndarray) -> float:
    x = values[np.isfinite(values)]
    if x.size < 20:
        return float("nan")
    q1, q3 = np.percentile(x, [25, 75])
    iqr = q3 - q1
    if iqr <= 0:
        return 0.0
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return float(np.mean((x < lo) | (x > hi)))


def _adf_pvalue(series: pd.Series) -> float | None:
    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        return None
    y = series.astype(float).values
    y = y[np.isfinite(y)]
    if y.size < 30:
        return None
    # adfuller returns (adf_stat, pvalue, usedlag, nobs, critical_values, icbest)
    return float(adfuller(y, autolag="AIC")[1])


def _maybe_plot_series(
    s: pd.Series,
    site: str,
    param: str,
    out_dir: Path,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib not installed; skip plot)")
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(s.index, s.values, linewidth=0.8)
    ax.set_title(f"{site}  {param}  (hourly mean, UTC)")
    ax.set_xlabel("time")
    ax.set_ylabel(param)
    fig.tight_layout()
    safe = f"{site}_{param}.png".replace("/", "-")
    fig.savefig(out_dir / safe, dpi=120)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    csv_path: Path = args.iv_csv
    if not csv_path.is_file():
        print(f"CSV not found: {csv_path}")
        print("Fetch first: python fetch_usgs_puget_sound.py --days 30")
        return 2

    params = [x.strip() for x in args.parameters.split(",") if x.strip()]
    df = pd.read_csv(csv_path)
    _print_title("1) Raw table overview")
    print(f"rows={len(df):,}  cols={len(df.columns)}")
    if "datetime" in df.columns:
        dt = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
        print(f"datetime range (UTC): {dt.min()}  ->  {dt.max()}")
    if "site_no" in df.columns:
        ns = df["site_no"].astype(str).nunique()
        print(f"distinct site_no: {ns}")
    print("columns:", ", ".join(df.columns.astype(str).tolist()))

    _print_title("2) Raw missingness (parameter columns)")
    miss_rows: dict[str, Any] = {}
    for c in params:
        if c not in df.columns:
            print(f"  {c}: COLUMN ABSENT")
            miss_rows[c] = {"present": False}
            continue
        s = df[c]
        nn = int(s.notna().sum())
        frac = float(nn / len(df)) if len(df) else 0.0
        print(f"  {c}: non-null {nn:,} / {len(df):,}  ({frac:.2%})")
        miss_rows[c] = {"present": True, "non_null_frac": round(frac, 4)}

    sites: list[str] = []
    if "site_no" in df.columns:
        sites = sorted(df["site_no"].astype(str).str.strip().unique().tolist())
        only = {x.strip() for x in str(args.site_nos).split(",") if x.strip()}
        if only:
            sites = [s for s in sites if s in only]
            missing = sorted(only - set(sites))
            if missing:
                print(f"Warning: site_nos not in CSV: {missing}", flush=True)
        if args.max_sites > 0:
            sites = sites[: args.max_sites]

    per_series: list[dict[str, Any]] = []
    out_dir = args.out_dir
    if out_dir:
        out_dir = Path(out_dir)

    _print_title("3–6) Hourly series (production-aligned resampling)")
    for site in sites:
        for param in params:
            if param not in df.columns:
                continue
            s = load_hourly_series(csv_path, site, param, dense=True)
            row: dict[str, Any] = {
                "site_no": site,
                "parameter_cd": param,
                "hourly_points": int(len(s)),
            }
            if s.empty:
                print(f"  {site}  {param}: EMPTY after hourly resample")
                row["empty"] = True
                per_series.append(row)
                continue
            row["empty"] = False
            v = s.values.astype(float)
            row["value_mean"] = round(float(np.nanmean(v)), 4)
            row["value_std"] = round(float(np.nanstd(v)), 4)
            # Drift: compare half-window means
            mid = len(s) // 2
            if mid > 5:
                m1 = float(np.nanmean(v[:mid]))
                m2 = float(np.nanmean(v[mid:]))
                row["half1_mean"] = round(m1, 4)
                row["half2_mean"] = round(m2, 4)
                denom = abs(m1) if abs(m1) > 1e-6 else 1.0
                row["rel_mean_shift_halfs"] = round((m2 - m1) / denom, 4)
            row["iqr_outlier_frac"] = (
                round(_iqr_outlier_fraction(v), 4) if np.isfinite(_iqr_outlier_fraction(v)) else None
            )
            # Hour-of-day pattern
            hod = s.groupby(s.index.hour).mean()
            hod_max_h = int(hod.idxmax()) if len(hod) else None
            hod_min_h = int(hod.idxmin()) if len(hod) else None
            row["hod_max_hour_utc"] = hod_max_h
            row["hod_min_hour_utc"] = hod_min_h
            # Day-of-week (Mon=0)
            dow = s.groupby(s.index.dayofweek).mean()
            dow_max_d = int(dow.idxmax()) if len(dow) else None
            row["dow_max_utc_mon0"] = dow_max_d

            adf_p: float | None = None
            if not args.skip_adf:
                adf_p = _adf_pvalue(s)
            row["adf_pvalue"] = adf_p

            per_series.append(row)

            print(
                f"  {site}  {param}: n={len(s)}  mean={row['value_mean']}  "
                f"std={row['value_std']}  iqr_outlier_frac={row['iqr_outlier_frac']}  "
                f"ADF_p={adf_p if adf_p is not None else 'n/a'}"
            )
            if out_dir and not args.skip_plots:
                _maybe_plot_series(s, site, param, out_dir)

    _print_title("How to read (short)")
    print(
        "- non-null frac: share of raw rows with a value; low => sparse column or site mismatch.\n"
        "- hourly n: points after 1h mean resample (same as forecast_engine); if n < MIN_HOURLY_POINTS, forecast may stay off.\n"
        "- iqr_outlier_frac: fraction of hourly points outside 1.5*IQR; high => spikes/messy sensor or events.\n"
        "- half1_mean vs half2_mean: crude drift; large relative shift => non-stationary locally.\n"
        "- hod_* / dow_*: weak seasonality hints (UTC clock).\n"
        "- ADF p-value: H0 usually unit root (non-stationary). LOW p => reject H0 => more stationary; interpret with plots.\n"
        "  If statsmodels missing, ADF shows n/a."
    )

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "iv_csv": str(csv_path.resolve()),
            "raw_missing": miss_rows,
            "hourly_per_series": per_series,
        }
        rep_path = out_dir / "eda_usgs_iv_summary.json"
        rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote JSON: {rep_path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

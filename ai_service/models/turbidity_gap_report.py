"""
Turbidity (63680) data-gap diagnostics on the features hourly grid.

Uses the same holdout split as ``turbidity_state_monitoring`` for tuning / holdout segments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest_turbidity_exog_ridge_lgbm import UPSTREAM_DISCHARGE_COL, _split_index_for_holdout
from .turbidity_state_monitoring import (
    CALIBRATION_MIN_MONTH_VALID_RATE,
    DEFAULT_FEATURES_CSV,
    DEFAULT_SITE_NO,
    WARNING_HORIZONS,
    _tuning_validity_counts,
    build_calibration_mask,
    load_features,
)

FLOOD_WINDOW_START = pd.Timestamp("2025-12-09", tz="UTC")
FLOOD_WINDOW_END = pd.Timestamp("2025-12-17 23:00:00", tz="UTC")
DEFAULT_OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "reports"
    / "turbidity_state"
    / "12117500_v2"
)


def _max_consecutive_runs(finite_mask: np.ndarray) -> tuple[int, int]:
    """Return (max consecutive True runs, max consecutive False runs) on a 1d bool array."""
    max_true = 0
    max_false = 0
    cur_true = 0
    cur_false = 0
    for v in finite_mask:
        if v:
            cur_true += 1
            cur_false = 0
            max_true = max(max_true, cur_true)
        else:
            cur_false += 1
            cur_true = 0
            max_false = max(max_false, cur_false)
    return int(max_true), int(max_false)


def _segment_summary(
    mask: pd.Series,
    y: pd.Series,
    prec: pd.Series | None,
    q_up: pd.Series | None,
) -> dict[str, Any]:
    counts = _tuning_validity_counts(mask, y, prec, q_up)
    grid_n = int(mask.sum())
    y_seg = y[mask].astype(float)
    finite = np.isfinite(y_seg.to_numpy(dtype=float, copy=False))
    max_valid, max_missing = _max_consecutive_runs(finite)
    out: dict[str, Any] = {
        "grid_hours": grid_n,
        **counts,
        "y_valid_rate": round(counts["y_valid_n"] / grid_n, 6) if grid_n else None,
        "max_consecutive_valid_hours": max_valid,
        "max_consecutive_missing_hours": max_missing,
    }
    if grid_n:
        out["segment_start_utc"] = str(y.index[mask][0])
        out["segment_end_utc"] = str(y.index[mask][-1])
    return out


def monthly_validity_table(y: pd.Series) -> pd.DataFrame:
    """One row per calendar month on the hourly index."""
    y_num = pd.to_numeric(y, errors="coerce")
    df = pd.DataFrame({"y": y_num}, index=y.index)
    df["year_month"] = df.index.strftime("%Y-%m")
    rows: list[dict[str, Any]] = []
    for ym, grp in df.groupby("year_month", sort=True):
        grid_n = len(grp)
        valid_n = int(np.isfinite(grp["y"]).sum())
        missing_n = grid_n - valid_n
        rows.append(
            {
                "year_month": ym,
                "grid_hours": grid_n,
                "y_valid_n": valid_n,
                "y_valid_rate": round(valid_n / grid_n, 6) if grid_n else None,
                "y_missing_rate": round(missing_n / grid_n, 6) if grid_n else None,
            }
        )
    return pd.DataFrame(rows)


def flood_window_summary(
    y: pd.Series,
    *,
    start: pd.Timestamp = FLOOD_WINDOW_START,
    end: pd.Timestamp = FLOOD_WINDOW_END,
) -> dict[str, Any]:
    start = start.tz_convert("UTC") if start.tzinfo else start.tz_localize("UTC")
    end = end.tz_convert("UTC") if end.tzinfo else end.tz_localize("UTC")
    win = y.loc[(y.index >= start) & (y.index <= end)]
    grid_n = len(win)
    valid = win[np.isfinite(win.astype(float))]
    valid_n = len(valid)
    missing_n = grid_n - valid_n
    note_parts: list[str] = []
    if grid_n == 0:
        note_parts.append("no grid hours in flood window on features index")
    elif missing_n == grid_n:
        note_parts.append("all turbidity missing in flood window")
    elif missing_n > 0:
        note_parts.append(f"{missing_n} of {grid_n} hours missing 63680")
    else:
        note_parts.append("complete 63680 coverage in flood window")
    out: dict[str, Any] = {
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "grid_hours": grid_n,
        "y_valid_n": valid_n,
        "y_valid_rate": round(valid_n / grid_n, 6) if grid_n else None,
        "y_missing_n": missing_n,
        "y_missing_rate": round(missing_n / grid_n, 6) if grid_n else None,
        "y_max_if_valid": round(float(valid.max()), 6) if valid_n else None,
        "note": "; ".join(note_parts),
    }
    return out


def worst_months(monthly: pd.DataFrame, *, n: int = 5) -> list[dict[str, Any]]:
    if monthly.empty:
        return []
    ranked = monthly.sort_values("y_valid_rate", ascending=True).head(n)
    return ranked.to_dict(orient="records")


def maybe_plot_monthly(monthly: pd.DataFrame, out_png: Path) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    if monthly.empty:
        return False

    fig, ax = plt.subplots(figsize=(12, 4))
    x = np.arange(len(monthly))
    rates = monthly["y_valid_rate"].to_numpy(dtype=float) * 100.0
    ax.bar(x, rates, color="#2a6f97", width=0.85)
    ax.set_ylabel("Valid 63680 (%)")
    ax.set_xlabel("Month")
    ax.set_ylim(0, 100)
    ax.set_title("Monthly turbidity (63680) valid rate — site 12117500")
    step = max(1, len(monthly) // 12)
    ax.set_xticks(x[::step])
    ax.set_xticklabels(monthly["year_month"].iloc[::step], rotation=45, ha="right")
    ax.axhline(50, color="#e76f51", linestyle="--", linewidth=0.8, alpha=0.7)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=120)
    plt.close(fig)
    return True


def run_gap_report(
    features_csv: Path,
    *,
    site_no: str = DEFAULT_SITE_NO,
    holdout_fraction: float = 0.2,
    holdout_min_hours: int = 336,
    min_tuning_hours: int = 2000,
    out_dir: Path | None = None,
    write_plot: bool = True,
    include_holdout: bool = True,
) -> dict[str, Any]:
    csv_path = Path(features_csv)
    if not csv_path.is_file():
        raise FileNotFoundError(f"features CSV not found: {csv_path}")

    df = load_features(csv_path)
    y = df["63680"]
    prec = df["precipitation_mm"] if "precipitation_mm" in df.columns else None
    q_up = df[UPSTREAM_DISCHARGE_COL] if UPSTREAM_DISCHARGE_COL in df.columns else None

    n = len(y)
    split_info = _split_index_for_holdout(
        n,
        max_horizon=max(WARNING_HORIZONS),
        holdout_fraction=float(holdout_fraction),
        holdout_min_hours=int(holdout_min_hours),
        min_tuning_hours=int(min_tuning_hours),
    )
    split_ix = int(split_info["split_index"])
    tuning_mask = pd.Series(y.index < y.index[split_ix], index=y.index)
    holdout_mask = ~tuning_mask
    full_mask = pd.Series(True, index=y.index)

    monthly = monthly_validity_table(y)
    _, calibration_meta = build_calibration_mask(tuning_mask, y)
    report: dict[str, Any] = {
        "site_no": site_no,
        "features_csv": str(csv_path.resolve()),
        "series_hours": n,
        "time_range_utc": [str(y.index[0]), str(y.index[-1])],
        "holdout_split": split_info,
        "split_index": split_ix,
        "split_time_utc": str(y.index[split_ix]),
        "calibration_min_month_valid_rate": CALIBRATION_MIN_MONTH_VALID_RATE,
        "calibration_months_excluded_tuning": calibration_meta["calibration_months_excluded"],
        "calibration_months_included_tuning_n": calibration_meta["calibration_months_included_n"],
        "segments": {
            "tuning": _segment_summary(tuning_mask, y, prec, q_up),
            "full": _segment_summary(full_mask, y, prec, q_up),
        },
        "flood_window_dec_2025": flood_window_summary(y),
        "monthly_worst_by_valid_rate": worst_months(monthly),
    }
    if include_holdout:
        report["segments"]["holdout"] = _segment_summary(holdout_mask, y, prec, q_up)

    out_path = Path(out_dir) if out_dir is not None else DEFAULT_OUT_DIR
    out_path.mkdir(parents=True, exist_ok=True)
    monthly_csv = out_path / "gap_report_monthly.csv"
    monthly.to_csv(monthly_csv, index=False)
    report["outputs"] = {
        "gap_report_json": str((out_path / "gap_report.json").resolve()),
        "gap_report_monthly_csv": str(monthly_csv.resolve()),
    }

    plot_written = False
    if write_plot:
        plot_written = maybe_plot_monthly(monthly, out_path / "gap_report_monthly.png")
    report["plot_written"] = plot_written
    if plot_written:
        report["outputs"]["gap_report_monthly_png"] = str((out_path / "gap_report_monthly.png").resolve())

    (out_path / "gap_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report

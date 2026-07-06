"""
Holdout evaluation for turbidity alert tiers (v2) using frozen thresholds.

Loads artifacts from a state-monitoring report directory, reuses the same holdout
split as ``turbidity_state_monitoring``, and writes ``holdout_eval.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest_turbidity_exog_ridge_lgbm import _split_index_for_holdout
from .turbidity_gap_report import FLOOD_WINDOW_END, FLOOD_WINDOW_START
from .turbidity_state_monitoring import (
    ALERT_TIERS,
    ALL_ALERT_TIERS,
    GAP_TIERS,
    WARNING_HORIZONS,
    holdout_tier_fractions,
    is_gap_tier,
    label_alert_tier,
    load_features,
)

DEFAULT_REPORT_DIR = (
    Path(__file__).resolve().parent.parent
    / "reports"
    / "turbidity_state"
    / "12117500_v2"
)
RULE_WARNING_COLUMN_PATTERNS = (
    "rule_warning_{h}h",
    "warning_{h}h",
    "rule_warning_{h}",
)


def _tier_counts_and_rates(tiers: pd.Series) -> dict[str, Any]:
    n = int(len(tiers))
    counts = {t: int((tiers == t).sum()) for t in ALL_ALERT_TIERS}
    rates = {t: round(counts[t] / n, 6) if n else None for t in ALL_ALERT_TIERS}
    gap_n = int(tiers.map(is_gap_tier).sum())
    valid_mask = ~tiers.map(is_gap_tier)
    n_valid = int(valid_mask.sum())
    quality_counts = {t: int((tiers[valid_mask] == t).sum()) for t in ALERT_TIERS}
    quality_rates = {
        t: round(quality_counts[t] / n_valid, 6) if n_valid else None for t in ALERT_TIERS
    }
    return {
        "n_hours": n,
        "tier_counts": counts,
        "tier_rates": rates,
        "n_gap_hours": gap_n,
        "gap_tier_counts": {t: counts[t] for t in GAP_TIERS},
        "quality_tier_counts": quality_counts,
        "quality_tier_rates": quality_rates,
    }


def _load_thresholds(report_dir: Path) -> dict[str, Any]:
    path = report_dir / "state_thresholds.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing state_thresholds.json in {report_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_features_csv(report_dir: Path, thresholds: dict[str, Any], features_csv: Path | None) -> Path:
    if features_csv is not None:
        p = Path(features_csv)
        if not p.is_file():
            raise FileNotFoundError(f"features CSV not found: {p}")
        return p
    if thresholds.get("features_csv"):
        p = Path(str(thresholds["features_csv"]))
        if p.is_file():
            return p
    raise FileNotFoundError(
        "features CSV not specified and not found via state_thresholds.json features_csv"
    )


def _holdout_mask_from_split(y: pd.Series, thresholds: dict[str, Any], split_info: dict[str, Any]) -> pd.Series:
    if "split_index" in thresholds:
        split_ix = int(thresholds["split_index"])
    else:
        split_ix = int(split_info["split_index"])
    return pd.Series(y.index >= y.index[split_ix], index=y.index)


def _load_hourly_states(report_dir: Path) -> pd.DataFrame | None:
    path = report_dir / "hourly_states.csv"
    if not path.is_file():
        return None
    hourly = pd.read_csv(path)
    if "datetime_utc" not in hourly.columns:
        raise ValueError("hourly_states.csv must contain datetime_utc")
    hourly["datetime_utc"] = pd.to_datetime(hourly["datetime_utc"], utc=True, errors="coerce")
    hourly = hourly.dropna(subset=["datetime_utc"]).sort_values("datetime_utc")
    hourly = hourly.drop_duplicates(subset=["datetime_utc"], keep="last")
    return hourly.set_index("datetime_utc")


def _resolve_holdout_tiers(
    y: pd.Series,
    thresholds: dict[str, Any],
    holdout_mask: pd.Series,
    hourly: pd.DataFrame | None,
) -> tuple[pd.Series, str]:
    """Return alert tiers on holdout hours and a short source label."""
    holdout_ix = y.index[holdout_mask]
    if hourly is not None and "alert_tier" in hourly.columns:
        aligned = hourly.reindex(holdout_ix)
        if aligned["alert_tier"].notna().all():
            return pd.Series(aligned["alert_tier"].astype(str).values, index=holdout_ix), "hourly_states.csv"
    tiers_all = label_alert_tier(y, thresholds)
    return tiers_all[holdout_mask], "recomputed_from_thresholds"


def _rule_warning_column(hourly: pd.DataFrame, horizon: int) -> str | None:
    for pat in RULE_WARNING_COLUMN_PATTERNS:
        col = pat.format(h=horizon)
        if col in hourly.columns:
            return col
    return None


def _rule_warning_counts_holdout(
    hourly: pd.DataFrame | None,
    holdout_mask: pd.Series,
) -> dict[str, Any] | None:
    if hourly is None:
        return None
    out: dict[str, Any] = {}
    any_col = False
    h_mask = holdout_mask.reindex(hourly.index, fill_value=False)
    n_holdout = int(h_mask.sum())
    for h in WARNING_HORIZONS:
        col = _rule_warning_column(hourly, h)
        hs = str(h)
        if col is None:
            out[hs] = None
            continue
        any_col = True
        sub = hourly.loc[h_mask, col]
        fired = sub.astype(bool) if sub.dtype == bool else sub.fillna(False).astype(bool)
        n_fire = int(fired.sum())
        out[hs] = {
            "column": col,
            "n_holdout_hours": n_holdout,
            "n_fired": n_fire,
            "rate": round(n_fire / n_holdout, 6) if n_holdout else None,
        }
    return out if any_col else None


def _flood_window_tier_summary(
    tiers: pd.Series,
    y: pd.Series,
    *,
    start: pd.Timestamp = FLOOD_WINDOW_START,
    end: pd.Timestamp = FLOOD_WINDOW_END,
) -> dict[str, Any]:
    start = start.tz_convert("UTC") if start.tzinfo else start.tz_localize("UTC")
    end = end.tz_convert("UTC") if end.tzinfo else end.tz_localize("UTC")
    win_ix = tiers.index[(tiers.index >= start) & (tiers.index <= end)]
    tiers_win = tiers.reindex(win_ix)
    y_win = y.reindex(win_ix)
    y_num = pd.to_numeric(y_win, errors="coerce")
    valid = y_num[np.isfinite(y_num)]
    tier_block = _tier_counts_and_rates(tiers_win)
    return {
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "n_grid_hours": int(len(win_ix)),
        "y_max": round(float(valid.max()), 6) if len(valid) else None,
        "y_valid_n": int(len(valid)),
        "tier_counts": tier_block["tier_counts"],
        "tier_rates": tier_block["tier_rates"],
        "hours_per_tier": tier_block["tier_counts"],
    }


def _monthly_tier_rates_holdout(tiers: pd.Series) -> list[dict[str, Any]]:
    if tiers.empty:
        return []
    df = pd.DataFrame({"tier": tiers.astype(str)}, index=tiers.index)
    df["year_month"] = df.index.strftime("%Y-%m")
    rows: list[dict[str, Any]] = []
    for ym, grp in df.groupby("year_month", sort=True):
        n = len(grp)
        counts = {t: int((grp["tier"] == t).sum()) for t in ALL_ALERT_TIERS}
        rates = {t: round(counts[t] / n, 6) if n else None for t in ALL_ALERT_TIERS}
        rows.append(
            {
                "year_month": ym,
                "n_hours": n,
                "tier_counts": counts,
                "tier_rates": rates,
            }
        )
    return rows


def format_holdout_eval_summary(eval_dict: dict[str, Any]) -> str:
    """Markdown summary table for holdout tier evaluation."""
    lines = [
        "# Turbidity holdout tier evaluation",
        "",
        f"- Site: `{eval_dict.get('site_no')}`",
        f"- Model: `{eval_dict.get('model_version')}`",
        f"- Holdout: {eval_dict.get('holdout_start_utc')} → {eval_dict.get('holdout_end_utc')}",
        f"- Grid hours: {eval_dict.get('n_grid_hours')} (valid y: {eval_dict.get('n_valid_y')}, gap/skipped: {eval_dict.get('n_skipped_no_y')})",
        f"- Tier source: {eval_dict.get('tier_source')}",
        "",
        "## Holdout tier rates",
        "",
        "| Tier | Count | Rate |",
        "|------|------:|-----:|",
    ]
    counts = eval_dict.get("tier_counts") or {}
    rates = eval_dict.get("tier_rates") or {}
    for t in ALL_ALERT_TIERS:
        lines.append(f"| {t} | {counts.get(t, 0)} | {rates.get(t)} |")
    q_rates = eval_dict.get("quality_tier_rates") or {}
    if q_rates:
        lines.extend(
            [
                "",
                "## Quality tier rates (finite y only)",
                "",
                "| Tier | Rate |",
                "|------|-----:|",
            ]
        )
        for t in ALERT_TIERS:
            lines.append(f"| {t} | {q_rates.get(t)} |")
    flood = eval_dict.get("flood_window_dec_2025") or {}
    lines.extend(
        [
            "",
            "## Dec 2025 flood window (2025-12-09 — 2025-12-17)",
            "",
            f"- Grid hours: {flood.get('n_grid_hours')}",
            f"- Max y (NTU): {flood.get('y_max')}",
            "",
            "| Tier | Hours | Rate |",
            "|------|------:|-----:|",
        ]
    )
    f_counts = flood.get("tier_counts") or {}
    f_rates = flood.get("tier_rates") or {}
    for t in ALL_ALERT_TIERS:
        lines.append(f"| {t} | {f_counts.get(t, 0)} | {f_rates.get(t)} |")
    lines.append("")
    return "\n".join(lines)


def run_holdout_eval(
    report_dir: Path,
    *,
    features_csv: Path | None = None,
    holdout_fraction: float = 0.2,
    holdout_min_hours: int = 336,
    write_md: bool = True,
) -> dict[str, Any]:
    """
    Evaluate frozen v2 alert tiers on the holdout segment.

    Writes ``holdout_eval.json`` (and optional ``holdout_eval.md``) under ``report_dir``.
    """
    report_path = Path(report_dir)
    thresholds = _load_thresholds(report_path)
    csv_path = _resolve_features_csv(report_path, thresholds, features_csv)

    df = load_features(csv_path)
    y = df["63680"]
    n = len(y)
    split_info = _split_index_for_holdout(
        n,
        max_horizon=max(WARNING_HORIZONS),
        holdout_fraction=float(holdout_fraction),
        holdout_min_hours=int(holdout_min_hours),
        min_tuning_hours=2000,
    )
    holdout_mask = _holdout_mask_from_split(y, thresholds, split_info)
    hourly = _load_hourly_states(report_path)

    tiers_holdout, tier_source = _resolve_holdout_tiers(y, thresholds, holdout_mask, hourly)
    holdout_ix = y.index[holdout_mask]
    y_holdout = y.loc[holdout_ix]

    n_grid = int(len(holdout_ix))
    y_num = pd.to_numeric(y_holdout, errors="coerce")
    valid_mask = np.isfinite(y_num.to_numpy(dtype=float, copy=False))
    n_valid_y = int(valid_mask.sum())
    n_skipped_no_y = n_grid - n_valid_y

    tier_block = _tier_counts_and_rates(tiers_holdout)
    n_gap_tiers = int(tier_block["n_gap_hours"])
    rule_warnings = _rule_warning_counts_holdout(hourly, holdout_mask)

    result: dict[str, Any] = {
        "spec": "turbidity_holdout_eval",
        "site_no": thresholds.get("site_no"),
        "model_version": thresholds.get("model_version"),
        "report_dir": str(report_path.resolve()),
        "features_csv": str(csv_path.resolve()),
        "tier_source": tier_source,
        "holdout_start_utc": str(holdout_ix.min()) if n_grid else None,
        "holdout_end_utc": str(holdout_ix.max()) if n_grid else None,
        "n_grid_hours": n_grid,
        "n_valid_y": n_valid_y,
        "n_skipped_no_y": n_gap_tiers,
        "n_skipped_no_y_matches_invalid_y": n_skipped_no_y == n_gap_tiers,
        "gap_tier_counts": tier_block["gap_tier_counts"],
        "quality_tier_counts": tier_block["quality_tier_counts"],
        "quality_tier_rates": tier_block["quality_tier_rates"],
        "tier_counts": tier_block["tier_counts"],
        "tier_rates": tier_block["tier_rates"],
        "holdout_split": split_info,
        "flood_window_dec_2025": _flood_window_tier_summary(tiers_holdout, y_holdout),
        "monthly_tier_rates_holdout": _monthly_tier_rates_holdout(tiers_holdout),
        "holdout_tier_fractions": holdout_tier_fractions(
            pd.Series(tiers_holdout.values, index=holdout_ix), holdout_mask
        ),
    }
    if rule_warnings is not None:
        result["rule_warning_counts"] = rule_warnings

    report_path.mkdir(parents=True, exist_ok=True)
    (report_path / "holdout_eval.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if write_md:
        (report_path / "holdout_eval.md").write_text(
            format_holdout_eval_summary(result), encoding="utf-8"
        )
    return result

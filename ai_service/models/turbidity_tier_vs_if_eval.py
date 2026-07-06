"""
Holdout comparison: rule-based alert tiers (v2.1) vs on-demand univariate IsolationForest.

For each holdout hour with finite 63680, scores IF at index t using the same hyperparameters
as ``site_param_anomaly_on_demand`` (trailing min(2500, n_valid) hours up to t).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

from .backtest_turbidity_exog_ridge_lgbm import _split_index_for_holdout
from .forecast_engine import load_hourly_series
from .site_param_anomaly_on_demand import (
    MAX_TRAIN_POINTS,
    MIN_HOURLY_POINTS,
    MODEL_VERSION as IF_MODEL_VERSION,
)
from .turbidity_gap_report import FLOOD_WINDOW_END, FLOOD_WINDOW_START
from .turbidity_holdout_eval import (
    _holdout_mask_from_split,
    _load_hourly_states,
    _load_thresholds,
    _resolve_features_csv,
    _resolve_holdout_tiers,
)
from .turbidity_state_monitoring import (
    GAP_TIERS,
    WARNING_HORIZONS,
    is_gap_tier,
    load_features,
)

DEFAULT_REPORT_DIR = (
    Path(__file__).resolve().parent.parent
    / "reports"
    / "turbidity_state"
    / "12117500_v2"
)

TIER_ALERT_LEVELS: Final[frozenset[str]] = frozenset({"WATCH", "HIGH", "CRITICAL"})
IF_N_ESTIMATORS = 200
IF_CONTAMINATION = 0.05
IF_RANDOM_STATE = 42


def tier_is_alert(tier: str) -> bool:
    return str(tier).strip().upper() in TIER_ALERT_LEVELS


def fit_if_is_anomaly(window: np.ndarray) -> tuple[bool | None, dict[str, Any]]:
    """
    Fit RobustScaler + IsolationForest on ``window`` and classify the last point.

    Returns (is_anomaly, meta). ``is_anomaly`` is None when history is insufficient.
    """
    w = np.asarray(window, dtype=float)
    w = w[np.isfinite(w)]
    n = len(w)
    if n < MIN_HOURLY_POINTS:
        return None, {"reason": "insufficient_history", "samples_used": n}

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
    pred_label = int(iso.predict(X_scaled[-1:])[0])
    return pred_label == -1, {"reason": None, "samples_used": len(tail)}


def build_calendar_y_series(
    *,
    features_csv: Path,
    iv_csv: Path | None,
    site_no: str,
) -> pd.Series:
    """Hourly 63680 on the features calendar grid (optional IV fill for missing cells)."""
    df = load_features(features_csv)
    y = df["63680"].astype(float)
    if iv_csv is not None and iv_csv.is_file():
        iv = load_hourly_series(iv_csv, site_no, "63680", dense=False)
        if not iv.empty:
            aligned = iv.reindex(y.index)
            miss = ~np.isfinite(y.to_numpy(dtype=float, copy=False))
            fill = np.isfinite(aligned.to_numpy(dtype=float, copy=False))
            y = y.copy()
            y.iloc[miss & fill] = aligned.iloc[miss & fill]
    return y


def _score_if_one_hour(
    y_num: np.ndarray,
    valid_pos: np.ndarray,
    t_pos: int,
) -> dict[str, Any]:
    upto = valid_pos[valid_pos <= t_pos]
    if len(upto) == 0 or upto[-1] != t_pos:
        return {
            "if_is_anomaly": None,
            "if_available": False,
            "if_reason": "y_not_finite_at_t",
            "if_samples_used": 0,
        }
    is_anom, meta = fit_if_is_anomaly(y_num[upto])
    return {
        "if_is_anomaly": is_anom,
        "if_available": is_anom is not None,
        "if_reason": meta.get("reason"),
        "if_samples_used": int(meta.get("samples_used") or 0),
    }


def _score_if_chunk(
    eval_times: list[pd.Timestamp],
    y_num: np.ndarray,
    valid_pos: np.ndarray,
    pos_by_time: dict[pd.Timestamp, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ts in eval_times:
        t_pos = pos_by_time.get(ts)
        if t_pos is None:
            rows.append(
                {
                    "if_is_anomaly": None,
                    "if_available": False,
                    "if_reason": "timestamp_not_on_grid",
                    "if_samples_used": 0,
                }
            )
        else:
            rows.append(_score_if_one_hour(y_num, valid_pos, t_pos))
    return rows


def score_if_on_holdout_hours(
    y: pd.Series,
    eval_index: pd.DatetimeIndex,
    *,
    progress_every: int = 500,
    n_jobs: int = -1,
) -> pd.DataFrame:
    """
    For each timestamp in ``eval_index``, fit IF on trailing valid hours up to that hour.

    ``eval_index`` must be sorted UTC; typically holdout hours with finite y.
    """
    if eval_index.empty:
        return pd.DataFrame(
            columns=["if_is_anomaly", "if_available", "if_reason", "if_samples_used"],
            index=eval_index,
        )

    import os

    from joblib import Parallel, delayed

    y_num = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float, copy=False)
    grid_ix = y.index
    pos_by_time = {ts: i for i, ts in enumerate(grid_ix)}
    valid_pos = np.flatnonzero(np.isfinite(y_num))

    workers = os.cpu_count() or 4 if n_jobs < 0 else max(1, n_jobs)
    times = list(eval_index)
    chunk_size = max(1, (len(times) + workers - 1) // workers)
    chunks = [times[i : i + chunk_size] for i in range(0, len(times), chunk_size)]

    if progress_every > 0:
        print(
            f"  IF scoring {len(times)} hours in {len(chunks)} chunks (workers={workers})...",
            flush=True,
        )

    chunk_rows = Parallel(n_jobs=workers)(
        delayed(_score_if_chunk)(chunk, y_num, valid_pos, pos_by_time) for chunk in chunks
    )
    row_dicts = [row for chunk in chunk_rows for row in chunk]

    if progress_every > 0:
        print(f"  IF scored {len(row_dicts)}/{len(eval_index)} holdout hours.", flush=True)

    return pd.DataFrame(row_dicts, index=eval_index)


def _contingency_block(
    tier_alert: pd.Series,
    if_alert: pd.Series,
) -> dict[str, Any]:
    n = int(len(tier_alert))
    both = int((tier_alert & if_alert).sum())
    tier_only = int((tier_alert & ~if_alert).sum())
    if_only = int((~tier_alert & if_alert).sum())
    neither = int((~tier_alert & ~if_alert).sum())
    tier_n = int(tier_alert.sum())
    if_n = int(if_alert.sum())
    agree = both + neither
    return {
        "n_hours": n,
        "tier_alert_n": tier_n,
        "tier_alert_rate": round(tier_n / n, 6) if n else None,
        "if_alert_n": if_n,
        "if_alert_rate": round(if_n / n, 6) if n else None,
        "both_alert_n": both,
        "both_alert_rate": round(both / n, 6) if n else None,
        "tier_only_n": tier_only,
        "tier_only_rate": round(tier_only / n, 6) if n else None,
        "if_only_n": if_only,
        "if_only_rate": round(if_only / n, 6) if n else None,
        "neither_n": neither,
        "neither_rate": round(neither / n, 6) if n else None,
        "agreement_n": agree,
        "agreement_rate": round(agree / n, 6) if n else None,
        "tier_precision_vs_if": round(both / tier_n, 6) if tier_n else None,
        "tier_recall_vs_if": round(both / if_n, 6) if if_n else None,
        "if_precision_vs_tier": round(both / if_n, 6) if if_n else None,
        "if_recall_vs_tier": round(both / tier_n, 6) if tier_n else None,
    }


def _gap_summary(tiers: pd.Series) -> dict[str, Any]:
    n = int(len(tiers))
    counts = {t: int((tiers == t).sum()) for t in GAP_TIERS}
    return {
        "n_hours": n,
        "gap_tier_counts": counts,
        "gap_any_n": int(tiers.map(is_gap_tier).sum()),
    }


def _subset_mask(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    start = start.tz_convert("UTC") if start.tzinfo else start.tz_localize("UTC")
    end = end.tz_convert("UTC") if end.tzinfo else end.tz_localize("UTC")
    return pd.Series((index >= start) & (index <= end), index=index)


def format_tier_vs_if_md(result: dict[str, Any]) -> str:
    """Markdown comparison table for resume."""
    defs = result.get("definitions") or {}
    holdout = result.get("holdout") or {}
    quality = result.get("quality_hours") or {}
    gap = result.get("gap_hours") or {}
    flood = result.get("flood_window_dec_2025") or {}

    lines = [
        "# Turbidity holdout: alert tier vs IsolationForest",
        "",
        f"- Site: `{result.get('site_no')}`",
        f"- Tier model: `{result.get('tier_model_version')}`",
        f"- IF model: `{result.get('if_model_version')}`",
        f"- Holdout: {holdout.get('start_utc')} → {holdout.get('end_utc')}",
        f"- Tier source: {result.get('tier_source')}",
        "",
        "## Definitions",
        "",
        f"- Tier alert: {defs.get('tier_alert')}",
        f"- IF alert: {defs.get('if_alert')}",
        f"- Agreement stats population: {defs.get('agreement_population')}",
        f"- IF window: {defs.get('if_window')}",
        "",
        "## Holdout counts",
        "",
        f"| Segment | Hours |",
        f"|---------|------:|",
        f"| Grid (holdout) | {holdout.get('n_grid_hours')} |",
        f"| Finite y | {holdout.get('n_finite_y')} |",
        f"| Gap tier on grid (excluded) | {holdout.get('n_gap_tier_on_grid')} |",
        f"| Gap tier with finite y | {holdout.get('n_gap_tier_finite_y')} |",
        f"| Quality (finite y, non-gap) | {quality.get('n_hours')} |",
        f"| IF unavailable on quality | {quality.get('if_unavailable_n')} |",
        "",
        "## 2×2 contingency (quality hours, IF available)",
        "",
        "| | IF alert | IF normal |",
        "|--|---------:|----------:|",
    ]
    c = quality.get("contingency") or {}
    lines.extend(
        [
            f"| Tier alert | {c.get('both_alert_n')} | {c.get('tier_only_n')} |",
            f"| Tier normal | {c.get('if_only_n')} | {c.get('neither_n')} |",
            "",
            f"- Tier alert rate: {c.get('tier_alert_rate')}",
            f"- IF alert rate: {c.get('if_alert_rate')}",
            f"- Agreement rate: {c.get('agreement_rate')}",
            f"- Tier precision (vs IF): {c.get('tier_precision_vs_if')}",
            f"- Tier recall (vs IF): {c.get('tier_recall_vs_if')}",
            "",
            "## Gap-tier hours (excluded from agreement)",
            "",
        ]
    )
    gc = gap.get("gap_tier_counts") or {}
    for t in GAP_TIERS:
        lines.append(f"- {t}: {gc.get(t, 0)}")
    lines.extend(
        [
            "",
            "## Dec 2025 flood window (2025-12-09 — 2025-12-17)",
            "",
        ]
    )
    fc = flood.get("contingency") or {}
    if fc:
        lines.extend(
            [
                f"- Quality hours in window: {flood.get('n_quality_hours')}",
                "",
                "| | IF alert | IF normal |",
                "|--|---------:|----------:|",
                f"| Tier alert | {fc.get('both_alert_n')} | {fc.get('tier_only_n')} |",
                f"| Tier normal | {fc.get('if_only_n')} | {fc.get('neither_n')} |",
                "",
                f"- Agreement rate: {fc.get('agreement_rate')}",
                "",
            ]
        )
    else:
        lines.append("- (no quality hours in window)")
        lines.append("")
    return "\n".join(lines)


def run_tier_vs_if_eval(
    report_dir: Path,
    *,
    features_csv: Path | None = None,
    iv_csv: Path | None = None,
    holdout_fraction: float = 0.2,
    holdout_min_hours: int = 336,
    progress_every: int = 500,
    n_jobs: int = -1,
    write_md: bool = True,
) -> dict[str, Any]:
    """
    Compare v2.1 ``alert_tier`` with rolling univariate IF on the holdout segment.

    Writes ``tier_vs_if_holdout.json`` and optional ``tier_vs_if_holdout.md``.
    """
    report_path = Path(report_dir)
    thresholds = _load_thresholds(report_path)
    csv_path = _resolve_features_csv(report_path, thresholds, features_csv)
    site_no = str(thresholds.get("site_no") or "12117500")

    y = build_calendar_y_series(features_csv=csv_path, iv_csv=iv_csv, site_no=site_no)
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
    y_finite = np.isfinite(pd.to_numeric(y_holdout, errors="coerce").to_numpy(dtype=float, copy=False))
    finite_ix = holdout_ix[y_finite]

    print(f"Scoring IF on {len(finite_ix)} holdout hours with finite y...", flush=True)
    if_scores = score_if_on_holdout_hours(
        y, finite_ix, progress_every=progress_every, n_jobs=n_jobs
    )
    tiers_finite = tiers_holdout.reindex(finite_ix)

    gap_mask_finite = tiers_finite.map(is_gap_tier)
    quality_ix = finite_ix[~gap_mask_finite.to_numpy()]
    quality_tiers = tiers_finite.loc[quality_ix]
    quality_if = if_scores.loc[quality_ix]

    if_avail = quality_if["if_available"].astype(bool)
    eval_ix = quality_ix[if_avail.to_numpy()]
    tier_alert = quality_tiers.loc[eval_ix].map(tier_is_alert)
    if_alert = quality_if.loc[eval_ix, "if_is_anomaly"].astype(bool)

    quality_contingency = _contingency_block(tier_alert, if_alert)

    flood_mask = _subset_mask(eval_ix, FLOOD_WINDOW_START, FLOOD_WINDOW_END)
    flood_ix = eval_ix[flood_mask.to_numpy()]
    flood_contingency = None
    if len(flood_ix):
        flood_contingency = _contingency_block(
            tier_alert.reindex(flood_ix),
            if_alert.reindex(flood_ix),
        )

    gap_on_grid_mask = tiers_holdout.map(is_gap_tier)
    gap_summary = _gap_summary(tiers_holdout[gap_on_grid_mask])
    gap_finite_n = int(gap_mask_finite.sum())

    result: dict[str, Any] = {
        "spec": "turbidity_tier_vs_if_holdout",
        "site_no": site_no,
        "tier_model_version": thresholds.get("model_version"),
        "if_model_version": IF_MODEL_VERSION,
        "report_dir": str(report_path.resolve()),
        "features_csv": str(csv_path.resolve()),
        "iv_csv": str(iv_csv.resolve()) if iv_csv else None,
        "tier_source": tier_source,
        "definitions": {
            "tier_alert": "alert_tier in WATCH | HIGH | CRITICAL",
            "if_alert": "IsolationForest predict(last point) == -1",
            "agreement_population": "holdout hours with finite 63680, non-gap alert_tier, IF available",
            "if_window": (
                f"trailing min({MAX_TRAIN_POINTS}, n_valid) finite hours up to t; "
                f"min {MIN_HOURLY_POINTS} valid hours required; "
                f"n_estimators={IF_N_ESTIMATORS}, contamination={IF_CONTAMINATION}, "
                f"RobustScaler + IsolationForest (random_state={IF_RANDOM_STATE})"
            ),
            "gap_tiers_excluded": list(GAP_TIERS),
        },
        "holdout": {
            "start_utc": str(holdout_ix.min()) if len(holdout_ix) else None,
            "end_utc": str(holdout_ix.max()) if len(holdout_ix) else None,
            "n_grid_hours": int(len(holdout_ix)),
            "n_finite_y": int(len(finite_ix)),
            "n_gap_tier_on_grid": int(gap_on_grid_mask.sum()),
            "n_gap_tier_finite_y": gap_finite_n,
        },
        "quality_hours": {
            "n_hours": int(len(quality_ix)),
            "if_unavailable_n": int((~if_avail).sum()),
            "if_unavailable_reasons": quality_if.loc[~if_avail, "if_reason"].value_counts().to_dict()
            if (~if_avail).any()
            else {},
            "contingency": quality_contingency,
        },
        "gap_hours": gap_summary,
        "flood_window_dec_2025": {
            "window_start_utc": FLOOD_WINDOW_START.isoformat(),
            "window_end_utc": FLOOD_WINDOW_END.isoformat(),
            "n_quality_hours": int(len(flood_ix)),
            "contingency": flood_contingency,
        },
        "holdout_split": split_info,
    }

    report_path.mkdir(parents=True, exist_ok=True)
    (report_path / "tier_vs_if_holdout.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if write_md:
        (report_path / "tier_vs_if_holdout.md").write_text(
            format_tier_vs_if_md(result), encoding="utf-8"
        )
    return result

"""
Holdout comparison: alert tiers vs univariate IF vs multivariate IF (63680 + exog at t).

Multivariate features at hour t (no exog forward-fill): 63680, precipitation_mm,
upstream_discharge_cfs_12116400. Same IsolationForest hyperparameters as univariate on-demand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

from .backtest_turbidity_exog_ridge_lgbm import UPSTREAM_DISCHARGE_COL, _split_index_for_holdout
from .site_param_anomaly_on_demand import MAX_TRAIN_POINTS, MIN_HOURLY_POINTS
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
from .turbidity_tier_vs_if_eval import (
    DEFAULT_REPORT_DIR,
    IF_CONTAMINATION,
    IF_N_ESTIMATORS,
    IF_RANDOM_STATE,
    _contingency_block,
    _subset_mask,
    build_calendar_y_series,
    score_if_on_holdout_hours,
    tier_is_alert,
)
MULTIVAR_MODEL_VERSION: Final[str] = "site-param-iforest-multivar-ondemand-v1"
MULTIVAR_FEATURE_COLS: Final[tuple[str, ...]] = (
    "63680",
    "precipitation_mm",
    UPSTREAM_DISCHARGE_COL,
)


def fit_multivar_if_is_anomaly(window: np.ndarray) -> tuple[bool | None, dict[str, Any]]:
    """Fit RobustScaler + IsolationForest on ``window`` (n_rows, 3) and score the last row."""
    w = np.asarray(window, dtype=float)
    if w.ndim != 2 or w.shape[1] != len(MULTIVAR_FEATURE_COLS):
        raise ValueError(f"window must be (n, {len(MULTIVAR_FEATURE_COLS)})")
    row_ok = np.all(np.isfinite(w), axis=1)
    w = w[row_ok]
    n = len(w)
    if n < MIN_HOURLY_POINTS:
        return None, {"reason": "insufficient_history", "samples_used": n}

    tail = w[-MAX_TRAIN_POINTS:]
    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(tail)
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


def build_multivar_matrix(df: pd.DataFrame) -> np.ndarray:
    """Stack multivariate feature columns; caller must ensure columns exist."""
    missing = [c for c in MULTIVAR_FEATURE_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"features CSV missing multivariate columns: {missing}")
    parts = [pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float, copy=False) for c in MULTIVAR_FEATURE_COLS]
    return np.column_stack(parts)


def _row_all_finite(matrix: np.ndarray) -> np.ndarray:
    return np.all(np.isfinite(matrix), axis=1)


def _segment_complete_case_counts(
    matrix: np.ndarray,
    mask: np.ndarray,
) -> dict[str, Any]:
    """Counts on hours where ``mask`` is True on the hourly grid."""
    n_grid = int(mask.sum())
    if n_grid == 0:
        return {
            "n_grid": 0,
            "n_y_valid": 0,
            "n_multivar_ready": 0,
            "y_valid_rate": None,
            "multivar_ready_rate": None,
            "multivar_ready_given_y_valid_rate": None,
        }
    sub = matrix[mask]
    y_ok = np.isfinite(sub[:, 0])
    multivar_ok = _row_all_finite(sub)
    n_y = int(y_ok.sum())
    n_mv = int(multivar_ok.sum())
    return {
        "n_grid": n_grid,
        "n_y_valid": n_y,
        "n_multivar_ready": n_mv,
        "y_valid_rate": round(n_y / n_grid, 6),
        "multivar_ready_rate": round(n_mv / n_grid, 6),
        "multivar_ready_given_y_valid_rate": round(n_mv / n_y, 6) if n_y else None,
    }


def compute_exog_complete_case_counts(
    matrix: np.ndarray,
    tuning_mask: pd.Series,
    holdout_mask: pd.Series,
) -> dict[str, Any]:
    """Complete-case counts for tuning, holdout, and full series (no exog ffill)."""
    full_mask = np.ones(len(matrix), dtype=bool)
    return {
        "feature_columns": list(MULTIVAR_FEATURE_COLS),
        "exog_ffill": False,
        "tuning": _segment_complete_case_counts(matrix, tuning_mask.to_numpy(dtype=bool, copy=False)),
        "holdout": _segment_complete_case_counts(matrix, holdout_mask.to_numpy(dtype=bool, copy=False)),
        "full": _segment_complete_case_counts(matrix, full_mask),
    }


def _score_multivar_if_one_hour(
    x_num: np.ndarray,
    multivar_pos: np.ndarray,
    t_pos: int,
) -> dict[str, Any]:
    upto = multivar_pos[multivar_pos <= t_pos]
    if len(upto) == 0 or upto[-1] != t_pos:
        return {
            "mif_is_anomaly": None,
            "mif_available": False,
            "mif_reason": "incomplete_exog_at_t",
            "mif_samples_used": 0,
        }
    is_anom, meta = fit_multivar_if_is_anomaly(x_num[upto])
    return {
        "mif_is_anomaly": is_anom,
        "mif_available": is_anom is not None,
        "mif_reason": meta.get("reason"),
        "mif_samples_used": int(meta.get("samples_used") or 0),
    }


def _score_multivar_if_chunk(
    eval_times: list[pd.Timestamp],
    x_num: np.ndarray,
    multivar_pos: np.ndarray,
    pos_by_time: dict[pd.Timestamp, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ts in eval_times:
        t_pos = pos_by_time.get(ts)
        if t_pos is None:
            rows.append(
                {
                    "mif_is_anomaly": None,
                    "mif_available": False,
                    "mif_reason": "timestamp_not_on_grid",
                    "mif_samples_used": 0,
                }
            )
        else:
            rows.append(_score_multivar_if_one_hour(x_num, multivar_pos, t_pos))
    return rows


def score_multivar_if_on_holdout_hours(
    x_num: np.ndarray,
    eval_index: pd.DatetimeIndex,
    grid_index: pd.DatetimeIndex,
    *,
    progress_every: int = 500,
    n_jobs: int = -1,
) -> pd.DataFrame:
    """Rolling multivariate IF on ``eval_index`` using complete-case rows only (no exog ffill)."""
    if eval_index.empty:
        return pd.DataFrame(
            columns=["mif_is_anomaly", "mif_available", "mif_reason", "mif_samples_used"],
            index=eval_index,
        )

    import os

    from joblib import Parallel, delayed

    pos_by_time = {ts: i for i, ts in enumerate(grid_index)}
    multivar_pos = np.flatnonzero(_row_all_finite(x_num))

    workers = os.cpu_count() or 4 if n_jobs < 0 else max(1, n_jobs)
    times = list(eval_index)
    chunk_size = max(1, (len(times) + workers - 1) // workers)
    chunks = [times[i : i + chunk_size] for i in range(0, len(times), chunk_size)]

    if progress_every > 0:
        print(
            f"  Multivariate IF scoring {len(times)} hours in {len(chunks)} chunks "
            f"(workers={workers})...",
            flush=True,
        )

    chunk_rows = Parallel(n_jobs=workers)(
        delayed(_score_multivar_if_chunk)(chunk, x_num, multivar_pos, pos_by_time) for chunk in chunks
    )
    row_dicts = [row for chunk in chunk_rows for row in chunk]

    if progress_every > 0:
        print(
            f"  Multivariate IF scored {len(row_dicts)}/{len(eval_index)} holdout hours.",
            flush=True,
        )

    return pd.DataFrame(row_dicts, index=eval_index)


def format_tier_vs_univariate_vs_multivar_md(result: dict[str, Any]) -> str:
    defs = result.get("definitions") or {}
    holdout = result.get("holdout") or {}
    counts = result.get("exog_complete_case_counts") or {}
    h_counts = counts.get("holdout") or {}
    three = result.get("three_way_hours") or {}
    tier_uni = three.get("tier_vs_univariate") or {}
    tier_mv = three.get("tier_vs_multivariate") or {}
    uni_mv = three.get("univariate_vs_multivariate") or {}

    lines = [
        "# Turbidity holdout: tier vs univariate IF vs multivariate IF",
        "",
        f"- Site: `{result.get('site_no')}`",
        f"- Tier model: `{result.get('tier_model_version')}`",
        f"- Univariate IF: `{result.get('univariate_if_model_version')}`",
        f"- Multivariate IF: `{result.get('multivariate_if_model_version')}`",
        f"- Holdout: {holdout.get('start_utc')} → {holdout.get('end_utc')}",
        "",
        "## Multivariate features (complete case at t, no exog ffill)",
        "",
        f"- Columns: `{', '.join(defs.get('multivariate_feature_columns') or [])}`",
        f"- Excluded: temperature and other weather beyond precipitation",
        "",
        "## Holdout complete-case counts",
        "",
        f"| Metric | Count | Rate |",
        f"|--------|------:|-----:|",
        f"| Grid hours | {h_counts.get('n_grid')} | — |",
        f"| Finite 63680 | {h_counts.get('n_y_valid')} | {h_counts.get('y_valid_rate')} |",
        f"| Multivariate-ready | {h_counts.get('n_multivar_ready')} | {h_counts.get('multivar_ready_rate')} |",
        f"| Multivar-ready given finite y | {h_counts.get('n_multivar_ready')} | "
        f"{h_counts.get('multivar_ready_given_y_valid_rate')} |",
        "",
        "## Three-way population",
        "",
        f"- Hours (tier + uni IF + multivar IF all available): {three.get('n_hours')}",
        "",
        "### Tier vs univariate IF",
        "",
        "| | Uni IF alert | Uni IF normal |",
        "|--|------------:|--------------:|",
        f"| Tier alert | {tier_uni.get('both_alert_n')} | {tier_uni.get('tier_only_n')} |",
        f"| Tier normal | {tier_uni.get('if_only_n')} | {tier_uni.get('neither_n')} |",
        "",
        f"- Agreement rate: {tier_uni.get('agreement_rate')}",
        "",
        "### Tier vs multivariate IF",
        "",
        "| | Multivar IF alert | Multivar IF normal |",
        "|--|------------------:|-------------------:|",
        f"| Tier alert | {tier_mv.get('both_alert_n')} | {tier_mv.get('tier_only_n')} |",
        f"| Tier normal | {tier_mv.get('if_only_n')} | {tier_mv.get('neither_n')} |",
        "",
        f"- Agreement rate: {tier_mv.get('agreement_rate')}",
        "",
        "### Univariate IF vs multivariate IF",
        "",
        "| | Multivar IF alert | Multivar IF normal |",
        "|--|------------------:|-------------------:|",
        f"| Uni IF alert | {uni_mv.get('both_alert_n')} | {uni_mv.get('tier_only_n')} |",
        f"| Uni IF normal | {uni_mv.get('if_only_n')} | {uni_mv.get('neither_n')} |",
        "",
        f"- Agreement rate: {uni_mv.get('agreement_rate')}",
        "",
    ]
    return "\n".join(lines)


def run_tier_vs_univariate_vs_multivar_eval(
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
    Compare alert tiers with univariate and multivariate IF on holdout.

    Writes ``exog_complete_case_counts.json`` and ``tier_vs_univariate_vs_multivar_holdout.json``.
    """
    from .site_param_anomaly_on_demand import MODEL_VERSION as UNIVARIATE_IF_MODEL_VERSION

    report_path = Path(report_dir)
    thresholds = _load_thresholds(report_path)
    csv_path = _resolve_features_csv(report_path, thresholds, features_csv)
    site_no = str(thresholds.get("site_no") or "12117500")

    df_raw = load_features(csv_path, use_exog_ffill=False)
    x_num = build_multivar_matrix(df_raw)

    y = build_calendar_y_series(features_csv=csv_path, iv_csv=iv_csv, site_no=site_no)
    if not y.index.equals(df_raw.index):
        raise ValueError("63680 calendar index mismatch between raw features and y series")

    n = len(y)
    split_info = _split_index_for_holdout(
        n,
        max_horizon=max(WARNING_HORIZONS),
        holdout_fraction=float(holdout_fraction),
        holdout_min_hours=int(holdout_min_hours),
        min_tuning_hours=2000,
    )
    split_ix = int(split_info["split_index"])
    tuning_mask = pd.Series(y.index < y.index[split_ix], index=y.index)
    holdout_mask = _holdout_mask_from_split(y, thresholds, split_info)

    exog_counts = compute_exog_complete_case_counts(x_num, tuning_mask, holdout_mask)

    hourly = _load_hourly_states(report_path)
    tiers_holdout, tier_source = _resolve_holdout_tiers(y, thresholds, holdout_mask, hourly)

    holdout_ix = y.index[holdout_mask]
    y_holdout = y.loc[holdout_ix]
    y_finite = np.isfinite(pd.to_numeric(y_holdout, errors="coerce").to_numpy(dtype=float, copy=False))
    finite_ix = holdout_ix[y_finite]

    print(f"Scoring univariate IF on {len(finite_ix)} holdout hours with finite y...", flush=True)
    uni_scores = score_if_on_holdout_hours(
        y, finite_ix, progress_every=progress_every, n_jobs=n_jobs
    )

    print(
        f"Scoring multivariate IF on {len(finite_ix)} holdout hours (complete exog at t only)...",
        flush=True,
    )
    multivar_scores = score_multivar_if_on_holdout_hours(
        x_num,
        finite_ix,
        y.index,
        progress_every=progress_every,
        n_jobs=n_jobs,
    )

    tiers_finite = tiers_holdout.reindex(finite_ix)
    gap_mask_finite = tiers_finite.map(is_gap_tier)
    quality_ix = finite_ix[~gap_mask_finite.to_numpy()]

    uni_avail = uni_scores.loc[quality_ix, "if_available"].astype(bool)
    mif_avail = multivar_scores.loc[quality_ix, "mif_available"].astype(bool)
    three_ix = quality_ix[uni_avail.to_numpy() & mif_avail.to_numpy()]

    tier_alert = tiers_finite.loc[three_ix].map(tier_is_alert)
    uni_alert = uni_scores.loc[three_ix, "if_is_anomaly"].astype(bool)
    mif_alert = multivar_scores.loc[three_ix, "mif_is_anomaly"].astype(bool)

    tier_vs_uni = _contingency_block(tier_alert, uni_alert)
    tier_vs_mv = _contingency_block(tier_alert, mif_alert)
    uni_vs_mv = _contingency_block(uni_alert, mif_alert)

    flood_mask = _subset_mask(three_ix, FLOOD_WINDOW_START, FLOOD_WINDOW_END)
    flood_ix = three_ix[flood_mask.to_numpy()]
    flood_three = None
    if len(flood_ix):
        flood_three = {
            "n_hours": int(len(flood_ix)),
            "tier_vs_univariate": _contingency_block(
                tier_alert.reindex(flood_ix), uni_alert.reindex(flood_ix)
            ),
            "tier_vs_multivariate": _contingency_block(
                tier_alert.reindex(flood_ix), mif_alert.reindex(flood_ix)
            ),
            "univariate_vs_multivariate": _contingency_block(
                uni_alert.reindex(flood_ix), mif_alert.reindex(flood_ix)
            ),
        }

    mif_quality = multivar_scores.loc[quality_ix]
    mif_unavail = mif_quality[~mif_quality["mif_available"].astype(bool)]
    mif_unavail_reasons = (
        mif_unavail["mif_reason"].value_counts().to_dict() if len(mif_unavail) else {}
    )

    result: dict[str, Any] = {
        "spec": "turbidity_tier_vs_univariate_vs_multivar_holdout",
        "site_no": site_no,
        "tier_model_version": thresholds.get("model_version"),
        "univariate_if_model_version": UNIVARIATE_IF_MODEL_VERSION,
        "multivariate_if_model_version": MULTIVAR_MODEL_VERSION,
        "report_dir": str(report_path.resolve()),
        "features_csv": str(csv_path.resolve()),
        "iv_csv": str(iv_csv.resolve()) if iv_csv else None,
        "tier_source": tier_source,
        "definitions": {
            "tier_alert": "alert_tier in WATCH | HIGH | CRITICAL",
            "univariate_if_alert": "IsolationForest on 63680 only; trailing finite-y window",
            "multivariate_if_alert": (
                "IsolationForest on "
                + ", ".join(MULTIVAR_FEATURE_COLS)
                + " at t; trailing complete-case rows only; no exog ffill"
            ),
            "agreement_population": (
                "holdout hours with finite 63680, non-gap alert_tier, "
                "univariate IF available, multivariate IF available"
            ),
            "multivariate_feature_columns": list(MULTIVAR_FEATURE_COLS),
            "exog_ffill": False,
            "if_window": (
                f"trailing min({MAX_TRAIN_POINTS}, n_valid_rows) up to t; "
                f"min {MIN_HOURLY_POINTS} rows required; "
                f"n_estimators={IF_N_ESTIMATORS}, contamination={IF_CONTAMINATION}, "
                f"RobustScaler + IsolationForest (random_state={IF_RANDOM_STATE})"
            ),
            "gap_tiers_excluded": list(GAP_TIERS),
        },
        "exog_complete_case_counts": exog_counts,
        "holdout": {
            "start_utc": str(holdout_ix.min()) if len(holdout_ix) else None,
            "end_utc": str(holdout_ix.max()) if len(holdout_ix) else None,
            "n_grid_hours": int(len(holdout_ix)),
            "n_finite_y": int(len(finite_ix)),
            **exog_counts["holdout"],
        },
        "quality_hours": {
            "n_hours": int(len(quality_ix)),
            "n_multivar_ready": int(mif_avail.sum()),
            "multivar_unavailable_n": int((~mif_avail).sum()),
            "multivar_unavailable_reasons": mif_unavail_reasons,
        },
        "three_way_hours": {
            "n_hours": int(len(three_ix)),
            "tier_vs_univariate": tier_vs_uni,
            "tier_vs_multivariate": tier_vs_mv,
            "univariate_vs_multivariate": uni_vs_mv,
        },
        "flood_window_dec_2025": flood_three,
        "holdout_split": split_info,
    }

    report_path.mkdir(parents=True, exist_ok=True)
    (report_path / "exog_complete_case_counts.json").write_text(
        json.dumps(exog_counts, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (report_path / "tier_vs_univariate_vs_multivar_holdout.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if write_md:
        (report_path / "tier_vs_univariate_vs_multivar_holdout.md").write_text(
            format_tier_vs_univariate_vs_multivar_md(result), encoding="utf-8"
        )
    return result

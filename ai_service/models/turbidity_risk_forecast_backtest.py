"""
12h turbidity RISK forecast backtest (site 12117500).

Approach A1: Ridge direct per horizon on 63680 with precip + upstream exog (no temperature),
then map predicted NTU to alert tiers via frozen ``tier_rules`` from ``state_thresholds.json``.

Exogenous modes at forecast time ``T`` for horizon ``h``:
- **oracle**: exog lag blocks end at ``T+h`` (actual future weather/Q — deployability upper bound).
- **persistence**: exog lag blocks end at ``T`` (last known exog only).

Holdout metrics use ``split_index`` from the state-monitoring artifact when provided.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from .backtest_turbidity_exog_ridge_lgbm import (
    UPSTREAM_DISCHARGE_COL,
    _lag_matrix_block,
    _split_index_for_holdout,
)
from .forecast_engine import MAX_LAG, MIN_HOURLY_POINTS, _effective_lag, slice_series_upto_cutoff
from .turbidity_gap_report import FLOOD_WINDOW_END, FLOOD_WINDOW_START
from .turbidity_state_monitoring import (
    ALERT_TIERS,
    GAP_TIERS,
    MODEL_VERSION,
    _alert_tier_at,
    is_gap_tier,
    is_quality_alert_tier,
    label_alert_tier,
    load_features,
    tier_is_anomaly,
)

DEFAULT_SITE_NO = "12117500"
DEFAULT_FEATURES_CSV = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "features_12117500_63680_openmeteo_upstream_2022.csv"
)
DEFAULT_THRESHOLDS_JSON = (
    Path(__file__).resolve().parent.parent
    / "reports"
    / "turbidity_state"
    / "12117500_v2"
    / "state_thresholds.json"
)
DEFAULT_REPORT_DIR = (
    Path(__file__).resolve().parent.parent
    / "reports"
    / "turbidity_risk_forecast_12117500"
)
DEFAULT_HORIZONS = list(range(1, 13))
DEFAULT_RIDGE_ALPHA = 5.0
DEFAULT_HISTORY_WINDOW_HOURS = 1440
DEFAULT_HOLDOUT_STEP = 24

ExogMode = Literal["oracle", "persistence"]

TIER_RANK: dict[str, int] = {
    "NORMAL": 0,
    "WATCH": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}


def _parse_horizons(s: str | list[int]) -> list[int]:
    if isinstance(s, list):
        return [int(x) for x in s]
    s = str(s).strip()
    if s == "1-12":
        return list(range(1, 13))
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _feat_dim_no_temp(lag: int, *, has_upstream: bool) -> int:
    n_blocks = 3 if has_upstream else 2
    return n_blocks * int(lag)


def _exog_blocks_no_temp(
    y: pd.Series,
    prec: pd.Series,
    q_up: pd.Series | None,
    *,
    end_ix_y: int,
    end_ix_exog: int,
    lag: int,
) -> np.ndarray | None:
    """Concatenate lag blocks: y ends at ``end_ix_y``; precip/upstream at ``end_ix_exog``."""
    wy = _lag_matrix_block(y, end_ix_y, lag)
    wp = _lag_matrix_block(prec, end_ix_exog, lag)
    if wy is None or wp is None:
        return None
    parts = [wy, wp]
    if q_up is not None:
        wq = _lag_matrix_block(q_up, end_ix_exog, lag)
        if wq is None:
            return None
        parts.append(wq)
    return np.concatenate(parts, axis=0)


def _exog_end_ix(T: int, h: int, mode: ExogMode) -> int:
    if mode == "oracle":
        return int(T + h)
    return int(T)


def _tier_meta(thresholds: dict[str, Any]) -> dict[str, Any]:
    return thresholds.get("tier_rules") or {}


def tier_from_predicted_ntu(
    y_hat: float,
    y_anchor: float,
    thresholds: dict[str, Any],
) -> str:
    """Map predicted NTU at ``T+h`` to alert tier; diff vs anchor (y at cutoff ``T``)."""
    meta = _tier_meta(thresholds)
    diff = float(y_hat) - float(y_anchor)
    return _alert_tier_at(
        float(y_hat),
        diff,
        p75=float(meta["p75"]),
        p90=float(meta["p90"]),
        p95=float(meta["p95"]),
        p99=float(meta["p99"]),
        delta_watch=float(meta["delta_watch_1h"]),
        delta_high=float(meta["delta_high_1h"]),
        absolute_ntu_critical=float(meta["absolute_ntu_critical"]),
    )


def max_quality_tier(tiers: list[str]) -> str | None:
    """Highest WATCH/HIGH/CRITICAL among finite quality tiers; None if none."""
    best: str | None = None
    best_r = -1
    for t in tiers:
        if t not in TIER_RANK:
            continue
        r = TIER_RANK[t]
        if r > best_r:
            best_r = r
            best = t
    return best


def recommend_alert_from_max_tier(max_tier: str | None) -> bool:
    return max_tier is not None and is_quality_alert_tier(max_tier)


def _metrics_regression(pred: np.ndarray, actual: np.ndarray) -> dict[str, Any]:
    pred = pred.astype(float)
    actual = actual.astype(float)
    m = np.isfinite(pred) & np.isfinite(actual)
    if not m.any():
        return {"n": 0, "mae": None, "rmse": None}
    err = pred[m] - actual[m]
    return {
        "n": int(m.sum()),
        "mae": round(float(np.mean(np.abs(err))), 6),
        "rmse": round(float(np.sqrt(np.mean(err**2))), 6),
    }


def _tier_accuracy(pred_tiers: list[str], actual_tiers: list[str]) -> dict[str, Any]:
    n = 0
    match = 0
    by_actual: dict[str, dict[str, int]] = {t: {} for t in ALERT_TIERS}
    for p, a in zip(pred_tiers, actual_tiers, strict=True):
        if is_gap_tier(a):
            continue
        n += 1
        if p == a:
            match += 1
        by_actual.setdefault(a, {})
        by_actual[a][p] = by_actual[a].get(p, 0) + 1
    return {
        "n_finite_actual": n,
        "accuracy": round(match / n, 6) if n else None,
        "confusion_on_finite_actual": by_actual,
    }


def _alert_contingency(pred_alert: np.ndarray, actual_alert: np.ndarray) -> dict[str, Any]:
    pa = pred_alert.astype(bool)
    aa = actual_alert.astype(bool)
    tp = int((pa & aa).sum())
    fp = int((pa & ~aa).sum())
    fn = int((~pa & aa).sum())
    tn = int((~pa & ~aa).sum())
    n = int(len(pa))
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * prec * rec / (prec + rec)) if prec is not None and rec is not None and (prec + rec) else None
    return {
        "n": n,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(prec, 6) if prec is not None else None,
        "recall": round(rec, 6) if rec is not None else None,
        "f1": round(f1, 6) if f1 is not None else None,
        "pred_alert_rate": round(float(pa.mean()), 6) if n else None,
        "actual_alert_rate": round(float(aa.mean()), 6) if n else None,
    }


def walk_forward_direct_ridge_risk(
    y: pd.Series,
    prec: pd.Series,
    q_up: pd.Series | None,
    horizon: int,
    *,
    exog_mode: ExogMode,
    lag: int,
    step: int,
    split_ix: int,
    ridge_alpha: float,
    history_window_hours: int,
    holdout_only: bool = True,
) -> dict[str, Any]:
    """
    Walk-forward Ridge direct model for one horizon; optional holdout-only cutoffs.

    Returns arrays keyed by cutoff index with predictions and tier labels.
    """
    h = int(horizon)
    step = max(1, int(step))
    n = len(y)
    lag_full = _effective_lag(n, MAX_LAG)
    lag = int(min(lag, lag_full))
    has_q = q_up is not None
    idx_start = max(MIN_HOURLY_POINTS - 1, lag_full)
    records: list[dict[str, Any]] = []
    skipped = 0

    for idx_T in range(idx_start, n - h, step):
        if holdout_only and idx_T < int(split_ix):
            continue
        if pd.isna(y.iloc[idx_T + h]):
            skipped += 1
            continue
        sub_y, loc = slice_series_upto_cutoff(y, idx_T, history_window_hours)
        if loc < 0:
            skipped += 1
            continue
        lag_loc = int(min(lag, _effective_lag(len(sub_y), MAX_LAG)))
        feat_dim = _feat_dim_no_temp(lag_loc, has_upstream=has_q)
        rows_x: list[np.ndarray] = []
        rows_yy: list[float] = []
        for o in range(lag_loc - 1, loc - h + 1):
            g = idx_T - loc + o
            row = _exog_blocks_no_temp(
                y,
                prec,
                q_up,
                end_ix_y=g,
                end_ix_exog=g,
                lag=lag_loc,
            )
            if row is None:
                continue
            if pd.isna(y.iloc[g + h]):
                continue
            rows_x.append(row)
            rows_yy.append(float(y.iloc[g + h]))
        if len(rows_yy) < 20:
            skipped += 1
            continue
        exog_end = _exog_end_ix(idx_T, h, exog_mode)
        x_row = _exog_blocks_no_temp(
            y,
            prec,
            q_up,
            end_ix_y=idx_T,
            end_ix_exog=exog_end,
            lag=lag_loc,
        )
        if x_row is None:
            skipped += 1
            continue
        X = np.stack(rows_x, axis=0)
        if X.shape[1] != feat_dim:
            skipped += 1
            continue
        try:
            model = Ridge(alpha=float(ridge_alpha))
            model.fit(X, np.asarray(rows_yy, dtype=float))
            y_hat = float(model.predict(x_row.reshape(1, -1))[0])
        except ValueError:
            skipped += 1
            continue
        y_act = float(y.iloc[idx_T + h])
        y_anchor = float(y.iloc[idx_T]) if np.isfinite(y.iloc[idx_T]) else np.nan
        records.append(
            {
                "cutoff_ix": int(idx_T),
                "cutoff_utc": str(y.index[idx_T]),
                "target_ix": int(idx_T + h),
                "horizon": h,
                "y_hat": y_hat,
                "y_actual": y_act,
                "y_anchor": y_anchor,
            }
        )

    return {"horizon": h, "records": records, "skipped": skipped, "exog_mode": exog_mode}


def _aggregate_per_horizon(
    records: list[dict[str, Any]],
    actual_tiers: pd.Series,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    pred_tiers: list[str] = []
    act_tiers: list[str] = []
    y_hat: list[float] = []
    y_act: list[float] = []
    for r in records:
        anchor = r["y_anchor"]
        if not np.isfinite(anchor):
            continue
        pt = tier_from_predicted_ntu(r["y_hat"], anchor, thresholds)
        ti = int(r["target_ix"])
        at = str(actual_tiers.iloc[ti])
        pred_tiers.append(pt)
        act_tiers.append(at)
        y_hat.append(float(r["y_hat"]))
        y_act.append(float(r["y_actual"]))
    reg = _metrics_regression(np.asarray(y_hat), np.asarray(y_act))
    tier_m = _tier_accuracy(pred_tiers, act_tiers)
    alert_c = _alert_contingency(
        np.asarray([tier_is_anomaly(t) for t in pred_tiers]),
        np.asarray([tier_is_anomaly(t) for t in act_tiers]),
    )
    return {
        "regression": reg,
        "tier": tier_m,
        "alert_tier_match": alert_c,
        "n_records": len(records),
    }


def _window_metrics_by_cutoff(
    per_h_records: dict[int, list[dict[str, Any]]],
    actual_tiers: pd.Series,
    thresholds: dict[str, Any],
    horizons: list[int],
) -> dict[str, Any]:
    """Max tier over horizons 1..12 and recommend_alert at each cutoff."""
    by_T: dict[int, dict[int, dict[str, Any]]] = {}
    for h, recs in per_h_records.items():
        for r in recs:
            T = int(r["cutoff_ix"])
            by_T.setdefault(T, {})[h] = r

    pred_max_tiers: list[str | None] = []
    act_max_tiers: list[str | None] = []
    pred_alert: list[bool] = []
    act_alert: list[bool] = []
    cutoffs_used = 0

    for T, hmap in sorted(by_T.items()):
        if len(hmap) < len(horizons):
            continue
        anchor = hmap[min(hmap.keys())]["y_anchor"]
        if not np.isfinite(anchor):
            continue
        pred_t_list: list[str] = []
        act_t_list: list[str] = []
        for h in horizons:
            r = hmap[h]
            pred_t_list.append(tier_from_predicted_ntu(r["y_hat"], anchor, thresholds))
            act_t_list.append(str(actual_tiers.iloc[int(r["target_ix"])]))
        pm = max_quality_tier(pred_t_list)
        am = max_quality_tier([t for t in act_t_list if not is_gap_tier(t)])
        pred_max_tiers.append(pm or "NORMAL")
        act_max_tiers.append(am or "NORMAL")
        pred_alert.append(recommend_alert_from_max_tier(pm))
        act_alert.append(recommend_alert_from_max_tier(am))
        cutoffs_used += 1

    return {
        "n_cutoffs": cutoffs_used,
        "recommend_alert": _alert_contingency(np.asarray(pred_alert), np.asarray(act_alert)),
        "max_tier_exact_match_rate": round(
            float(np.mean([p == a for p, a in zip(pred_max_tiers, act_max_tiers, strict=True)])),
            6,
        )
        if cutoffs_used
        else None,
    }


def _persistence_baseline_per_horizon(
    records_template: list[dict[str, Any]],
    actual_tiers: pd.Series,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """y_hat[t+h] = y[t] persistence; tiers from frozen rules."""
    pred_tiers: list[str] = []
    act_tiers: list[str] = []
    y_hat: list[float] = []
    y_act: list[float] = []
    for r in records_template:
        anchor = r["y_anchor"]
        if not np.isfinite(anchor):
            continue
        y_hat_val = float(anchor)
        ti = int(r["target_ix"])
        pt = tier_from_predicted_ntu(y_hat_val, anchor, thresholds)
        at = str(actual_tiers.iloc[ti])
        pred_tiers.append(pt)
        act_tiers.append(at)
        y_hat.append(y_hat_val)
        y_act.append(float(r["y_actual"]))
    return {
        "regression": _metrics_regression(np.asarray(y_hat), np.asarray(y_act)),
        "tier": _tier_accuracy(pred_tiers, act_tiers),
        "alert_tier_match": _alert_contingency(
            np.asarray([tier_is_anomaly(t) for t in pred_tiers]),
            np.asarray([tier_is_anomaly(t) for t in act_tiers]),
        ),
    }


def _flood_window_lead_times(
    per_h_records: dict[int, list[dict[str, Any]]],
    y: pd.Series,
    actual_tiers: pd.Series,
    thresholds: dict[str, Any],
    horizons: list[int],
    *,
    exog_mode: ExogMode,
) -> dict[str, Any]:
    """Lead hours from first recommend_alert cutoff to y peak in Dec 2025 flood window."""
    start = FLOOD_WINDOW_START
    end = FLOOD_WINDOW_END
    win_mask = (y.index >= start) & (y.index <= end)
    y_win = y[win_mask]
    y_num = pd.to_numeric(y_win, errors="coerce")
    valid = y_num[np.isfinite(y_num)]
    if valid.empty:
        return {"error": "no_valid_y_in_flood_window"}
    peak_t = valid.idxmax()
    peak_ix = int(y.index.get_loc(peak_t))

    by_T: dict[int, dict[int, dict[str, Any]]] = {}
    for h, recs in per_h_records.items():
        for r in recs:
            T = int(r["cutoff_ix"])
            if T >= peak_ix:
                continue
            t_cut = y.index[T]
            if t_cut < start or t_cut > end:
                continue
            by_T.setdefault(T, {})[h] = r

    def _first_alert_cutoff(use_pred: bool) -> int | None:
        for T in sorted(by_T.keys()):
            hmap = by_T[T]
            if len(hmap) < len(horizons):
                continue
            anchor = hmap[min(hmap.keys())]["y_anchor"]
            if not np.isfinite(anchor):
                continue
            if use_pred:
                tiers = [
                    tier_from_predicted_ntu(hmap[h]["y_hat"], anchor, thresholds) for h in horizons
                ]
                pm = max_quality_tier(tiers)
                if not recommend_alert_from_max_tier(pm):
                    continue
            else:
                act_ts = [str(actual_tiers.iloc[int(hmap[h]["target_ix"])]) for h in horizons]
                am = max_quality_tier([t for t in act_ts if not is_gap_tier(t)])
                if not recommend_alert_from_max_tier(am):
                    continue
            return T
        return None

    pred_T = _first_alert_cutoff(True)
    act_T = _first_alert_cutoff(False)
    out: dict[str, Any] = {
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "y_peak_utc": str(peak_t),
        "y_peak": round(float(valid.max()), 6),
        "exog_mode": exog_mode,
    }
    if pred_T is not None:
        out["predicted_first_alert_cutoff_utc"] = str(y.index[pred_T])
        out["predicted_lead_hours_to_peak"] = int(peak_ix - pred_T)
    else:
        out["predicted_first_alert_cutoff_utc"] = None
        out["predicted_lead_hours_to_peak"] = None
    if act_T is not None:
        out["actual_first_alert_cutoff_utc"] = str(y.index[act_T])
        out["actual_lead_hours_to_peak"] = int(peak_ix - act_T)
    else:
        out["actual_first_alert_cutoff_utc"] = None
        out["actual_lead_hours_to_peak"] = None
    return out


def format_risk_forecast_md(result: dict[str, Any]) -> str:
    lines = [
        "# Turbidity 12h risk forecast holdout backtest",
        "",
        f"- Site: `{result.get('site_no')}`",
        f"- Thresholds: `{result.get('thresholds_path')}` (model `{result.get('tier_model_version')}`)",
        f"- Features: `{result.get('features_csv')}`",
        f"- Holdout: {result.get('holdout_start_utc')} → {result.get('holdout_end_utc')}",
        f"- Walk-forward step (holdout): **{result.get('holdout_step')}**",
        f"- Ridge alpha: {result.get('ridge_alpha')}",
        "",
        "## recommend_alert (max tier in 1–12h ≥ WATCH)",
        "",
        "| Exog mode | Precision | Recall | F1 | Pred alert rate |",
        "|-----------|----------:|-------:|---:|----------------:|",
    ]
    for mode in ("oracle", "persistence"):
        block = (result.get("by_exog_mode") or {}).get(mode, {})
        w = block.get("window_1_12h") or {}
        ra = w.get("recommend_alert") or {}
        lines.append(
            f"| {mode} | {ra.get('precision')} | {ra.get('recall')} | {ra.get('f1')} | {ra.get('pred_alert_rate')} |"
        )
    lines.extend(["", "## Per-horizon tier accuracy (oracle exog)", ""])
    oracle = (result.get("by_exog_mode") or {}).get("oracle", {})
    ph = oracle.get("per_horizon") or {}
    lines.append("| h | Tier accuracy | MAE (63680) | n |")
    lines.append("|--:|--------------:|------------:|--:|")
    for h in sorted(ph.keys(), key=lambda x: int(x)):
        row = ph[str(h)] if str(h) in ph else ph.get(h, {})
        tier = row.get("tier") or {}
        reg = row.get("regression") or {}
        lines.append(
            f"| {h} | {tier.get('accuracy')} | {reg.get('mae')} | {tier.get('n_finite_actual')} |"
        )
    lines.extend(["", "## Baselines (oracle exog context)", ""])
    bl = oracle.get("baselines") or {}
    pers = (bl.get("persistence_y") or {}).get("window_1_12h", {}).get("recommend_alert", {})
    lines.append(f"- Persistence y, recommend_alert F1: {pers.get('f1')}")
    lines.append("")
    lines.append("## Flood window 2025-12-09 → 2025-12-17")
    for mode in ("oracle", "persistence"):
        fw = ((result.get("by_exog_mode") or {}).get(mode) or {}).get("flood_window") or {}
        lines.append(
            f"- **{mode}**: predicted lead h={fw.get('predicted_lead_hours_to_peak')}, "
            f"actual lead h={fw.get('actual_lead_hours_to_peak')}, peak={fw.get('y_peak')} NTU"
        )
    return "\n".join(lines) + "\n"


def run_risk_forecast_backtest(
    *,
    features_csv: Path,
    thresholds_json: Path,
    report_dir: Path,
    horizons: list[int] | str = "1-12",
    holdout_step: int = DEFAULT_HOLDOUT_STEP,
    ridge_alpha: float = DEFAULT_RIDGE_ALPHA,
    history_window_hours: int = DEFAULT_HISTORY_WINDOW_HOURS,
    lag: int | None = None,
    write_md: bool = True,
) -> dict[str, Any]:
    """Run full Phase A backtest and write JSON (+ optional MD) under ``report_dir``."""
    csv_path = Path(features_csv)
    thr_path = Path(thresholds_json)
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not csv_path.is_file():
        raise FileNotFoundError(f"features CSV not found: {csv_path}")
    if not thr_path.is_file():
        raise FileNotFoundError(f"thresholds JSON not found: {thr_path}")

    thresholds = json.loads(thr_path.read_text(encoding="utf-8"))
    df = load_features(csv_path, use_exog_ffill=True)
    y = df["63680"]
    prec = df["precipitation_mm"]
    q_up = df[UPSTREAM_DISCHARGE_COL] if UPSTREAM_DISCHARGE_COL in df.columns else None

    hz = _parse_horizons(horizons)
    max_h = max(hz)
    n = len(y)

    if "split_index" in thresholds:
        split_ix = int(thresholds["split_index"])
    else:
        split_info = _split_index_for_holdout(
            n,
            max_h,
            holdout_fraction=0.2,
            holdout_min_hours=336,
            min_tuning_hours=2000,
        )
        split_ix = int(split_info["split_index"])

    holdout_mask = y.index >= y.index[split_ix]
    lag_eff = int(lag) if lag is not None else int(min(_effective_lag(n, MAX_LAG), MAX_LAG))

    actual_tiers = label_alert_tier(y, thresholds)

    by_mode: dict[str, Any] = {}
    for mode in ("oracle", "persistence"):
        per_h_records: dict[int, list[dict[str, Any]]] = {}
        per_h_metrics: dict[str, Any] = {}
        skipped_map: dict[str, int] = {}
        for h in hz:
            wf = walk_forward_direct_ridge_risk(
                y,
                prec,
                q_up,
                h,
                exog_mode=mode,  # type: ignore[arg-type]
                lag=lag_eff,
                step=holdout_step,
                split_ix=split_ix,
                ridge_alpha=ridge_alpha,
                history_window_hours=history_window_hours,
                holdout_only=True,
            )
            recs = wf["records"]
            per_h_records[h] = recs
            per_h_metrics[str(h)] = _aggregate_per_horizon(recs, actual_tiers, thresholds)
            skipped_map[str(h)] = int(wf["skipped"])

        window_block = _window_metrics_by_cutoff(per_h_records, actual_tiers, thresholds, hz)
        pers_h: dict[str, Any] = {}
        for h in hz:
            pers_h[str(h)] = _persistence_baseline_per_horizon(
                per_h_records[h], actual_tiers, thresholds
            )
        pers_window = _window_metrics_by_cutoff(
            {
                h: [
                    {**r, "y_hat": r["y_anchor"]}
                    for r in per_h_records[h]
                    if np.isfinite(r.get("y_anchor", np.nan))
                ]
                for h in hz
            },
            actual_tiers,
            thresholds,
            hz,
        )

        by_mode[mode] = {
            "per_horizon": per_h_metrics,
            "window_1_12h": window_block,
            "skipped_by_horizon": skipped_map,
            "baselines": {
                "persistence_y": {
                    "per_horizon": pers_h,
                    "window_1_12h": pers_window,
                },
            },
            "flood_window": _flood_window_lead_times(
                per_h_records,
                y,
                actual_tiers,
                thresholds,
                hz,
                exog_mode=mode,  # type: ignore[arg-type]
            ),
        }

    result: dict[str, Any] = {
        "spec": "turbidity_risk_forecast_holdout_phase_a",
        "site_no": thresholds.get("site_no", DEFAULT_SITE_NO),
        "tier_model_version": thresholds.get("model_version", MODEL_VERSION),
        "features_csv": str(csv_path.resolve()),
        "thresholds_path": str(thr_path.resolve()),
        "split_index": split_ix,
        "split_time_utc": str(y.index[split_ix]),
        "holdout_start_utc": str(y.index[split_ix]),
        "holdout_end_utc": str(y.index[-1]),
        "holdout_hours": int(holdout_mask.sum()),
        "holdout_step": int(holdout_step),
        "horizons": hz,
        "ridge_alpha": float(ridge_alpha),
        "lag": lag_eff,
        "history_window_hours": int(history_window_hours),
        "exog_columns": ["precipitation_mm"]
        + ([UPSTREAM_DISCHARGE_COL] if q_up is not None else []),
        "tier_rules_frozen": _tier_meta(thresholds),
        "recommend_alert_definition": "max(predicted tier over h=1..12) is WATCH, HIGH, or CRITICAL",
        "by_exog_mode": by_mode,
    }

    json_path = out_dir / "risk_forecast_holdout.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if write_md:
        md_path = out_dir / "risk_forecast_holdout.md"
        md_path.write_text(format_risk_forecast_md(result), encoding="utf-8")
    result["outputs"] = {"json": str(json_path), "md": str(out_dir / "risk_forecast_holdout.md") if write_md else None}
    return result

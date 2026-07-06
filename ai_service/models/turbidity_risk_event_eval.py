"""
Event-window metrics for 12h turbidity risk classification (site 12117500).

Reports TP/FP/FN/TN counts plus precision/recall/F1 on holdout subsets:
full holdout, tier-upgrade events, no-upgrade cutoffs, flood window, and optional
y-rise events (12h turbidity delta above ``delta_up_1h``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .backtest_turbidity_exog_ridge_lgbm import UPSTREAM_DISCHARGE_COL, _split_index_for_holdout
from .forecast_engine import MAX_LAG, MIN_HOURLY_POINTS, _effective_lag
from .turbidity_gap_report import FLOOD_WINDOW_END, FLOOD_WINDOW_START
from .turbidity_risk_class_backtest import (
    DEFAULT_ALERT_PROBA_THRESHOLD,
    DEFAULT_FEATURES_CSV,
    DEFAULT_FP_GUARDRAIL_RATIO,
    DEFAULT_HOLDOUT_STEP,
    DEFAULT_LAG,
    DEFAULT_MIN_VALID_FUTURE_HOURS,
    DEFAULT_REPORT_DIR,
    DEFAULT_THRESHOLDS_JSON,
    MAX_FUTURE_H,
    ML_TUNABLE_KEYS,
    _alert_metrics,
    _fit_ml_bundle,
    _predict_baseline,
    _predict_ml_alert_proba,
    alert_proba_to_binary,
    build_exog_policy,
    build_labeled_cutoffs,
    is_tier_upgrade_event,
    tune_ml_alert_thresholds,
)
from .turbidity_risk_features import (
    IfScoreCache,
    build_multivar_matrix_from_df,
    warm_if_cache,
)
from .turbidity_risk_forecast_backtest import _alert_contingency
from .turbidity_state_monitoring import (
    MODEL_VERSION,
    label_alert_tier,
    load_features,
)

EVENT_OUTPUT_BASENAME = "risk_class_event_metrics"
FOCUS_MODELS: tuple[str, ...] = ("persistence_alert", "logistic_regression", "lightgbm")

PopulationKey = str
PopulationFilter = Callable[[dict[str, Any], pd.Series], bool]


def _delta_up_1h_from_thresholds(thresholds: dict[str, Any]) -> float:
    rules = thresholds.get("tier_rules") or {}
    for key in ("delta_up_1h", "delta_up_1h_ntu"):
        if key in rules:
            return float(rules[key])
    if "delta_up_1h" in thresholds:
        return float(thresholds["delta_up_1h"])
    return 0.1


def max_future_y_delta(y: pd.Series, idx_T: int, *, max_h: int = MAX_FUTURE_H) -> float | None:
    """Max y[T+1..T+max_h] minus y[T] over finite future hours."""
    y0 = float(y.iloc[idx_T])
    if not np.isfinite(y0):
        return None
    h_end = min(int(max_h), len(y) - 1 - idx_T)
    deltas: list[float] = []
    for h in range(1, h_end + 1):
        yh = float(y.iloc[idx_T + h])
        if np.isfinite(yh):
            deltas.append(yh - y0)
    if not deltas:
        return None
    return float(max(deltas))


def is_y_rise_event(
    row: dict[str, Any],
    y: pd.Series,
    *,
    delta_up_1h: float,
) -> bool:
    """NORMAL at T with 12h max turbidity rise >= ``delta_up_1h`` (rising signal)."""
    if str(row.get("tier_at_T")) != "NORMAL":
        return False
    dmax = max_future_y_delta(y, int(row["cutoff_ix"]))
    if dmax is None:
        return False
    return dmax >= float(delta_up_1h)


def is_flood_window_cutoff(row: dict[str, Any]) -> bool:
    t = pd.Timestamp(row["cutoff_utc"])
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return bool(FLOOD_WINDOW_START <= t <= FLOOD_WINDOW_END)


def is_no_upgrade_cutoff(row: dict[str, Any]) -> bool:
    return int(row.get("alert_12h", 0)) == 0


def population_filters(
    y: pd.Series,
    *,
    delta_up_1h: float,
) -> dict[PopulationKey, PopulationFilter]:
    return {
        "full_holdout": lambda _r, _y: True,
        "tier_upgrade_events": lambda r, _y: is_tier_upgrade_event(r),
        "no_upgrade_12h": lambda r, _y: is_no_upgrade_cutoff(r),
        "flood_window": lambda r, _y: is_flood_window_cutoff(r),
        "y_rise_12h": lambda r, ys: is_y_rise_event(r, ys, delta_up_1h=delta_up_1h),
    }


def population_definitions(*, delta_up_1h: float) -> dict[str, str]:
    return {
        "full_holdout": "All labeled holdout cutoffs at holdout step",
        "tier_upgrade_events": (
            "NORMAL at T with WATCH+ in T+1..T+12 (same as lead-time upgrade events)"
        ),
        "no_upgrade_12h": "alert_12h=0 — no WATCH+ in next 12h (FP guardrail population)",
        "flood_window": (
            f"Cutoff UTC in [{FLOOD_WINDOW_START.date()} .. {FLOOD_WINDOW_END.date()}]"
        ),
        "y_rise_12h": (
            f"NORMAL at T with max(y[T+1..T+12]) - y[T] >= {delta_up_1h} NTU"
        ),
    }


def filter_rows(
    rows: list[dict[str, Any]],
    pred: np.ndarray,
    population: PopulationKey,
    y: pd.Series,
    filters: dict[PopulationKey, PopulationFilter],
) -> tuple[list[dict[str, Any]], np.ndarray]:
    fn = filters[population]
    sub_rows: list[dict[str, Any]] = []
    sub_pred: list[int] = []
    for r, p in zip(rows, pred, strict=True):
        if fn(r, y):
            sub_rows.append(r)
            sub_pred.append(int(p))
    return sub_rows, np.asarray(sub_pred, dtype=int)


def metrics_for_population(
    rows: list[dict[str, Any]],
    alert_pred: np.ndarray,
) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "tn": 0,
            "precision": None,
            "recall": None,
            "f1": None,
            "pred_alert_rate": None,
            "actual_alert_rate": None,
        }
    y_true = np.asarray([int(r["alert_12h"]) for r in rows], dtype=int)
    return _alert_contingency(alert_pred, y_true)


def evaluate_model_variants_on_populations(
    holdout_rows: list[dict[str, Any]],
    y: pd.Series,
    *,
    filters: dict[PopulationKey, PopulationFilter],
    persistence_pred: np.ndarray,
    ml_proba: dict[str, np.ndarray | None],
    tuned_thresholds: dict[str, float],
) -> dict[str, Any]:
    """Score focus models (persistence + ML default/tuned) per population."""
    variants: list[tuple[str, str, np.ndarray]] = [
        ("persistence_alert", "default", persistence_pred),
    ]
    for mk in ML_TUNABLE_KEYS:
        proba = ml_proba.get(mk)
        if proba is None:
            continue
        variants.append(
            (
                mk,
                "default_threshold_0.5",
                alert_proba_to_binary(proba, DEFAULT_ALERT_PROBA_THRESHOLD),
            )
        )
        tau = tuned_thresholds.get(mk, DEFAULT_ALERT_PROBA_THRESHOLD)
        variants.append(
            (mk, f"tuned_threshold_{tau}", alert_proba_to_binary(proba, tau)),
        )

    by_variant: dict[str, Any] = {}
    for model_key, threshold_mode, pred in variants:
        variant_id = (
            model_key
            if threshold_mode == "default" and model_key == "persistence_alert"
            else f"{model_key}__{threshold_mode}"
        )
        by_pop: dict[str, Any] = {}
        for pop_key in filters:
            sub_rows, sub_pred = filter_rows(holdout_rows, pred, pop_key, y, filters)
            by_pop[pop_key] = {
                "n_cutoffs": len(sub_rows),
                "alert_12h": metrics_for_population(sub_rows, sub_pred),
            }
        by_variant[variant_id] = {
            "model": model_key,
            "threshold_mode": threshold_mode,
            "alert_proba_threshold": (
                tuned_thresholds.get(model_key)
                if threshold_mode.startswith("tuned")
                else (
                    DEFAULT_ALERT_PROBA_THRESHOLD
                    if model_key in ML_TUNABLE_KEYS
                    else None
                )
            ),
            "by_population": by_pop,
        }
    return by_variant


def format_event_metrics_md(result: dict[str, Any]) -> str:
    lines = [
        "# Turbidity 12h risk — event-window classification metrics",
        "",
        f"- Site: `{result.get('site_no')}`",
        f"- Holdout: {result.get('holdout_start_utc')} → {result.get('holdout_end_utc')}",
        f"- Holdout step: **{result.get('holdout_step')}**",
        f"- Holdout labeled cutoffs: **{result.get('n_holdout_labeled_cutoffs')}**",
        "",
        "## Evaluation contract",
        "",
        "- **Rising / upgrade events** (`tier_upgrade_events`, `y_rise_12h`): primary = "
        "**recall** and **FN count** (missed alerts at event-defining cutoffs).",
        "- **No-upgrade cutoffs** (`no_upgrade_12h`): guardrail = **FP count** and **FP rate**.",
        "- **Flood window**: operational stress test on Dec 2025 flood cutoffs.",
        "",
        "## Populations",
        "",
    ]
    for k, desc in (result.get("population_definitions") or {}).items():
        lines.append(f"- **{k}**: {desc}")
    lines.extend(["", "## Metrics by model variant", ""])

    for variant_id, block in (result.get("by_model_variant") or {}).items():
        model = block.get("model")
        thr_mode = block.get("threshold_mode")
        tau = block.get("alert_proba_threshold")
        hdr = f"### {variant_id}"
        if tau is not None and thr_mode != "default":
            hdr += f" (τ={tau})"
        lines.extend(["", hdr, ""])
        for pop_key, pop_block in (block.get("by_population") or {}).items():
            m = pop_block.get("alert_12h") or {}
            lines.extend(
                [
                    f"#### {pop_key} (n={pop_block.get('n_cutoffs')})",
                    "",
                    "| TP | FP | FN | TN | Precision | Recall | F1 |",
                    "|---:|---:|---:|---:|----------:|-------:|---:|",
                    (
                        f"| {m.get('tp')} | {m.get('fp')} | {m.get('fn')} | {m.get('tn')} | "
                        f"{m.get('precision')} | {m.get('recall')} | {m.get('f1')} |"
                    ),
                    "",
                ]
            )
    return "\n".join(lines) + "\n"


def run_event_metrics_eval(
    *,
    features_csv: Path,
    thresholds_json: Path,
    report_dir: Path,
    holdout_step: int = DEFAULT_HOLDOUT_STEP,
    lag: int = DEFAULT_LAG,
    min_valid_future_hours: int = DEFAULT_MIN_VALID_FUTURE_HOURS,
    use_exog_ffill: bool = True,
    use_precip_ffill: bool | None = None,
    use_upstream_ffill: bool | None = None,
    with_if_features: bool = False,
    tune_alert_threshold: bool = True,
    fp_guardrail_ratio: float = DEFAULT_FP_GUARDRAIL_RATIO,
    tuning_dense_step: int = 24,
    tuned_thresholds_json: Path | None = None,
    output_basename: str = EVENT_OUTPUT_BASENAME,
    write_md: bool = True,
) -> dict[str, Any]:
    """Train models, score holdout, and write per-population alert metrics."""
    csv_path = Path(features_csv)
    thr_path = Path(thresholds_json)
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    thresholds = json.loads(thr_path.read_text(encoding="utf-8"))
    precip_ffill = use_exog_ffill if use_precip_ffill is None else use_precip_ffill
    upstream_ffill = use_exog_ffill if use_upstream_ffill is None else use_upstream_ffill
    exog_policy = build_exog_policy(
        use_exog_ffill=bool(precip_ffill and upstream_ffill),
        use_precip_ffill=precip_ffill,
        use_upstream_ffill=upstream_ffill,
    )

    df = load_features(
        csv_path,
        use_exog_ffill=use_exog_ffill,
        use_precip_ffill=use_precip_ffill,
        use_upstream_ffill=use_upstream_ffill,
    )
    y = df["63680"]
    prec = df["precipitation_mm"]
    q_up = df[UPSTREAM_DISCHARGE_COL] if UPSTREAM_DISCHARGE_COL in df.columns else None
    n = len(y)
    split_ix = int(thresholds["split_index"]) if "split_index" in thresholds else int(
        _split_index_for_holdout(n, MAX_FUTURE_H)["split_index"]
    )
    lag_eff = int(min(lag, _effective_lag(n, MAX_LAG)))
    tiers = label_alert_tier(y, thresholds)
    delta_up = _delta_up_1h_from_thresholds(thresholds)
    pop_filters = population_filters(y, delta_up_1h=delta_up)

    if_cache: IfScoreCache | None = None
    if with_if_features:
        mvar = build_multivar_matrix_from_df(df)
        if_cache = IfScoreCache(
            y,
            multivar_matrix=mvar,
            with_univariate=True,
            with_multivariate=True,
        )

    train_step = max(int(holdout_step), 24) if with_if_features else 1

    def _build(idx_start: int, idx_end: int, step: int) -> list[dict[str, Any]]:
        if if_cache is not None:
            lag_full = _effective_lag(len(y), MAX_LAG)
            start = max(int(idx_start), lag_full - 1, MIN_HOURLY_POINTS - 1)
            end = min(int(idx_end), len(y) - MAX_FUTURE_H - 1)
            indices = list(range(start, end + 1, max(1, int(step))))
            warm_if_cache(
                if_cache,
                indices,
                with_univariate_if=True,
                with_multivariate_if=True,
                log_every=500,
            )
        return build_labeled_cutoffs(
            y,
            prec,
            q_up,
            tiers,
            lag=lag_eff,
            min_valid_future_hours=min_valid_future_hours,
            idx_start=idx_start,
            idx_end=idx_end,
            step=step,
            if_cache=if_cache,
            with_extended_features=True,
            with_univariate_if=with_if_features,
            with_multivariate_if=with_if_features,
        )

    train_rows = _build(0, split_ix - 1, train_step)
    holdout_rows = _build(split_ix, n - 1, holdout_step)
    tuning_rows_dense: list[dict[str, Any]] = []
    if tune_alert_threshold:
        tuning_rows_dense = _build(0, split_ix - 1, max(1, int(tuning_dense_step)))

    ml_bundles = {mk: _fit_ml_bundle(mk, train_rows) for mk in ML_TUNABLE_KEYS}
    tuned_thresholds: dict[str, float] = {}
    if tuned_thresholds_json is not None and tuned_thresholds_json.is_file():
        prior = json.loads(tuned_thresholds_json.read_text(encoding="utf-8"))
        tuned_thresholds = dict(
            (prior.get("threshold_tuning_spec") or {}).get("selected_thresholds")
            or (prior.get("selected_thresholds") or {})
        )
    elif tune_alert_threshold and tuning_rows_dense:
        thr_tune = tune_ml_alert_thresholds(
            tiers,
            y,
            train_rows,
            tuning_rows_dense,
            fp_guardrail_ratio=fp_guardrail_ratio,
            if_cache=if_cache,
        )
        for mk in ML_TUNABLE_KEYS:
            block = (thr_tune.get("by_model") or {}).get(mk) or {}
            tuned_thresholds[mk] = float(
                block.get("selected_threshold", DEFAULT_ALERT_PROBA_THRESHOLD)
            )
    else:
        tuned_thresholds = {mk: DEFAULT_ALERT_PROBA_THRESHOLD for mk in ML_TUNABLE_KEYS}

    pers_pred, _, _ = _predict_baseline("persistence_alert", holdout_rows)
    ml_proba = {
        mk: _predict_ml_alert_proba(mk, ml_bundles.get(mk), holdout_rows)
        for mk in ML_TUNABLE_KEYS
    }

    by_variant = evaluate_model_variants_on_populations(
        holdout_rows,
        y,
        filters=pop_filters,
        persistence_pred=pers_pred,
        ml_proba=ml_proba,
        tuned_thresholds=tuned_thresholds,
    )

    pop_counts = {
        k: sum(1 for r in holdout_rows if fn(r, y))
        for k, fn in pop_filters.items()
    }

    result: dict[str, Any] = {
        "spec": "turbidity_risk_class_event_metrics",
        "site_no": thresholds.get("site_no", "12117500"),
        "tier_model_version": thresholds.get("model_version", MODEL_VERSION),
        "features_csv": str(csv_path.resolve()),
        "thresholds_path": str(thr_path.resolve()),
        "holdout_start_utc": str(y.index[split_ix]),
        "holdout_end_utc": str(y.index[-1]),
        "holdout_step": int(holdout_step),
        "lag": lag_eff,
        "exog_policy": exog_policy,
        "with_if_features": with_if_features,
        "n_holdout_labeled_cutoffs": len(holdout_rows),
        "population_counts": pop_counts,
        "population_definitions": population_definitions(delta_up_1h=delta_up),
        "evaluation_contract": {
            "rising_events_primary": ["recall", "fn"],
            "non_upgrade_guardrail": ["fp", "fp_rate"],
            "populations_for_rising": ["tier_upgrade_events", "y_rise_12h"],
            "populations_for_guardrail": ["no_upgrade_12h"],
        },
        "tuned_thresholds": tuned_thresholds,
        "tuned_thresholds_source": (
            str(tuned_thresholds_json.resolve())
            if tuned_thresholds_json and tuned_thresholds_json.is_file()
            else ("inline_tune" if tune_alert_threshold else "default_0.5")
        ),
        "model_variants_evaluated": list(by_variant.keys()),
        "by_model_variant": by_variant,
    }

    json_path = out_dir / f"{output_basename}.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    md_path = out_dir / f"{output_basename}.md"
    if write_md:
        md_path.write_text(format_event_metrics_md(result), encoding="utf-8")
    result["outputs"] = {"json": str(json_path), "md": str(md_path) if write_md else None}
    return result

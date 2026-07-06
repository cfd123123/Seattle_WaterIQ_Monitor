"""
R7a: 12h turbidity escalate risk backtest (site 12117500).

Only cutoffs where quality tier at T is NORMAL. Label ``escalate_12h`` is 1 when
WATCH+ appears in T+1..T+12 (same as ``alert_12h`` on the full population).
Persistence at NORMAL always predicts no escalate (recall 0 on escalate events).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .backtest_turbidity_exog_ridge_lgbm import (
    UPSTREAM_DISCHARGE_COL,
    _as_lgbm_frame,
    _split_index_for_holdout,
)
from .forecast_engine import MAX_LAG, _effective_lag
from .turbidity_gap_report import FLOOD_WINDOW_END, FLOOD_WINDOW_START
from .turbidity_risk_class_backtest import (
    DEFAULT_ALERT_PROBA_THRESHOLD,
    DEFAULT_FP_GUARDRAIL_RATIO,
    DEFAULT_HOLDOUT_STEP,
    DEFAULT_LAG,
    DEFAULT_MIN_VALID_FUTURE_HOURS,
    DEFAULT_THRESHOLD_GRID,
    ML_TUNABLE_KEYS,
    _alert_metrics,
    alert_proba_to_binary,
    build_exog_policy,
    build_labeled_cutoffs,
    evaluate_upgrade_lead_time,
    is_tier_upgrade_event,
)
from .turbidity_risk_event_eval import is_flood_window_cutoff
from .turbidity_risk_features import (
    IfScoreCache,
    build_multivar_matrix_from_df,
    extended_feature_dim,
    warm_if_cache,
)
from .turbidity_risk_forecast_backtest import (
    DEFAULT_FEATURES_CSV,
    DEFAULT_REPORT_DIR,
    DEFAULT_SITE_NO,
    DEFAULT_THRESHOLDS_JSON,
    _alert_contingency,
    _feat_dim_no_temp,
)
from .turbidity_state_monitoring import (
    MODEL_VERSION,
    is_gap_tier,
    label_alert_tier,
    load_features,
)

DEFAULT_FLOOD_SAMPLE_WEIGHT = 5.0
ESCALATE_OUTPUT_BASENAME = "risk_class_escalate_12h"

EscalateModelKey = Literal[
    "majority_never_escalate",
    "persistence_escalate",
    "logistic_regression",
    "lightgbm",
]

ESCALATE_MODEL_ORDER: tuple[EscalateModelKey, ...] = (
    "majority_never_escalate",
    "persistence_escalate",
    "logistic_regression",
    "lightgbm",
)

PopulationKey = Literal[
    "full_normal_holdout",
    "normal_escalate_events",
    "normal_no_escalate",
    "flood_window_normal",
]


def is_normal_quality_cutoff(row: dict[str, Any]) -> bool:
    """Quality tier NORMAL at T (non-gap)."""
    t = str(row.get("tier_at_T", ""))
    return t == "NORMAL" and not is_gap_tier(t)


def annotate_escalate_label(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy ``alert_12h`` to ``escalate_12h`` for NORMAL-only rows."""
    out: list[dict[str, Any]] = []
    for r in rows:
        if not is_normal_quality_cutoff(r):
            continue
        row = dict(r)
        row["escalate_12h"] = int(r.get("alert_12h", 0))
        out.append(row)
    return out


def filter_normal_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return annotate_escalate_label(rows)


def is_normal_escalate_event(row: dict[str, Any]) -> bool:
    return is_normal_quality_cutoff(row) and int(row.get("escalate_12h", 0)) == 1


def is_normal_no_escalate(row: dict[str, Any]) -> bool:
    return is_normal_quality_cutoff(row) and int(row.get("escalate_12h", 0)) == 0


def is_flood_window_normal(row: dict[str, Any]) -> bool:
    return is_normal_quality_cutoff(row) and is_flood_window_cutoff(row)


def population_filters() -> dict[PopulationKey, Any]:
    return {
        "full_normal_holdout": is_normal_quality_cutoff,
        "normal_escalate_events": is_normal_escalate_event,
        "normal_no_escalate": is_normal_no_escalate,
        "flood_window_normal": is_flood_window_normal,
    }


def population_definitions() -> dict[str, str]:
    return {
        "full_normal_holdout": "All NORMAL quality cutoffs on holdout (step=holdout_step)",
        "normal_escalate_events": (
            "NORMAL at T with WATCH+ in T+1..T+12 (escalate_12h=1; primary recall KPI)"
        ),
        "normal_no_escalate": (
            "NORMAL at T with no WATCH+ in T+1..T+12 (escalate_12h=0; FP guardrail)"
        ),
        "flood_window_normal": (
            f"NORMAL cutoffs with UTC in [{FLOOD_WINDOW_START.date()} .. "
            f"{FLOOD_WINDOW_END.date()}]"
        ),
    }


def tuning_sample_weights(
    rows: list[dict[str, Any]],
    *,
    flood_weight: float,
) -> np.ndarray:
    """
    Per-row training weight: ``flood_weight`` if flood-window cutoff or escalate_12h=1.
    """
    w = np.ones(len(rows), dtype=float)
    fw = float(flood_weight)
    for i, r in enumerate(rows):
        if int(r.get("escalate_12h", 0)) == 1 or is_flood_window_cutoff(r):
            w[i] = fw
    return w


def _false_positive_rate_escalate(
    rows: list[dict[str, Any]],
    pred: np.ndarray,
) -> dict[str, Any]:
    """FP rate when escalate_12h=0 (NORMAL, no WATCH+ in next 12h)."""
    y_true = np.asarray([int(r["escalate_12h"]) for r in rows], dtype=int)
    mask = y_true == 0
    n = int(mask.sum())
    if n == 0:
        return {"n": 0, "fp_rate": None, "fp": 0}
    fp = int((pred[mask] == 1).sum())
    return {"n": n, "fp": fp, "fp_rate": round(fp / n, 6)}


def metrics_for_population(
    rows: list[dict[str, Any]],
    pred: np.ndarray,
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
            "pred_escalate_rate": None,
            "actual_escalate_rate": None,
        }
    y_true = np.asarray([int(r["escalate_12h"]) for r in rows], dtype=int)
    out = _alert_contingency(pred, y_true)
    out["pred_escalate_rate"] = round(float((pred == 1).mean()), 6)
    out["actual_escalate_rate"] = round(float((y_true == 1).mean()), 6)
    return out


def evaluate_populations(
    holdout_rows: list[dict[str, Any]],
    pred: np.ndarray,
) -> dict[str, Any]:
    filters = population_filters()
    by_pop: dict[str, Any] = {}
    for key, fn in filters.items():
        sub_rows: list[dict[str, Any]] = []
        sub_pred: list[int] = []
        for r, p in zip(holdout_rows, pred, strict=True):
            if fn(r):
                sub_rows.append(r)
                sub_pred.append(int(p))
        by_pop[key] = metrics_for_population(
            sub_rows, np.asarray(sub_pred, dtype=int)
        )
    return by_pop


def _predict_escalate_baseline(
    model_key: EscalateModelKey,
    rows: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray | None]:
    """Baselines: always 0 (persistence_escalate / majority_never_escalate)."""
    n = len(rows)
    zeros = np.zeros(n, dtype=int)
    if model_key in ("majority_never_escalate", "persistence_escalate"):
        return zeros, None
    raise ValueError(f"not a baseline model: {model_key}")


def _fit_logistic_weighted(
    X: np.ndarray,
    y: np.ndarray,
    sample_weight: np.ndarray | None,
) -> tuple[Any, Any]:
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    clf = LogisticRegression(class_weight="balanced", max_iter=2000, random_state=42)
    if sample_weight is not None:
        clf.fit(Xs, y, sample_weight=sample_weight)
    else:
        clf.fit(Xs, y)
    return scaler, clf


def _fit_lightgbm_weighted(
    X: np.ndarray,
    y: np.ndarray,
    sample_weight: np.ndarray | None,
) -> LGBMClassifier:
    clf = LGBMClassifier(
        objective="binary",
        class_weight="balanced",
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=-1,
    )
    Xf = _as_lgbm_frame(X)
    if sample_weight is not None:
        clf.fit(Xf, y, sample_weight=sample_weight)
    else:
        clf.fit(Xf, y)
    return clf


def _fit_escalate_ml(
    model_key: EscalateModelKey,
    train_rows: list[dict[str, Any]],
    *,
    sample_weight: np.ndarray | None = None,
) -> Any | None:
    if model_key not in ML_TUNABLE_KEYS:
        raise ValueError(f"not an ML model: {model_key}")
    X = np.stack([r["features"] for r in train_rows], axis=0)
    y = np.asarray([r["escalate_12h"] for r in train_rows], dtype=int)
    if len(train_rows) < 30 or len(np.unique(y)) < 2:
        return None
    if model_key == "logistic_regression":
        return _fit_logistic_weighted(X, y, sample_weight)
    return _fit_lightgbm_weighted(X, y, sample_weight)


def _predict_escalate_ml_proba(
    model_key: EscalateModelKey,
    bundle: Any,
    eval_rows: list[dict[str, Any]],
) -> np.ndarray | None:
    if bundle is None or not eval_rows:
        return None
    X = np.stack([r["features"] for r in eval_rows], axis=0)
    if model_key == "logistic_regression":
        scaler, clf = bundle
        proba = clf.predict_proba(scaler.transform(X))[:, 1]
        return proba
    clf: LGBMClassifier = bundle
    proba = clf.predict_proba(_as_lgbm_frame(X))
    return proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]


def sweep_escalate_threshold(
    rows: list[dict[str, Any]],
    escalate_proba: np.ndarray,
    *,
    model_key: str,
    persistence_fp_rate: float | None,
    fp_guardrail_ratio: float,
    threshold_grid: tuple[float, ...] = DEFAULT_THRESHOLD_GRID,
) -> dict[str, Any]:
    """
    Select τ on tuning NORMAL cutoffs: maximize recall subject to
    FP(no escalate) <= persistence_fp * fp_guardrail_ratio.
    """
    pers_pred = np.zeros(len(rows), dtype=int)
    pers_fp = _false_positive_rate_escalate(rows, pers_pred)
    pers_fp_rate = pers_fp.get("fp_rate")
    if persistence_fp_rate is not None:
        pers_fp_rate = float(persistence_fp_rate)
    fp_cap = (
        float(pers_fp_rate) * float(fp_guardrail_ratio)
        if pers_fp_rate is not None
        else None
    )

    y_true = np.asarray([int(r["escalate_12h"]) for r in rows], dtype=int)
    n_pos = int((y_true == 1).sum())

    sweep: list[dict[str, Any]] = []
    for thr in threshold_grid:
        pred = alert_proba_to_binary(escalate_proba, thr)
        fp_block = _false_positive_rate_escalate(rows, pred)
        fp_rate = fp_block.get("fp_rate")
        meets_fp = fp_cap is None or (
            fp_rate is not None and float(fp_rate) <= float(fp_cap) + 1e-12
        )
        pop = metrics_for_population(rows, pred)
        esc_mask = np.asarray(
            [is_normal_escalate_event(r) for r in rows], dtype=bool
        )
        recall_esc = None
        if n_pos and esc_mask.any():
            recall_esc = metrics_for_population(
                [rows[i] for i in range(len(rows)) if esc_mask[i]],
                pred[esc_mask],
            ).get("recall")
        sweep.append(
            {
                "threshold": float(thr),
                "fp_normal_no_escalate": fp_block,
                "fp_guardrail_ok": meets_fp,
                "recall_full_normal": pop.get("recall"),
                "recall_escalate_events": recall_esc,
                "f1_full_normal": pop.get("f1"),
            }
        )

    eligible = [s for s in sweep if s["fp_guardrail_ok"]]
    if eligible:
        best = max(
            eligible,
            key=lambda s: (
                s["recall_escalate_events"]
                if s["recall_escalate_events"] is not None
                else -1.0,
                s["recall_full_normal"] if s["recall_full_normal"] is not None else -1.0,
                -s["threshold"],
            ),
        )
        selection_reason = "max_recall_escalate_among_fp_ok"
    else:
        best = min(
            sweep,
            key=lambda s: (
                s["fp_normal_no_escalate"].get("fp_rate")
                if s["fp_normal_no_escalate"].get("fp_rate") is not None
                else 1.0,
                -(s["recall_escalate_events"] or -1.0),
            ),
        )
        selection_reason = "no_threshold_met_fp_guardrail_min_fp_fallback"

    return {
        "model": model_key,
        "persistence_fp_rate_tuning": pers_fp_rate,
        "fp_guardrail_ratio": float(fp_guardrail_ratio),
        "fp_cap": fp_cap,
        "default_threshold": DEFAULT_ALERT_PROBA_THRESHOLD,
        "selected_threshold": float(best["threshold"]),
        "selection_reason": selection_reason,
        "selection_objective": "maximize recall on normal_escalate_events",
        "n_thresholds": len(sweep),
        "n_fp_ok": len(eligible),
        "selected": best,
        "sweep": sweep,
    }


def tune_escalate_thresholds(
    train_rows: list[dict[str, Any]],
    tuning_rows_dense: list[dict[str, Any]],
    *,
    flood_weight: float,
    fp_guardrail_ratio: float = DEFAULT_FP_GUARDRAIL_RATIO,
    threshold_grid: tuple[float, ...] = DEFAULT_THRESHOLD_GRID,
) -> dict[str, Any]:
    """Tune ML thresholds on dense NORMAL tuning cutoffs."""
    pers_pred = np.zeros(len(tuning_rows_dense), dtype=int)
    pers_fp_rate = _false_positive_rate_escalate(tuning_rows_dense, pers_pred).get(
        "fp_rate"
    )
    weights = tuning_sample_weights(train_rows, flood_weight=flood_weight)

    by_model: dict[str, Any] = {}
    for mk in ML_TUNABLE_KEYS:
        bundle = _fit_escalate_ml(mk, train_rows, sample_weight=weights)
        proba = _predict_escalate_ml_proba(mk, bundle, tuning_rows_dense)
        if proba is None:
            by_model[mk] = {
                "error": "insufficient_training_or_empty_tuning",
                "selected_threshold": DEFAULT_ALERT_PROBA_THRESHOLD,
            }
            continue
        by_model[mk] = sweep_escalate_threshold(
            tuning_rows_dense,
            proba,
            model_key=mk,
            persistence_fp_rate=pers_fp_rate,
            fp_guardrail_ratio=fp_guardrail_ratio,
            threshold_grid=threshold_grid,
        )
        by_model[mk]["bundle_trained"] = bundle is not None
    return {
        "tuning_dense_n_cutoffs": len(tuning_rows_dense),
        "persistence_fp_rate_normal_no_escalate": pers_fp_rate,
        "fp_guardrail_ratio": float(fp_guardrail_ratio),
        "threshold_grid": list(threshold_grid),
        "sample_weights": {
            "flood_weight": float(flood_weight),
            "rule": (
                f"weight={flood_weight} when cutoff in flood window "
                f"[{FLOOD_WINDOW_START.date()}..{FLOOD_WINDOW_END.date()}] "
                "OR escalate_12h=1; else 1.0"
            ),
            "applied_on": "tuning train rows only (logistic + lightgbm fit)",
        },
        "by_model": by_model,
    }


def evaluate_escalate_model(
    model_key: EscalateModelKey,
    train_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
    *,
    alert_threshold: float | None = None,
    ml_bundle: Any | None = None,
    flood_weight: float = DEFAULT_FLOOD_SAMPLE_WEIGHT,
) -> dict[str, Any]:
    """Score holdout NORMAL cutoffs for one model."""
    y_true = np.asarray([r["escalate_12h"] for r in holdout_rows], dtype=int)
    if not holdout_rows:
        return {
            "model": model_key,
            "n_eval": 0,
            "escalate_12h": _alert_metrics(y_true, np.array([], dtype=int)),
            "by_population": {},
        }

    thr = (
        float(alert_threshold)
        if alert_threshold is not None
        else DEFAULT_ALERT_PROBA_THRESHOLD
    )

    if model_key in ("majority_never_escalate", "persistence_escalate"):
        pred, score = _predict_escalate_baseline(model_key, holdout_rows)
    else:
        weights = tuning_sample_weights(train_rows, flood_weight=flood_weight)
        bundle = (
            ml_bundle
            if ml_bundle is not None
            else _fit_escalate_ml(model_key, train_rows, sample_weight=weights)
        )
        score = _predict_escalate_ml_proba(model_key, bundle, holdout_rows)
        if score is None:
            pred = np.zeros(len(holdout_rows), dtype=int)
        else:
            pred = alert_proba_to_binary(score, thr)

    metrics = _alert_metrics(y_true, pred, score)
    out: dict[str, Any] = {
        "model": model_key,
        "n_eval": len(holdout_rows),
        "escalate_12h": metrics,
        "by_population": evaluate_populations(holdout_rows, pred),
    }
    if model_key in ML_TUNABLE_KEYS and alert_threshold is not None:
        out["escalate_proba_threshold"] = thr
    return out


def assess_escalate_launch_policy(
    by_model: dict[str, Any],
    *,
    baseline_key: str = "persistence_escalate",
    ml_keys: tuple[str, ...] = ("logistic_regression", "lightgbm"),
    fp_tolerance_ratio: float = 1.05,
) -> dict[str, Any]:
    """
    Escalate ML candidate when recall on normal_escalate_events beats persistence
    and FP on normal_no_escalate is within guardrail.
    """
    base_pop = (
        (by_model.get(baseline_key) or {}).get("by_population") or {}
    ).get("normal_escalate_events") or {}
    base_recall = base_pop.get("recall")
    base_fp_pop = (
        (by_model.get(baseline_key) or {}).get("by_population") or {}
    ).get("normal_no_escalate") or {}
    base_fp_rate = None
    if base_fp_pop.get("n", 0) > 0:
        fp = int(base_fp_pop.get("fp", 0))
        base_fp_rate = fp / int(base_fp_pop["n"])

    decisions: dict[str, Any] = {}
    for mk in ml_keys:
        block = by_model.get(mk) or {}
        ev = (block.get("by_population") or {}).get("normal_escalate_events") or {}
        no_esc = (block.get("by_population") or {}).get("normal_no_escalate") or {}
        recall = ev.get("recall")
        fp_rate = None
        if no_esc.get("n", 0) > 0:
            fp_rate = int(no_esc.get("fp", 0)) / int(no_esc["n"])
        beats_recall = (
            recall is not None
            and base_recall is not None
            and float(recall) > float(base_recall)
        )
        fp_ok = True
        if fp_rate is not None and base_fp_rate is not None:
            fp_ok = float(fp_rate) <= float(base_fp_rate) * fp_tolerance_ratio + 1e-12
        decisions[mk] = {
            "escalate_ml_candidate": bool(beats_recall and fp_ok),
            "beats_persistence_recall": beats_recall,
            "fp_guardrail_ok": fp_ok,
            "recall_normal_escalate_events": recall,
            "baseline_recall": base_recall,
            "fp_rate_normal_no_escalate": fp_rate,
            "baseline_fp_rate": base_fp_rate,
        }

    any_cand = any(d.get("escalate_ml_candidate") for d in decisions.values())
    return {
        "hybrid_online_recommendation": {
            "tier_NORMAL": (
                "ml_escalate_experimental"
                if any_cand
                else "persistence_escalate_always_0"
            ),
            "tier_WATCH_plus": "persistence_alert",
        },
        "escalate_ml_experimental": not any_cand,
        "escalate_ml_production_candidate": any_cand,
        "by_model": decisions,
    }


def format_escalate_md(result: dict[str, Any]) -> str:
    title = result.get("report_title") or "Turbidity R7a escalate_12h (NORMAL only)"
    lines = [
        f"# {title}",
        "",
        f"- Site: `{result.get('site_no')}`",
        f"- Holdout: {result.get('holdout_start_utc')} → {result.get('holdout_end_utc')}",
        f"- Holdout step: **{result.get('holdout_step')}**",
        f"- NORMAL holdout cutoffs: **{result.get('n_holdout_normal_cutoffs')}**",
        "",
        "## Task",
        "",
        "At quality tier **NORMAL** at T, predict **escalate_12h** "
        "(WATCH+ in T+1..T+12). Persistence at NORMAL always predicts 0.",
        "",
        "## Evaluation contract",
        "",
        "- **normal_escalate_events**: primary = recall, FN (missed escalations)",
        "- **normal_no_escalate**: guardrail = FP count / FP rate",
        "- **flood_window_normal**: operational stress (Dec 2025 flood)",
        "",
        "## Populations",
        "",
    ]
    for k, desc in (result.get("population_definitions") or {}).items():
        lines.append(f"- **{k}**: {desc}")

    lines.extend(["", "## escalate_12h — full NORMAL holdout", ""])
    lines.extend(
        [
            "| Model | Precision | Recall | F1 | PR-AUC |",
            "|-------|----------:|-------:|---:|-------:|",
        ]
    )
    for key in result.get("model_order") or []:
        m = (result.get("by_model") or {}).get(key, {})
        a = m.get("escalate_12h") or {}
        lines.append(
            f"| {key} | {a.get('precision')} | {a.get('recall')} | "
            f"{a.get('f1')} | {a.get('pr_auc')} |"
        )

    lines.extend(["", "## By population (holdout)", ""])
    for key in result.get("model_order") or []:
        m = (result.get("by_model") or {}).get(key, {})
        lines.append(f"### {key}")
        lines.append("")
        for pop, block in (m.get("by_population") or {}).items():
            lines.append(
                f"- **{pop}** (n={block.get('n')}): "
                f"TP={block.get('tp')} FP={block.get('fp')} "
                f"FN={block.get('fn')} TN={block.get('tn')} — "
                f"P={block.get('precision')} R={block.get('recall')} F1={block.get('f1')}"
            )
        lines.append("")

    sw = result.get("sample_weights_spec") or {}
    if sw:
        lines.extend(
            [
                "## Training sample weights",
                "",
                f"- {sw.get('rule', '')}",
                "",
            ]
        )

    thr = result.get("threshold_tuning_spec")
    if thr:
        lines.extend(
            [
                "## Threshold tuning (tuning NORMAL → holdout)",
                "",
                f"- Objective: {thr.get('selection_objective')}",
                f"- FP guardrail: {thr.get('fp_guardrail')}",
                "",
                "| Model | Selected τ |",
                "|-------|----------:|",
            ]
        )
        for mk, tau in (thr.get("selected_thresholds") or {}).items():
            lines.append(f"| {mk} | {tau} |")

    lt = result.get("lead_time_eval_spec")
    if lt:
        lines.extend(
            [
                "",
                "## Lead time (event-local, NORMAL escalate events)",
                "",
                f"- {lt.get('lead_time_definition', '')}",
                "",
                "| Model | Median lead (h) | % with lead |",
                "|-------|----------------:|------------:|",
            ]
        )
        for mk in ("persistence_escalate", "logistic_regression", "lightgbm"):
            block = ((result.get("by_model") or {}).get(mk) or {}).get("lead_time_eval") or {}
            lh = block.get("lead_hours") or {}
            lines.append(
                f"| {mk} | {lh.get('median_hours')} | {block.get('pct_events_with_lead')} |"
            )

    launch = result.get("launch_policy") or {}
    if launch:
        hyb = launch.get("hybrid_online_recommendation") or {}
        lines.extend(
            [
                "",
                "## Launch policy (R7a)",
                "",
                f"- NORMAL @ T: **{hyb.get('tier_NORMAL')}**",
                f"- WATCH+ @ T: **{hyb.get('tier_WATCH_plus')}**",
                f"- ML production candidate: **{launch.get('escalate_ml_production_candidate')}**",
            ]
        )
    return "\n".join(lines) + "\n"


def run_escalate_backtest(
    *,
    features_csv: Path,
    thresholds_json: Path,
    report_dir: Path,
    holdout_step: int = DEFAULT_HOLDOUT_STEP,
    lag: int = DEFAULT_LAG,
    min_valid_future_hours: int = DEFAULT_MIN_VALID_FUTURE_HOURS,
    write_md: bool = True,
    use_exog_ffill: bool = True,
    use_precip_ffill: bool | None = None,
    use_upstream_ffill: bool | None = None,
    output_basename: str = ESCALATE_OUTPUT_BASENAME,
    report_title: str | None = None,
    with_if_features: bool = False,
    tune_alert_threshold: bool = False,
    fp_guardrail_ratio: float = DEFAULT_FP_GUARDRAIL_RATIO,
    threshold_grid: tuple[float, ...] = DEFAULT_THRESHOLD_GRID,
    tuning_dense_step: int = 1,
    flood_weight: float = DEFAULT_FLOOD_SAMPLE_WEIGHT,
    leadtime_eval: bool = True,
    leadtime_holdout_step: int = 1,
) -> dict[str, Any]:
    """Run R7a escalate backtest; writes JSON + optional MD under report_dir."""
    csv_path = Path(features_csv)
    thr_path = Path(thresholds_json)
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    precip_ffill = use_exog_ffill if use_precip_ffill is None else use_precip_ffill
    upstream_ffill = use_exog_ffill if use_upstream_ffill is None else use_upstream_ffill
    exog_policy = build_exog_policy(
        use_exog_ffill=bool(precip_ffill and upstream_ffill),
        use_precip_ffill=precip_ffill,
        use_upstream_ffill=upstream_ffill,
    )

    thresholds = json.loads(thr_path.read_text(encoding="utf-8"))
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

    if "split_index" in thresholds:
        split_ix = int(thresholds["split_index"])
    else:
        split_info = _split_index_for_holdout(
            n,
            12,
            holdout_fraction=0.2,
            holdout_min_hours=336,
            min_tuning_hours=2000,
        )
        split_ix = int(split_info["split_index"])

    lag_eff = int(min(lag, _effective_lag(n, MAX_LAG)))
    tiers = label_alert_tier(y, thresholds)

    if_cache: IfScoreCache | None = None
    if with_if_features:
        mvar = build_multivar_matrix_from_df(df)
        if_cache = IfScoreCache(
            y,
            multivar_matrix=mvar,
            with_univariate=True,
            with_multivariate=True,
        )
    else:
        if_cache = IfScoreCache(y, with_univariate=False, with_multivariate=False)

    use_extended = True

    def _warm_if(idx_start: int, idx_end: int, step: int, label: str) -> None:
        if not with_if_features or if_cache is None:
            return
        from .forecast_engine import MIN_HOURLY_POINTS

        lag_full = _effective_lag(len(y), MAX_LAG)
        start = max(idx_start, lag_full - 1, MIN_HOURLY_POINTS - 1)
        end = min(idx_end, len(y) - 13)
        indices = list(range(start, end + 1, max(1, step)))
        if indices:
            print(f"Warming IF for {label} ({len(indices)} cutoffs)...", flush=True)
            warm_if_cache(
                if_cache,
                indices,
                with_univariate_if=True,
                with_multivariate_if=True,
                log_every=500,
            )

    def _build(idx_start: int, idx_end: int, step: int) -> list[dict[str, Any]]:
        _warm_if(idx_start, idx_end, step, "build")
        raw = build_labeled_cutoffs(
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
            with_extended_features=use_extended,
            with_univariate_if=with_if_features,
            with_multivariate_if=with_if_features,
        )
        return filter_normal_rows(raw)

    train_step = max(holdout_step, 24) if with_if_features else 1
    train_rows = _build(0, split_ix - 1, train_step)
    tuning_dense: list[dict[str, Any]] = []
    if tune_alert_threshold:
        dense_step = max(1, int(tuning_dense_step))
        tuning_dense = _build(0, split_ix - 1, dense_step)
    holdout_rows = _build(split_ix, n - 1, holdout_step)
    holdout_dense: list[dict[str, Any]] = []
    if leadtime_eval:
        holdout_dense = _build(split_ix, n - 1, max(1, int(leadtime_holdout_step)))

    ml_bundles: dict[str, Any] = {}
    weights = tuning_sample_weights(train_rows, flood_weight=flood_weight)
    for mk in ML_TUNABLE_KEYS:
        ml_bundles[mk] = _fit_escalate_ml(mk, train_rows, sample_weight=weights)

    selected_thresholds: dict[str, float] = {}
    threshold_tuning: dict[str, Any] | None = None
    if tune_alert_threshold and tuning_dense:
        threshold_tuning = tune_escalate_thresholds(
            train_rows,
            tuning_dense,
            flood_weight=flood_weight,
            fp_guardrail_ratio=fp_guardrail_ratio,
            threshold_grid=threshold_grid,
        )
        for mk in ML_TUNABLE_KEYS:
            block = (threshold_tuning.get("by_model") or {}).get(mk) or {}
            selected_thresholds[mk] = float(
                block.get("selected_threshold", DEFAULT_ALERT_PROBA_THRESHOLD)
            )

    by_model: dict[str, Any] = {}
    for mk in ESCALATE_MODEL_ORDER:
        thr = (
            selected_thresholds.get(mk)
            if tune_alert_threshold and mk in ML_TUNABLE_KEYS
            else None
        )
        metrics = evaluate_escalate_model(
            mk,
            train_rows,
            holdout_rows,
            alert_threshold=thr,
            ml_bundle=ml_bundles.get(mk),
            flood_weight=flood_weight,
        )

        if mk in ("majority_never_escalate", "persistence_escalate"):
            pred, _ = _predict_escalate_baseline(mk, holdout_rows)
        else:
            proba = _predict_escalate_ml_proba(mk, ml_bundles.get(mk), holdout_rows)
            tau = float(thr) if thr is not None else DEFAULT_ALERT_PROBA_THRESHOLD
            pred = (
                alert_proba_to_binary(proba, tau)
                if proba is not None
                else np.zeros(len(holdout_rows), dtype=int)
            )

        if leadtime_eval and holdout_dense:
            for r in holdout_dense:
                if "escalate_12h" not in r:
                    r["escalate_12h"] = int(r.get("alert_12h", 0))
            if mk in ("majority_never_escalate", "persistence_escalate"):
                lt_pred, _ = _predict_escalate_baseline(mk, holdout_dense)
            else:
                proba_lt = _predict_escalate_ml_proba(mk, ml_bundles.get(mk), holdout_dense)
                tau_lt = float(
                    selected_thresholds.get(mk, DEFAULT_ALERT_PROBA_THRESHOLD)
                )
                lt_pred = (
                    alert_proba_to_binary(proba_lt, tau_lt)
                    if proba_lt is not None
                    else np.zeros(len(holdout_dense), dtype=int)
                )
            metrics["lead_time_eval"] = evaluate_upgrade_lead_time(
                tiers,
                y,
                holdout_dense,
                lt_pred,
                model_name=mk,
                if_cache=if_cache if with_if_features else None,
            )
            metrics["fp_guardrail_holdout_dense"] = {
                "normal_no_escalate": _false_positive_rate_escalate(
                    holdout_dense, lt_pred
                ),
            }

        by_model[mk] = metrics

    result: dict[str, Any] = {
        "spec": "turbidity_risk_escalate_12h_r7a",
        "site_no": thresholds.get("site_no", DEFAULT_SITE_NO),
        "tier_model_version": thresholds.get("model_version", MODEL_VERSION),
        "features_csv": str(csv_path.resolve()),
        "thresholds_path": str(thr_path.resolve()),
        "split_index": split_ix,
        "holdout_start_utc": str(y.index[split_ix]),
        "holdout_end_utc": str(y.index[-1]),
        "holdout_step": int(holdout_step),
        "lag": lag_eff,
        "feature_dim": extended_feature_dim(
            lag_eff,
            has_upstream=q_up is not None,
            with_univariate_if=with_if_features,
            with_multivariate_if=with_if_features,
        ),
        "min_valid_future_hours": int(min_valid_future_hours),
        "label_definitions": {
            "escalate_12h": (
                "1 if max quality tier in (T+1..T+12) is WATCH+; "
                "evaluated only when tier_at_T is NORMAL"
            ),
            "same_as_alert_12h_on_normal_subset": True,
        },
        "exog_policy": exog_policy,
        "population_definitions": population_definitions(),
        "evaluation_contract": {
            "normal_escalate_events": "primary: recall, FN",
            "normal_no_escalate": "guardrail: FP, FP rate",
            "flood_window_normal": "operational stress",
        },
        "n_tuning_normal_cutoffs": len(train_rows),
        "n_holdout_normal_cutoffs": len(holdout_rows),
        "model_order": list(ESCALATE_MODEL_ORDER),
        "by_model": by_model,
        "sample_weights_spec": {
            "flood_weight": float(flood_weight),
            "rule": (
                f"weight={flood_weight} on tuning rows in flood window "
                f"or escalate_12h=1"
            ),
        },
        "launch_policy": assess_escalate_launch_policy(
            by_model, fp_tolerance_ratio=fp_guardrail_ratio
        ),
    }

    if threshold_tuning is not None:
        result["threshold_tuning"] = threshold_tuning
        result["threshold_tuning_spec"] = {
            "tuning_dense_step": int(tuning_dense_step),
            "n_tuning_dense_normal_cutoffs": len(tuning_dense),
            "threshold_grid": list(threshold_grid),
            "fp_guardrail": (
                "fp_rate(escalate_12h=0) on tuning NORMAL <= "
                f"persistence_fp * {fp_guardrail_ratio}"
            ),
            "selection_objective": (
                "maximize recall on normal_escalate_events among FP-ok thresholds"
            ),
            "selected_thresholds": selected_thresholds,
        }

    if leadtime_eval and holdout_dense:
        n_ev = sum(1 for r in holdout_dense if is_tier_upgrade_event(r))
        result["lead_time_eval_spec"] = {
            "holdout_step_dense": int(leadtime_holdout_step),
            "n_holdout_dense_normal_cutoffs": len(holdout_dense),
            "n_escalate_events": n_ev,
            "lead_time_mode": "event_local",
            "lead_time_definition": (
                "hours from first predicted escalate=1 in [T, first_upgrade) "
                "to first WATCH+; capped at min(12, upgrade-T)"
            ),
        }

    if report_title:
        result["report_title"] = report_title

    json_path = out_dir / f"{output_basename}.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    md_path = out_dir / f"{output_basename}.md"
    if write_md:
        md_path.write_text(format_escalate_md(result), encoding="utf-8")
    result["outputs"] = {"json": str(json_path), "md": str(md_path) if write_md else None}
    return result

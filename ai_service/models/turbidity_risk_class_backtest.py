"""
12h turbidity RISK classification backtest (site 12117500, Phase A').

At cutoff ``T``, labels use future hours ``T+1..T+12`` (quality tiers only; skip if
``< min_valid_future_hours`` valid y hours). Features are lag blocks of 63680, precipitation,
and upstream discharge ending at ``T`` (no future leakage).

Models train once on tuning cutoffs (``idx_T < split_index``); holdout is evaluated at
``step`` hours (default 24) on ``idx_T >= split_index``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, average_precision_score, f1_score
from sklearn.preprocessing import LabelEncoder, StandardScaler

from .backtest_turbidity_exog_ridge_lgbm import (
    UPSTREAM_DISCHARGE_COL,
    _as_lgbm_frame,
    _split_index_for_holdout,
)
from .forecast_engine import MAX_LAG, MIN_HOURLY_POINTS, _effective_lag
from .turbidity_gap_report import FLOOD_WINDOW_END, FLOOD_WINDOW_START
from .turbidity_risk_forecast_backtest import (
    DEFAULT_FEATURES_CSV,
    DEFAULT_HOLDOUT_STEP,
    DEFAULT_REPORT_DIR,
    DEFAULT_SITE_NO,
    DEFAULT_THRESHOLDS_JSON,
    _alert_contingency,
    _exog_blocks_no_temp,
    _feat_dim_no_temp,
    max_quality_tier,
)
from .turbidity_risk_features import (
    IfScoreCache,
    build_multivar_matrix_from_df,
    extended_feature_dim,
    features_at_cutoff_extended,
    warm_if_cache,
)
from .turbidity_state_monitoring import (
    ALERT_TIERS,
    MODEL_VERSION,
    UPSTREAM_FFILL_LIMIT_HOURS,
    is_gap_tier,
    is_quality_alert_tier,
    label_alert_tier,
    load_features,
    tier_is_anomaly,
)

DEFAULT_LAG = 36
DEFAULT_MIN_VALID_FUTURE_HOURS = 6
DEFAULT_HORIZONS = list(range(1, 13))
MAX_FUTURE_H = 12
DEFAULT_ALERT_PROBA_THRESHOLD = 0.5
DEFAULT_FP_GUARDRAIL_RATIO = 1.05
DEFAULT_THRESHOLD_GRID: tuple[float, ...] = tuple(
    round(float(x), 2) for x in np.arange(0.05, 1.0, 0.05)
)
ML_TUNABLE_KEYS: tuple[str, ...] = ("logistic_regression", "lightgbm")

TIER_RANK: dict[str, int] = {
    "NORMAL": 0,
    "WATCH": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}

ModelKey = Literal[
    "majority_always_normal",
    "persistence_alert",
    "persistence_max_tier",
    "logistic_regression",
    "lightgbm",
]


def _labels_12h_at_cutoff(
    tiers: pd.Series,
    y: pd.Series,
    idx_T: int,
    *,
    min_valid_future_hours: int,
    max_h: int = MAX_FUTURE_H,
) -> dict[str, Any] | None:
    """
    Future-window labels at ``T`` using hours ``T+1..T+max_h``.

    Only hours with finite 63680 (quality tier, not gap) count toward validity.
    Returns None if the window has fewer than ``min_valid_future_hours`` valid hours.
    """
    n = len(tiers)
    h_end = min(int(max_h), n - 1 - idx_T)
    if h_end < 1:
        return None

    quality_tiers: list[str] = []
    for h in range(1, h_end + 1):
        ti = idx_T + h
        if not np.isfinite(y.iloc[ti]):
            continue
        tname = str(tiers.iloc[ti])
        if is_gap_tier(tname):
            continue
        quality_tiers.append(tname)

    if len(quality_tiers) < int(min_valid_future_hours):
        return None

    max_t = max_quality_tier(quality_tiers)
    if max_t is None:
        return None
    alert = int(tier_is_anomaly(max_t))
    return {
        "alert_12h": alert,
        "max_tier_12h": max_t,
        "n_valid_future_hours": len(quality_tiers),
        "future_horizon_max": h_end,
    }


def _features_at_cutoff(
    y: pd.Series,
    prec: pd.Series,
    q_up: pd.Series | None,
    idx_T: int,
    *,
    lag: int,
) -> np.ndarray | None:
    """Lag blocks for y, precip, upstream; all series end at ``idx_T`` (causal)."""
    return _exog_blocks_no_temp(
        y,
        prec,
        q_up,
        end_ix_y=idx_T,
        end_ix_exog=idx_T,
        lag=lag,
    )


def build_labeled_cutoffs(
    y: pd.Series,
    prec: pd.Series,
    q_up: pd.Series | None,
    tiers: pd.Series,
    *,
    lag: int,
    min_valid_future_hours: int,
    idx_start: int,
    idx_end: int,
    step: int = 1,
    if_cache: IfScoreCache | None = None,
    with_extended_features: bool = False,
    with_univariate_if: bool = False,
    with_multivariate_if: bool = False,
) -> list[dict[str, Any]]:
    """Collect cutoffs with valid labels and feature vectors."""
    lag_full = _effective_lag(len(y), MAX_LAG)
    lag_use = int(min(lag, lag_full))
    start = max(int(idx_start), lag_full - 1, MIN_HOURLY_POINTS - 1)
    end = min(int(idx_end), len(y) - MAX_FUTURE_H - 1)
    step = max(1, int(step))
    rows: list[dict[str, Any]] = []

    for idx_T in range(start, end + 1, step):
        lab = _labels_12h_at_cutoff(
            tiers,
            y,
            idx_T,
            min_valid_future_hours=min_valid_future_hours,
        )
        if lab is None:
            continue
        if with_extended_features or with_univariate_if or with_multivariate_if:
            feat = features_at_cutoff_extended(
                y,
                prec,
                q_up,
                idx_T,
                lag=lag_use,
                if_cache=if_cache,
                with_univariate_if=with_univariate_if,
                with_multivariate_if=with_multivariate_if,
            )
        else:
            feat = _features_at_cutoff(y, prec, q_up, idx_T, lag=lag_use)
        if feat is None:
            continue
        tier_now = str(tiers.iloc[idx_T])
        rows.append(
            {
                "cutoff_ix": int(idx_T),
                "cutoff_utc": str(y.index[idx_T]),
                "features": feat,
                "tier_at_T": tier_now,
                "alert_12h": int(lab["alert_12h"]),
                "max_tier_12h": str(lab["max_tier_12h"]),
                "n_valid_future_hours": int(lab["n_valid_future_hours"]),
            }
        )
    return rows


def first_future_upgrade_ix(
    tiers: pd.Series,
    y: pd.Series,
    idx_T: int,
    *,
    max_h: int = MAX_FUTURE_H,
) -> int | None:
    """First hour index in (T, T+max_h] where quality tier is WATCH+."""
    h_end = min(int(max_h), len(tiers) - 1 - idx_T)
    for h in range(1, h_end + 1):
        ti = idx_T + h
        if not np.isfinite(y.iloc[ti]):
            continue
        tname = str(tiers.iloc[ti])
        if is_gap_tier(tname):
            continue
        if is_quality_alert_tier(tname):
            return int(ti)
    return None


def is_tier_upgrade_event(row: dict[str, Any]) -> bool:
    """NORMAL at T with WATCH+ in the next 12h (flood/rising turbidity lead-time events)."""
    return (
        str(row.get("tier_at_T")) == "NORMAL"
        and int(row.get("alert_12h", 0)) == 1
        and not is_gap_tier(str(row.get("tier_at_T")))
    )


def _false_positive_rate(rows: list[dict[str, Any]], alert_pred: np.ndarray) -> dict[str, Any]:
    """FP rate when label alert_12h=0 (no WATCH+ in next 12h)."""
    y_true = np.asarray([int(r["alert_12h"]) for r in rows], dtype=int)
    mask = y_true == 0
    n = int(mask.sum())
    if n == 0:
        return {"n": 0, "fp_rate": None, "fp": 0}
    fp = int((alert_pred[mask] == 1).sum())
    return {"n": n, "fp": fp, "fp_rate": round(fp / n, 6)}


def _control_population_fp(
    rows: list[dict[str, Any]],
    alert_pred: np.ndarray,
    if_cache: IfScoreCache | None,
) -> dict[str, Any]:
    """
    FP on control hours: tier NORMAL + univariate IF not alerting at T.

    Complements ``_false_positive_rate`` (no upgrade in 12h).
    """
    if if_cache is None:
        return {"n": 0, "fp_rate": None, "note": "if_cache_not_provided"}
    preds: list[int] = []
    for i, r in enumerate(rows):
        if str(r["tier_at_T"]) != "NORMAL":
            continue
        u = if_cache.univariate_at(int(r["cutoff_ix"]))
        if not u.get("available"):
            continue
        if float(u.get("is_anomaly", 0)) >= 0.5:
            continue
        preds.append(int(alert_pred[i]))
    if not preds:
        return {"n": 0, "fp_rate": None}
    fp = sum(1 for p in preds if p == 1)
    n = len(preds)
    return {"n": n, "fp": fp, "fp_rate": round(fp / n, 6)}


def evaluate_upgrade_lead_time(
    tiers: pd.Series,
    y: pd.Series,
    eval_rows: list[dict[str, Any]],
    alert_pred: np.ndarray,
    *,
    model_name: str,
    if_cache: IfScoreCache | None = None,
) -> dict[str, Any]:
    """
    Event-local lead time: first predicted alert in [T, first_upgrade) before WATCH+.

    Events: NORMAL at T with WATCH+ in (T, T+12]. Only cutoffs within the event window
    are scanned (not from holdout start). Lead hours are capped at the window length
    (min(12, first_upgrade_ix - T)). No alert before upgrade -> lead_hours omitted
    (has_lead=False; excluded from median/mean).
    """
    by_ix: dict[int, tuple[dict[str, Any], int]] = {}
    for r, ap in zip(eval_rows, alert_pred, strict=True):
        by_ix[int(r["cutoff_ix"])] = (r, int(ap))

    events: list[dict[str, Any]] = []
    for r in eval_rows:
        if not is_tier_upgrade_event(r):
            continue
        idx_T = int(r["cutoff_ix"])
        up_ix = first_future_upgrade_ix(tiers, y, idx_T)
        if up_ix is None:
            continue

        window_end_ix = int(min(up_ix - 1, idx_T + MAX_FUTURE_H))
        first_pred_ix: int | None = None
        for cut_ix in range(idx_T, window_end_ix + 1):
            if cut_ix not in by_ix:
                continue
            _, pred_a = by_ix[cut_ix]
            if pred_a == 1:
                first_pred_ix = cut_ix
                break

        lead_h: int | None = None
        has_lead = False
        if first_pred_ix is not None and first_pred_ix < up_ix:
            raw_lead = int(up_ix - first_pred_ix)
            max_lead = int(min(MAX_FUTURE_H, up_ix - idx_T))
            lead_h = min(raw_lead, max_lead)
            has_lead = True

        up_utc = str(y.index[up_ix])
        in_flood = (
            pd.Timestamp(up_utc) >= FLOOD_WINDOW_START
            and pd.Timestamp(up_utc) <= FLOOD_WINDOW_END
        )
        events.append(
            {
                "event_cutoff_ix": idx_T,
                "event_cutoff_utc": str(r["cutoff_utc"]),
                "first_upgrade_ix": up_ix,
                "first_upgrade_utc": up_utc,
                "window_end_ix": window_end_ix,
                "first_pred_ix": first_pred_ix,
                "first_pred_utc": str(y.index[first_pred_ix]) if first_pred_ix is not None else None,
                "lead_hours": lead_h,
                "has_lead": has_lead,
                "in_flood_window": bool(in_flood),
            }
        )

    leads = [e["lead_hours"] for e in events if e.get("has_lead") and e["lead_hours"] is not None]
    flood_events = [e for e in events if e["in_flood_window"]]
    flood_leads = [e["lead_hours"] for e in flood_events if e["lead_hours"] is not None and e["has_lead"]]

    def _summarize_leads(vals: list[int]) -> dict[str, Any]:
        if not vals:
            return {"n_with_lead": 0, "mean_hours": None, "median_hours": None}
        arr = np.asarray(vals, dtype=float)
        return {
            "n_with_lead": len(vals),
            "mean_hours": round(float(arr.mean()), 3),
            "median_hours": round(float(np.median(arr)), 3),
        }

    n_events = len(events)
    n_with_lead = sum(1 for e in events if e["has_lead"])
    n_no_lead = n_events - n_with_lead
    return {
        "model": model_name,
        "lead_time_mode": "event_local",
        "n_upgrade_events": n_events,
        "n_with_any_lead": n_with_lead,
        "n_without_lead_before_upgrade": n_no_lead,
        "pct_events_with_lead": round(n_with_lead / n_events, 6) if n_events else None,
        "lead_hours": _summarize_leads(leads),
        "flood_window": {
            "window_start_utc": FLOOD_WINDOW_START.isoformat(),
            "window_end_utc": FLOOD_WINDOW_END.isoformat(),
            "n_events": len(flood_events),
            "n_with_lead": sum(1 for e in flood_events if e["has_lead"]),
            "lead_hours": _summarize_leads(flood_leads),
        },
        "events_sample": events[:20],
        "n_events_in_output": min(20, len(events)),
    }


def compare_leadtime_v2_v3(
    v3_result: dict[str, Any],
    v2_json: dict[str, Any],
) -> dict[str, Any]:
    """Compare event-local (v3) vs holdout-wide scan (v2) lead-time medians."""
    focus = ("persistence_alert", "logistic_regression", "lightgbm")
    by_model: dict[str, Any] = {}
    for mk in focus:
        v3_lt = ((v3_result.get("by_model") or {}).get(mk) or {}).get("lead_time_eval") or {}
        v2_lt = ((v2_json.get("by_model") or {}).get(mk) or {}).get("lead_time_eval") or {}
        v3_med = ((v3_lt.get("lead_hours") or {}).get("median_hours"))
        v2_med = ((v2_lt.get("lead_hours") or {}).get("median_hours"))
        delta = None
        if v3_med is not None and v2_med is not None:
            delta = round(float(v3_med) - float(v2_med), 3)
        by_model[mk] = {
            "v2_median_hours": v2_med,
            "v3_median_hours": v3_med,
            "median_delta_v3_minus_v2": delta,
            "v2_pct_with_lead": v2_lt.get("pct_events_with_lead"),
            "v3_pct_with_lead": v3_lt.get("pct_events_with_lead"),
        }
    return {
        "v2_spec": v2_json.get("spec"),
        "v3_spec": v3_result.get("spec"),
        "v2_lead_time_definition": (v2_json.get("lead_time_eval_spec") or {}).get("lead_time_definition"),
        "v3_lead_time_definition": (v3_result.get("lead_time_eval_spec") or {}).get("lead_time_definition"),
        "by_model": by_model,
    }


def write_leadtime_comparison_plot(result: dict[str, Any], out_png: Path) -> bool:
    """Bar chart: median lead hours for persistence vs ML on holdout upgrade events."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    keys = ("persistence_alert", "logistic_regression", "lightgbm")
    labels: list[str] = []
    medians: list[float] = []
    for mk in keys:
        lt = ((result.get("by_model") or {}).get(mk) or {}).get("lead_time_eval") or {}
        med = ((lt.get("lead_hours") or {}).get("median_hours"))
        if med is None:
            continue
        labels.append(mk.replace("_", "\n"))
        medians.append(float(med))

    if not labels:
        return False

    fig, ax = plt.subplots(figsize=(7, 4))
    colors = ["#457b9d", "#e76f51", "#2a9d8f"]
    ax.bar(labels, medians, color=colors[: len(labels)])
    ax.set_ylabel("Median lead time (hours)")
    ax.set_title("Lead time before tier upgrade (holdout)")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=120)
    plt.close(fig)
    return True


def assess_launch_policy(
    by_model: dict[str, Any],
    *,
    baseline_key: str = "persistence_alert",
    ml_keys: tuple[str, ...] = ("logistic_regression", "lightgbm"),
    fp_tolerance_ratio: float = 1.05,
) -> dict[str, Any]:
    """
    Production candidate if ML median lead time beats persistence and FP guardrail holds.
    """
    base_lt = (by_model.get(baseline_key) or {}).get("lead_time_eval") or {}
    base_med = ((base_lt.get("lead_hours") or {}).get("median_hours"))
    base_fp = ((by_model.get(baseline_key) or {}).get("fp_guardrail") or {}).get("no_upgrade_12h", {})
    base_fp_rate = base_fp.get("fp_rate")

    decisions: dict[str, Any] = {}
    for mk in ml_keys:
        block = by_model.get(mk) or {}
        lt = block.get("lead_time_eval") or {}
        med = ((lt.get("lead_hours") or {}).get("median_hours"))
        fp_block = block.get("fp_guardrail") or {}
        fp_rate = (fp_block.get("no_upgrade_12h") or {}).get("fp_rate")
        beats_lead = (
            med is not None
            and base_med is not None
            and float(med) > float(base_med)
        )
        fp_ok = True
        if fp_rate is not None and base_fp_rate is not None:
            fp_ok = float(fp_rate) <= float(base_fp_rate) * fp_tolerance_ratio
        decisions[mk] = {
            "production_candidate": bool(beats_lead and fp_ok),
            "beats_persistence_median_lead": beats_lead,
            "fp_guardrail_ok": fp_ok,
            "median_lead_hours": med,
            "baseline_median_lead_hours": base_med,
            "fp_rate": fp_rate,
            "baseline_fp_rate": base_fp_rate,
        }

    any_prod = any(d.get("production_candidate") for d in decisions.values())
    return {
        "default_launch": "persistence" if not any_prod else "best_ml_candidate",
        "persistence_stays_default": not any_prod,
        "ml_status_if_not_candidate": "experimental",
        "by_model": decisions,
    }


def _macro_f1_multiclass(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    labels = list(ALERT_TIERS)
    if not y_true:
        return {"n": 0, "accuracy": None, "macro_f1": None}
    acc = accuracy_score(y_true, y_pred)
    macro = f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
    return {
        "n": len(y_true),
        "accuracy": round(float(acc), 6),
        "macro_f1": round(float(macro), 6),
    }


def _alert_metrics(y_true: np.ndarray, y_pred: np.ndarray, y_score: np.ndarray | None = None) -> dict[str, Any]:
    out = _alert_contingency(y_pred, y_true)
    if y_score is not None and len(np.unique(y_true)) > 1:
        try:
            pr_auc = float(average_precision_score(y_true, y_score))
            out["pr_auc"] = round(pr_auc, 6)
        except ValueError:
            out["pr_auc"] = None
    else:
        out["pr_auc"] = None
    return out


def _predict_baseline(
    model_key: ModelKey,
    rows: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Return (alert_pred, alert_proba_or_none, max_tier_pred)."""
    n = len(rows)
    alert_p = np.zeros(n, dtype=int)
    tier_p: list[str] = ["NORMAL"] * n

    if model_key == "majority_always_normal":
        return alert_p, None, tier_p

    for i, r in enumerate(rows):
        t_now = str(r["tier_at_T"])
        if model_key == "persistence_alert":
            alert_p[i] = int(is_quality_alert_tier(t_now) and t_now != "NORMAL")
        elif model_key == "persistence_max_tier":
            if is_quality_alert_tier(t_now):
                tier_p[i] = t_now
            else:
                tier_p[i] = "NORMAL"
            alert_p[i] = int(tier_is_anomaly(tier_p[i]))
    return alert_p, None, tier_p


def _fit_logistic(
    X: np.ndarray,
    y_alert: np.ndarray,
    y_tier: np.ndarray,
) -> tuple[Any, Any, LabelEncoder, LabelEncoder]:
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    le_tier = LabelEncoder()
    le_tier.fit(list(ALERT_TIERS))
    y_tier_ix = le_tier.transform(y_tier)

    clf_alert = LogisticRegression(class_weight="balanced", max_iter=2000, random_state=42)
    clf_alert.fit(Xs, y_alert)

    clf_tier = LogisticRegression(
        class_weight="balanced",
        max_iter=2000,
        random_state=42,
        solver="lbfgs",
    )
    clf_tier.fit(Xs, y_tier_ix)
    return (scaler, clf_alert, clf_tier), le_tier


def _fit_lightgbm(
    X: np.ndarray,
    y_alert: np.ndarray,
    y_tier: np.ndarray,
) -> tuple[LGBMClassifier, LGBMClassifier, LabelEncoder]:
    le_tier = LabelEncoder()
    le_tier.fit(list(ALERT_TIERS))
    y_tier_ix = le_tier.transform(y_tier)

    clf_alert = LGBMClassifier(
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
    clf_tier = LGBMClassifier(
        objective="multiclass",
        num_class=len(ALERT_TIERS),
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
    clf_alert.fit(Xf, y_alert)
    clf_tier.fit(Xf, y_tier_ix)
    return clf_alert, clf_tier, le_tier


def _predict_sklearn_logistic(
    bundle: tuple[Any, Any, LabelEncoder],
    X: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    scaler, clf_alert, clf_tier = bundle[0]
    le_tier: LabelEncoder = bundle[1]
    Xs = scaler.transform(X)
    alert_p = clf_alert.predict(Xs).astype(int)
    alert_proba = clf_alert.predict_proba(Xs)[:, 1]
    tier_ix = clf_tier.predict(Xs)
    tier_p = list(le_tier.inverse_transform(tier_ix))
    return alert_p, alert_proba, tier_p


def _predict_lightgbm(
    clf_alert: LGBMClassifier,
    clf_tier: LGBMClassifier,
    le_tier: LabelEncoder,
    X: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    Xf = _as_lgbm_frame(X)
    alert_p = clf_alert.predict(Xf).astype(int)
    proba = clf_alert.predict_proba(Xf)
    alert_score = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]
    tier_ix = clf_tier.predict(Xf)
    tier_p = list(le_tier.inverse_transform(tier_ix))
    return alert_p, alert_score, tier_p


def alert_proba_to_binary(alert_proba: np.ndarray, threshold: float) -> np.ndarray:
    """Binary alert from P(alert_12h=1) at ``threshold``."""
    return (np.asarray(alert_proba, dtype=float) >= float(threshold)).astype(int)


def _fit_ml_bundle(
    model_key: ModelKey,
    train_rows: list[dict[str, Any]],
) -> Any | None:
    """Fit logistic or LightGBM; None when training is not possible."""
    if model_key not in ML_TUNABLE_KEYS:
        raise ValueError(f"not an ML model: {model_key}")
    X_train = np.stack([r["features"] for r in train_rows], axis=0)
    y_a_train = np.asarray([r["alert_12h"] for r in train_rows], dtype=int)
    y_t_train = [r["max_tier_12h"] for r in train_rows]
    if len(train_rows) < 30 or len(np.unique(y_a_train)) < 2:
        return None
    if model_key == "logistic_regression":
        return _fit_logistic(X_train, y_a_train, y_t_train)
    clf_a, clf_t, le = _fit_lightgbm(X_train, y_a_train, y_t_train)
    return (clf_a, clf_t, le)


def _predict_ml_alert_proba(
    model_key: ModelKey,
    bundle: Any,
    eval_rows: list[dict[str, Any]],
) -> np.ndarray | None:
    """P(alert_12h=1) for logistic / LightGBM on ``eval_rows``."""
    if bundle is None or not eval_rows:
        return None
    X_eval = np.stack([r["features"] for r in eval_rows], axis=0)
    if model_key == "logistic_regression":
        _, alert_proba, _ = _predict_sklearn_logistic(bundle, X_eval)
        return alert_proba
    clf_a, clf_t, le = bundle
    _, alert_score, _ = _predict_lightgbm(clf_a, clf_t, le, X_eval)
    return alert_score


def sweep_ml_alert_threshold(
    tiers: pd.Series,
    y: pd.Series,
    rows: list[dict[str, Any]],
    alert_proba: np.ndarray,
    *,
    model_key: str,
    persistence_fp_rate: float | None,
    fp_guardrail_ratio: float,
    threshold_grid: tuple[float, ...] = DEFAULT_THRESHOLD_GRID,
    if_cache: IfScoreCache | None = None,
) -> dict[str, Any]:
    """
    Score each probability threshold on ``rows`` (tuning only for selection).

    Objective: maximize event-local median lead time subject to
    ``fp_rate(no_upgrade_12h) <= persistence_fp_rate * fp_guardrail_ratio``.
    """
    pers_rows = rows
    pers_pred, _, _ = _predict_baseline("persistence_alert", pers_rows)
    pers_fp = _false_positive_rate(pers_rows, pers_pred)
    pers_fp_rate = pers_fp.get("fp_rate")
    if persistence_fp_rate is not None:
        pers_fp_rate = float(persistence_fp_rate)
    fp_cap = (
        float(pers_fp_rate) * float(fp_guardrail_ratio)
        if pers_fp_rate is not None
        else None
    )

    sweep: list[dict[str, Any]] = []
    for thr in threshold_grid:
        pred = alert_proba_to_binary(alert_proba, thr)
        fp_block = _false_positive_rate(rows, pred)
        fp_rate = fp_block.get("fp_rate")
        lt = evaluate_upgrade_lead_time(
            tiers,
            y,
            rows,
            pred,
            model_name=model_key,
            if_cache=if_cache,
        )
        med = ((lt.get("lead_hours") or {}).get("median_hours"))
        meets_fp = fp_cap is None or (
            fp_rate is not None and float(fp_rate) <= float(fp_cap) + 1e-12
        )
        sweep.append(
            {
                "threshold": float(thr),
                "fp_no_upgrade_12h": fp_block,
                "fp_guardrail_ok": meets_fp,
                "median_lead_hours": med,
                "pct_events_with_lead": lt.get("pct_events_with_lead"),
                "n_upgrade_events": lt.get("n_upgrade_events"),
            }
        )

    eligible = [s for s in sweep if s["fp_guardrail_ok"]]
    if eligible:
        best = max(
            eligible,
            key=lambda s: (
                s["median_lead_hours"] if s["median_lead_hours"] is not None else -1.0,
                s["pct_events_with_lead"] if s["pct_events_with_lead"] is not None else -1.0,
                -s["threshold"],
            ),
        )
        selection_reason = "max_median_lead_among_fp_ok"
    else:
        best = min(
            sweep,
            key=lambda s: (
                s["fp_no_upgrade_12h"].get("fp_rate")
                if s["fp_no_upgrade_12h"].get("fp_rate") is not None
                else 1.0,
                -(s["median_lead_hours"] or -1.0),
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
        "n_thresholds": len(sweep),
        "n_fp_ok": len(eligible),
        "selected": best,
        "sweep": sweep,
    }


def tune_ml_alert_thresholds(
    tiers: pd.Series,
    y: pd.Series,
    train_rows: list[dict[str, Any]],
    tuning_rows_dense: list[dict[str, Any]],
    *,
    fp_guardrail_ratio: float = DEFAULT_FP_GUARDRAIL_RATIO,
    threshold_grid: tuple[float, ...] = DEFAULT_THRESHOLD_GRID,
    if_cache: IfScoreCache | None = None,
) -> dict[str, Any]:
    """Tune alert probability thresholds on tuning cutoffs only."""
    pers_pred, _, _ = _predict_baseline("persistence_alert", tuning_rows_dense)
    pers_fp_rate = _false_positive_rate(tuning_rows_dense, pers_pred).get("fp_rate")

    by_model: dict[str, Any] = {}
    for mk in ML_TUNABLE_KEYS:
        bundle = _fit_ml_bundle(mk, train_rows)
        proba = _predict_ml_alert_proba(mk, bundle, tuning_rows_dense)
        if proba is None:
            by_model[mk] = {
                "error": "insufficient_training_or_empty_tuning",
                "selected_threshold": DEFAULT_ALERT_PROBA_THRESHOLD,
            }
            continue
        by_model[mk] = sweep_ml_alert_threshold(
            tiers,
            y,
            tuning_rows_dense,
            proba,
            model_key=mk,
            persistence_fp_rate=pers_fp_rate,
            fp_guardrail_ratio=fp_guardrail_ratio,
            threshold_grid=threshold_grid,
            if_cache=if_cache,
        )
        by_model[mk]["bundle_trained"] = bundle is not None
    return {
        "tuning_dense_n_cutoffs": len(tuning_rows_dense),
        "persistence_fp_rate_no_upgrade_12h": pers_fp_rate,
        "fp_guardrail_ratio": float(fp_guardrail_ratio),
        "threshold_grid": list(threshold_grid),
        "by_model": by_model,
    }


def evaluate_model_on_rows(
    model_key: ModelKey,
    train_rows: list[dict[str, Any]],
    eval_rows: list[dict[str, Any]],
    *,
    alert_threshold: float | None = None,
    ml_bundle: Any | None = None,
) -> dict[str, Any]:
    """Train (if needed) and score ``eval_rows``."""
    y_alert_true = np.asarray([r["alert_12h"] for r in eval_rows], dtype=int)
    y_tier_true = [r["max_tier_12h"] for r in eval_rows]

    if not eval_rows:
        return {
            "model": model_key,
            "n_eval": 0,
            "alert_12h": _alert_metrics(y_alert_true, np.array([], dtype=int)),
            "max_tier_12h": _macro_f1_multiclass([], []),
        }

    alert_thr = (
        float(alert_threshold)
        if alert_threshold is not None
        else DEFAULT_ALERT_PROBA_THRESHOLD
    )

    if model_key in ("majority_always_normal", "persistence_alert", "persistence_max_tier"):
        alert_p, alert_score, tier_p = _predict_baseline(model_key, eval_rows)
    else:
        bundle = ml_bundle if ml_bundle is not None else _fit_ml_bundle(model_key, train_rows)
        alert_score = _predict_ml_alert_proba(model_key, bundle, eval_rows)
        if alert_score is None:
            alert_p = np.zeros(len(eval_rows), dtype=int)
            tier_p = ["NORMAL"] * len(eval_rows)
        elif model_key == "logistic_regression":
            X_eval = np.stack([r["features"] for r in eval_rows], axis=0)
            _, _, tier_p = _predict_sklearn_logistic(bundle, X_eval)
            alert_p = alert_proba_to_binary(alert_score, alert_thr)
        elif model_key == "lightgbm":
            X_eval = np.stack([r["features"] for r in eval_rows], axis=0)
            clf_a, clf_t, le = bundle
            _, _, tier_p = _predict_lightgbm(clf_a, clf_t, le, X_eval)
            alert_p = alert_proba_to_binary(alert_score, alert_thr)
        else:
            raise ValueError(f"unknown model: {model_key}")

    out: dict[str, Any] = {
        "model": model_key,
        "n_eval": len(eval_rows),
        "alert_12h": _alert_metrics(y_alert_true, alert_p, alert_score),
        "max_tier_12h": _macro_f1_multiclass(y_tier_true, tier_p),
    }
    if model_key in ML_TUNABLE_KEYS and alert_threshold is not None:
        out["alert_proba_threshold"] = alert_thr
    return out


def _flood_lead_times_classification(
    y: pd.Series,
    eval_rows: list[dict[str, Any]],
    alert_pred: np.ndarray,
    *,
    model_name: str,
) -> dict[str, Any]:
    """Hours from first predicted alert cutoff in flood window to y peak."""
    start = FLOOD_WINDOW_START
    end = FLOOD_WINDOW_END
    y_win = y[(y.index >= start) & (y.index <= end)]
    y_num = pd.to_numeric(y_win, errors="coerce")
    valid = y_num[np.isfinite(y_num)]
    if valid.empty:
        return {"error": "no_valid_y_in_flood_window", "model": model_name}

    peak_t = valid.idxmax()
    peak_ix = int(y.index.get_loc(peak_t))

    pred_T: int | None = None
    act_T: int | None = None
    for r, ap in zip(eval_rows, alert_pred, strict=True):
        T = int(r["cutoff_ix"])
        if T >= peak_ix:
            continue
        t_cut = y.index[T]
        if t_cut < start or t_cut > end:
            continue
        if act_T is None and int(r["alert_12h"]) == 1:
            act_T = T
        if pred_T is None and int(ap) == 1:
            pred_T = T

    out: dict[str, Any] = {
        "model": model_name,
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "y_peak_utc": str(peak_t),
        "y_peak": round(float(valid.max()), 6),
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


def _load_phase_a_reference(phase_a_json: Path | None) -> dict[str, Any] | None:
    if phase_a_json is None or not phase_a_json.is_file():
        return None
    try:
        data = json.loads(phase_a_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    out: dict[str, Any] = {}
    for mode in ("oracle", "persistence"):
        block = (data.get("by_exog_mode") or {}).get(mode, {})
        w = block.get("window_1_12h") or {}
        ra = w.get("recommend_alert") or {}
        out[mode] = {
            "recommend_alert_f1": ra.get("f1"),
            "recommend_alert_precision": ra.get("precision"),
            "recommend_alert_recall": ra.get("recall"),
            "n_cutoffs": w.get("n_cutoffs"),
        }
        fw = block.get("flood_window") or {}
        out[mode]["flood_predicted_lead_hours"] = fw.get("predicted_lead_hours_to_peak")
    pers_bl = (
        ((data.get("by_exog_mode") or {}).get("oracle") or {}).get("baselines") or {}
    ).get("persistence_y", {})
    pw = pers_bl.get("window_1_12h", {}).get("recommend_alert", {})
    out["phase_a_persistence_y_oracle_context"] = {
        "recommend_alert_f1": pw.get("f1"),
    }
    return out


def build_exog_policy(
    *,
    use_exog_ffill: bool,
    use_precip_ffill: bool,
    use_upstream_ffill: bool,
    upstream_ffill_limit: int = UPSTREAM_FFILL_LIMIT_HOURS,
) -> dict[str, Any]:
    """Document exogenous fill policy for risk-class feature lags."""
    return {
        "use_exog_ffill": use_exog_ffill,
        "use_precip_ffill": use_precip_ffill,
        "use_upstream_ffill": use_upstream_ffill,
        "upstream_ffill_limit_hours": int(upstream_ffill_limit),
        "precip_no_ffill_rationale": (
            "Hourly precipitation_mm is an interval accumulation, not a level variable. "
            "Forward-fill would treat missing hours as continuing rain and inflate lag sums; "
            "NaN is kept so dry gaps stay dry in precip lag blocks."
        ),
    }


def compare_risk_class_to_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    baseline_label: str = "exog_ffill_both",
) -> dict[str, Any]:
    """Delta vs a prior holdout JSON (cutoff counts and alert F1 for key models)."""
    focus = ("persistence_alert", "logistic_regression", "lightgbm")
    alert_f1_delta: dict[str, Any] = {}
    for mk in focus:
        cur_f1 = ((current.get("by_model") or {}).get(mk) or {}).get("alert_12h", {}).get("f1")
        base_f1 = ((baseline.get("by_model") or {}).get(mk) or {}).get("alert_12h", {}).get("f1")
        if cur_f1 is not None and base_f1 is not None:
            alert_f1_delta[mk] = round(float(cur_f1) - float(base_f1), 6)
        else:
            alert_f1_delta[mk] = None

    return {
        "baseline_label": baseline_label,
        "baseline_json_spec": baseline.get("spec"),
        "baseline_exog_policy": baseline.get("exog_policy")
        or {"use_exog_ffill": baseline.get("use_exog_ffill")},
        "n_tuning_labeled_cutoffs_baseline": baseline.get("n_tuning_labeled_cutoffs"),
        "n_holdout_labeled_cutoffs_baseline": baseline.get("n_holdout_labeled_cutoffs"),
        "n_tuning_labeled_cutoffs_delta": int(current.get("n_tuning_labeled_cutoffs", 0))
        - int(baseline.get("n_tuning_labeled_cutoffs", 0)),
        "n_holdout_labeled_cutoffs_delta": int(current.get("n_holdout_labeled_cutoffs", 0))
        - int(baseline.get("n_holdout_labeled_cutoffs", 0)),
        "alert_12h_f1_delta": alert_f1_delta,
    }


def format_risk_class_md(result: dict[str, Any]) -> str:
    title = result.get("report_title") or "Turbidity 12h risk classification holdout (Phase A')"
    lines = [
        f"# {title}",
        "",
        f"- Site: `{result.get('site_no')}`",
        f"- Thresholds: `{result.get('thresholds_path')}`",
        f"- Holdout: {result.get('holdout_start_utc')} → {result.get('holdout_end_utc')}",
        f"- Holdout step: **{result.get('holdout_step')}**",
        f"- Min valid future hours (label): **{result.get('min_valid_future_hours')}**",
        f"- Feature lag: {result.get('lag')}",
    ]
    exog = result.get("exog_policy") or {}
    if exog:
        lines.extend(
            [
                "",
                "## Exogenous feature policy",
                "",
                f"- `use_precip_ffill`: **{exog.get('use_precip_ffill')}**",
                f"- `use_upstream_ffill`: **{exog.get('use_upstream_ffill')}** "
                f"(limit {exog.get('upstream_ffill_limit_hours')} h)",
                f"- Tuning labeled cutoffs: **{result.get('n_tuning_labeled_cutoffs')}**",
                f"- Holdout labeled cutoffs: **{result.get('n_holdout_labeled_cutoffs')}**",
                "",
                exog.get("precip_no_ffill_rationale", ""),
            ]
        )
    cmp_ = result.get("comparison_vs_baseline")
    if cmp_:
        lines.extend(
            [
                "",
                f"## Comparison vs {cmp_.get('baseline_label', 'baseline')}",
                "",
                "| Field | Baseline | Current | Delta |",
                "|-------|----------:|--------:|------:|",
                f"| n_tuning cutoffs | {cmp_.get('n_tuning_labeled_cutoffs_baseline')} "
                f"| {result.get('n_tuning_labeled_cutoffs')} "
                f"| {cmp_.get('n_tuning_labeled_cutoffs_delta')} |",
                f"| n_holdout cutoffs | {cmp_.get('n_holdout_labeled_cutoffs_baseline')} "
                f"| {result.get('n_holdout_labeled_cutoffs')} "
                f"| {cmp_.get('n_holdout_labeled_cutoffs_delta')} |",
                "",
                "### alert_12h F1 change",
                "",
            ]
        )
        for mk, delta in (cmp_.get("alert_12h_f1_delta") or {}).items():
            base_f1 = (
                ((cmp_.get("baseline_by_model") or {}).get(mk) or {}).get("alert_12h") or {}
            ).get("f1")
            cur_f1 = ((result.get("by_model") or {}).get(mk) or {}).get("alert_12h", {}).get("f1")
            sign = "+" if delta is not None and delta >= 0 else ""
            delta_s = f"{sign}{delta}" if delta is not None else "n/a"
            lines.append(f"- **{mk}**: {base_f1} → {cur_f1} (Δ {delta_s})")
    lines.extend(
        [
            "",
            "## alert_12h (holdout)",
            "",
            "| Model | Precision | Recall | F1 | PR-AUC |",
            "|-------|----------:|-------:|---:|-------:|",
        ]
    )
    for key in result.get("model_order") or []:
        m = (result.get("by_model") or {}).get(key, {})
        a = m.get("alert_12h") or {}
        lines.append(
            f"| {key} | {a.get('precision')} | {a.get('recall')} | {a.get('f1')} | {a.get('pr_auc')} |"
        )
    lines.extend(
        [
            "",
            "## max_tier_12h (holdout)",
            "",
            "| Model | Accuracy | Macro-F1 |",
            "|-------|----------:|---------:|",
        ]
    )
    for key in result.get("model_order") or []:
        m = (result.get("by_model") or {}).get(key, {})
        t = m.get("max_tier_12h") or {}
        lines.append(f"| {key} | {t.get('accuracy')} | {t.get('macro_f1')} |")

    pa = result.get("phase_a_reference") or {}
    if pa:
        lines.extend(["", "## Phase A ridge reference (recommend_alert F1)", ""])
        for mode in ("oracle", "persistence"):
            if mode in pa:
                lines.append(f"- Ridge {mode}: F1={pa[mode].get('recommend_alert_f1')}")
    lines.extend(["", "## Flood window 2025-12-09 → 2025-12-17", ""])
    for key in result.get("model_order") or []:
        fw = ((result.get("by_model") or {}).get(key) or {}).get("flood_window") or {}
        lines.append(
            f"- **{key}**: pred lead h={fw.get('predicted_lead_hours_to_peak')}, "
            f"actual lead h={fw.get('actual_lead_hours_to_peak')}"
        )

    lt_spec = result.get("lead_time_eval_spec")
    if lt_spec:
        mode = lt_spec.get("lead_time_mode", "event_local")
        lines.extend(
            [
                "",
                "## Lead time before tier upgrade (holdout, step=1)",
                "",
                f"- Mode: **{mode}** — {lt_spec.get('lead_time_definition', '')}",
                f"- Events: NORMAL at T with WATCH+ in T+1..T+12 ({lt_spec.get('n_upgrade_events')} total)",
                f"- No alert before upgrade: omitted from median/mean ({lt_spec.get('no_alert_before_upgrade_policy', '')})",
                "",
                "| Model | Median lead (h) | Mean lead (h) | % with lead | FP (no upgrade 12h) | FP (tier+IF normal) |",
                "|-------|----------------:|--------------:|------------:|--------------------:|---------------------:|",
            ]
        )
        for key in ("persistence_alert", "logistic_regression", "lightgbm"):
            m = (result.get("by_model") or {}).get(key) or {}
            lt = m.get("lead_time_eval") or {}
            lh = lt.get("lead_hours") or {}
            fp = m.get("fp_guardrail") or {}
            fp0 = (fp.get("no_upgrade_12h") or {}).get("fp_rate")
            fpc = (fp.get("control_tier_if_normal") or {}).get("fp_rate")
            lines.append(
                f"| {key} | {lh.get('median_hours')} | {lh.get('mean_hours')} | "
                f"{lt.get('pct_events_with_lead')} | {fp0} | {fpc} |"
            )
        fw_lt = result.get("flood_window_lead_time_summary") or {}
        if fw_lt:
            lines.extend(["", "### Flood window upgrade events (first upgrade in Dec 2025 window)", ""])
            for key, block in fw_lt.items():
                lh = block.get("lead_hours") or {}
                lines.append(
                    f"- **{key}**: n={block.get('n_events')}, median lead={lh.get('median_hours')}h, "
                    f"with lead={block.get('n_with_lead')}"
                )
        cmp_lt = result.get("comparison_leadtime_v2_v3")
        if cmp_lt:
            lines.extend(
                [
                    "",
                    "## Comparison vs lead-time v2 (holdout-wide scan)",
                    "",
                    "| Model | v2 median (h) | v3 median (h) | Δ v3−v2 |",
                    "|-------|-------------:|-------------:|--------:|",
                ]
            )
            for mk, row in (cmp_lt.get("by_model") or {}).items():
                delta = row.get("median_delta_v3_minus_v2")
                delta_s = f"{delta:+.3f}" if delta is not None else "n/a"
                lines.append(
                    f"| {mk} | {row.get('v2_median_hours')} | {row.get('v3_median_hours')} | {delta_s} |"
                )
        launch = result.get("launch_policy") or {}
        if launch:
            lines.extend(
                [
                    "",
                    "## Launch policy",
                    "",
                    f"- Persistence stays default: **{launch.get('persistence_stays_default')}**",
                    f"- Recommended default: **{launch.get('default_launch')}**",
                ]
            )
            for mk, dec in (launch.get("by_model") or {}).items():
                lines.append(
                    f"- {mk}: production_candidate={dec.get('production_candidate')} "
                    f"(beats lead={dec.get('beats_persistence_median_lead')}, "
                    f"fp_ok={dec.get('fp_guardrail_ok')})"
                )
    thr_spec = result.get("threshold_tuning_spec")
    thr_tune = result.get("threshold_tuning") or {}
    if thr_spec:
        lines.extend(
            [
                "",
                "## ML alert probability threshold tuning (tuning → holdout)",
                "",
                f"- Grid: {thr_spec.get('threshold_grid')} (step 0.05)",
                f"- FP guardrail: {thr_spec.get('fp_guardrail')}",
                f"- Tuning dense cutoffs: **{thr_spec.get('n_tuning_dense_cutoffs')}** "
                f"(step={thr_spec.get('tuning_dense_step')})",
                "",
                "| Model | Selected τ | Tuning median lead (h) | Tuning FP (no upgrade) | Holdout median lead (h) | Holdout FP |",
                "|-------|----------:|----------------------:|-----------------------:|------------------------:|-----------:|",
            ]
        )
        for mk in ML_TUNABLE_KEYS:
            sel = float((thr_spec.get("selected_thresholds") or {}).get(mk, 0.5))
            tun = (thr_tune.get("by_model") or {}).get(mk) or {}
            tun_sel = tun.get("selected") or {}
            hold = (result.get("by_model") or {}).get(mk) or {}
            lt_h = (hold.get("lead_time_eval") or {}).get("lead_hours") or {}
            fp_h = (hold.get("fp_guardrail") or {}).get("no_upgrade_12h") or {}
            lines.append(
                f"| {mk} | {sel} | {tun_sel.get('median_lead_hours')} | "
                f"{(tun_sel.get('fp_no_upgrade_12h') or {}).get('fp_rate')} | "
                f"{lt_h.get('median_hours')} | {fp_h.get('fp_rate')} |"
            )
    return "\n".join(lines) + "\n"


def run_risk_class_backtest(
    *,
    features_csv: Path,
    thresholds_json: Path,
    report_dir: Path,
    holdout_step: int = DEFAULT_HOLDOUT_STEP,
    lag: int = DEFAULT_LAG,
    min_valid_future_hours: int = DEFAULT_MIN_VALID_FUTURE_HOURS,
    phase_a_json: Path | None = None,
    write_md: bool = True,
    use_exog_ffill: bool = True,
    use_precip_ffill: bool | None = None,
    use_upstream_ffill: bool | None = None,
    output_basename: str = "risk_class_holdout",
    compare_baseline_json: Path | None = None,
    report_title: str | None = None,
    with_extended_features: bool = False,
    with_univariate_if: bool = False,
    with_multivariate_if: bool = False,
    leadtime_eval: bool = False,
    leadtime_holdout_step: int = 1,
    tuning_step: int | None = None,
    compare_leadtime_v2_json: Path | None = None,
    tune_alert_threshold: bool = False,
    fp_guardrail_ratio: float = DEFAULT_FP_GUARDRAIL_RATIO,
    threshold_grid: tuple[float, ...] = DEFAULT_THRESHOLD_GRID,
    tuning_dense_step: int = 1,
) -> dict[str, Any]:
    """Run Phase A' classification backtest and write JSON (+ optional MD)."""
    csv_path = Path(features_csv)
    thr_path = Path(thresholds_json)
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not csv_path.is_file():
        raise FileNotFoundError(f"features CSV not found: {csv_path}")
    if not thr_path.is_file():
        raise FileNotFoundError(f"thresholds JSON not found: {thr_path}")

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
            MAX_FUTURE_H,
            holdout_fraction=0.2,
            holdout_min_hours=336,
            min_tuning_hours=2000,
        )
        split_ix = int(split_info["split_index"])

    lag_eff = int(min(lag, _effective_lag(n, MAX_LAG)))
    tiers = label_alert_tier(y, thresholds)

    use_extended = bool(
        with_extended_features or with_univariate_if or with_multivariate_if or leadtime_eval
    )
    if_cache: IfScoreCache | None = None
    if use_extended and (with_univariate_if or with_multivariate_if):
        mvar = build_multivar_matrix_from_df(df) if with_multivariate_if else None
        if_cache = IfScoreCache(
            y,
            multivar_matrix=mvar,
            with_univariate=with_univariate_if,
            with_multivariate=with_multivariate_if,
        )
    elif use_extended:
        if_cache = IfScoreCache(y, with_univariate=False, with_multivariate=False)

    def _row_index_range(idx_start: int, idx_end: int, step: int) -> tuple[int, int, int]:
        lag_full = _effective_lag(len(y), MAX_LAG)
        start = max(int(idx_start), lag_full - 1, MIN_HOURLY_POINTS - 1)
        end = min(int(idx_end), len(y) - MAX_FUTURE_H - 1)
        return start, end, max(1, int(step))

    def _warm_if_for_range(idx_start: int, idx_end: int, step: int, *, label: str) -> None:
        if if_cache is None or not (with_univariate_if or with_multivariate_if):
            return
        start, end, st = _row_index_range(idx_start, idx_end, step)
        indices = list(range(start, end + 1, st))
        if not indices:
            return
        n_pending = sum(
            1
            for ix in indices
            if if_cache.needs_warm(
                ix,
                with_univariate_if=with_univariate_if,
                with_multivariate_if=with_multivariate_if,
            )
        )
        print(
            f"Warming IF cache for {label} ({len(indices)} cutoffs, "
            f"{n_pending} pending, step={st})...",
            flush=True,
        )
        warm_if_cache(
            if_cache,
            indices,
            with_univariate_if=with_univariate_if,
            with_multivariate_if=with_multivariate_if,
            log_every=500,
        )

    def _build_rows(idx_start: int, idx_end: int, step: int) -> list[dict[str, Any]]:
        _warm_if_for_range(idx_start, idx_end, step, label="feature build")
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
            with_extended_features=use_extended,
            with_univariate_if=with_univariate_if,
            with_multivariate_if=with_multivariate_if,
        )

    train_step = int(tuning_step) if tuning_step is not None else 1
    if (with_univariate_if or with_multivariate_if) and train_step == 1:
        # IF refit per cutoff is expensive; coarser tuning grid is enough for ML fit.
        train_step = max(holdout_step, 24)
    train_rows = _build_rows(0, split_ix - 1, train_step)
    tuning_rows_dense: list[dict[str, Any]] = []
    if tune_alert_threshold:
        dense_step = max(1, int(tuning_dense_step))
        print(
            f"Building dense tuning cutoffs for threshold sweep (step={dense_step})...",
            flush=True,
        )
        tuning_rows_dense = _build_rows(0, split_ix - 1, dense_step)
    holdout_rows = _build_rows(split_ix, n - 1, holdout_step)
    holdout_rows_leadtime: list[dict[str, Any]] = []
    if leadtime_eval:
        print(
            f"Building dense holdout cutoffs for lead-time (step={leadtime_holdout_step})...",
            flush=True,
        )
        holdout_rows_leadtime = _build_rows(
            split_ix, n - 1, max(1, int(leadtime_holdout_step))
        )

    model_order: list[ModelKey] = [
        "majority_always_normal",
        "persistence_alert",
        "persistence_max_tier",
        "logistic_regression",
        "lightgbm",
    ]
    by_model: dict[str, Any] = {}
    ml_bundles: dict[str, Any] = {}
    for mk in ML_TUNABLE_KEYS:
        ml_bundles[mk] = _fit_ml_bundle(mk, train_rows)

    threshold_tuning: dict[str, Any] | None = None
    selected_thresholds: dict[str, float] = {}
    if tune_alert_threshold and tuning_rows_dense:
        print("Tuning ML alert probability thresholds on tuning cutoffs...", flush=True)
        threshold_tuning = tune_ml_alert_thresholds(
            tiers,
            y,
            train_rows,
            tuning_rows_dense,
            fp_guardrail_ratio=fp_guardrail_ratio,
            threshold_grid=threshold_grid,
            if_cache=if_cache,
        )
        for mk in ML_TUNABLE_KEYS:
            block = (threshold_tuning.get("by_model") or {}).get(mk) or {}
            selected_thresholds[mk] = float(
                block.get("selected_threshold", DEFAULT_ALERT_PROBA_THRESHOLD)
            )

    for mk in model_order:
        alert_thr = (
            selected_thresholds.get(mk)
            if tune_alert_threshold and mk in ML_TUNABLE_KEYS
            else None
        )
        metrics = evaluate_model_on_rows(
            mk,
            train_rows,
            holdout_rows,
            alert_threshold=alert_thr,
            ml_bundle=ml_bundles.get(mk),
        )
        if mk in ("majority_always_normal", "persistence_alert", "persistence_max_tier"):
            alert_p, _, _ = _predict_baseline(mk, holdout_rows)
        elif mk in ML_TUNABLE_KEYS:
            proba = _predict_ml_alert_proba(mk, ml_bundles.get(mk), holdout_rows)
            thr_use = (
                float(alert_thr)
                if alert_thr is not None
                else DEFAULT_ALERT_PROBA_THRESHOLD
            )
            alert_p = (
                alert_proba_to_binary(proba, thr_use)
                if proba is not None
                else np.zeros(len(holdout_rows), dtype=int)
            )
        else:
            alert_p = np.zeros(len(holdout_rows), dtype=int)

        metrics["flood_window"] = _flood_lead_times_classification(
            y, holdout_rows, alert_p, model_name=mk
        )

        if leadtime_eval and holdout_rows_leadtime:
            if mk in ("majority_always_normal", "persistence_alert", "persistence_max_tier"):
                lt_pred, _, _ = _predict_baseline(mk, holdout_rows_leadtime)
            elif mk in ML_TUNABLE_KEYS:
                proba_lt = _predict_ml_alert_proba(mk, ml_bundles.get(mk), holdout_rows_leadtime)
                thr_lt = (
                    float(selected_thresholds[mk])
                    if tune_alert_threshold and mk in selected_thresholds
                    else DEFAULT_ALERT_PROBA_THRESHOLD
                )
                lt_pred = (
                    alert_proba_to_binary(proba_lt, thr_lt)
                    if proba_lt is not None
                    else np.zeros(len(holdout_rows_leadtime), dtype=int)
                )
            else:
                lt_pred = np.zeros(len(holdout_rows_leadtime), dtype=int)

            metrics["lead_time_eval"] = evaluate_upgrade_lead_time(
                tiers,
                y,
                holdout_rows_leadtime,
                lt_pred,
                model_name=mk,
                if_cache=if_cache,
            )
            metrics["fp_guardrail"] = {
                "no_upgrade_12h": _false_positive_rate(holdout_rows_leadtime, lt_pred),
                "control_tier_if_normal": _control_population_fp(
                    holdout_rows_leadtime, lt_pred, if_cache
                ),
            }
            if tune_alert_threshold and mk in ML_TUNABLE_KEYS:
                metrics["alert_proba_threshold"] = float(
                    selected_thresholds.get(mk, DEFAULT_ALERT_PROBA_THRESHOLD)
                )
                metrics["alert_12h_at_default_threshold"] = evaluate_model_on_rows(
                    mk,
                    train_rows,
                    holdout_rows_leadtime,
                    alert_threshold=DEFAULT_ALERT_PROBA_THRESHOLD,
                    ml_bundle=ml_bundles.get(mk),
                ).get("alert_12h")

        by_model[mk] = metrics

    if phase_a_json is None:
        default_pa = out_dir.parent / "turbidity_risk_forecast_12117500" / "risk_forecast_holdout.json"
        phase_a_json = default_pa if default_pa.is_file() else None

    spec_name = "turbidity_risk_class_holdout_phase_a_prime"
    if tune_alert_threshold:
        spec_name = "turbidity_risk_class_holdout_leadtime_v4_threshold"
    elif leadtime_eval:
        spec_name = (
            "turbidity_risk_class_holdout_leadtime_v3"
            if "v3" in output_basename
            else "turbidity_risk_class_holdout_leadtime_v2"
        )
    result: dict[str, Any] = {
        "spec": spec_name,
        "site_no": thresholds.get("site_no", DEFAULT_SITE_NO),
        "tier_model_version": thresholds.get("model_version", MODEL_VERSION),
        "features_csv": str(csv_path.resolve()),
        "thresholds_path": str(thr_path.resolve()),
        "split_index": split_ix,
        "split_time_utc": str(y.index[split_ix]),
        "holdout_start_utc": str(y.index[split_ix]),
        "holdout_end_utc": str(y.index[-1]),
        "holdout_step": int(holdout_step),
        "lag": lag_eff,
        "feature_dim": (
            extended_feature_dim(
                lag_eff,
                has_upstream=q_up is not None,
                with_univariate_if=with_univariate_if,
                with_multivariate_if=with_multivariate_if,
            )
            if use_extended
            else _feat_dim_no_temp(lag_eff, has_upstream=q_up is not None)
        ),
        "extended_features": {
            "enabled": use_extended,
            "precip_sum_windows_h": [6, 12, 24],
            "upstream_q_diff_1h": q_up is not None,
            "upstream_rolling_max_h": [6, 12, 24] if q_up is not None else [],
            "with_univariate_if": with_univariate_if,
            "with_multivariate_if": with_multivariate_if,
            "if_hyperparams": {
                "min_hourly_points": 72,
                "max_train_points": 2500,
                "contamination": 0.05,
            },
        },
        "min_valid_future_hours": int(min_valid_future_hours),
        "label_definitions": {
            "alert_12h": "1 if max quality tier in (T+1..T+12) is WATCH/HIGH/CRITICAL else 0",
            "max_tier_12h": "max ordinal among quality tiers in (T+1..T+12)",
            "skip_rule": f"cutoff skipped when < {min_valid_future_hours} valid future y hours in 1..12",
        },
        "exog_columns": ["precipitation_mm"]
        + ([UPSTREAM_DISCHARGE_COL] if q_up is not None else []),
        "use_exog_ffill": bool(precip_ffill and upstream_ffill),
        "exog_policy": exog_policy,
        "tuning_step": train_step,
        "n_tuning_labeled_cutoffs": len(train_rows),
        "n_holdout_labeled_cutoffs": len(holdout_rows),
        "model_order": model_order,
        "by_model": by_model,
        "phase_a_reference": _load_phase_a_reference(phase_a_json),
    }
    if threshold_tuning is not None:
        result["threshold_tuning"] = threshold_tuning
        result["threshold_tuning_spec"] = {
            "tuning_dense_step": int(tuning_dense_step) if tune_alert_threshold else None,
            "n_tuning_dense_cutoffs": len(tuning_rows_dense),
            "threshold_grid": list(threshold_grid),
            "fp_guardrail": (
                "fp_rate(alert_12h=0) on tuning <= persistence_fp * "
                f"{fp_guardrail_ratio}"
            ),
            "selection_objective": "maximize event-local median lead hours among FP-ok thresholds",
            "holdout_evaluation": "apply selected threshold to holdout only (no holdout tuning)",
            "selected_thresholds": selected_thresholds,
        }
    if leadtime_eval:
        n_events = sum(
            1
            for r in holdout_rows_leadtime
            if is_tier_upgrade_event(r)
        )
        result["lead_time_eval_spec"] = {
            "holdout_step_dense": int(leadtime_holdout_step),
            "n_holdout_dense_cutoffs": len(holdout_rows_leadtime),
            "n_upgrade_events": n_events,
            "event_definition": "NORMAL at T with max tier WATCH+ in T+1..T+12",
            "lead_time_mode": "event_local",
            "lead_time_definition": (
                "hours from first predicted alert_12h=1 at cutoff in [T, first_upgrade) "
                "to first WATCH+ hour; capped at min(12, upgrade-T)"
            ),
            "prediction_scan_window": "[T, min(T+12, first_upgrade_ix - 1)]",
            "no_alert_before_upgrade_policy": "lead_hours=null, excluded from median/mean",
        }
        result["flood_window_lead_time_summary"] = {
            mk: ((by_model.get(mk) or {}).get("lead_time_eval") or {}).get("flood_window")
            for mk in ("persistence_alert", "logistic_regression", "lightgbm")
        }
        result["launch_policy"] = assess_launch_policy(by_model)
        if compare_leadtime_v2_json is not None and compare_leadtime_v2_json.is_file():
            v2_data = json.loads(compare_leadtime_v2_json.read_text(encoding="utf-8"))
            if tune_alert_threshold:
                result["comparison_leadtime_prior"] = compare_leadtime_v2_v3(result, v2_data)
            else:
                result["comparison_leadtime_v2_v3"] = compare_leadtime_v2_v3(result, v2_data)
    if report_title:
        result["report_title"] = report_title

    if compare_baseline_json is not None and compare_baseline_json.is_file():
        baseline = json.loads(compare_baseline_json.read_text(encoding="utf-8"))
        cmp = compare_risk_class_to_baseline(result, baseline)
        cmp["baseline_by_model"] = {
            k: {"alert_12h": (baseline.get("by_model") or {}).get(k, {}).get("alert_12h")}
            for k in ("persistence_alert", "logistic_regression", "lightgbm")
        }
        result["comparison_vs_baseline"] = cmp

    json_path = out_dir / f"{output_basename}.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    md_path = out_dir / f"{output_basename}.md"
    if write_md:
        md_path.write_text(format_risk_class_md(result), encoding="utf-8")
    result["outputs"] = {"json": str(json_path), "md": str(md_path) if write_md else None}
    return result

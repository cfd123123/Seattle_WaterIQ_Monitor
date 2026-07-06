#!/usr/bin/env python3
"""
Unified walk-forward benchmark for 00060 (exclude selected sites).

Models covered:
- ridge_recursive
- ridge_direct
- lightgbm_direct (falls back to HistGradientBoosting when lightgbm is unavailable)
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
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from forecast_engine import (
    FORECAST_MODEL_VERSION,
    MAX_LAG,
    MIN_HOURLY_POINTS,
    _effective_lag,
    _recursive_train_and_predict_at_cutoff,
    load_hourly_series,
    ridge_direct_predict_at_cutoff,
    slice_series_upto_cutoff,
)

try:
    from lightgbm import LGBMRegressor  # type: ignore

    _HAS_LIGHTGBM = True
except Exception:
    LGBMRegressor = None  # type: ignore
    _HAS_LIGHTGBM = False


def _metrics(pred: np.ndarray, actual: np.ndarray) -> dict[str, float | int]:
    pred = pred.astype(float)
    actual = actual.astype(float)
    err = pred - actual
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    denom = (np.abs(actual) + np.abs(pred) + 1e-9) / 2.0
    smape = float(np.mean(np.abs(err) / denom) * 100.0)
    mask = np.abs(actual) > 1e-6
    mape = float(np.mean(np.abs(err[mask] / actual[mask])) * 100.0) if np.any(mask) else float("nan")
    corr = float("nan")
    if len(pred) >= 2:
        c = np.corrcoef(pred, actual)[0, 1]
        corr = float(c) if not np.isnan(c) else float("nan")
    dir_acc = float("nan")
    if len(pred) >= 2:
        dp = np.diff(pred)
        da = np.diff(actual)
        ok = (dp != 0) & (da != 0)
        if np.any(ok):
            dir_acc = float(np.mean(np.sign(dp[ok]) == np.sign(da[ok])) * 100.0)
    return {
        "n": int(len(pred)),
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
        "smape_pct": round(smape, 4),
        "mape_pct": round(mape, 4) if not np.isnan(mape) else float("nan"),
        "pred_actual_corr": round(corr, 6) if not np.isnan(corr) else float("nan"),
        "directional_accuracy_pct": round(dir_acc, 4) if not np.isnan(dir_acc) else float("nan"),
    }


def _ai_service_root() -> Path:
    d = Path(__file__).resolve().parent
    return d.parent if d.name == "models" else d


_ROOT = _ai_service_root()
for _p in (_ROOT, _ROOT / "models"):
    sp = str(_p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


def _parse_horizons(s: str) -> list[int]:
    s = str(s).strip()
    if s == "1-12":
        return list(range(1, 13))
    return [int(x.strip()) for x in s.split(",") if x.strip()]


_ALLOWED_MODEL_SUITE = ("ridge_recursive", "ridge_direct", "lightgbm_direct")


def _parse_model_names(s: str) -> list[str]:
    """Comma-separated model subset; preserves order, de-duplicates."""
    raw = [x.strip() for x in str(s).split(",") if x.strip()]
    if not raw:
        raise SystemExit("--models must list at least one model name")
    out: list[str] = []
    for name in raw:
        if name not in _ALLOWED_MODEL_SUITE:
            raise SystemExit(
                f"Unknown model {name!r}; allowed: {', '.join(_ALLOWED_MODEL_SUITE)}"
            )
        if name not in out:
            out.append(name)
    return out


def _models_to_plan_list(model_names: list[str], tree_backend: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in model_names:
        if m == "ridge_recursive":
            rows.append({"model": m, "notes": "online baseline style"})
        elif m == "ridge_direct":
            rows.append({"model": m, "notes": "horizon-specific direct ridge"})
        elif m == "lightgbm_direct":
            rows.append(
                {
                    "model": "lightgbm_direct",
                    "notes": "tree direct model; fallback to HistGradientBoosting when lightgbm is unavailable",
                    "backend": tree_backend,
                }
            )
    return rows


def _adaptive_lag(n: int) -> int:
    return _effective_lag(n, MAX_LAG)


def _fit_predict_tree_direct_calendar(
    sub: pd.Series,
    idx_cutoff: int,
    horizon: int,
    *,
    lag: int,
    lgbm_extra: dict[str, Any] | None = None,
    full_series: pd.Series | None = None,
    full_idx_cutoff: int | None = None,
) -> tuple[float | None, str | None]:
    h = int(horizon)
    rows_x: list[np.ndarray] = []
    rows_y: list[float] = []
    for o in range(lag - 1, idx_cutoff - h + 1):
        w = sub.iloc[o - lag + 1 : o + 1]
        if int(w.shape[0]) != lag or not w.notna().all():
            continue
        if pd.isna(sub.iloc[o + h]):
            continue
        rows_x.append(w.to_numpy(dtype=float, copy=False))
        rows_y.append(float(sub.iloc[o + h]))
    if len(rows_y) < 20:
        return None, "insufficient_history"
    w_test = sub.iloc[idx_cutoff - lag + 1 : idx_cutoff + 1]
    if int(w_test.shape[0]) != lag or not w_test.notna().all():
        return None, "invalid_cutoff"
    if full_series is not None and full_idx_cutoff is not None:
        gi = int(full_idx_cutoff)
        if gi + h >= len(full_series) or gi < 0:
            return None, "horizon_beyond_series"
        if pd.isna(full_series.iloc[gi + h]):
            return None, "invalid_cutoff"
    else:
        if idx_cutoff + h >= len(sub):
            return None, "horizon_beyond_series"
        if pd.isna(sub.iloc[idx_cutoff + h]):
            return None, "invalid_cutoff"
    X = np.stack(rows_x, axis=0)
    y_tr = np.asarray(rows_y, dtype=float)
    x_test = w_test.to_numpy(dtype=float, copy=False).reshape(1, -1)
    try:
        model = _build_tree_direct_model(lgbm_extra=lgbm_extra)
        model.fit(X, y_tr)
        pred = float(model.predict(x_test)[0])
    except ValueError:
        return None, "fit_failed"
    return pred, None


def _build_tree_direct_model(lgbm_extra: dict[str, Any] | None = None) -> Any:
    if _HAS_LIGHTGBM and LGBMRegressor is not None:
        base: dict[str, Any] = {
            "objective": "regression",
            "n_estimators": 40,
            "learning_rate": 0.1,
            "num_leaves": 15,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": 42,
            "verbosity": -1,
            "n_jobs": 1,
        }
        if lgbm_extra:
            extra = {k: v for k, v in lgbm_extra.items() if k != "random_state"}
            base.update(extra)
            base["random_state"] = int(lgbm_extra.get("random_state", base["random_state"]))
        return LGBMRegressor(**base)
    if lgbm_extra:
        pass
    return HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.1,
        max_depth=4,
        max_iter=50,
        min_samples_leaf=20,
        random_state=42,
    )


def _walk_forward(
    s: pd.Series,
    horizon: int,
    *,
    step: int,
    model_name: str,
    ridge_alpha: float,
    max_cutoffs: int,
    history_window_hours: int,
    lgbm_extra: dict[str, Any] | None = None,
) -> tuple[np.ndarray, np.ndarray, int]:
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
        sub, loc = slice_series_upto_cutoff(s, idx_T, history_window_hours)
        if loc < 0:
            skipped += 1
            continue
        lag = _effective_lag(len(sub), MAX_LAG)
        if model_name == "ridge_recursive":
            p, err = _recursive_train_and_predict_at_cutoff(
                sub,
                loc,
                h,
                lag,
                ridge_alpha=ridge_alpha,
                require_actual_at_horizon=True,
                full_series=s,
                full_idx_cutoff=idx_T,
            )
        elif model_name == "ridge_direct":
            p, err = ridge_direct_predict_at_cutoff(
                sub, loc, h, lag, ridge_alpha=ridge_alpha, full_series=s, full_idx_cutoff=idx_T
            )
        elif model_name == "lightgbm_direct":
            p, err = _fit_predict_tree_direct_calendar(
                sub, loc, h, lag=lag, lgbm_extra=lgbm_extra, full_series=s, full_idx_cutoff=idx_T
            )
        else:
            raise ValueError(f"unsupported model_name: {model_name}")
        if p is None or err is not None:
            skipped += 1
            continue
        preds.append(p)
        actuals.append(float(s.iloc[idx_T + h]))
    return np.asarray(preds, dtype=float), np.asarray(actuals, dtype=float), skipped


def _safe_float(v: Any) -> float:
    try:
        x = float(v)
    except Exception:
        return math.inf
    return x if np.isfinite(x) else math.inf


def _summarize_model(model_horizons: dict[str, dict[str, Any]]) -> dict[str, Any]:
    smapes: list[float] = []
    maes: list[float] = []
    rmses: list[float] = []
    corr_vals: list[float] = []
    dir_vals: list[float] = []
    n_total = 0
    h_ok = 0
    for block in model_horizons.values():
        if "error" in block:
            continue
        h_ok += 1
        n_total += int(block.get("n", 0))
        smapes.append(float(block["smape_pct"]))
        maes.append(float(block["mae"]))
        rmses.append(float(block["rmse"]))
        c = _safe_float(block.get("pred_actual_corr", float("nan")))
        if np.isfinite(c):
            corr_vals.append(c)
        d = _safe_float(block.get("directional_accuracy_pct", float("nan")))
        if np.isfinite(d):
            dir_vals.append(d)
    return {
        "horizons_evaluated": h_ok,
        "total_eval_points": n_total,
        "mean_smape_pct": round(float(np.mean(smapes)), 6) if smapes else float("nan"),
        "mean_mae": round(float(np.mean(maes)), 6) if maes else float("nan"),
        "mean_rmse": round(float(np.mean(rmses)), 6) if rmses else float("nan"),
        "mean_pred_actual_corr": round(float(np.mean(corr_vals)), 6) if corr_vals else float("nan"),
        "mean_directional_accuracy_pct": round(float(np.mean(dir_vals)), 6) if dir_vals else float("nan"),
    }


def _load_sites_from_config(config_path: Path, excluded_sites: set[str]) -> list[str]:
    raw = config_path.read_text(encoding="utf-8")
    # Allow JSONC-style single-line comments in local config files.
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Unified benchmark for 00060 model suite (horizon 1..12)")
    p.add_argument("--iv-csv", default=str(_ROOT / "data" / "usgs_puget_iv.csv"))
    p.add_argument(
        "--sites-config",
        default=str(_ROOT / "config" / "usgs_puget_default_sites.json"),
    )
    p.add_argument("--parameter-cd", default="00060")
    p.add_argument("--exclude-sites", default="12147600")
    p.add_argument("--horizons", default="1-12")
    p.add_argument("--step", type=int, default=1)
    p.add_argument(
        "--max-cutoffs",
        type=int,
        default=720,
        help="Evaluate latest N cutoffs per horizon (step is still applied).",
    )
    p.add_argument(
        "--history-window-hours",
        type=int,
        default=1440,
        help="Use latest N history hours for each cutoff fit to keep runtime bounded.",
    )
    p.add_argument("--ridge-alpha", type=float, default=50.0)
    p.add_argument(
        "--out-dir",
        default=str(_ROOT / "reports" / "model_suite_00060_h1_12_step1"),
    )
    p.add_argument(
        "--lgbm-params-json",
        default="",
        help=(
            "Optional JSON: {\"12117000\": {\"n_estimators\": ...}, ...} per-site LightGBM kwargs "
            "(from tune_lightgbm_direct_00060.py best_params)."
        ),
    )
    p.add_argument(
        "--models",
        default="ridge_recursive,ridge_direct,lightgbm_direct",
        help=(
            "Comma-separated subset of ridge_recursive,ridge_direct,lightgbm_direct. "
            "Smoke runs: e.g. ridge_recursive,ridge_direct to skip tree re-fits per cutoff."
        ),
    )
    return p.parse_args()


def _load_lgbm_by_site(path_str: str) -> dict[str, dict[str, Any]]:
    if not str(path_str).strip():
        return {}
    p = Path(path_str)
    if not p.is_file():
        raise SystemExit(f"Missing --lgbm-params-json: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(v, dict) and "best_params" in v:
            out[str(k).strip()] = dict(v["best_params"])
        elif isinstance(v, dict):
            out[str(k).strip()] = dict(v)
    return out


def main() -> None:
    args = parse_args()
    csv_path = Path(args.iv_csv)
    config_path = Path(args.sites_config)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not csv_path.is_file():
        raise SystemExit(f"Missing IV CSV: {csv_path}")
    if not config_path.is_file():
        raise SystemExit(f"Missing sites config: {config_path}")

    excluded_sites = {x.strip() for x in str(args.exclude_sites).split(",") if x.strip()}
    horizons = _parse_horizons(args.horizons)
    model_candidates = _parse_model_names(str(args.models))
    tree_backend = "lightgbm" if _HAS_LIGHTGBM else "hist_gradient_boosting_fallback"
    sites = _load_sites_from_config(config_path, excluded_sites)
    lgbm_by_site = _load_lgbm_by_site(str(args.lgbm_params_json))

    plan_payload = {
        "business_target": "predict next 1..12 hours",
        "parameter_cd": str(args.parameter_cd),
        "excluded_sites": sorted(excluded_sites),
        "sites_under_test": sites,
        "walk_forward_step": int(args.step),
        "horizons": horizons,
        "models_to_test": _models_to_plan_list(model_candidates, tree_backend),
    }
    (out_dir / "model_test_plan_00060.json").write_text(
        json.dumps(plan_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=== Model suite backtest for parameter 00060 ===")
    print(f"iv_csv={csv_path.resolve()}")
    print(f"sites={sites}")
    print(f"excluded_sites={sorted(excluded_sites)}")
    print(f"horizons={horizons} step={args.step} ridge_alpha={args.ridge_alpha}")
    print(f"max_cutoffs={args.max_cutoffs} history_window_hours={args.history_window_hours}")
    print(f"tree_backend={tree_backend}")
    print(f"models={model_candidates}", flush=True)
    if lgbm_by_site:
        print(f"lgbm per-site overrides: {sorted(lgbm_by_site.keys())}")

    global_rows: list[dict[str, Any]] = []
    routing: dict[str, dict[str, Any]] = {}
    site_reports: dict[str, dict[str, Any]] = {}

    for site_no in sites:
        print(f"=== site {site_no} ===", flush=True)
        s = load_hourly_series(csv_path, site_no, args.parameter_cd, dense=False)
        if s.empty:
            continue
        lgbm_extra = lgbm_by_site.get(site_no)
        site_block: dict[str, Any] = {
            "site_no": site_no,
            "parameter_cd": args.parameter_cd,
            "series_grid_hours": int(len(s)),
            "time_range_utc": [s.index[0].isoformat(), s.index[-1].isoformat()],
            "horizons": horizons,
            "step": int(args.step),
            "ridge_alpha": float(args.ridge_alpha),
            "tree_backend": tree_backend,
            "lightgbm_params_override": lgbm_extra,
            "models": {},
        }
        for model_name in model_candidates:
            h_block: dict[str, Any] = {}
            for h in horizons:
                pred, actual, skipped = _walk_forward(
                    s,
                    h,
                    step=args.step,
                    model_name=model_name,
                    ridge_alpha=float(args.ridge_alpha),
                    max_cutoffs=int(args.max_cutoffs),
                    history_window_hours=int(args.history_window_hours),
                    lgbm_extra=lgbm_extra if model_name == "lightgbm_direct" else None,
                )
                if len(pred) == 0:
                    h_block[str(h)] = {"error": "no_valid_predictions", "skipped_cutoffs": skipped}
                else:
                    m = _metrics(pred, actual)
                    m["skipped_cutoffs"] = skipped
                    h_block[str(h)] = m
            summary = _summarize_model(h_block)
            site_block["models"][model_name] = {"summary": summary, "horizons": h_block}
            global_rows.append(
                {
                    "site_no": site_no,
                    "parameter_cd": args.parameter_cd,
                    "model_name": model_name,
                    "tree_backend": tree_backend if model_name == "lightgbm_direct" else "",
                    "horizons_evaluated": summary["horizons_evaluated"],
                    "total_eval_points": summary["total_eval_points"],
                    "mean_smape_pct": summary["mean_smape_pct"],
                    "mean_mae": summary["mean_mae"],
                    "mean_rmse": summary["mean_rmse"],
                    "mean_pred_actual_corr": summary["mean_pred_actual_corr"],
                    "mean_directional_accuracy_pct": summary["mean_directional_accuracy_pct"],
                }
            )
            print(f"  finished model={model_name} ({len(horizons)} horizons)", flush=True)

        ranking = sorted(
            [
                {
                    "model_name": m,
                    "mean_smape_pct": _safe_float(site_block["models"][m]["summary"]["mean_smape_pct"]),
                    "mean_mae": _safe_float(site_block["models"][m]["summary"]["mean_mae"]),
                    "horizons_evaluated": int(site_block["models"][m]["summary"]["horizons_evaluated"]),
                }
                for m in model_candidates
            ],
            key=lambda x: (x["mean_smape_pct"], x["mean_mae"], -x["horizons_evaluated"]),
        )
        winner = ranking[0]
        rationale = (
            f"{winner['model_name']} has the lowest mean sMAPE ({winner['mean_smape_pct']:.4f}%), "
            f"with mean MAE {winner['mean_mae']:.6f} over {winner['horizons_evaluated']} horizons."
        )
        routing[site_no] = {
            "recommended_model": winner["model_name"],
            "ranking": ranking,
            "reason": rationale,
        }
        site_block["routing_recommendation"] = routing[site_no]
        site_reports[site_no] = site_block
        (out_dir / f"{site_no}_{args.parameter_cd}_model_suite.json").write_text(
            json.dumps(site_block, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    summary_csv = out_dir / "summary_by_site_model.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "site_no",
                "parameter_cd",
                "model_name",
                "tree_backend",
                "horizons_evaluated",
                "total_eval_points",
                "mean_smape_pct",
                "mean_mae",
                "mean_rmse",
                "mean_pred_actual_corr",
                "mean_directional_accuracy_pct",
            ],
        )
        writer.writeheader()
        writer.writerows(global_rows)

    routing_json = out_dir / "routing_recommendation_by_site.json"
    routing_json.write_text(
        json.dumps(
            {
                "business_target": "next 1..12h forecast for 00060",
                "tree_backend": tree_backend,
                "route_by_site": routing,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    merged_json = out_dir / "summary_by_site_model.json"
    merged_json.write_text(
        json.dumps(
            {
                "model_version": FORECAST_MODEL_VERSION,
                "parameter_cd": args.parameter_cd,
                "excluded_sites": sorted(excluded_sites),
                "horizons": horizons,
                "step": int(args.step),
                "max_cutoffs": int(args.max_cutoffs),
                "history_window_hours": int(args.history_window_hours),
                "ridge_alpha": float(args.ridge_alpha),
                "tree_backend": tree_backend,
                "models": model_candidates,
                "sites": site_reports,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"Written: {summary_csv}")
    print(f"Written: {merged_json}")
    print(f"Written: {routing_json}")
    print(f"Written per-site json count={len(site_reports)}")


if __name__ == "__main__":
    main()

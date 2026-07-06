#!/usr/bin/env python3
"""
00060 walk-forward: lag-only baseline vs internal derived features (1h / 3h flow deltas).

Derived (causal at row end index o, hours <= o only):
  - delta_1h = y[o] - y[o-1]
  - delta_3h = y[o] - y[o-3]

Also reports persistence and seasonal-lag-24h baselines on the same cutoffs (per horizon).

Example:
  .venv/bin/python models/backtest_flow_00060_internal_compare.py \\
    --features-dir data/features_00060_openmeteo \\
    --step 24 --max-cutoffs 0 --out-dir reports/flow_00060_internal_compare_2y
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "models"):
    sp = str(_p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

warnings.filterwarnings(
    "ignore",
    message=".*feature names.*",
    category=UserWarning,
    module="sklearn.utils.validation",
)

from backtest_model_suite_00060 import (  # noqa: E402
    _HAS_LIGHTGBM,
    _load_lgbm_by_site,
    _load_sites_from_config,
    _metrics,
    _parse_horizons,
    _summarize_model,
    _walk_forward,
)
from backtest_turbidity_exog_ridge_lgbm import _as_lgbm_frame, _lag_matrix_block  # noqa: E402
from forecast_engine import MAX_LAG, MIN_HOURLY_POINTS, _effective_lag, slice_series_upto_cutoff  # noqa: E402

try:
    from lightgbm import LGBMRegressor  # type: ignore
except Exception:
    LGBMRegressor = None  # type: ignore

TARGET_COL = "00060"
INTERNAL_EXTRA = 2  # delta_1h, delta_3h


def load_flow_y(csv_path: Path) -> pd.Series:
    df = pd.read_csv(csv_path)
    if "datetime_utc" not in df.columns:
        raise ValueError(f"{csv_path}: missing datetime_utc")
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["datetime_utc"]).sort_values("datetime_utc").drop_duplicates("datetime_utc", keep="last")
    df = df.set_index("datetime_utc")
    if TARGET_COL not in df.columns:
        raise ValueError(f"{csv_path}: missing {TARGET_COL}")
    return df[TARGET_COL].astype(float)


def _flow_deltas_at(y: pd.Series, end_ix: int) -> np.ndarray | None:
    """Return [delta_1h, delta_3h] at end_ix; None if history insufficient or non-finite."""
    if end_ix < 3:
        return None
    v0 = float(y.iloc[end_ix])
    v1 = float(y.iloc[end_ix - 1])
    v3 = float(y.iloc[end_ix - 3])
    if not np.isfinite([v0, v1, v3]).all():
        return None
    return np.array([v0 - v1, v0 - v3], dtype=float)


def _y_internal_features_at(y: pd.Series, end_ix: int, lag: int) -> np.ndarray | None:
    wy = _lag_matrix_block(y, end_ix, lag)
    d = _flow_deltas_at(y, end_ix)
    if wy is None or d is None:
        return None
    return np.concatenate([wy, d], axis=0)


def walk_forward_direct_y_internal(
    y: pd.Series,
    horizon: int,
    *,
    lag: int,
    step: int,
    max_cutoffs: int,
    history_window_hours: int,
    model_kind: str,
    ridge_alpha: float,
    lgbm_params: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    h = int(horizon)
    step = max(1, int(step))
    n = len(y)
    lag_full = _effective_lag(n, MAX_LAG)
    lag = int(min(lag, lag_full))
    idx_start = max(MIN_HOURLY_POINTS - 1, lag_full)
    if max_cutoffs > 0:
        idx_start = max(idx_start, (n - h) - int(max_cutoffs))
    preds: list[float] = []
    actuals: list[float] = []
    cutoffs: list[int] = []
    skipped = 0

    for idx_T in range(idx_start, n - h, step):
        if pd.isna(y.iloc[idx_T + h]):
            skipped += 1
            continue
        sub_y, loc = slice_series_upto_cutoff(y, idx_T, history_window_hours)
        if loc < 0:
            skipped += 1
            continue
        lag_loc = int(min(lag, _effective_lag(len(sub_y), MAX_LAG)))
        feat_dim = lag_loc + INTERNAL_EXTRA
        rows_x: list[np.ndarray] = []
        rows_yy: list[float] = []
        for o in range(lag_loc - 1, loc - h + 1):
            g = idx_T - loc + o
            row = _y_internal_features_at(y, g, lag_loc)
            if row is None:
                continue
            if pd.isna(y.iloc[g + h]):
                continue
            rows_x.append(row)
            rows_yy.append(float(y.iloc[g + h]))
        if len(rows_yy) < 20:
            skipped += 1
            continue
        x_row = _y_internal_features_at(y, idx_T, lag_loc)
        if x_row is None:
            skipped += 1
            continue
        X = np.stack(rows_x, axis=0)
        y_tr = np.asarray(rows_yy, dtype=float)
        x_test = x_row.reshape(1, -1)
        if X.shape[1] != feat_dim:
            skipped += 1
            continue
        try:
            if model_kind == "direct_ridge":
                m = Ridge(alpha=float(ridge_alpha))
                m.fit(X, y_tr)
                pred = float(m.predict(x_test)[0])
            else:
                if LGBMRegressor is None:
                    skipped += 1
                    continue
                m = LGBMRegressor(
                    objective="regression",
                    random_state=int(lgbm_params.get("random_state", 42)),
                    verbosity=-1,
                    n_jobs=1,
                    **{k: v for k, v in lgbm_params.items() if k != "random_state"},
                )
                m.fit(_as_lgbm_frame(X), y_tr)
                pred = float(m.predict(_as_lgbm_frame(x_test))[0])
        except ValueError:
            skipped += 1
            continue
        preds.append(pred)
        actuals.append(float(y.iloc[idx_T + h]))
        cutoffs.append(int(idx_T))
    return (
        np.asarray(preds, dtype=float),
        np.asarray(actuals, dtype=float),
        skipped,
        np.asarray(cutoffs, dtype=np.int64),
    )


def _baseline_pairs(y: pd.Series, cutoffs: np.ndarray, h: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    ci = cutoffs.astype(np.int64, copy=False)
    h = int(h)
    pers_p = y.iloc[ci].to_numpy(dtype=float, copy=False)
    pers_a = y.iloc[ci + h].to_numpy(dtype=float, copy=False)
    lag_ix = ci + h - 24
    ok = lag_ix >= 0
    seas_p = np.full(ci.shape[0], np.nan, dtype=float)
    if np.any(ok):
        seas_p[ok] = y.iloc[lag_ix[ok]].to_numpy(dtype=float, copy=False)
    seas_a = pers_a.copy()
    seas_mask = ok & np.isfinite(seas_p) & np.isfinite(seas_a)
    return pers_p, pers_a, seas_p, seas_mask


def _per_horizon_table(
    horizons: list[int],
    model_by_h: dict[int, dict[str, Any]],
    pers_by_h: dict[int, dict[str, Any]],
    seas_by_h: dict[int, dict[str, Any]],
    internal_by_h: dict[int, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for h in horizons:
        mb = model_by_h.get(h, {})
        pb = pers_by_h.get(h, {})
        sb = seas_by_h.get(h, {})
        ib = (internal_by_h or {}).get(h, {})
        sm_m = mb.get("smape_pct")
        sm_p = pb.get("smape_pct")
        sm_i = ib.get("smape_pct")
        row: dict[str, Any] = {
            "h": h,
            "ridge_direct_smape_pct": sm_m,
            "persistence_smape_pct": sm_p,
            "seasonal_lag24_smape_pct": sb.get("smape_pct"),
            "n_model": mb.get("n", 0),
        }
        if sm_m is not None and sm_p is not None:
            row["ridge_minus_persistence_smape_pct"] = round(float(sm_m - sm_p), 4)
        if sm_i is not None and sm_m is not None:
            row["internal_minus_ridge_smape_pct"] = round(float(sm_i - sm_m), 4)
        rows.append(row)
    return rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="00060 lag baseline vs internal delta features")
    p.add_argument("--features-dir", default=str(_ROOT / "data" / "features_00060_openmeteo"))
    p.add_argument(
        "--sites-config",
        default=str(_ROOT / "config" / "usgs_puget_default_sites.json"),
    )
    p.add_argument("--exclude-sites", default="12147600")
    p.add_argument("--horizons", default="1-12")
    p.add_argument("--step", type=int, default=24)
    p.add_argument(
        "--max-cutoffs",
        type=int,
        default=0,
        help="0 = all valid cutoffs; >0 limits evaluation to the last N hour indices.",
    )
    p.add_argument("--history-window-hours", type=int, default=1440)
    p.add_argument("--ridge-alpha", type=float, default=50.0)
    p.add_argument("--lgbm-params-json", default=str(_ROOT / "reports" / "lgbm_tune_step1" / "lgbm_best_by_site.json"))
    p.add_argument("--out-dir", default=str(_ROOT / "reports" / "flow_00060_internal_compare_2y"))
    p.add_argument(
        "--models",
        default="ridge_direct,lightgbm_direct,ridge_direct_internal,lightgbm_direct_internal",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    features_dir = Path(args.features_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    excluded = {x.strip() for x in str(args.exclude_sites).split(",") if x.strip()}
    sites = _load_sites_from_config(Path(args.sites_config), excluded)
    horizons = _parse_horizons(args.horizons)
    lgbm_by_site = _load_lgbm_by_site(str(args.lgbm_params_json))
    wanted = {x.strip() for x in str(args.models).split(",") if x.strip()}

    site_reports: dict[str, Any] = {}
    summary_rows: list[dict[str, Any]] = []

    print("=== 00060 lag baseline vs internal deltas (1h, 3h) ===", flush=True)
    print(f"features_dir={features_dir.resolve()} step={args.step} max_cutoffs={args.max_cutoffs}", flush=True)

    for site_no in sites:
        feat_path = features_dir / f"features_{site_no}_{TARGET_COL}_openmeteo.csv"
        if not feat_path.is_file():
            print(f"  skip {site_no}: missing {feat_path}", flush=True)
            continue
        y = load_flow_y(feat_path)
        lgbm_extra = lgbm_by_site.get(site_no)
        site_block: dict[str, Any] = {
            "site_no": site_no,
            "features_csv": str(feat_path.resolve()),
            "internal_features": {
                "delta_1h": "y[t] - y[t-1] at training row end (causal)",
                "delta_3h": "y[t] - y[t-3] at training row end (causal)",
                "concat": "lag block (00060) + delta_1h + delta_3h",
            },
            "horizons": horizons,
            "step": int(args.step),
            "max_cutoffs": int(args.max_cutoffs),
            "history_window_hours": int(args.history_window_hours),
            "models": {},
            "baselines": {},
            "per_horizon_comparison": {},
        }

        pers_h: dict[int, dict[str, Any]] = {}
        seas_h: dict[int, dict[str, Any]] = {}

        for model_name, kind in (
            ("ridge_direct", "ridge_lag"),
            ("lightgbm_direct", "lgbm_lag"),
            ("ridge_direct_internal", "ridge_internal"),
            ("lightgbm_direct_internal", "lgbm_internal"),
        ):
            if model_name not in wanted:
                continue
            h_block = {}
            for h in horizons:
                if kind.endswith("_lag"):
                    pred, actual, skipped = _walk_forward(
                        y,
                        h,
                        step=args.step,
                        model_name="ridge_direct" if kind == "ridge_lag" else "lightgbm_direct",
                        ridge_alpha=float(args.ridge_alpha),
                        max_cutoffs=int(args.max_cutoffs),
                        history_window_hours=int(args.history_window_hours),
                        lgbm_extra=lgbm_extra if kind == "lgbm_lag" else None,
                    )
                    cut = None
                else:
                    pred, actual, skipped, cut = walk_forward_direct_y_internal(
                        y,
                        h,
                        lag=36,
                        step=args.step,
                        max_cutoffs=int(args.max_cutoffs),
                        history_window_hours=int(args.history_window_hours),
                        model_kind="direct_ridge" if kind == "ridge_internal" else "direct_lgbm",
                        ridge_alpha=float(args.ridge_alpha),
                        lgbm_params=lgbm_extra or {},
                    )
                if len(pred) == 0:
                    h_block[str(h)] = {"error": "no_valid_predictions", "skipped_cutoffs": skipped}
                    continue
                m = _metrics(pred, actual)
                m["skipped_cutoffs"] = skipped
                h_block[str(h)] = m
                if model_name == "ridge_direct_internal" and cut is not None and len(cut) == len(pred):
                    pp, pa, sp, sm = _baseline_pairs(y, cut, h)
                    pers_h[h] = _metrics(pp, pa)
                    if sm.any():
                        seas_h[h] = _metrics(sp[sm], pa[sm])
                    else:
                        seas_h[h] = {"error": "no_valid_seasonal_pairs", "n": 0}
            site_block["models"][model_name] = {"summary": _summarize_model(h_block), "horizons": h_block}

        if pers_h:
            site_block["baselines"]["persistence"] = {"horizons": {str(k): v for k, v in pers_h.items()}}
            site_block["baselines"]["seasonal_lag_24h"] = {"horizons": {str(k): v for k, v in seas_h.items()}}

        # Per-horizon: ridge vs persistence vs internal (LGBM)
        rd = {int(h): site_block["models"].get("ridge_direct", {}).get("horizons", {}).get(str(h), {}) for h in horizons}
        ri = {
            int(h): site_block["models"].get("ridge_direct_internal", {}).get("horizons", {}).get(str(h), {})
            for h in horizons
        }
        ph = {
            int(h): site_block.get("baselines", {}).get("persistence", {}).get("horizons", {}).get(str(h), {})
            for h in horizons
        }
        sh = {
            int(h): site_block.get("baselines", {}).get("seasonal_lag_24h", {}).get("horizons", {}).get(str(h), {})
            for h in horizons
        }
        site_block["per_horizon_comparison"] = _per_horizon_table(horizons, rd, ph, sh, ri)

        deltas: dict[str, Any] = {}
        if "ridge_direct" in site_block["models"] and "ridge_direct_internal" in site_block["models"]:
            b = site_block["models"]["ridge_direct"]["summary"]["mean_smape_pct"]
            e = site_block["models"]["ridge_direct_internal"]["summary"]["mean_smape_pct"]
            if isinstance(b, (int, float)) and isinstance(e, (int, float)) and np.isfinite(b) and np.isfinite(e):
                deltas["ridge_direct_internal_minus_ridge_direct_mean_smape_pct"] = round(float(e - b), 6)
        if "lightgbm_direct" in site_block["models"] and "lightgbm_direct_internal" in site_block["models"]:
            b = site_block["models"]["lightgbm_direct"]["summary"]["mean_smape_pct"]
            e = site_block["models"]["lightgbm_direct_internal"]["summary"]["mean_smape_pct"]
            if isinstance(b, (int, float)) and isinstance(e, (int, float)) and np.isfinite(b) and np.isfinite(e):
                deltas["lightgbm_direct_internal_minus_lightgbm_direct_mean_smape_pct"] = round(float(e - b), 6)
        site_block["internal_vs_baseline_smape_delta"] = deltas
        site_reports[site_no] = site_block
        (out_dir / f"{site_no}_{TARGET_COL}_internal_compare.json").write_text(
            json.dumps(site_block, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        for mname, block in site_block["models"].items():
            sm = block["summary"]
            summary_rows.append(
                {
                    "site_no": site_no,
                    "model": mname,
                    "mean_smape_pct": sm.get("mean_smape_pct"),
                    "mean_mae": sm.get("mean_mae"),
                    "horizons_evaluated": sm.get("horizons_evaluated"),
                }
            )
            print(f"  {site_no} {mname} mean_sMAPE={sm.get('mean_smape_pct')}%", flush=True)

    summary_csv = out_dir / "summary_by_site_model.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["site_no", "model", "mean_smape_pct", "mean_mae", "horizons_evaluated"],
        )
        w.writeheader()
        w.writerows(summary_rows)

    payload = {
        "parameter_cd": TARGET_COL,
        "walk_forward": {
            "step_hours": int(args.step),
            "max_cutoffs": int(args.max_cutoffs),
            "history_window_hours": int(args.history_window_hours),
        },
        "sites": site_reports,
        "interpretation": (
            "Compare per-horizon tables vs persistence; negative internal_minus_ridge_smape_pct means "
            "internal deltas helped vs lag-only Ridge. ~10% sMAPE alone does not imply deployable — check "
            "beats persistence and horizon tiers."
        ),
    }
    (out_dir / "summary.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written {summary_csv}")
    print(f"Written {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()

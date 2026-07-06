#!/usr/bin/env python3
"""
Compare 00060 (discharge) walk-forward models with vs without Open-Meteo precipitation exog.

Baseline: lag-only ridge_direct / lightgbm_direct (same protocol as backtest_model_suite_00060).
Exog: direct Ridge / LGBM with concatenated lags of y and precipitation_mm (causal, no future peek).

Example:
  .venv/bin/python models/backtest_flow_00060_exog_compare.py \\
    --features-dir data/features_00060_openmeteo \\
    --step 24 --max-cutoffs 0 --horizons 1-12 \\
    --out-dir reports/flow_00060_exog_compare
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
from backtest_turbidity_exog_ridge_lgbm import (  # noqa: E402
    _as_lgbm_frame,
    _lag_matrix_block,
)
from forecast_engine import MAX_LAG, MIN_HOURLY_POINTS, _effective_lag, slice_series_upto_cutoff  # noqa: E402

try:
    from lightgbm import LGBMRegressor  # type: ignore
except Exception:
    LGBMRegressor = None  # type: ignore

TARGET_COL = "00060"


def _causal_fill_series(s: pd.Series, limit: int = 24) -> pd.Series:
    return s.ffill(limit=limit)


def load_flow_features(csv_path: Path) -> tuple[pd.Series, pd.Series]:
    df = pd.read_csv(csv_path)
    if "datetime_utc" not in df.columns:
        raise ValueError(f"{csv_path}: missing datetime_utc")
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["datetime_utc"]).sort_values("datetime_utc").drop_duplicates("datetime_utc", keep="last")
    df = df.set_index("datetime_utc")
    if TARGET_COL not in df.columns:
        raise ValueError(f"{csv_path}: missing {TARGET_COL}")
    if "precipitation_mm" not in df.columns:
        raise ValueError(f"{csv_path}: missing precipitation_mm")
    y = df[TARGET_COL].astype(float)
    prec = _causal_fill_series(df["precipitation_mm"].astype(float))
    return y, prec


def _y_precip_blocks_at(y: pd.Series, prec: pd.Series, end_ix: int, lag: int) -> np.ndarray | None:
    wy = _lag_matrix_block(y, end_ix, lag)
    wp = _lag_matrix_block(prec, end_ix, lag)
    if wy is None or wp is None:
        return None
    return np.concatenate([wy, wp], axis=0)


def walk_forward_direct_y_precip(
    y: pd.Series,
    prec: pd.Series,
    horizon: int,
    *,
    lag: int,
    step: int,
    max_cutoffs: int,
    history_window_hours: int,
    model_kind: str,
    ridge_alpha: float,
    lgbm_params: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, int]:
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
        feat_dim_loc = 2 * lag_loc
        rows_x: list[np.ndarray] = []
        rows_yy: list[float] = []
        for o in range(lag_loc - 1, loc - h + 1):
            g = idx_T - loc + o
            row = _y_precip_blocks_at(y, prec, g, lag_loc)
            if row is None:
                continue
            if pd.isna(y.iloc[g + h]):
                continue
            rows_x.append(row)
            rows_yy.append(float(y.iloc[g + h]))
        if len(rows_yy) < 20:
            skipped += 1
            continue
        x_row = _y_precip_blocks_at(y, prec, idx_T, lag_loc)
        if x_row is None:
            skipped += 1
            continue
        X = np.stack(rows_x, axis=0)
        y_tr = np.asarray(rows_yy, dtype=float)
        x_test = x_row.reshape(1, -1)
        if X.shape[1] != feat_dim_loc:
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
    return np.asarray(preds, dtype=float), np.asarray(actuals, dtype=float), skipped


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="00060 baseline vs precipitation exog backtest")
    p.add_argument("--features-dir", default=str(_ROOT / "data" / "features_00060_openmeteo"))
    p.add_argument(
        "--sites-config",
        default=str(_ROOT / "config" / "usgs_puget_default_sites.json"),
    )
    p.add_argument("--exclude-sites", default="12147600")
    p.add_argument("--horizons", default="1-12")
    p.add_argument("--step", type=int, default=24, help="Walk-forward step in hours (24 matches model suite smoke).")
    p.add_argument(
        "--models",
        default="ridge_direct,lightgbm_direct,ridge_direct_exog_precip,lightgbm_direct_exog_precip",
        help="Comma-separated model names to run.",
    )
    p.add_argument(
        "--max-cutoffs",
        type=int,
        default=0,
        help="Max cutoff span from series end (hours). 0 = evaluate from earliest valid cutoff through end.",
    )
    p.add_argument("--history-window-hours", type=int, default=1440)
    p.add_argument("--ridge-alpha", type=float, default=50.0)
    p.add_argument("--lgbm-params-json", default=str(_ROOT / "reports" / "lgbm_tune_step1" / "lgbm_best_by_site.json"))
    p.add_argument("--out-dir", default=str(_ROOT / "reports" / "flow_00060_exog_compare"))
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
    all_models = (
        "ridge_direct",
        "lightgbm_direct",
        "ridge_direct_exog_precip",
        "lightgbm_direct_exog_precip",
    )
    for m in wanted:
        if m not in all_models:
            raise SystemExit(f"Unknown model {m!r}; allowed: {', '.join(all_models)}")

    site_reports: dict[str, Any] = {}
    summary_rows: list[dict[str, Any]] = []

    print("=== 00060 baseline vs precipitation exog ===", flush=True)
    print(f"features_dir={features_dir.resolve()} sites={sites}", flush=True)

    for site_no in sites:
        feat_path = features_dir / f"features_{site_no}_{TARGET_COL}_openmeteo.csv"
        if not feat_path.is_file():
            print(f"  skip {site_no}: missing {feat_path}", flush=True)
            continue
        y, prec = load_flow_features(feat_path)
        lgbm_extra = lgbm_by_site.get(site_no)
        site_block: dict[str, Any] = {
            "site_no": site_no,
            "features_csv": str(feat_path.resolve()),
            "exog": {
                "precipitation_mm": "Open-Meteo archive hourly precipitation at NWIS site lat/lon",
                "feature_blocks": "concatenated lags of 00060 and precipitation_mm (causal, hours <= cutoff)",
            },
            "horizons": horizons,
            "step": int(args.step),
            "max_cutoffs": int(args.max_cutoffs),
            "history_window_hours": int(args.history_window_hours),
            "models": {},
        }

        if "ridge_direct" in wanted or "lightgbm_direct" in wanted:
            for model_name in ("ridge_direct", "lightgbm_direct"):
                if model_name not in wanted:
                    continue
                h_block: dict[str, Any] = {}
                for h in horizons:
                    pred, actual, skipped = _walk_forward(
                        y,
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
                site_block["models"][model_name] = {
                    "summary": _summarize_model(h_block),
                    "horizons": h_block,
                }

        exog_runs = (
            ("ridge_direct_exog_precip", "direct_ridge"),
            ("lightgbm_direct_exog_precip", "direct_lgbm"),
        )
        for label, kind in exog_runs:
            if label not in wanted:
                continue
            h_block = {}
            for h in horizons:
                pred, actual, skipped = walk_forward_direct_y_precip(
                    y,
                    prec,
                    h,
                    lag=36,
                    step=args.step,
                    max_cutoffs=int(args.max_cutoffs),
                    history_window_hours=int(args.history_window_hours),
                    model_kind=kind,
                    ridge_alpha=float(args.ridge_alpha),
                    lgbm_params=lgbm_extra or {},
                )
                if len(pred) == 0:
                    h_block[str(h)] = {"error": "no_valid_predictions", "skipped_cutoffs": skipped}
                else:
                    m = _metrics(pred, actual)
                    m["skipped_cutoffs"] = skipped
                    h_block[str(h)] = m
            site_block["models"][label] = {
                "summary": _summarize_model(h_block),
                "horizons": h_block,
            }

        # Pairwise deltas (exog - baseline) on mean sMAPE
        deltas: dict[str, Any] = {}
        for base, exog in (
            ("ridge_direct", "ridge_direct_exog_precip"),
            ("lightgbm_direct", "lightgbm_direct_exog_precip"),
        ):
            if base not in site_block["models"] or exog not in site_block["models"]:
                continue
            b = site_block["models"][base]["summary"]["mean_smape_pct"]
            e = site_block["models"][exog]["summary"]["mean_smape_pct"]
            if isinstance(b, (int, float)) and isinstance(e, (int, float)) and np.isfinite(b) and np.isfinite(e):
                deltas[f"{exog}_minus_{base}_mean_smape_pct"] = round(float(e - b), 6)
        site_block["exog_vs_baseline_smape_delta"] = deltas
        site_reports[site_no] = site_block
        (out_dir / f"{site_no}_{TARGET_COL}_exog_compare.json").write_text(
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
            print(
                f"  {site_no} {mname} mean_sMAPE={sm.get('mean_smape_pct')}%",
                flush=True,
            )

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
        "precipitation_source": "open-meteo-archive-v1",
        "walk_forward": {
            "step_hours": int(args.step),
            "max_cutoffs": int(args.max_cutoffs),
            "max_cutoffs_note": "0 means all valid cutoffs on the hourly grid (not limited to recent 720h).",
            "history_window_hours": int(args.history_window_hours),
        },
        "sites": site_reports,
        "note": "Negative exog_minus_baseline mean_smape_delta means precipitation exog improved average sMAPE.",
    }
    (out_dir / "summary.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written {summary_csv}")
    print(f"Written {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()

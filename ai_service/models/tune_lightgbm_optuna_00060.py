#!/usr/bin/env python3
"""
Optuna (TPE) hyperparameter search for LightGBM direct forecasts (horizons 1..12).

Same walk-forward objective as tune_lightgbm_direct_00060.py: minimize mean sMAPE
across horizons. Output JSON matches the merge script expectations (site_no,
best_params, trials list).

Optional --holdout-tail-hours trims the end of the series before optimization so
scores are not computed on the same calendar tail used for a final holdout report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import optuna
from optuna.samplers import TPESampler

# Allow imports from ai_service when this file lives under ai_service/models/.
_AI_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(_AI_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_SERVICE_ROOT))

from forecast_engine import load_hourly_series
from tune_lightgbm_direct_00060 import _mean_smape_across_horizons


def _parse_horizons(s: str) -> list[int]:
    s = str(s).strip()
    if s == "1-12":
        return list(range(1, 13))
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _suggest_lgbm_params(trial: optuna.Trial) -> dict[str, Any]:
    max_depth = trial.suggest_categorical("max_depth", [-1, 4, 6, 8, 10, 12, 16, 24])
    return {
        "n_estimators": trial.suggest_int("n_estimators", 40, 600),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 8, 256),
        "max_depth": int(max_depth),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 120),
        "reg_lambda": trial.suggest_float("reg_lambda", 0.0, 10.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.0, 5.0),
        "random_state": 42,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Optuna (TPE) tuner for LightGBM direct (00060)")
    p.add_argument(
        "--iv-csv",
        default=str(_AI_SERVICE_ROOT / "data" / "usgs_puget_iv.csv"),
    )
    p.add_argument("--site-no", required=True)
    p.add_argument("--parameter-cd", default="00060")
    p.add_argument("--horizons", default="1-12")
    p.add_argument("--step", type=int, default=24)
    p.add_argument("--max-cutoffs", type=int, default=720)
    p.add_argument("--history-window-hours", type=int, default=1440)
    p.add_argument(
        "--holdout-tail-hours",
        type=int,
        default=0,
        help="If >0, drop this many hourly points from the end of y before tuning "
        "(keep a calendar tail for separate evaluation).",
    )
    p.add_argument("--n-trials", type=int, default=80)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--study-name", default="", help="Optuna study name (default: site_no)")
    p.add_argument("--json-out", default="")
    p.add_argument(
        "--trials-csv-out",
        default="",
        help="If set, write Optuna trials dataframe to this CSV path.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.iv_csv)
    if not csv_path.is_file():
        print(f"Missing IV CSV: {csv_path}", file=sys.stderr)
        raise SystemExit(1)

    s = load_hourly_series(csv_path, args.site_no, args.parameter_cd, dense=False)
    if s.empty:
        print(f"No series for site={args.site_no} param={args.parameter_cd}", file=sys.stderr)
        raise SystemExit(1)

    holdout_h = max(0, int(args.holdout_tail_hours))
    if holdout_h > 0:
        if len(s) <= holdout_h:
            print(
                f"holdout_tail_hours={holdout_h} >= series length {len(s)}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        s_tune = s.iloc[:-holdout_h]
        print(
            f"Using grid length {len(s_tune)} for tuning (dropped last {holdout_h} calendar hours as holdout tail)."
        )
    else:
        s_tune = s

    horizons = _parse_horizons(args.horizons)
    step = int(args.step)
    max_cutoffs = int(args.max_cutoffs)
    history_window_hours = int(args.history_window_hours)
    n_trials = int(args.n_trials)
    seed = int(args.seed)
    study_name = (args.study_name or f"lgbm_direct_{args.site_no}_{args.parameter_cd}").strip()

    trials_out: list[dict[str, Any]] = []

    def objective(trial: optuna.Trial) -> float:
        params = _suggest_lgbm_params(trial)
        score, ok_h = _mean_smape_across_horizons(
            s_tune,
            horizons,
            step=step,
            params=params,
            max_cutoffs=max_cutoffs,
            history_window_hours=history_window_hours,
        )
        trials_out.append(
            {
                "trial": trial.number,
                "mean_smape_pct": score,
                "horizons_ok": ok_h,
                "params": dict(params),
            }
        )
        print(f"  trial {trial.number + 1}/{n_trials} mean_sMAPE={score:.4f}% ok_h={ok_h}")
        return float(score)

    sampler = TPESampler(seed=seed)
    study = optuna.create_study(direction="minimize", study_name=study_name, sampler=sampler)
    print(
        f"site={args.site_no} horizons={horizons} step={step} "
        f"n_trials={n_trials} study={study_name} sampler=TPE"
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_score = float(study.best_value)
    raw = dict(study.best_trial.params)
    best_params: dict[str, Any] = {
        "n_estimators": int(raw["n_estimators"]),
        "learning_rate": float(raw["learning_rate"]),
        "num_leaves": int(raw["num_leaves"]),
        "max_depth": int(raw["max_depth"]),
        "subsample": float(raw["subsample"]),
        "colsample_bytree": float(raw["colsample_bytree"]),
        "min_child_samples": int(raw["min_child_samples"]),
        "reg_lambda": float(raw["reg_lambda"]),
        "reg_alpha": float(raw["reg_alpha"]),
        "random_state": 42,
    }

    print()
    print(f"BEST mean_sMAPE={best_score:.6f}%")
    print(f"BEST params: {json.dumps(best_params, indent=2)}")

    if args.trials_csv_out:
        df = study.trials_dataframe()
        outp_csv = Path(args.trials_csv_out)
        outp_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(outp_csv, index=False)
        print(f"Wrote trials CSV {outp_csv.resolve()}")

    payload = {
        "tuner": "optuna_tpe",
        "site_no": args.site_no,
        "parameter_cd": args.parameter_cd,
        "business_objective": "minimize mean sMAPE over horizons (default 1..12)",
        "horizons": horizons,
        "step": step,
        "max_cutoffs": max_cutoffs,
        "history_window_hours": history_window_hours,
        "holdout_tail_hours": holdout_h,
        "n_trials": n_trials,
        "seed": seed,
        "study_name": study_name,
        "best_mean_smape_pct": best_score,
        "best_params": best_params,
        "trials": trials_out,
    }

    if args.json_out:
        outp = Path(args.json_out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {outp.resolve()}")


if __name__ == "__main__":
    main()

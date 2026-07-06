#!/usr/bin/env python3
"""
CLI for turbidity 12h RISK classification holdout backtest (Phase A', site 12117500).

Example::

    .venv/bin/python turbidity_risk_class_backtest.py \\
      --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \\
      --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \\
      --report-dir reports/turbidity_risk_forecast_12117500 \\
      --holdout-step 24
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from models.turbidity_risk_class_backtest import (
    DEFAULT_FEATURES_CSV,
    DEFAULT_HOLDOUT_STEP,
    DEFAULT_LAG,
    DEFAULT_MIN_VALID_FUTURE_HOURS,
    DEFAULT_REPORT_DIR,
    DEFAULT_THRESHOLDS_JSON,
    format_risk_class_md,
    run_risk_class_backtest,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Turbidity 12h risk classification holdout backtest (Phase A')."
    )
    p.add_argument("--features-csv", type=Path, default=DEFAULT_FEATURES_CSV)
    p.add_argument("--thresholds-json", type=Path, default=DEFAULT_THRESHOLDS_JSON)
    p.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    p.add_argument("--holdout-step", type=int, default=DEFAULT_HOLDOUT_STEP)
    p.add_argument("--lag", type=int, default=DEFAULT_LAG)
    p.add_argument(
        "--min-valid-future-hours",
        type=int,
        default=DEFAULT_MIN_VALID_FUTURE_HOURS,
        help="Minimum finite-y hours in T+1..T+12 required to keep a cutoff.",
    )
    p.add_argument(
        "--phase-a-json",
        type=Path,
        default=None,
        help="Optional Phase A ridge JSON for comparison (default: report-dir sibling).",
    )
    p.add_argument("--no-md", action="store_true", help="Skip risk_class_holdout.md")
    p.add_argument(
        "--no-precip-ffill",
        action="store_true",
        help="Do not forward-fill precipitation_mm; upstream may still ffill (limit 24h).",
    )
    p.add_argument(
        "--no-exog-ffill",
        action="store_true",
        help="Disable ffill on both precip and upstream (overrides --no-precip-ffill).",
    )
    p.add_argument(
        "--output-basename",
        type=str,
        default="risk_class_holdout",
        help="Output stem under report-dir (default: risk_class_holdout).",
    )
    p.add_argument(
        "--compare-baseline-json",
        type=Path,
        default=None,
        help="Prior holdout JSON for cutoff/F1 comparison section.",
    )
    p.add_argument(
        "--report-title",
        type=str,
        default=None,
        help="Optional markdown H1 override.",
    )
    p.add_argument(
        "--with-if-features",
        action="store_true",
        help="Add univariate + multivariate IF is_anomaly and score at cutoff T.",
    )
    p.add_argument(
        "--with-extended-exog",
        action="store_true",
        help="Add precip sums (6/12/24h) and upstream diff/rolling max (no precip ffill).",
    )
    p.add_argument(
        "--leadtime-eval",
        action="store_true",
        help="Evaluate lead time before tier upgrades on dense holdout (step=1).",
    )
    p.add_argument(
        "--leadtime-holdout-step",
        type=int,
        default=1,
        help="Holdout step for lead-time eval only (default 1).",
    )
    p.add_argument(
        "--plot-leadtime",
        action="store_true",
        help="Write lead-time bar chart PNG when --leadtime-eval is set.",
    )
    p.add_argument(
        "--tune-alert-threshold",
        action="store_true",
        help="Sweep alert P(alert) on tuning cutoffs; apply best τ on holdout (v4).",
    )
    p.add_argument(
        "--fp-guardrail-ratio",
        type=float,
        default=1.05,
        help="ML FP cap vs persistence on tuning (no upgrade in 12h). Default 1.05.",
    )
    p.add_argument(
        "--tuning-dense-step",
        type=int,
        default=1,
        help="Step for dense tuning cutoffs used in threshold sweep (default 1).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.no_exog_ffill:
        use_exog_ffill = False
        use_precip_ffill = False
        use_upstream_ffill = False
    elif args.no_precip_ffill:
        use_exog_ffill = True
        use_precip_ffill = False
        use_upstream_ffill = True
    else:
        use_exog_ffill = True
        use_precip_ffill = None
        use_upstream_ffill = None

    compare_json = args.compare_baseline_json
    if compare_json is None and args.no_precip_ffill:
        default_baseline = Path(args.report_dir) / "risk_class_holdout.json"
        if default_baseline.is_file() and args.output_basename != "risk_class_holdout":
            compare_json = default_baseline

    compare_v2_lt: Path | None = None
    if args.leadtime_eval:
        if "v4" in str(args.output_basename):
            default_prior = Path(args.report_dir) / "risk_class_leadtime_v3.json"
            if default_prior.is_file():
                compare_v2_lt = default_prior
        elif "v3" in str(args.output_basename):
            default_v2 = Path(args.report_dir) / "risk_class_leadtime_v2.json"
            if default_v2.is_file():
                compare_v2_lt = default_v2

    leadtime = bool(args.leadtime_eval or args.tune_alert_threshold)
    extended_exog = bool(args.with_extended_exog or args.with_if_features or leadtime)
    result = run_risk_class_backtest(
        features_csv=Path(args.features_csv),
        thresholds_json=Path(args.thresholds_json),
        report_dir=Path(args.report_dir),
        holdout_step=int(args.holdout_step),
        lag=int(args.lag),
        min_valid_future_hours=int(args.min_valid_future_hours),
        phase_a_json=Path(args.phase_a_json) if args.phase_a_json else None,
        write_md=not args.no_md,
        use_exog_ffill=use_exog_ffill,
        use_precip_ffill=use_precip_ffill,
        use_upstream_ffill=use_upstream_ffill,
        output_basename=str(args.output_basename),
        compare_baseline_json=compare_json,
        report_title=args.report_title,
        with_extended_features=extended_exog,
        with_univariate_if=bool(args.with_if_features),
        with_multivariate_if=bool(args.with_if_features),
        leadtime_eval=leadtime,
        leadtime_holdout_step=int(args.leadtime_holdout_step),
        compare_leadtime_v2_json=compare_v2_lt,
        tune_alert_threshold=bool(args.tune_alert_threshold),
        fp_guardrail_ratio=float(args.fp_guardrail_ratio),
        tuning_dense_step=int(args.tuning_dense_step),
    )
    if args.leadtime_eval and args.plot_leadtime:
        from models.turbidity_risk_class_backtest import write_leadtime_comparison_plot

        png = Path(args.report_dir) / f"{args.output_basename}_leadtime.png"
        write_leadtime_comparison_plot(result, png)
        result.setdefault("outputs", {})["leadtime_png"] = str(png)
    print(format_risk_class_md(result))
    summary = {
        "holdout_step": result.get("holdout_step"),
        "n_holdout": result.get("n_holdout_labeled_cutoffs"),
        "alert_f1": {
            k: (result.get("by_model") or {}).get(k, {}).get("alert_12h", {}).get("f1")
            for k in result.get("model_order") or []
        },
        "outputs": result.get("outputs"),
    }
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

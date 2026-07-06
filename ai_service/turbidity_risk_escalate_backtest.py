#!/usr/bin/env python3
"""
CLI for R7a turbidity escalate_12h backtest (NORMAL-only, site 12117500).

Example::

    .venv/bin/python turbidity_risk_escalate_backtest.py \\
      --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \\
      --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \\
      --report-dir reports/turbidity_risk_forecast_12117500 \\
      --holdout-step 24 \\
      --tuning-dense-step 24 \\
      --no-precip-ffill \\
      --with-if-features \\
      --tune-alert-threshold \\
      --flood-weight 5.0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from models.turbidity_risk_escalate_backtest import (
    DEFAULT_FEATURES_CSV,
    DEFAULT_FLOOD_SAMPLE_WEIGHT,
    DEFAULT_HOLDOUT_STEP,
    DEFAULT_LAG,
    DEFAULT_MIN_VALID_FUTURE_HOURS,
    DEFAULT_REPORT_DIR,
    DEFAULT_THRESHOLDS_JSON,
    ESCALATE_OUTPUT_BASENAME,
    format_escalate_md,
    run_escalate_backtest,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="R7a: NORMAL-only escalate_12h holdout backtest (turbidity 12117500)."
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
    )
    p.add_argument("--no-md", action="store_true")
    p.add_argument(
        "--no-precip-ffill",
        action="store_true",
        help="Do not forward-fill precipitation_mm.",
    )
    p.add_argument(
        "--output-basename",
        type=str,
        default=ESCALATE_OUTPUT_BASENAME,
    )
    p.add_argument(
        "--with-if-features",
        action="store_true",
        help="Add univariate + multivariate IF at cutoff T.",
    )
    p.add_argument(
        "--tune-alert-threshold",
        action="store_true",
        help="Sweep P(escalate) on tuning NORMAL cutoffs; apply best τ on holdout.",
    )
    p.add_argument(
        "--fp-guardrail-ratio",
        type=float,
        default=1.05,
    )
    p.add_argument(
        "--tuning-dense-step",
        type=int,
        default=24,
        help="Step for dense tuning cutoffs in threshold sweep (default 24).",
    )
    p.add_argument(
        "--flood-weight",
        type=float,
        default=DEFAULT_FLOOD_SAMPLE_WEIGHT,
        help="Training weight for flood-window cutoffs and escalate_12h=1 (default 5.0).",
    )
    p.add_argument(
        "--leadtime-holdout-step",
        type=int,
        default=1,
        help="Holdout step for event-local lead-time eval (default 1).",
    )
    p.add_argument("--no-leadtime-eval", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.no_precip_ffill:
        use_precip_ffill = False
        use_upstream_ffill = True
    else:
        use_precip_ffill = None
        use_upstream_ffill = None

    result = run_escalate_backtest(
        features_csv=Path(args.features_csv),
        thresholds_json=Path(args.thresholds_json),
        report_dir=Path(args.report_dir),
        holdout_step=int(args.holdout_step),
        lag=int(args.lag),
        min_valid_future_hours=int(args.min_valid_future_hours),
        write_md=not args.no_md,
        use_precip_ffill=use_precip_ffill,
        use_upstream_ffill=use_upstream_ffill,
        output_basename=str(args.output_basename),
        with_if_features=bool(args.with_if_features),
        tune_alert_threshold=bool(args.tune_alert_threshold),
        fp_guardrail_ratio=float(args.fp_guardrail_ratio),
        tuning_dense_step=int(args.tuning_dense_step),
        flood_weight=float(args.flood_weight),
        leadtime_eval=not args.no_leadtime_eval,
        leadtime_holdout_step=int(args.leadtime_holdout_step),
    )
    print(format_escalate_md(result))
    summary = {
        "n_holdout_normal": result.get("n_holdout_normal_cutoffs"),
        "escalate_recall": {
            mk: (
                (result.get("by_model") or {})
                .get(mk, {})
                .get("by_population", {})
                .get("normal_escalate_events", {})
                .get("recall")
            )
            for mk in result.get("model_order") or []
        },
        "outputs": result.get("outputs"),
    }
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

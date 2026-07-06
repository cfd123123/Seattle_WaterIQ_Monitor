#!/usr/bin/env python3
"""
CLI for event-window turbidity 12h risk classification metrics.

Example::

    .venv/bin/python turbidity_risk_event_eval.py \\
      --with-if-features --no-precip-ffill \\
      --holdout-step 24 --tuning-dense-step 24
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from models.turbidity_risk_event_eval import (
    DEFAULT_FEATURES_CSV,
    DEFAULT_HOLDOUT_STEP,
    DEFAULT_REPORT_DIR,
    DEFAULT_THRESHOLDS_JSON,
    EVENT_OUTPUT_BASENAME,
    format_event_metrics_md,
    run_event_metrics_eval,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Event-window metrics for turbidity 12h risk classification."
    )
    p.add_argument("--features-csv", type=Path, default=DEFAULT_FEATURES_CSV)
    p.add_argument("--thresholds-json", type=Path, default=DEFAULT_THRESHOLDS_JSON)
    p.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    p.add_argument("--holdout-step", type=int, default=DEFAULT_HOLDOUT_STEP)
    p.add_argument("--no-precip-ffill", action="store_true")
    p.add_argument("--no-exog-ffill", action="store_true")
    p.add_argument(
        "--with-if-features",
        action="store_true",
        help="Extended exog + uni/multi IF at cutoff T.",
    )
    p.add_argument(
        "--tuning-dense-step",
        type=int,
        default=24,
        help="Step for dense tuning cutoffs in threshold sweep.",
    )
    p.add_argument(
        "--no-tune-threshold",
        action="store_true",
        help="Use --tuned-thresholds-json or default 0.5 for ML.",
    )
    p.add_argument(
        "--tuned-thresholds-json",
        type=Path,
        default=None,
        help="Prior v4 JSON with selected_thresholds (default: v4 in report-dir).",
    )
    p.add_argument(
        "--fp-guardrail-ratio",
        type=float,
        default=1.05,
    )
    p.add_argument("--output-basename", type=str, default=EVENT_OUTPUT_BASENAME)
    p.add_argument("--no-md", action="store_true")
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

    tuned_json = args.tuned_thresholds_json
    if tuned_json is None:
        default_v4 = Path(args.report_dir) / "risk_class_leadtime_v4_threshold.json"
        if default_v4.is_file():
            tuned_json = default_v4

    result = run_event_metrics_eval(
        features_csv=Path(args.features_csv),
        thresholds_json=Path(args.thresholds_json),
        report_dir=Path(args.report_dir),
        holdout_step=int(args.holdout_step),
        use_exog_ffill=use_exog_ffill,
        use_precip_ffill=use_precip_ffill,
        use_upstream_ffill=use_upstream_ffill,
        with_if_features=bool(args.with_if_features),
        tune_alert_threshold=not args.no_tune_threshold and tuned_json is None,
        fp_guardrail_ratio=float(args.fp_guardrail_ratio),
        tuning_dense_step=int(args.tuning_dense_step),
        tuned_thresholds_json=tuned_json,
        output_basename=str(args.output_basename),
        write_md=not args.no_md,
    )
    print(format_event_metrics_md(result))
    print()
    print(json.dumps({"outputs": result.get("outputs"), "population_counts": result.get("population_counts")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

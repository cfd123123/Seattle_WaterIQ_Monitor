#!/usr/bin/env python3
"""
CLI for turbidity (63680) state monitoring — see plan/turbidity_state_monitoring.md.

Example::

    .venv/bin/python turbidity_state_monitoring.py \\
      --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \\
      --out-dir reports/turbidity_state/12117500_v1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from models.turbidity_gap_report import run_gap_report
from models.turbidity_state_monitoring import (
    DEFAULT_ABSOLUTE_NTU_CRITICAL,
    DEFAULT_SITE_NO,
    run_state_monitoring,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Turbidity 4-state monitoring and rule warning evaluation.")
    p.add_argument("--features-csv", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--site-no", type=str, default=DEFAULT_SITE_NO)
    p.add_argument("--holdout-fraction", type=float, default=0.2)
    p.add_argument("--holdout-min-hours", type=int, default=336)
    p.add_argument("--recovery-window-hours", type=int, default=48)
    p.add_argument("--thresholds-json", type=Path, default=None, help="Reuse frozen thresholds from JSON.")
    p.add_argument(
        "--absolute-ntu-critical",
        type=float,
        default=None,
        help="CRITICAL tier absolute NTU floor (default 50, aligned with water.turbidity-threshold.warn-ntu).",
    )
    p.add_argument("--no-plot", action="store_true")
    p.add_argument(
        "--gap-report",
        action="store_true",
        help="Also write gap_report.json / gap_report_monthly.csv (and PNG) under --out-dir.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.gap_report:
        run_gap_report(
            Path(args.features_csv),
            site_no=str(args.site_no),
            holdout_fraction=float(args.holdout_fraction),
            holdout_min_hours=int(args.holdout_min_hours),
            out_dir=Path(args.out_dir),
            write_plot=not args.no_plot,
        )
    abs_crit = (
        float(args.absolute_ntu_critical)
        if args.absolute_ntu_critical is not None
        else DEFAULT_ABSOLUTE_NTU_CRITICAL
    )
    summary = run_state_monitoring(
        Path(args.features_csv),
        site_no=str(args.site_no),
        holdout_fraction=float(args.holdout_fraction),
        holdout_min_hours=int(args.holdout_min_hours),
        recovery_window_hours=int(args.recovery_window_hours),
        out_dir=Path(args.out_dir),
        write_plot=not args.no_plot,
        thresholds_json=args.thresholds_json,
        absolute_ntu_critical=abs_crit,
    )
    print(
        json.dumps(
            {
                "out_dir": str(Path(args.out_dir).resolve()),
                "state_counts_all": summary["state_counts_all"],
                "warning": summary["warning_rule_holdout"],
                "warning_vs_never_alert": summary["warning_vs_never_alert"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

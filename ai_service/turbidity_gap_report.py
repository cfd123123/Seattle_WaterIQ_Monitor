#!/usr/bin/env python3
"""
CLI for turbidity (63680) gap diagnostics.

Example::

    .venv/bin/python turbidity_gap_report.py \\
      --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \\
      --out-dir reports/turbidity_state/12117500_v2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from models.turbidity_gap_report import DEFAULT_FEATURES_CSV, DEFAULT_OUT_DIR, DEFAULT_SITE_NO, run_gap_report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Turbidity 63680 data-gap report on features CSV.")
    p.add_argument("--features-csv", type=Path, default=DEFAULT_FEATURES_CSV)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--site-no", type=str, default=DEFAULT_SITE_NO)
    p.add_argument("--holdout-fraction", type=float, default=0.2)
    p.add_argument("--holdout-min-hours", type=int, default=336)
    p.add_argument("--no-holdout-segment", action="store_true")
    p.add_argument("--no-plot", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    report = run_gap_report(
        Path(args.features_csv),
        site_no=str(args.site_no),
        holdout_fraction=float(args.holdout_fraction),
        holdout_min_hours=int(args.holdout_min_hours),
        out_dir=Path(args.out_dir),
        write_plot=not args.no_plot,
        include_holdout=not args.no_holdout_segment,
    )
    print(
        json.dumps(
            {
                "outputs": report.get("outputs"),
                "segments": report.get("segments"),
                "flood_window_dec_2025": report.get("flood_window_dec_2025"),
                "monthly_worst_by_valid_rate": report.get("monthly_worst_by_valid_rate"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

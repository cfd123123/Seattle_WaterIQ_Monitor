#!/usr/bin/env python3
"""
CLI for turbidity (63680) holdout tier evaluation (frozen v2 thresholds).

Example::

    .venv/bin/python turbidity_holdout_eval.py \\
      --report-dir reports/turbidity_state/12117500_v2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from models.turbidity_holdout_eval import DEFAULT_REPORT_DIR, format_holdout_eval_summary, run_holdout_eval


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Turbidity v2 holdout tier evaluation from report artifacts.")
    p.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    p.add_argument("--features-csv", type=Path, default=None)
    p.add_argument("--holdout-fraction", type=float, default=0.2)
    p.add_argument("--holdout-min-hours", type=int, default=336)
    p.add_argument("--no-md", action="store_true", help="Skip holdout_eval.md")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = run_holdout_eval(
        Path(args.report_dir),
        features_csv=args.features_csv,
        holdout_fraction=float(args.holdout_fraction),
        holdout_min_hours=int(args.holdout_min_hours),
        write_md=not args.no_md,
    )
    print(format_holdout_eval_summary(result))
    print()
    print(
        json.dumps(
            {
                "holdout_start_utc": result.get("holdout_start_utc"),
                "holdout_end_utc": result.get("holdout_end_utc"),
                "n_grid_hours": result.get("n_grid_hours"),
                "tier_rates": result.get("tier_rates"),
                "flood_window_dec_2025": result.get("flood_window_dec_2025"),
                "outputs": {
                    "json": str(Path(args.report_dir) / "holdout_eval.json"),
                    "md": None if args.no_md else str(Path(args.report_dir) / "holdout_eval.md"),
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
CLI: holdout comparison of turbidity alert tiers (v2.1) vs univariate IsolationForest.

Example::

    .venv/bin/python turbidity_tier_vs_if_eval.py \\
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

from models.turbidity_tier_vs_if_eval import (
    DEFAULT_REPORT_DIR,
    format_tier_vs_if_md,
    run_tier_vs_if_eval,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Holdout alert-tier vs IsolationForest comparison for turbidity monitoring."
    )
    p.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    p.add_argument("--features-csv", type=Path, default=None)
    p.add_argument("--iv-csv", type=Path, default=None, help="Optional IV CSV for 63680 fill")
    p.add_argument("--holdout-fraction", type=float, default=0.2)
    p.add_argument("--holdout-min-hours", type=int, default=336)
    p.add_argument("--progress-every", type=int, default=500, help="Print progress every N IF fits")
    p.add_argument("--n-jobs", type=int, default=-1, help="Parallel workers for IF scoring")
    p.add_argument("--no-md", action="store_true", help="Skip tier_vs_if_holdout.md")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = run_tier_vs_if_eval(
        Path(args.report_dir),
        features_csv=args.features_csv,
        iv_csv=args.iv_csv,
        holdout_fraction=float(args.holdout_fraction),
        holdout_min_hours=int(args.holdout_min_hours),
        progress_every=int(args.progress_every),
        n_jobs=int(args.n_jobs),
        write_md=not args.no_md,
    )
    print(format_tier_vs_if_md(result))
    print()
    c = (result.get("quality_hours") or {}).get("contingency") or {}
    print(
        json.dumps(
            {
                "n_quality_hours": (result.get("quality_hours") or {}).get("n_hours"),
                "contingency": c,
                "flood_window": result.get("flood_window_dec_2025"),
                "outputs": {
                    "json": str(Path(args.report_dir) / "tier_vs_if_holdout.json"),
                    "md": None if args.no_md else str(Path(args.report_dir) / "tier_vs_if_holdout.md"),
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
CLI for turbidity 12h RISK forecast holdout backtest (Phase A, site 12117500).

Example::

    .venv/bin/python turbidity_risk_forecast_backtest.py \\
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

from models.turbidity_risk_forecast_backtest import (
    DEFAULT_FEATURES_CSV,
    DEFAULT_REPORT_DIR,
    DEFAULT_THRESHOLDS_JSON,
    format_risk_forecast_md,
    run_risk_forecast_backtest,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Turbidity 12h risk forecast holdout backtest (Ridge direct + frozen tiers).")
    p.add_argument("--features-csv", type=Path, default=DEFAULT_FEATURES_CSV)
    p.add_argument("--thresholds-json", type=Path, default=DEFAULT_THRESHOLDS_JSON)
    p.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    p.add_argument("--horizons", type=str, default="1-12")
    p.add_argument("--holdout-step", type=int, default=24, help="Walk-forward step on holdout cutoffs (hours).")
    p.add_argument("--ridge-alpha", type=float, default=5.0)
    p.add_argument("--history-window-hours", type=int, default=1440)
    p.add_argument("--no-md", action="store_true", help="Skip risk_forecast_holdout.md")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = run_risk_forecast_backtest(
        features_csv=Path(args.features_csv),
        thresholds_json=Path(args.thresholds_json),
        report_dir=Path(args.report_dir),
        horizons=args.horizons,
        holdout_step=int(args.holdout_step),
        ridge_alpha=float(args.ridge_alpha),
        history_window_hours=int(args.history_window_hours),
        write_md=not args.no_md,
    )
    print(format_risk_forecast_md(result))
    oracle = (result.get("by_exog_mode") or {}).get("oracle", {})
    summary = {
        "holdout_step": result.get("holdout_step"),
        "recommend_alert_oracle": oracle.get("window_1_12h", {}).get("recommend_alert"),
        "flood_oracle": oracle.get("flood_window"),
        "outputs": result.get("outputs"),
    }
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

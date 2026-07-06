#!/usr/bin/env python3
"""
Run all turbidity exogenous backtest models with identical knobs (evaluation_contract aligned).

Writes one JSON per model under --out-dir and a suite_manifest.json with arguments and exit codes.

Example (full protocol: dense cutoffs)::

    .venv/bin/python models/run_turbidity_exog_model_suite.py \\
      --features-csv data/features_12117500_63680_with_openmeteo.csv \\
      --out-dir reports/turbidity_exog_suite/run_20260513 \\
      --step 1 --horizons 1-12

Quick smoke (not final reporting)::

    .venv/bin/python models/run_turbidity_exog_model_suite.py \\
      --features-csv data/features_12117500_63680_with_openmeteo.csv \\
      --out-dir reports/turbidity_exog_suite/smoke \\
      --quick
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_SUITE_MODELS: tuple[str, ...] = (
    "direct_ridge",
    "direct_lgbm",
    "direct_ridge_upstream",
    "direct_lgbm_upstream",
    "recursive_ridge_exog_hindcast",
    "recursive_lgbm_exog_hindcast",
    "recursive_ridge_exog_upstream_hindcast",
    "recursive_lgbm_exog_upstream_hindcast",
    "recursive_ridge_univariate",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run full turbidity exog model suite with shared evaluation knobs.")
    p.add_argument("--features-csv", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True, help="Directory for per-model JSON outputs.")
    p.add_argument("--horizons", type=str, default="1-12")
    p.add_argument("--step", type=int, default=1)
    p.add_argument("--max-cutoffs", type=int, default=720)
    p.add_argument("--history-window-hours", type=int, default=1440)
    p.add_argument("--ridge-alpha", type=float, default=5.0)
    p.add_argument("--holdout-fraction", type=float, default=0.2)
    p.add_argument("--holdout-min-hours", type=int, default=336)
    p.add_argument("--min-tuning-hours", type=int, default=2000)
    p.add_argument(
        "--quick",
        action="store_true",
        help="Use step=48 and max_cutoffs=120 for a fast sanity run (not contract-final).",
    )
    p.add_argument(
        "--models",
        type=str,
        default=None,
        help=f"Comma-separated subset of models (default: all). Choices: {','.join(_SUITE_MODELS)}.",
    )
    p.add_argument("--dry-run", action="store_true", help="Print commands only; do not execute.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = args.features_csv.resolve()
    if not csv_path.is_file():
        print(f"Missing features CSV: {csv_path}", file=sys.stderr)
        return 2

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    step = int(args.step)
    max_cutoffs = int(args.max_cutoffs)
    if args.quick:
        step = 48
        max_cutoffs = min(max_cutoffs, 120)

    models = list(_SUITE_MODELS)
    if args.models:
        wanted = {x.strip() for x in str(args.models).split(",") if x.strip()}
        models = [m for m in _SUITE_MODELS if m in wanted]
        unknown = wanted - set(_SUITE_MODELS)
        if unknown:
            print(f"Unknown model names: {sorted(unknown)}", file=sys.stderr)
            return 2
        if not models:
            print("No models selected.", file=sys.stderr)
            return 2

    ai_root = Path(__file__).resolve().parent.parent
    backtest = ai_root / "models" / "backtest_turbidity_exog_ridge_lgbm.py"

    common = [
        sys.executable,
        str(backtest),
        "--features-csv",
        str(csv_path),
        "--horizons",
        str(args.horizons),
        "--step",
        str(step),
        "--max-cutoffs",
        str(max_cutoffs),
        "--history-window-hours",
        str(int(args.history_window_hours)),
        "--ridge-alpha",
        str(float(args.ridge_alpha)),
        "--holdout-fraction",
        str(float(args.holdout_fraction)),
        "--holdout-min-hours",
        str(int(args.holdout_min_hours)),
        "--min-tuning-hours",
        str(int(args.min_tuning_hours)),
    ]

    manifest: dict[str, object] = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "features_csv": str(csv_path),
        "out_dir": str(out_dir.resolve()),
        "quick": bool(args.quick),
        "knobs": {
            "horizons": str(args.horizons),
            "step": step,
            "max_cutoffs": max_cutoffs,
            "history_window_hours": int(args.history_window_hours),
            "ridge_alpha": float(args.ridge_alpha),
            "holdout_fraction": float(args.holdout_fraction),
            "holdout_min_hours": int(args.holdout_min_hours),
            "min_tuning_hours": int(args.min_tuning_hours),
        },
        "models": [],
    }

    rc_all = 0
    for model in models:
        json_out = out_dir / f"{model}.json"
        cmd = common + ["--model", model, "--json-out", str(json_out)]
        entry = {"model": model, "json_out": str(json_out.resolve()), "exit_code": None, "cmd": cmd}
        manifest["models"].append(entry)  # type: ignore[union-attr]
        print(f"\n=== {model} ===", flush=True)
        print(" ".join(cmd), flush=True)
        if args.dry_run:
            entry["exit_code"] = 0
            continue
        proc = subprocess.run(cmd, cwd=str(ai_root))
        entry["exit_code"] = int(proc.returncode)
        if proc.returncode != 0:
            rc_all = max(rc_all, int(proc.returncode))

    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["suite_exit_code"] = rc_all
    (out_dir / "suite_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_dir / 'suite_manifest.json'}")
    return rc_all


if __name__ == "__main__":
    raise SystemExit(main())

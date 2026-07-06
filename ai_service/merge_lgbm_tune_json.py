#!/usr/bin/env python3
"""Merge per-site LightGBM tune JSON outputs into one JSON for --lgbm-params-json.

Compatible with tune_lightgbm_direct_00060.py and tune_lightgbm_optuna_00060.py
(--json-out payloads that include site_no and best_params).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="Merge LightGBM tune JSON files into site_no -> best_params map")
    p.add_argument("inputs", nargs="+", help="Paths from tune_lightgbm_*_00060.py --json-out")
    p.add_argument("-o", "--output", required=True)
    args = p.parse_args()

    merged: dict[str, dict] = {}
    for fp in args.inputs:
        path = Path(fp)
        if not path.is_file():
            print(f"Skip missing: {path}", file=sys.stderr)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        site = str(data.get("site_no", "")).strip()
        bp = data.get("best_params")
        if not site or not isinstance(bp, dict):
            print(f"Skip invalid: {path}", file=sys.stderr)
            continue
        merged[site] = bp

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(merged)} sites -> {out.resolve()}")


if __name__ == "__main__":
    main()

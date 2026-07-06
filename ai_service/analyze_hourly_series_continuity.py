#!/usr/bin/env python3
"""
Post-1h-resample continuity diagnostics for USGS IV (calendar grid, NaNs kept).

Use before committing to strict calendar walk-forward (scheme 1): valid ratio, longest NaN runs,
gaps between successive observed hours, and walk-forward-eligible cutoff counts per horizon.

Examples:
  python analyze_hourly_series_continuity.py --site-no 12117000 --parameter-cd 00060
  python analyze_hourly_series_continuity.py --all-sites-from-config --parameter-cd 00060 --report-out reports/hourly_continuity_00060.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT, _ROOT / "models"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from forecast_engine import hourly_grid_continuity_report, load_hourly_series


def _parse_horizons(s: str) -> tuple[int, ...]:
    s = str(s).strip()
    if s == "1-12":
        return tuple(range(1, 13))
    return tuple(int(x.strip()) for x in s.split(",") if x.strip())


def _load_site_nos_from_config(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    clean = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("//"))
    clean = re.sub(r",\s*([\]}])", r"\1", clean)
    payload = json.loads(clean)
    rows = payload.get("sites", [])
    out: list[str] = []
    for row in rows:
        if isinstance(row, str):
            sn = row.strip()
        else:
            sn = str(row.get("site_no", "")).strip()
        if sn:
            out.append(sn)
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyze 1h calendar-grid continuity after resample (same pipeline as forecast_engine)."
    )
    p.add_argument(
        "--iv-csv",
        type=Path,
        default=_ROOT / "data" / "usgs_puget_iv.csv",
        help="Merged IV CSV",
    )
    p.add_argument("--site-no", default="", help="USGS site number (omit if --all-sites-from-config).")
    p.add_argument("--parameter-cd", default="00060", help="NWIS parameterCd, e.g. 00060.")
    p.add_argument(
        "--all-sites-from-config",
        type=Path,
        nargs="?",
        const=_ROOT / "config" / "usgs_puget_default_sites.json",
        help="Run all site_no from this JSON (default: config/usgs_puget_default_sites.json).",
    )
    p.add_argument("--horizons", default="1-12", help='e.g. "1-12" or "1,6,12".')
    p.add_argument("--walk-forward-step", type=int, default=1, help="Step between cutoffs (match backtest).")
    p.add_argument(
        "--lag",
        type=int,
        default=0,
        help="Override lag for eligibility simulation (0 = use same rule as forecast_engine _effective_lag).",
    )
    p.add_argument("--report-out", type=Path, default=None, help="Write full JSON report to this path.")
    return p.parse_args()


def _print_human_summary(site_no: str, parameter_cd: str, rep: dict[str, Any]) -> None:
    print(f"=== hourly grid continuity: site={site_no} param={parameter_cd} ===")
    if rep.get("notes") and "empty_series" in rep["notes"]:
        print("  (empty series)")
        return
    print(f"  grid_rows={rep.get('grid_rows')} valid_hours={rep.get('valid_hours')} valid_ratio={rep.get('valid_ratio')}")
    print(
        f"  max_consecutive_na_hours={rep.get('max_consecutive_na_hours')} "
        f"max_consecutive_valid_hours={rep.get('max_consecutive_valid_hours')}"
    )
    gh = rep.get("gap_hours_between_successive_valid")
    if isinstance(gh, dict) and gh.get("count_gaps", 0) > 0:
        print(
            f"  gaps_between_valid: n={gh['count_gaps']} max={gh['max']:.0f} "
            f"median={gh['median']:.1f} p95={gh['p95']:.1f}"
        )
    print(f"  effective_lag={rep.get('effective_lag')} walk_forward_step={rep.get('walk_forward_step')}")
    wf = rep.get("walk_forward_eligible_cutoffs_by_horizon", {})
    for hk in sorted(wf.keys(), key=lambda x: int(x)):
        b = wf[hk]
        if isinstance(b, dict):
            print(
                f"  h={hk:>2}: eligible={b.get('eligible')} / possible={b.get('possible_cutoffs_in_step_loop')} "
                f"ratio={b.get('eligible_ratio')}"
            )
    notes = rep.get("notes") or []
    if notes:
        print("  notes:")
        for n in notes:
            print(f"    - {n}")


def main() -> None:
    args = parse_args()
    csv_path = Path(args.iv_csv)
    if not csv_path.is_file():
        raise SystemExit(f"IV CSV not found: {csv_path}")

    horizons = _parse_horizons(args.horizons)
    lag_kw: dict[str, Any] = {}
    if int(args.lag) > 0:
        lag_kw["lag"] = int(args.lag)

    sites: list[str] = []
    if args.all_sites_from_config is not None:
        cfg = Path(args.all_sites_from_config)
        if not cfg.is_file():
            raise SystemExit(f"Sites config not found: {cfg}")
        sites = _load_site_nos_from_config(cfg)
    else:
        sn = str(args.site_no).strip()
        if not sn:
            raise SystemExit("Provide --site-no or --all-sites-from-config.")
        sites = [sn]

    combined: dict[str, Any] = {
        "iv_csv": str(csv_path.resolve()),
        "parameter_cd": str(args.parameter_cd),
        "horizons": list(horizons),
        "walk_forward_step": int(args.walk_forward_step),
        "lag_override": int(args.lag) if int(args.lag) > 0 else None,
        "sites": {},
    }

    for site_no in sites:
        s = load_hourly_series(csv_path, site_no, args.parameter_cd, dense=False)
        rep = hourly_grid_continuity_report(
            s,
            horizons=horizons,
            walk_forward_step=int(args.walk_forward_step),
            **lag_kw,
        )
        combined["sites"][site_no] = rep
        _print_human_summary(site_no, str(args.parameter_cd), rep)
        print()

    if args.report_out is not None:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {args.report_out.resolve()}")


if __name__ == "__main__":
    main()

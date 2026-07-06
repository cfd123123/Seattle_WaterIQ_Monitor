#!/usr/bin/env python3
"""
Build hourly feature table for Cedar River turbidity modeling (12117500).

Target: USGS parameter 63680 (turbidity, FNU) at site 12117500.
Upstream exogenous: USGS parameter **00060 (discharge, ft³/s)** at site **12116400**
(Cedar River at Powerplant at Cedar Falls) — **not** turbidity; NWIS has no 63680 at 12116400.

Open-Meteo: precipitation_mm, temperature_2m_c at target coordinates.

Example::

    .venv/bin/python fetch_turbidity_upstream_features.py \\
      --start-date 2022-01-01 \\
      --out-csv data/features_12117500_63680_openmeteo_upstream_2022.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT, _ROOT / "models"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fetch_open_meteo_archive_hourly import (
    _lat_lon_from_site,
    _parse_date,
    _rename_openmeteo_columns,
    fetch_archive_hourly,
)
from fetch_usgs_puget_sound import fetch_iv_for_parameter
from forecast_engine import load_hourly_series

TARGET_SITE = "12117500"
TARGET_PARAM = "63680"
UPSTREAM_SITE = "12116400"
UPSTREAM_PARAM = "00060"
UPSTREAM_COL = "upstream_discharge_cfs_12116400"


def _site_drainage_area(site_no: str) -> float | None:
    import dataretrieval.nwis as nwis

    r = nwis.get_record(sites=site_no, service="site")
    if r is None or r.empty:
        return None
    v = r.iloc[0].get("drain_area_va")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _site_name(site_no: str) -> str:
    import dataretrieval.nwis as nwis

    r = nwis.get_record(sites=site_no, service="site")
    if r is None or r.empty:
        return ""
    return str(r.iloc[0].get("station_nm", ""))


def validate_upstream_hydrology(target_site: str, upstream_site: str) -> dict[str, Any]:
    """Document and check that upstream is on the same river, upstream of target."""
    t_name = _site_name(target_site)
    u_name = _site_name(upstream_site)
    t_da = _site_drainage_area(target_site)
    u_da = _site_drainage_area(upstream_site)
    checks: dict[str, Any] = {
        "target_site_no": target_site,
        "target_station_name": t_name,
        "target_parameter": TARGET_PARAM,
        "target_parameter_label": "turbidity (63680)",
        "upstream_site_no": upstream_site,
        "upstream_station_name": u_name,
        "upstream_parameter": UPSTREAM_PARAM,
        "upstream_parameter_label": "discharge (00060), cubic feet per second — NOT turbidity",
        "upstream_csv_column": UPSTREAM_COL,
        "same_river_main_stem": "Cedar River, WA",
        "upstream_is_not_turbidity": True,
    }
    if t_da is not None and u_da is not None:
        checks["target_drainage_area_sq_mi"] = t_da
        checks["upstream_drainage_area_sq_mi"] = u_da
        checks["drainage_area_upstream_smaller"] = bool(u_da < t_da)
        checks["hydrologic_order_ok"] = bool(u_da < t_da)
    else:
        checks["hydrologic_order_ok"] = None
    # 12116400 is east/upstream reach (Cedar Falls); 12117500 is near Landsburg downstream.
    checks["reach_note"] = (
        "12116400 Cedar Falls powerplant is upstream of 12117500 near Landsburg on the Cedar River main stem; "
        "12117600 (below diversion) was rejected as redundant/near-target."
    )
    return checks


def _hourly_from_iv_csv(iv_path: Path, site: str, param: str) -> pd.Series:
    s = load_hourly_series(iv_path, site, param, dense=False)
    s.index = pd.to_datetime(s.index, utc=True)
    return s.sort_index()


def _causal_fill(s: pd.Series, limit: int = 24) -> pd.Series:
    return s.ffill(limit=limit)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch turbidity + Open-Meteo + upstream discharge features.")
    p.add_argument("--start-date", type=str, default="2022-01-01")
    p.add_argument("--end-date", type=str, default="", help="YYYY-MM-DD inclusive; default today UTC.")
    p.add_argument("--out-csv", type=Path, required=True)
    p.add_argument("--upstream-site", type=str, default=UPSTREAM_SITE)
    p.add_argument("--work-dir", type=Path, default=Path("data/_build_turbidity_upstream"))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    start_d = _parse_date(args.start_date)
    end_d = _parse_date(args.end_date) if str(args.end_date).strip() else date.today()
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    hydrology = validate_upstream_hydrology(TARGET_SITE, str(args.upstream_site).strip())
    if hydrology.get("hydrologic_order_ok") is False:
        print("Upstream drainage area >= target; refusing (not a valid upstream).", file=sys.stderr)
        print(json.dumps(hydrology, indent=2), file=sys.stderr)
        return 2

    start_s, end_s = start_d.isoformat(), end_d.isoformat()

    # Target turbidity IV
    iv_tgt = work / f"iv_{TARGET_SITE}_{TARGET_PARAM}.csv"
    df_tgt = fetch_iv_for_parameter([TARGET_SITE], TARGET_PARAM, start_s, end_s)
    if df_tgt.empty:
        print("No target turbidity IV.", file=sys.stderr)
        return 3
    df_tgt.to_csv(iv_tgt, index=False)

    # Upstream discharge IV (NOT turbidity)
    iv_up = work / f"iv_{args.upstream_site}_{UPSTREAM_PARAM}.csv"
    df_up = fetch_iv_for_parameter([str(args.upstream_site)], UPSTREAM_PARAM, start_s, end_s)
    if df_up.empty:
        print("No upstream discharge IV.", file=sys.stderr)
        return 4
    df_up.to_csv(iv_up, index=False)

    y = _hourly_from_iv_csv(iv_tgt, TARGET_SITE, TARGET_PARAM)
    q_up = _hourly_from_iv_csv(iv_up, str(args.upstream_site), UPSTREAM_PARAM)

    lat, lon = _lat_lon_from_site(TARGET_SITE)
    meteo_raw = fetch_archive_hourly(
        latitude=lat,
        longitude=lon,
        start_d=start_d,
        end_d=end_d,
        hourly_vars="precipitation,temperature_2m",
    )
    meteo = _rename_openmeteo_columns(meteo_raw)
    meteo.index = pd.to_datetime(meteo.index, utc=True)

    feat = y.to_frame(name=TARGET_PARAM)
    feat[UPSTREAM_COL] = q_up.reindex(feat.index)
    feat = feat.join(meteo, how="left")
    feat["precipitation_mm"] = _causal_fill(feat["precipitation_mm"].astype(float))
    feat["temperature_2m_c"] = _causal_fill(feat["temperature_2m_c"].astype(float))
    feat[UPSTREAM_COL] = _causal_fill(feat[UPSTREAM_COL].astype(float))

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    jdf = feat.reset_index()
    if jdf.columns[0] != "datetime_utc":
        jdf = jdf.rename(columns={jdf.columns[0]: "datetime_utc"})
    jdf.to_csv(out_csv, index=False)

    # Data-quality / overlap stats
    both = feat[[TARGET_PARAM, UPSTREAM_COL]].dropna(how="any")
    if len(both) >= 50:
        corr = float(both[TARGET_PARAM].corr(both[UPSTREAM_COL]))
        corr_lag6 = float(
            both[TARGET_PARAM].corr(both[UPSTREAM_COL].shift(6))
        ) if len(both) > 6 else None
    else:
        corr, corr_lag6 = None, None

    prov: dict[str, Any] = {
        **hydrology,
        "start_date": start_s,
        "end_date": end_s,
        "rows_hourly_grid": int(len(feat)),
        "valid_hours": {
            TARGET_PARAM: int(feat[TARGET_PARAM].notna().sum()),
            UPSTREAM_COL: int(feat[UPSTREAM_COL].notna().sum()),
            "precipitation_mm": int(feat["precipitation_mm"].notna().sum()),
            "temperature_2m_c": int(feat["temperature_2m_c"].notna().sum()),
        },
        "overlap_y_and_upstream_hours": int(len(both)),
        "corr_turbidity_vs_upstream_q_same_hour": corr,
        "corr_turbidity_vs_upstream_q_upstream_lag6h": corr_lag6,
        "datetime_min_utc": str(feat.index.min()),
        "datetime_max_utc": str(feat.index.max()),
        "wrote_csv": str(out_csv.resolve()),
        "built_utc": datetime.now(timezone.utc).isoformat(),
    }
    prov_path = out_csv.with_name(out_csv.stem + "_upstream_provenance.json")
    prov_path.write_text(json.dumps(prov, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(prov, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

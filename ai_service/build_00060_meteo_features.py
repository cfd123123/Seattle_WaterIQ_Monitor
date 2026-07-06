#!/usr/bin/env python3
"""
Build hourly 00060 + Open-Meteo precipitation features for all default Puget sites.

Precipitation source: Open-Meteo Historical Archive (ERA5-based grid), same as turbidity track.
https://open-meteo.com/en/docs/historical-weather-api

Example:
  .venv/bin/python build_00060_meteo_features.py \\
    --iv-csv data/usgs_puget_iv.csv \\
    --sites-config config/usgs_puget_default_sites.json \\
    --exclude-sites 12147600
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fetch_open_meteo_archive_hourly import (  # noqa: E402
    _lat_lon_from_site,
    _rename_openmeteo_columns,
    fetch_archive_hourly,
)
from forecast_engine import load_hourly_series  # noqa: E402

TARGET_PARAM = "00060"


def _load_site_list(config_path: Path, excluded: set[str]) -> list[str]:
    raw = config_path.read_text(encoding="utf-8")
    clean = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("//"))
    clean = re.sub(r",\s*([\]}])", r"\1", clean)
    payload = json.loads(clean)
    out: list[str] = []
    for row in payload.get("sites", []):
        site = str(row.get("site_no", "")).strip()
        if site and site not in excluded:
            out.append(site)
    return out


def _iv_date_bounds(iv_csv: Path, site_no: str) -> tuple[date, date]:
    df = pd.read_csv(iv_csv, usecols=["datetime", "site_no"])
    sub = df[df["site_no"].astype(str).str.strip() == str(site_no).strip()]
    if sub.empty:
        raise ValueError(f"No IV rows for site {site_no}")
    t = pd.to_datetime(sub["datetime"], utc=True, errors="coerce").dropna()
    if t.empty:
        raise ValueError(f"No parseable datetimes for site {site_no}")
    return t.min().date(), t.max().date()


def build_site_features(
    *,
    iv_csv: Path,
    site_no: str,
    out_dir: Path,
    hourly_vars: str,
) -> Path | None:
    y = load_hourly_series(iv_csv, site_no, TARGET_PARAM, dense=False)
    if y.empty:
        print(f"  skip {site_no}: empty 00060 hourly series", file=sys.stderr)
        return None
    start_d, end_d = _iv_date_bounds(iv_csv, site_no)
    lat, lon = _lat_lon_from_site(site_no)
    raw = fetch_archive_hourly(
        latitude=lat,
        longitude=lon,
        start_d=start_d,
        end_d=end_d,
        hourly_vars=hourly_vars,
    )
    if raw.empty:
        print(f"  skip {site_no}: Open-Meteo returned no rows", file=sys.stderr)
        return None
    meteo = _rename_openmeteo_columns(raw)
    if "precipitation_mm" not in meteo.columns:
        print(f"  skip {site_no}: no precipitation_mm in meteo response", file=sys.stderr)
        return None
    feat = y.to_frame(name=TARGET_PARAM)
    feat = feat.join(meteo[["precipitation_mm"]], how="left")
    out_path = out_dir / f"features_{site_no}_{TARGET_PARAM}_openmeteo.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    jdf = feat.reset_index()
    first = str(jdf.columns[0])
    if first != "datetime_utc":
        jdf = jdf.rename(columns={first: "datetime_utc"})
    jdf.to_csv(out_path, index=False)
    meta = {
        "site_no": site_no,
        "parameter_cd": TARGET_PARAM,
        "precipitation_source": "open-meteo-archive-v1",
        "precipitation_variable": "precipitation (hourly, mm)",
        "latitude": lat,
        "longitude": lon,
        "iv_start_date": start_d.isoformat(),
        "iv_end_date": end_d.isoformat(),
        "rows": int(len(jdf)),
        "precip_nonnull": int(jdf["precipitation_mm"].notna().sum()),
    }
    meta_path = out_path.with_name(out_path.stem + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"site_no": site_no, "wrote": str(out_path), **meta}, indent=2))
    return out_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build 00060 + Open-Meteo precip feature CSVs for default sites")
    p.add_argument("--iv-csv", type=Path, default=_ROOT / "data" / "usgs_puget_iv.csv")
    p.add_argument("--sites-config", type=Path, default=_ROOT / "config" / "usgs_puget_default_sites.json")
    p.add_argument("--exclude-sites", default="12147600")
    p.add_argument("--out-dir", type=Path, default=_ROOT / "data" / "features_00060_openmeteo")
    p.add_argument("--hourly", default="precipitation", help="Open-Meteo hourly vars (archive API names).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.iv_csv.is_file():
        print(f"Missing IV CSV: {args.iv_csv}", file=sys.stderr)
        return 2
    excluded = {x.strip() for x in str(args.exclude_sites).split(",") if x.strip()}
    sites = _load_site_list(args.sites_config, excluded)
    written: list[str] = []
    for site in sites:
        print(f"=== {site} ===", flush=True)
        p = build_site_features(
            iv_csv=args.iv_csv,
            site_no=site,
            out_dir=args.out_dir,
            hourly_vars=str(args.hourly),
        )
        if p is not None:
            written.append(str(p))
    manifest = args.out_dir / "manifest.json"
    manifest.write_text(json.dumps({"sites": sites, "files": written}, indent=2), encoding="utf-8")
    print(f"Wrote manifest {manifest} ({len(written)} feature files)")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())

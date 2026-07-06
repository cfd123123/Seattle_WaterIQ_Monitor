#!/usr/bin/env python3
"""
Fetch hourly exogenous weather from Open-Meteo Historical Archive (ERA5-based grid).

Use case: merge precipitation + temperature with USGS IV hourly series for turbidity training.
Terms: https://open-meteo.com/en/terms — use a descriptive User-Agent; respect fair use.

Examples:
  .venv/bin/python fetch_open_meteo_archive_hourly.py --site-no 12117500 --days 30 \\
      --out data/open_meteo_archive_12117500.csv

  .venv/bin/python fetch_open_meteo_archive_hourly.py --site-no 12117500 --days 30 \\
      --out data/open_meteo_archive_12117500.csv \\
      --join-iv-csv data/usgs_puget_iv.csv --join-parameter-cd 63680 \\
      --join-out data/features_12117500_63680_meteo.csv
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT, _ROOT / "models"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    import dataretrieval.nwis as nwis
except ImportError:
    nwis = None  # type: ignore

from forecast_engine import load_hourly_series

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# Open-Meteo recommends chunking very long ranges; stay conservative.
_MAX_DAYS_PER_REQUEST = 120
_USER_AGENT = "environment_project/1.0 (research; contact: local-dev)"


def _parse_date(s: str) -> date:
    return date.fromisoformat(str(s).strip())


def _lat_lon_from_site(site_no: str) -> tuple[float, float]:
    if nwis is None:
        raise RuntimeError("dataretrieval is required for --site-no (nwis.get_record).")
    df = nwis.get_record(sites=str(site_no).strip(), service="site")
    if df is None or df.empty:
        raise ValueError(f"No NWIS site metadata for site_no={site_no!r}")
    row = df.iloc[0]
    return float(row["dec_lat_va"]), float(row["dec_long_va"])


def _http_get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_archive_hourly(
    *,
    latitude: float,
    longitude: float,
    start_d: date,
    end_d: date,
    hourly_vars: str,
) -> pd.DataFrame:
    """Return UTC-indexed hourly DataFrame (one row per hour in API response)."""
    if end_d < start_d:
        raise ValueError("end_date must be >= start_date")
    parts: list[pd.DataFrame] = []
    cur = start_d
    while cur <= end_d:
        chunk_end = min(end_d, cur + timedelta(days=_MAX_DAYS_PER_REQUEST - 1))
        q = urllib.parse.urlencode(
            {
                "latitude": str(latitude),
                "longitude": str(longitude),
                "start_date": cur.isoformat(),
                "end_date": chunk_end.isoformat(),
                "hourly": hourly_vars,
                "timezone": "UTC",
            }
        )
        url = f"{ARCHIVE_URL}?{q}"
        payload = _http_get_json(url)
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            parts.append(pd.DataFrame())
            cur = chunk_end + timedelta(days=1)
            continue
        rows: dict[str, list[Any]] = {"datetime": times}
        for var in [v.strip() for v in hourly_vars.split(",") if v.strip()]:
            rows[var] = hourly.get(var, [None] * len(times))
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
        df = df.set_index("datetime").sort_index()
        parts.append(df)
        cur = chunk_end + timedelta(days=1)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, axis=0)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def _rename_openmeteo_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Stable column names for downstream CSV."""
    m = {
        "precipitation": "precipitation_mm",
        "temperature_2m": "temperature_2m_c",
        "rain": "rain_mm",
        "snowfall": "snowfall_cm",
    }
    return df.rename(columns={k: v for k, v in m.items() if k in df.columns})


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Open-Meteo archive hourly exogenous features (+ optional IV join).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--site-no", type=str, default="", help="USGS site_no: lat/lon from NWIS site service.")
    g.add_argument("--coordinates", type=str, default="", help="latitude,longitude (decimal degrees).")
    p.add_argument("--start-date", type=str, default="", help="YYYY-MM-DD (UTC archive day).")
    p.add_argument("--end-date", type=str, default="", help="YYYY-MM-DD inclusive.")
    p.add_argument("--days", type=int, default=0, help="If start/end omitted: days back from today (UTC).")
    p.add_argument(
        "--hourly",
        type=str,
        default="precipitation,temperature_2m",
        help="Comma-separated Open-Meteo hourly variable names (archive schema).",
    )
    p.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output CSV path (UTC index written as column datetime).",
    )
    p.add_argument("--join-iv-csv", type=Path, default=None, help="Optional: USGS IV wide CSV to align with.")
    p.add_argument("--join-site-no", type=str, default="", help="Site for IV join (default: same as --site-no).")
    p.add_argument("--join-parameter-cd", type=str, default="63680", help="IV parameter column for target series.")
    p.add_argument("--join-out", type=Path, default=None, help="Output path for IV + meteo merged CSV.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.coordinates.strip():
        lat_s, lon_s = [x.strip() for x in args.coordinates.split(",")[:2]]
        lat, lon = float(lat_s), float(lon_s)
    else:
        if not nwis:
            print("Install dataretrieval to use --site-no.", file=sys.stderr)
            return 2
        lat, lon = _lat_lon_from_site(args.site_no)

    end_d = date.today()
    if str(args.end_date).strip():
        end_d = _parse_date(args.end_date)
    if str(args.start_date).strip():
        start_d = _parse_date(args.start_date)
    elif int(args.days) > 0:
        start_d = end_d - timedelta(days=int(args.days))
    else:
        print("Provide --start-date and --end-date, or --days.", file=sys.stderr)
        return 2

    raw = fetch_archive_hourly(
        latitude=lat,
        longitude=lon,
        start_d=start_d,
        end_d=end_d,
        hourly_vars=str(args.hourly),
    )
    if raw.empty:
        print("Open-Meteo returned no hourly rows.", file=sys.stderr)
        return 3
    meteo = _rename_openmeteo_columns(raw)
    meta = {
        "source": "open-meteo-archive-v1",
        "url_base": ARCHIVE_URL,
        "request_latitude": lat,
        "request_longitude": lon,
        "grid_latitude": None,
        "grid_longitude": None,
        "start_date": start_d.isoformat(),
        "end_date": end_d.isoformat(),
        "hourly_variables_requested": str(args.hourly),
        "rows": int(len(meteo)),
    }
    # Re-fetch one chunk header for snapped grid (optional)
    try:
        q0 = urllib.parse.urlencode(
            {
                "latitude": str(lat),
                "longitude": str(lon),
                "start_date": end_d.isoformat(),
                "end_date": end_d.isoformat(),
                "hourly": "precipitation",
                "timezone": "UTC",
            }
        )
        snap = _http_get_json(f"{ARCHIVE_URL}?{q0}")
        meta["grid_latitude"] = snap.get("latitude")
        meta["grid_longitude"] = snap.get("longitude")
        meta["elevation_m"] = snap.get("elevation")
    except Exception:
        pass

    out_csv = Path(args.out)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_df = meteo.reset_index().rename(columns={"datetime": "datetime_utc"})
    out_df.to_csv(out_csv, index=False)
    meta_path = out_csv.with_name(out_csv.stem + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"wrote_csv": str(out_csv.resolve()), "wrote_meta": str(meta_path.resolve()), **meta}, indent=2))

    join_iv = args.join_iv_csv
    if join_iv is not None:
        site_j = str(args.join_site_no or args.site_no).strip()
        if not site_j:
            print("--join-iv-csv requires --join-site-no (or use --site-no).", file=sys.stderr)
            return 2
        if not join_iv.is_file():
            print(f"Missing IV CSV: {join_iv}", file=sys.stderr)
            return 2
        pc = str(args.join_parameter_cd).strip()
        s_iv = load_hourly_series(join_iv, site_j, pc, dense=False)
        if s_iv.empty:
            print(f"No hourly IV for site={site_j} parameter={pc}", file=sys.stderr)
            return 4
        feat = s_iv.to_frame(name=pc)
        meteo_idx = meteo.copy()
        meteo_idx.index = pd.to_datetime(meteo_idx.index, utc=True)
        feat = feat.join(meteo_idx, how="left")
        join_out = args.join_out
        if join_out is None:
            join_out = out_csv.parent / f"features_{site_j}_{pc}_with_openmeteo.csv"
        join_out = Path(join_out)
        jdf = feat.reset_index()
        first = str(jdf.columns[0])
        if first != "datetime_utc":
            jdf = jdf.rename(columns={first: "datetime_utc"})
        jdf.to_csv(join_out, index=False)
        print(json.dumps({"wrote_joined": str(join_out.resolve()), "rows": int(len(jdf))}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

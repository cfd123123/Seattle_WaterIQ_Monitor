#!/usr/bin/env python3
"""
Find or verify USGS NWIS monitoring sites (stdlib only, no third-party deps).

Exactly one location filter is required: --sites, --state, --bbox, or --huc.

Examples:
  python find_sites.py --sites 12117500,12147600 --catalog
  python find_sites.py --state WA --parameters 63680
  python find_sites.py --bbox -122.6,47.2,-121.8,47.8 --parameters 00060,63680 --limit 20

Prints one JSON document to stdout. Exit codes: 0 ok, 1 network/service error, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SITE_URL = "https://waterservices.usgs.gov/nwis/site/"
USER_AGENT = "usgs-water-data-skill/1.0"


def fail(msg: str, code: int) -> int:
    print(json.dumps({"ok": False, "error": msg}, indent=2), file=sys.stdout)
    return code


def parse_rdb(text: str) -> list[dict[str, str]]:
    """Parse NWIS tab-delimited RDB: skip '#' comments and the column-width line."""
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 2:
        return []
    header = lines[0].split("\t")
    rows = []
    for ln in lines[2:]:
        parts = ln.split("\t")
        rows.append({h: (parts[i].strip() if i < len(parts) else "") for i, h in enumerate(header)})
    return rows


def query(params: dict[str, str]) -> str | None:
    """Return RDB text, or None when NWIS reports no matching sites (HTTP 404)."""
    url = SITE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"NWIS site service HTTP {e.code}: {body}") from e


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    loc = p.add_mutually_exclusive_group(required=True)
    loc.add_argument("--sites", help="Comma-separated site numbers to look up / verify (8-15 digits).")
    loc.add_argument("--state", help="Two-letter US state code, e.g. WA.")
    loc.add_argument("--bbox", help="west,south,east,north in decimal degrees (max 25 sq. degrees).")
    loc.add_argument("--huc", help="2- or 8-digit hydrologic unit code.")
    p.add_argument("--parameters", default="", help="Only sites measuring these parameter codes (comma-separated).")
    p.add_argument("--site-type", default="ST", help="NWIS site type (ST=stream, LK=lake, ES=estuary, GW=well). Ignored with --sites.")
    p.add_argument("--include-inactive", action="store_true", help="Include discontinued sites (search mode).")
    p.add_argument("--catalog", action="store_true", help="Also list each site's real-time (IV) parameters with date ranges.")
    p.add_argument("--limit", type=int, default=50, help="Max sites to print (default 50).")
    a = p.parse_args(argv)

    params: dict[str, str] = {"format": "rdb"}
    requested: list[str] = []
    if a.sites:
        requested = [s.strip() for s in a.sites.split(",") if s.strip()]
        bad = [s for s in requested if not re.fullmatch(r"\d{8,15}", s)]
        if bad or not requested:
            return fail(f"Site numbers must be 8-15 digits: {bad or a.sites!r}", 2)
        params["sites"] = ",".join(requested)
        params["siteStatus"] = "all"
    else:
        if a.state:
            params["stateCd"] = a.state.strip().upper()
        elif a.bbox:
            nums = a.bbox.split(",")
            try:
                w, s, e, n = (float(x) for x in nums)
            except ValueError:
                return fail("--bbox must be four numbers: west,south,east,north", 2)
            params["bBox"] = f"{w:.6f},{s:.6f},{e:.6f},{n:.6f}"
        else:
            params["huc"] = a.huc.strip()
        params["siteType"] = a.site_type
        params["hasDataTypeCd"] = "iv"
        params["siteStatus"] = "all" if a.include_inactive else "active"
    pcodes = [c.strip() for c in a.parameters.split(",") if c.strip()]
    if any(not re.fullmatch(r"\d{5}", c) for c in pcodes):
        return fail(f"Parameter codes must be 5 digits: {a.parameters!r}", 2)
    if pcodes:
        params["parameterCd"] = ",".join(pcodes)
    if a.catalog:
        params["seriesCatalogOutput"] = "true"
        params["outputDataTypeCd"] = "iv"

    try:
        text = query(params)
    except Exception as e:  # network errors, timeouts, non-404 HTTP errors
        return fail(str(e), 1)
    rows = parse_rdb(text) if text else []

    # With --catalog NWIS returns one row per (site, parameter series); fold them per site.
    sites: dict[str, dict[str, Any]] = {}
    for r in rows:
        sn = r.get("site_no", "")
        site = sites.setdefault(sn, {
            "site_no": sn,
            "name": r.get("station_nm", ""),
            "site_type": r.get("site_tp_cd", ""),
            "lat": float(r["dec_lat_va"]) if r.get("dec_lat_va") else None,
            "lon": float(r["dec_long_va"]) if r.get("dec_long_va") else None,
            "huc": r.get("huc_cd", ""),
        })
        if a.catalog and r.get("parm_cd"):
            site.setdefault("iv_parameters", []).append({
                "parameter_cd": r["parm_cd"],
                "description": r.get("loc_web_ds", ""),
                "begin_date": r.get("begin_date", ""),
                "end_date": r.get("end_date", ""),
            })

    found = list(sites.values())
    out: dict[str, Any] = {"ok": True, "total_found": len(found)}
    if requested:
        out["missing"] = [s for s in requested if s not in sites]
    out["truncated"] = len(found) > a.limit
    out["sites"] = found[: max(0, a.limit)]
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Fetch USGS NWIS instantaneous values (IV, ~15-min real-time sensor data) to a wide CSV
(stdlib only, no third-party deps).

Examples:
  python fetch_iv.py --sites 12117500 --parameters 00060,63680 --period P7D --out cedar.csv
  python fetch_iv.py --sites 12117500,12145500 --start 2025-11-01 --end 2025-11-15 --out flood.csv

CSV columns: site_no, datetime_utc, <pcode>, <pcode>_qualifiers, ... (one pair per parameter).
stdout gets a JSON summary (row count, units, per-series stats) so the CSV need not be read
to answer simple questions. Exit codes: 0 ok, 1 nothing fetched / service error, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

IV_URL = "https://waterservices.usgs.gov/nwis/iv/"
USER_AGENT = "usgs-water-data-skill/1.0"
# Discharge, water temp, specific conductance, dissolved oxygen, pH, turbidity
DEFAULT_PARAMETERS = "00060,00010,00095,00300,00400,63680"
MAX_SPAN_DAYS = 120  # keep single requests small; NWIS throttles/truncates huge pulls


def fail(msg: str, code: int) -> int:
    print(json.dumps({"ok": False, "error": msg}, indent=2))
    return code


def fetch_site(site_no: str, pcodes: list[str], window: dict[str, str]) -> dict[str, Any]:
    q = {"format": "json", "sites": site_no, "parameterCd": ",".join(pcodes), "siteStatus": "all", **window}
    req = urllib.request.Request(IV_URL + "?" + urllib.parse.urlencode(q), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def to_utc(ts: str) -> str:
    # NWIS returns local time with offset, e.g. 2026-10-16T15:15:00.000-07:00
    return datetime.fromisoformat(ts).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sites", required=True, help="Comma-separated USGS site numbers (8-15 digits).")
    p.add_argument("--parameters", default=DEFAULT_PARAMETERS, help=f"Comma-separated 5-digit codes (default {DEFAULT_PARAMETERS}).")
    p.add_argument("--period", default="", help="ISO-8601 duration back from now, e.g. PT6H, P7D (max P120D). Default P7D.")
    p.add_argument("--start", default="", help="Start date YYYY-MM-DD (use with --end instead of --period).")
    p.add_argument("--end", default="", help="End date YYYY-MM-DD (default today).")
    p.add_argument("--out", type=Path, required=True, help="Output CSV path (overwritten).")
    a = p.parse_args(argv)

    sites = [s.strip() for s in a.sites.split(",") if s.strip()]
    if not sites or any(not re.fullmatch(r"\d{8,15}", s) for s in sites):
        return fail(f"Site numbers must be 8-15 digits: {a.sites!r}", 2)
    pcodes = [c.strip() for c in a.parameters.split(",") if c.strip()]
    if not pcodes or any(not re.fullmatch(r"\d{5}", c) for c in pcodes):
        return fail(f"Parameter codes must be 5 digits: {a.parameters!r}", 2)

    if a.start:
        if a.period:
            return fail("Use either --period or --start/--end, not both.", 2)
        try:
            d0 = date.fromisoformat(a.start)
            d1 = date.fromisoformat(a.end) if a.end else datetime.now(timezone.utc).date()
        except ValueError:
            return fail("--start/--end must be YYYY-MM-DD.", 2)
        if d1 < d0:
            return fail("--end is before --start.", 2)
        if (d1 - d0).days > MAX_SPAN_DAYS:
            return fail(f"Window exceeds {MAX_SPAN_DAYS} days; split into smaller requests.", 2)
        window = {"startDT": d0.isoformat(), "endDT": d1.isoformat()}
    else:
        period = a.period or "P7D"
        m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?)?", period)
        if not m or not (m.group(1) or m.group(2)):
            return fail(f"--period must look like P7D or PT6H, got {period!r}", 2)
        if int(m.group(1) or 0) + int(m.group(2) or 0) / 24 > MAX_SPAN_DAYS:
            return fail(f"--period exceeds {MAX_SPAN_DAYS} days; use --start/--end in chunks.", 2)
        window = {"period": period}

    # rows[(site, time)][pcode] = (value, qualifiers); first non-empty series wins when NWIS
    # returns several series for one parameter (e.g. two turbidity sensors at one gage).
    rows: dict[tuple[str, str], dict[str, tuple[str, str]]] = {}
    series: dict[tuple[str, str], dict[str, Any]] = {}
    warnings: list[str] = []
    for sn in sites:
        try:
            doc = fetch_site(sn, pcodes, window)
        except urllib.error.HTTPError as e:
            warnings.append(f"site {sn}: HTTP {e.code}")
            continue
        except Exception as e:
            warnings.append(f"site {sn}: {e}")
            continue
        for ts in doc.get("value", {}).get("timeSeries", []):
            var = ts["variable"]
            pc = var["variableCode"][0]["value"]
            nodata = var.get("noDataValue")
            meta = series.setdefault((sn, pc), {
                "site_no": sn,
                "site_name": ts["sourceInfo"]["siteName"],
                "parameter_cd": pc,
                "parameter_name": html.unescape(var["variableName"]),
                "unit": var["unit"]["unitCode"],
                "values": [],
            })
            for block in ts.get("values", []):
                for v in block.get("value", []):
                    raw = v.get("value")
                    try:
                        num = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if nodata is not None and num == float(nodata):
                        continue
                    t = to_utc(v["dateTime"])
                    cell = rows.setdefault((sn, t), {})
                    if pc not in cell:
                        cell[pc] = (raw, "|".join(v.get("qualifiers", [])))
                        meta["values"].append((t, num))

    for sn in sites:
        for pc in pcodes:
            if not series.get((sn, pc), {}).get("values"):
                warnings.append(f"site {sn}: no data for {pc} in window")

    if not rows:
        return fail("No data returned. " + "; ".join(warnings), 1)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["site_no", "datetime_utc"] + [x for pc in pcodes for x in (pc, f"{pc}_qualifiers")])
        for (sn, t) in sorted(rows):
            cell = rows[(sn, t)]
            w.writerow([sn, t] + [x for pc in pcodes for x in cell.get(pc, ("", ""))])

    summary = []
    for meta in series.values():
        vals = sorted(meta.pop("values"))
        if not vals:
            continue
        nums = [v for _, v in vals]
        summary.append({**meta, "count": len(vals), "first_utc": vals[0][0], "last_utc": vals[-1][0],
                        "latest": nums[-1], "min": min(nums), "max": max(nums),
                        "mean": round(sum(nums) / len(nums), 4)})
    print(json.dumps({"ok": True, "out": str(a.out.resolve()), "rows": len(rows), "window": window,
                      "series": summary, "warnings": warnings}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

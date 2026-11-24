---
name: usgs-water-data
description: Find USGS stream/water-quality monitoring sites and download their real-time sensor data (streamflow, gage height, water temperature, turbidity, dissolved oxygen, pH, conductance) from the USGS NWIS web services. Use when the user asks about current or recent river/stream conditions in the US, wants USGS gage data, mentions a USGS site number or NWIS parameter code (e.g. 00060, 63680), or needs hydrology/water-quality time series as CSV for analysis.
---

# USGS Water Data

Two stdlib-only Python scripts (no `pip install` needed) wrap the public USGS NWIS services.
No API key is required. Run them with `python3` from this skill's directory.

| Script | Purpose |
|--------|---------|
| `scripts/find_sites.py` | Search sites by state / bounding box / HUC, or verify site numbers and list which parameters they report. |
| `scripts/fetch_iv.py` | Download instantaneous values (~15-min readings) to a wide CSV and print a JSON summary. |

Both print a single JSON document to stdout with `"ok": true|false`. Run `--help` for all flags.

## Workflow

1. **Resolve the site.** If the user gives a place name instead of a site number, search first:
   ```bash
   python3 scripts/find_sites.py --state WA --parameters 00060
   python3 scripts/find_sites.py --bbox -122.6,47.2,-121.8,47.8 --parameters 63680
   ```
   Pick the site whose `name` matches the user's river/location; if several plausibly match,
   show the candidates and ask. A bbox is the best way to search "near <city>" — build one roughly
   ±0.3° around the city's coordinates.

2. **Check what the site measures** before fetching, unless the user only wants discharge (00060)
   or gage height (00065), which nearly every stream gage reports:
   ```bash
   python3 scripts/find_sites.py --sites 12117500 --catalog
   ```
   `missing` lists site numbers that don't exist. `iv_parameters` shows each available parameter
   with its date range — don't request parameters a site doesn't have.

3. **Fetch the data:**
   ```bash
   python3 scripts/fetch_iv.py --sites 12117500 --parameters 00060,63680 --period P7D --out cedar_iv.csv
   python3 scripts/fetch_iv.py --sites 12117500 --start 2025-11-01 --end 2025-11-15 --out event.csv
   ```
   - `--period` takes ISO-8601 durations (`PT6H`, `P1D`, `P30D`). One request is capped at 120 days;
     for longer history loop over `--start/--end` chunks and concatenate the CSVs.
   - Write the CSV into the user's working directory with a descriptive name unless they specify one.

4. **Answer from the JSON summary first.** `series[]` already has `latest`, `min`, `max`, `mean`,
   `count`, `unit`, and the UTC time span per site × parameter — for "what is the river doing right
   now" questions that is enough; only load the CSV (e.g. with pandas) for trends, plots, or
   resampling.

## Interpreting results

- Always state the **unit** from the summary and the **timestamp** of the latest reading (UTC, and
  convert to the site's local time if the user is local).
- Recent data carries qualifier `P` (provisional, may be revised) — mention this when the numbers
  feed a decision.
- `warnings` like `no data for 63680 in window` mean the sensor was offline or the site doesn't
  carry that parameter; say so rather than silently dropping it.
- Turbidity (63680) is reported in FNU; it is roughly comparable to NTU but not identical.
- This is raw gage data, not an official forecast or flood warning — for flood safety point users
  to the National Weather Service (water.noaa.gov).

## Reference

Read `references/parameter_codes.md` when you need a parameter code not listed above, the meaning
of a qualifier code, site-type codes, or details on time zones and request limits.

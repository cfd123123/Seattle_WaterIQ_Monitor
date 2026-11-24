# USGS NWIS reference

## Common parameter codes (IV / real-time)

| Code  | Parameter                         | Typical unit   | Notes |
|-------|-----------------------------------|----------------|-------|
| 00060 | Discharge (streamflow)            | ft³/s          | Most widely available; computed from gage height via a rating curve. |
| 00065 | Gage height (stage)               | ft             | Raw water level; available at nearly every stream gage. |
| 00010 | Water temperature                 | °C             | |
| 00095 | Specific conductance @25 °C       | µS/cm          | Proxy for dissolved solids / salinity. |
| 00300 | Dissolved oxygen                  | mg/L           | |
| 00301 | Dissolved oxygen, % saturation    | %              | |
| 00400 | pH                                | standard units | |
| 63680 | Turbidity (FNU, ISO 7027 sensor)  | FNU            | FNU ≈ NTU for rough comparisons only; methods differ. |
| 00045 | Precipitation                     | in             | Only at sites with a rain gage. |
| 72019 | Depth to water below land surface | ft             | Groundwater wells (site type GW). |
| 99133 | Nitrate + nitrite, in situ        | mg/L as N      | Sparse; optical nitrate sensors. |
| 32315 | Chlorophyll, in situ fluorescence | RFU            | Sparse. |

Codes are always 5 digits with leading zeros. Not every site measures every parameter — use
`find_sites.py --sites <id> --catalog` to see what a site actually reports.

Full code list: https://help.waterdata.usgs.gov/codes-and-parameters/parameters

## Qualifier codes (`<pcode>_qualifiers` column)

| Code | Meaning |
|------|---------|
| P    | Provisional — not yet reviewed; may be revised. All recent real-time data is provisional. |
| A    | Approved — reviewed and final. |
| e    | Estimated value. |
| Ice  | Affected by ice (value usually missing). |
| Eqp  | Equipment malfunction. |
| Bkw  | Affected by backwater. |
| Ssn  | Parameter monitored seasonally. |
| Dis  | Data-collection discontinued. |

Multiple qualifiers are joined with `|`, e.g. `P|e`.

## Site types (`--site-type`)

ST stream · LK lake/reservoir · ES estuary · SP spring · GW well · AT atmosphere

## Service notes

- IV data is typically 15-minute (sometimes 5-minute) resolution; the real-time archive goes back
  to 2007 for most sites, but long windows return large payloads — the script caps one request
  at 120 days, so chunk longer histories.
- Times from the service carry a local UTC offset; the script normalizes to UTC (`datetime_utc`).
- `--start/--end` dates are interpreted in the **site's local time** and `--end` is inclusive, so the
  UTC range in the output can extend past the end date by the site's UTC offset.
- Site numbers are 8 digits for surface water, 15 digits for groundwater wells.
- Service docs: https://waterservices.usgs.gov/docs/instantaneous-values/ and
  https://waterservices.usgs.gov/docs/site-service/

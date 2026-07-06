"""
Discover USGS IV sites in a Puget Sound / greater-Seattle bounding box that have all core
parameters in the recent window, then merge **new** site_no entries into
``config/usgs_puget_default_sites.json`` (preserves existing order; appends new rows).

Uses the same NWIS IV endpoint pattern as ``discover_usgs_sites_for_core_params.py`` but
filters by ``bBox`` instead of ``stateCd`` so the candidate set is regional.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_CORE_PARAMS = ("00010", "00400", "00300", "00095", "63680")

# West, South, East, North — Puget Sound / greater Seattle (surface-water IV coverage).
# Adjust if you need tighter or wider discovery.
DEFAULT_PUGET_BBOX: tuple[float, float, float, float] = (-123.05, 46.88, -121.25, 48.58)


def _bbox_query(bbox: tuple[float, float, float, float]) -> str:
    w, s, e, n = bbox
    return f"{w},{s},{e},{n}"


def _geo_from_source_info(source_info: dict[str, Any]) -> tuple[float | None, float | None]:
    gl = source_info.get("geoLocation") or {}
    gg = gl.get("geogLocation") or {}
    try:
        lat = gg.get("latitude")
        lon = gg.get("longitude")
        if lat is None or lon is None:
            return None, None
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None


def fetch_sites_bbox_for_param(
    bbox: tuple[float, float, float, float],
    param_cd: str,
    days: int,
) -> tuple[set[str], dict[str, str], dict[str, tuple[float, float]]]:
    q = urllib.parse.urlencode(
        {
            "format": "json",
            "bBox": _bbox_query(bbox),
            "parameterCd": param_cd,
            "period": f"P{max(1, days)}D",
            "siteStatus": "active",
        }
    )
    url = f"https://waterservices.usgs.gov/nwis/iv/?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "water-monitor-puget-discovery/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        payload = json.load(r)
    series = payload.get("value", {}).get("timeSeries", [])
    sites: set[str] = set()
    names: dict[str, str] = {}
    coords: dict[str, tuple[float, float]] = {}
    for ts in series:
        src = ts.get("sourceInfo") or {}
        code = str(src.get("siteCode", [{}])[0].get("value", "")).strip()
        if not code:
            continue
        sites.add(code)
        nm = str(src.get("siteName", "")).strip()
        if nm:
            names.setdefault(code, nm)
        lat, lon = _geo_from_source_info(src)
        if lat is not None and lon is not None and code not in coords:
            coords[code] = (lat, lon)
    return sites, names, coords


def discover_core_sites_in_bbox(
    bbox: tuple[float, float, float, float],
    *,
    days: int = 30,
    params: tuple[str, ...] = DEFAULT_CORE_PARAMS,
) -> tuple[list[str], dict[str, str], dict[str, tuple[float, float]]]:
    """Return sorted intersection of sites that have IV data for every ``params`` in the bbox."""
    all_sets: list[set[str]] = []
    merged_names: dict[str, str] = {}
    merged_coords: dict[str, tuple[float, float]] = {}
    for p in params:
        sites, names, coords = fetch_sites_bbox_for_param(bbox, p, days)
        all_sets.append(sites)
        merged_names.update(names)
        merged_coords.update(coords)
    common = set.intersection(*all_sets) if all_sets else set()
    ordered = sorted(common)
    return ordered, merged_names, merged_coords


def load_puget_config(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("sites config must be a JSON object")
    sites = raw.get("sites")
    if not isinstance(sites, list):
        raise ValueError("sites config must contain a sites array")
    return raw


def merge_new_sites_into_config(
    config_path: Path,
    discovered_order: list[str],
    names: dict[str, str],
    coords: dict[str, tuple[float, float]],
    *,
    dry_run: bool = False,
    max_new: int | None = 80,
) -> dict[str, Any]:
    """
    Append site dicts for site_no present in ``discovered_order`` but not already in config.
    Existing entries keep their order and fields; new rows get site_no, name, latitude, longitude when known.
    """
    path = config_path.resolve()
    raw = load_puget_config(path)
    sites_list = raw.get("sites")
    assert isinstance(sites_list, list)

    existing_nos: set[str] = set()
    for item in sites_list:
        if isinstance(item, str):
            existing_nos.add(str(item).strip())
        elif isinstance(item, dict):
            no = str(item.get("site_no", "")).strip()
            if no:
                existing_nos.add(no)

    added: list[dict[str, Any]] = []
    for site_no in discovered_order:
        if site_no in existing_nos:
            continue
        if max_new is not None and len(added) >= max_new:
            break
        row: dict[str, Any] = {
            "site_no": site_no,
            "name": names.get(site_no, ""),
        }
        if site_no in coords:
            lat, lon = coords[site_no]
            row["latitude"] = round(lat, 6)
            row["longitude"] = round(lon, 6)
        added.append(row)
        existing_nos.add(site_no)

    original_len = len(sites_list)
    if not dry_run and added:
        sites_list.extend(added)
        raw["sites"] = sites_list
        raw["discovery_meta"] = {
            "source": "puget_site_discovery.merge_new_sites_into_config",
            "last_merge_added": len(added),
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    return {
        "config_path": str(path),
        "added": added,
        "added_count": len(added),
        "total_sites_after": original_len + len(added),
        "dry_run": dry_run,
    }

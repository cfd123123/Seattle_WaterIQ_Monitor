#!/usr/bin/env python3
"""
通过 NWIS IV 接口按 parameterCd 取站点集合并做交集，生成核心参数齐全的站点清单。
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_CORE_PARAMS = ("00010", "00400", "00300", "00095", "63680")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Discover WA IV sites with core params")
    p.add_argument("--state", default="WA", help="USGS stateCd, default WA")
    p.add_argument("--days", type=int, default=30, help="回溯天数")
    p.add_argument(
        "--params",
        default=",".join(DEFAULT_CORE_PARAMS),
        help="逗号分隔 parameter_cd",
    )
    p.add_argument("--limit", type=int, default=15, help="最多输出站点数（按 site_no 排序截断）")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "config" / "usgs_wa_core_sites.json"))
    return p.parse_args()


def fetch_sites_for_param(state_cd: str, param_cd: str, days: int) -> tuple[set[str], dict[str, str]]:
    q = urllib.parse.urlencode(
        {
            "format": "json",
            "stateCd": state_cd,
            "parameterCd": param_cd,
            "period": f"P{max(1, days)}D",
            "siteStatus": "active",
        }
    )
    url = f"https://waterservices.usgs.gov/nwis/iv/?{q}"
    with urllib.request.urlopen(url, timeout=60) as r:
        payload = json.load(r)
    series = payload.get("value", {}).get("timeSeries", [])
    sites: set[str] = set()
    names: dict[str, str] = {}
    for ts in series:
        src = ts.get("sourceInfo", {})
        code = str(src.get("siteCode", [{}])[0].get("value", "")).strip()
        if not code:
            continue
        sites.add(code)
        names.setdefault(code, str(src.get("siteName", "")).strip())
    return sites, names


def main() -> None:
    args = parse_args()
    params = [p.strip() for p in args.params.split(",") if p.strip()]
    all_sets: list[set[str]] = []
    merged_names: dict[str, str] = {}
    for p in params:
        sites, names = fetch_sites_for_param(args.state, p, args.days)
        all_sets.append(sites)
        merged_names.update(names)
        print(f"parameter {p}: {len(sites)} sites")
    common = sorted(set.intersection(*all_sets) if all_sets else set())
    selected = common[: max(1, args.limit)]

    out_json = {
        "region_label": f"{args.state} surface-water IV core sites (auto discovered)",
        "notes": (
            f"Auto-discovered by discover_usgs_sites_for_core_params.py; "
            f"params={params}, days={args.days}, intersection strategy"
        ),
        "sites": [{"site_no": s, "name": merged_names.get(s, "")} for s in selected],
        "discovery_meta": {
            "state": args.state,
            "params": params,
            "days": args.days,
            "selected_count": len(selected),
            "intersection_total": len(common),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Selected {len(selected)} / intersection {len(common)} -> {out.resolve()}")


if __name__ == "__main__":
    main()

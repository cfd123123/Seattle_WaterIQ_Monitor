#!/usr/bin/env python3
"""
从 USGS NWIS 拉取普吉特湾 / 大西雅图一带地表水瞬时数据（IV），供规则评分与短时预测管线使用。

参数码与项目内 11 字段对照见：monitor_business/docs/usgs-parameter-mapping.md

依赖：dataretrieval、pandas（见 requirements.txt）。

示例：
  .venv/bin/python fetch_usgs_puget_sound.py --days 30 --out data/usgs_puget_iv.csv
  （省略 --parameters 时使用 usgs_iv_constants 中与映射文档一致的默认 parameterCd 列表）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import dataretrieval.nwis as nwis
except ImportError as e:
    print("请先安装依赖: pip install dataretrieval pandas", file=sys.stderr)
    raise SystemExit(1) from e

from usgs_iv_constants import DEFAULT_FETCH_PARAMETER_CSV


def _as_utc_date(d: datetime) -> datetime:
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def load_sites_config(path: Path) -> tuple[str, list[dict[str, Any]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    region = str(raw.get("region_label", ""))
    sites = raw.get("sites")
    if not isinstance(sites, list) or not sites:
        raise ValueError("sites-config 需包含非空 sites 数组")
    out = []
    for s in sites:
        if isinstance(s, str):
            out.append({"site_no": s.strip(), "name": ""})
            continue
        no = str(s.get("site_no", "")).strip()
        if not no:
            continue
        out.append({"site_no": no, "name": str(s.get("name", ""))})
    if not out:
        raise ValueError("未解析到任何 site_no")
    return region, out


def _unwrap_iv_response(response: Any) -> pd.DataFrame:
    if isinstance(response, tuple) and len(response) > 0:
        return response[0]
    return response


def fetch_iv_for_parameter(
    site_numbers: list[str],
    parameter_cd: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    sites_arg = ",".join(site_numbers)
    response = nwis.get_iv(
        sites=sites_arg,
        parameterCd=parameter_cd,
        start=start,
        end=end,
    )
    df = _unwrap_iv_response(response)
    if df is None or df.empty:
        return pd.DataFrame(columns=["site_no", "datetime", parameter_cd, f"{parameter_cd}_quality_cd"])
    out = df.reset_index()
    # 列名：site_no, datetime + 参数值与审批码
    rename: dict[str, str] = {}
    if parameter_cd in out.columns:
        pass
    for c in list(out.columns):
        if c == f"{parameter_cd}_cd":
            rename[c] = f"{parameter_cd}_quality_cd"
    out = out.rename(columns=rename)
    keep = ["site_no", "datetime", parameter_cd]
    qc = f"{parameter_cd}_quality_cd"
    if qc in out.columns:
        keep.append(qc)
    return out[[c for c in keep if c in out.columns]]


def merge_parameter_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    base: pd.DataFrame | None = None
    for f in frames:
        if f.empty:
            continue
        if base is None:
            base = f
        else:
            base = base.merge(f, on=["site_no", "datetime"], how="outer")
    if base is None:
        return pd.DataFrame()
    return base.sort_values(["site_no", "datetime"]).reset_index(drop=True)


def run_fetch(
    *,
    sites_config: Path | None = None,
    start: str = "",
    end: str = "",
    days: int = 30,
    parameters: str | None = None,
    out: Path | None = None,
    include_latest_check_payloads: bool = False,
    extra_site_nos: list[str] | None = None,
) -> dict[str, Any]:
    """
    从 NWIS 拉取 IV、合并参数列并 **整文件覆盖** 写入 ``out``（不追加，避免 CSV 无限增长）。

    未指定 ``start``/``end`` 时，使用「当前 UTC 日期为 end、向前 ``days`` 天」为窗口。
    返回与 CLI 成功时打印的 JSON 元数据一致的字典。
    """
    cfg = sites_config or Path(__file__).resolve().parent / "config" / "usgs_puget_default_sites.json"
    out_path = out or Path(__file__).resolve().parent / "data" / "usgs_puget_iv.csv"
    param_csv = parameters if parameters is not None else DEFAULT_FETCH_PARAMETER_CSV

    region, site_rows = load_sites_config(cfg)
    site_numbers = [r["site_no"] for r in site_rows]
    name_by_site = {r["site_no"]: r["name"] for r in site_rows}
    seen = set(site_numbers)
    if extra_site_nos:
        for raw in extra_site_nos:
            sn = str(raw).strip()
            if sn and sn not in seen:
                site_numbers.append(sn)
                name_by_site[sn] = name_by_site.get(sn, "")
                seen.add(sn)

    end_dt = _as_utc_date(datetime.now(timezone.utc))
    if end:
        end_dt = _as_utc_date(datetime.fromisoformat(end).replace(tzinfo=timezone.utc))
    if start:
        start_dt = _as_utc_date(datetime.fromisoformat(start).replace(tzinfo=timezone.utc))
    else:
        start_dt = end_dt - timedelta(days=max(1, days))

    start_s = start_dt.date().isoformat()
    end_s = end_dt.date().isoformat()

    params = [x.strip() for x in param_csv.split(",") if x.strip()]
    if not params:
        raise ValueError("至少需要一个 parameterCd（parameters 非空）")

    frames: list[pd.DataFrame] = []
    for pc in params:
        try:
            df = fetch_iv_for_parameter(site_numbers, pc, start_s, end_s)
        except Exception as e:
            print(f"[警告] parameter {pc} 拉取失败: {e}", file=sys.stderr)
            continue
        if df.empty:
            print(f"[警告] parameter {pc} 无数据（站点或时段可能无该参数）", file=sys.stderr)
        else:
            frames.append(df)

    merged = merge_parameter_frames(frames)
    merged.insert(0, "region_label", region)
    merged["station_name"] = merged["site_no"].map(name_by_site).fillna("")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {
        "region": region,
        "sites": len(site_numbers),
        "parameters": params,
        "start": start_s,
        "end": end_s,
        "rows": int(len(merged)),
        "out": str(out_path.resolve()),
        "mode": "overwrite",
    }
    if include_latest_check_payloads:
        from usgs_iv_to_predict_payload import incremental_check_bundles, iv_row_keys_from_csv

        old_keys = iv_row_keys_from_csv(out_path)
        payloads = incremental_check_bundles(merged, old_keys)
        meta["incremental_check_payloads"] = payloads
        meta["incremental_rows_new"] = len(payloads)

    merged.to_csv(out_path, index=False)
    return meta


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch USGS NWIS IV for Puget Sound demo sites.")
    p.add_argument(
        "--sites-config",
        type=Path,
        default=Path(__file__).resolve().parent / "config" / "usgs_puget_default_sites.json",
        help="站点清单 JSON（含 sites[].site_no）",
    )
    p.add_argument("--start", type=str, default="", help="开始日期 YYYY-MM-DD（UTC 语义，与 NWIS 一致）")
    p.add_argument("--end", type=str, default="", help="结束日期 YYYY-MM-DD（不含次日可少一天重复点）")
    p.add_argument("--days", type=int, default=30, help="未指定 start/end 时，从 end 往前推的天数")
    p.add_argument(
        "--parameters",
        type=str,
        default=DEFAULT_FETCH_PARAMETER_CSV,
        metavar="CSV",
        help=(
            "USGS NWIS parameterCd，逗号分隔（必须为官方代号如 00010、63680）。"
            f"默认 {DEFAULT_FETCH_PARAMETER_CSV}；释义与映射见 monitor_business/docs/usgs-parameter-mapping.md"
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "usgs_puget_iv.csv",
        help="输出 CSV 路径",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        meta = run_fetch(
            sites_config=args.sites_config,
            start=args.start,
            end=args.end,
            days=args.days,
            parameters=args.parameters,
            out=args.out,
            include_latest_check_payloads=False,
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

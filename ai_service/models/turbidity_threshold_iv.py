"""
从 USGS IV 宽表读取某站 63680 浊度原始序列，取时间排序后最近 2 个有效点（去毛刺规则由 Java 侧判定）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

PARAM_63680 = "63680"


def site_nos_with_nonnull_63680(csv_path: Path) -> list[str]:
    """
    IV 宽表中至少存在一条可解析为数值的 63680 行的 site_no（去重、排序）。
    供 Java 仅对已登记且 NWIS 实际发布浊度的站点做阈值扫描。
    """
    if not csv_path.is_file():
        return []
    df = pd.read_csv(csv_path)
    if "site_no" not in df.columns or PARAM_63680 not in df.columns:
        return []
    s = pd.to_numeric(df[PARAM_63680], errors="coerce")
    sub = df.loc[s.notna()].copy()
    sub["site_no"] = sub["site_no"].astype(str).str.strip()
    sites = sorted(sub["site_no"].unique().tolist())
    return [x for x in sites if x]


def turbidity_threshold_batch_sites(csv_path: Path, site_nos: list[str]) -> dict[str, Any]:
    """
    单次读 CSV，为多个站点各返回最近至多 2 个 63680 采样（按 datetime 升序后的 tail(2)）。
    """
    sites_in = [str(s).strip() for s in site_nos if s and str(s).strip()]
    if not sites_in:
        return {"sites": {}}

    if not csv_path.is_file():
        return {
            "sites": {s: {"available": False, "points": [], "reason": "csv_missing"} for s in sites_in}
        }

    df = pd.read_csv(csv_path)
    required = {"datetime", "site_no", PARAM_63680}
    if not required.issubset(df.columns):
        return {
            "sites": {s: {"available": False, "points": [], "reason": "csv_schema"} for s in sites_in}
        }

    want = set(sites_in)
    df = df[df["site_no"].astype(str).str.strip().isin(want)].copy()
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df[PARAM_63680] = pd.to_numeric(df[PARAM_63680], errors="coerce")
    df = df.dropna(subset=["datetime", PARAM_63680])

    out: dict[str, Any] = {}
    for site in sites_in:
        sub = df[df["site_no"].astype(str).str.strip() == site].sort_values("datetime")
        if sub.empty:
            out[site] = {"available": False, "points": [], "reason": "no_turbidity_values"}
            continue
        tail = sub.tail(2)
        points: list[dict[str, Any]] = []
        for _, row in tail.iterrows():
            ts = row["datetime"]
            dt_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            points.append({"datetime": dt_iso, "ntu": float(row[PARAM_63680])})
        out[site] = {"available": True, "points": points, "reason": None}

    return {"sites": out}

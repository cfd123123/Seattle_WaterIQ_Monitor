#!/usr/bin/env python3
"""
将 fetch_usgs_puget_sound.py 产出的 IV CSV 映射为 /predict、/api/check 所需的 11 项 JSON。

parameter_cd → 字段对照单一来源：usgs_iv_constants.IV_PARM_TO_FIELD；释义见 ../monitor_business/docs/usgs-parameter-mapping.md

IV 中若缺失的指标使用「中性占位」（未观测，非实测）；输出中列出 imputed_fields，便于审计。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from rule_scoring import FEATURE_KEYS, evaluate_water_quality_rules
from usgs_iv_constants import IV_PARM_TO_FIELD

# 无 IV 列时使用的中性占位（略有代表性的寡营养河流背景，非「最优以免拉高总分」）
DEFAULT_FILLS: dict[str, float] = {
    "Water_Temperature_C": 18.0,
    "pH": 7.2,
    "Dissolved_Oxygen_mg_L": 8.0,
    "Conductivity_uS_cm": 280.0,
    "Turbidity_NTU": 4.0,
    "Nitrate_mg_L": 0.5,
    "Ammonia_N_mg_L": 0.08,
    "Total_Phosphorus_mg_L": 0.06,
    "COD_mg_L": 14.0,
    "BOD_mg_L": 2.5,
    "Heavy_Metals_Pb_ug_L": 1.5,
}


def load_iv_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "datetime" not in df.columns:
        raise ValueError("CSV 需包含 datetime 列")
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    if "site_no" in df.columns:
        df["site_no"] = df["site_no"].astype(str).str.strip()
    return df


def iv_row_keys_from_csv(csv_path: Path) -> set[tuple[str, str]]:
    """
    覆盖写入 **前** 读取旧 IV 文件，得到 ``(site_no, datetime 秒级 UTC ISO)`` 键集合，
    用于与本次合并结果做差集，只对**新增时间点**跑检测。
    """
    if not csv_path.is_file():
        return set()
    try:
        df = load_iv_csv(csv_path)
    except (ValueError, OSError):
        return set()
    return iv_row_keys_from_df(df)


def iv_row_keys_from_df(df: pd.DataFrame) -> set[tuple[str, str]]:
    if df.empty or "site_no" not in df.columns or "datetime" not in df.columns:
        return set()
    d = df.dropna(subset=["datetime", "site_no"]).copy()
    if d.empty:
        return set()
    keys: set[tuple[str, str]] = set()
    for _, row in d.iterrows():
        sn = str(row["site_no"]).strip()
        if not sn:
            continue
        ts = row["datetime"]
        if not isinstance(ts, pd.Timestamp):
            ts = pd.to_datetime(ts, utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        ts = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
        ts = ts.floor("s")
        keys.add((sn, ts.isoformat()))
    return keys


def incremental_check_bundles(merged: pd.DataFrame, old_keys: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """
    对 ``merged`` 中每条记录，若 ``(site_no, datetime)`` 不在 ``old_keys`` 中，则生成一条检测体。
    首次拉数（无旧文件）时 ``old_keys`` 为空，即对窗口内**所有行**各跑一次检测。
    """
    if merged.empty or "datetime" not in merged.columns or "site_no" not in merged.columns:
        return []
    df = merged.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df["site_no"] = df["site_no"].astype(str).str.strip()
    df = df.dropna(subset=["datetime", "site_no"])
    df = df.sort_values(["site_no", "datetime"])
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        sn = str(row["site_no"]).strip()
        ts = row["datetime"]
        if pd.isna(ts):
            continue
        ts = pd.Timestamp(ts)
        ts = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
        ts = ts.floor("s")
        k = (sn, ts.isoformat())
        if k in old_keys:
            continue
        b = row_to_predict_bundle(row)
        out.append(
            {
                "site_no": sn,
                "payload": b["payload"],
                "observed_fields": b["observed_fields"],
                "datetime": ts.isoformat(),
            }
        )
    return out


def pick_latest_row(df: pd.DataFrame, site_no: str | None) -> pd.Series:
    if df.empty:
        raise ValueError("数据为空")
    work = df.dropna(subset=["datetime"]).sort_values("datetime", ascending=False)
    if work.empty:
        raise ValueError("无有效 datetime")
    if site_no is not None:
        s = str(site_no).strip()
        sub = work[work["site_no"] == s]
        if sub.empty:
            raise ValueError(f"无站点 {site_no} 的记录")
        return sub.iloc[0]
    return work.iloc[0]


def row_to_predict_bundle(row: pd.Series) -> dict[str, Any]:
    observed: list[str] = []
    payload: dict[str, float] = dict(DEFAULT_FILLS)

    for parm, field in IV_PARM_TO_FIELD.items():
        if parm not in row.index:
            continue
        val = row[parm]
        if pd.isna(val):
            continue
        try:
            payload[field] = float(val)
        except (TypeError, ValueError):
            continue
        observed.append(field)

    imputed = [k for k in FEATURE_KEYS if k not in observed]

    meta = {
        "site_no": str(row.get("site_no", "")).strip() if pd.notna(row.get("site_no")) else None,
        "station_name": str(row.get("station_name", "")) if "station_name" in row.index else None,
        "datetime": row["datetime"].isoformat() if pd.notna(row.get("datetime")) else None,
        "region_label": str(row.get("region_label")) if "region_label" in row.index else None,
    }
    if "00060" in row.index and pd.notna(row.get("00060")):
        meta["discharge_ft3s"] = float(row["00060"])

    return {
        "payload": {k: payload[k] for k in FEATURE_KEYS},
        "observed_fields": observed,
        "imputed_fields": imputed,
        "meta": meta,
    }


def latest_bundles_per_site(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    按 ``site_no`` 分组，取各站 **datetime 最新** 一行（脚本/联调用；刷新管线请用 ``incremental_check_bundles``）。
    """
    if df.empty or "datetime" not in df.columns or "site_no" not in df.columns:
        return []
    work = df.dropna(subset=["datetime"]).copy()
    if work.empty:
        return []
    work = work.sort_values("datetime", ascending=False)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        sn = str(row.get("site_no", "")).strip()
        if not sn or sn in seen:
            continue
        seen.add(sn)
        b = row_to_predict_bundle(row)
        out.append(
            {
                "site_no": sn,
                "payload": b["payload"],
                "observed_fields": b["observed_fields"],
            }
        )
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="从 USGS Puget IV CSV 生成 /predict 与 /api/check 请求体 JSON",
    )
    p.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "usgs_puget_iv.csv",
        help="fetch_usgs_puget_sound.py 输出的 CSV",
    )
    p.add_argument("--site", type=str, default=None, help="8 位 USGS site_no；省略则取全表最新一条")
    p.add_argument(
        "--dry-predict",
        action="store_true",
        help="本地调用 rule_scoring 打印等级与综合分",
    )
    p.add_argument(
        "--compact-payload-only",
        action="store_true",
        help="只输出 11 项 JSON（便于管道传入 curl）",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.csv.is_file():
        print(f"文件不存在: {args.csv}", file=sys.stderr)
        return 1
    df = load_iv_csv(args.csv)
    try:
        row = pick_latest_row(df, args.site)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    bundle = row_to_predict_bundle(row)
    if args.compact_payload_only:
        print(json.dumps(bundle["payload"], ensure_ascii=False, indent=2))
        return 0
    out = dict(bundle)
    if args.dry_predict:
        out["rule_result"] = evaluate_water_quality_rules(
            bundle["payload"],
            observed_fields=bundle["observed_fields"],
        )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

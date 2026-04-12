#!/usr/bin/env python3
"""
分析 USGS IV CSV 是否适合做 USGS-only 训练集（阶段一：数据可用性评估）。

输出：
1) 控制台摘要
2) 可选 JSON 报告（--report-out）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

CORE_PARAMS = ("00010", "00400", "00300", "00095", "63680")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze USGS IV training readiness")
    p.add_argument(
        "--iv-csv",
        default=str(Path(__file__).resolve().parent / "data" / "usgs_puget_iv.csv"),
        help="IV CSV 路径",
    )
    p.add_argument(
        "--report-out",
        default="",
        help="可选：输出 JSON 报告路径",
    )
    return p.parse_args()


def _safe_ratio(a: int, b: int) -> float:
    return round((a / b) if b else 0.0, 4)


def main() -> None:
    args = parse_args()
    csv_path = Path(args.iv_csv)
    if not csv_path.is_file():
        raise SystemExit(f"IV CSV 不存在: {csv_path}")

    df = pd.read_csv(csv_path)
    total = len(df)
    if total == 0:
        raise SystemExit("IV CSV 为空。")

    site_col = "site_no" if "site_no" in df.columns else None
    dt_col = "datetime" if "datetime" in df.columns else None
    sites = int(df[site_col].astype(str).nunique()) if site_col else 0

    missing_cols = [c for c in CORE_PARAMS if c not in df.columns]
    present_cols = [c for c in CORE_PARAMS if c in df.columns]

    non_null_counts: dict[str, int] = {}
    non_null_ratios: dict[str, float] = {}
    for c in present_cols:
        n = int(df[c].notna().sum())
        non_null_counts[c] = n
        non_null_ratios[c] = _safe_ratio(n, total)

    if present_cols:
        complete_rows = int(df[present_cols].notna().all(axis=1).sum())
    else:
        complete_rows = 0

    per_site_complete: list[dict[str, Any]] = []
    if site_col and present_cols:
        g = df.groupby(site_col, dropna=False)
        for site_no, sub in g:
            rows = int(len(sub))
            comp = int(sub[present_cols].notna().all(axis=1).sum())
            per_site_complete.append(
                {
                    "site_no": str(site_no),
                    "rows": rows,
                    "complete_rows": comp,
                    "complete_ratio": _safe_ratio(comp, rows),
                }
            )
        per_site_complete.sort(key=lambda x: x["complete_rows"], reverse=True)

    report = {
        "iv_csv": str(csv_path.resolve()),
        "rows_total": total,
        "sites_total": sites,
        "datetime_present": bool(dt_col),
        "core_params_expected": list(CORE_PARAMS),
        "core_params_missing_columns": missing_cols,
        "core_params_non_null_counts": non_null_counts,
        "core_params_non_null_ratios": non_null_ratios,
        "rows_complete_all_present_core_params": complete_rows,
        "rows_complete_ratio": _safe_ratio(complete_rows, total),
        "per_site_complete_top10": per_site_complete[:10],
    }

    print("=== USGS IV 训练可用性评估 ===")
    print(f"CSV: {report['iv_csv']}")
    print(f"总行数: {total}, 站点数: {sites}")
    print(f"缺失参数列: {missing_cols if missing_cols else '无'}")
    print(f"完整行(核心参数全非空): {complete_rows} ({report['rows_complete_ratio']:.2%})")
    for c in present_cols:
        print(f"- {c}: non-null {non_null_counts[c]} ({non_null_ratios[c]:.2%})")
    if per_site_complete:
        print("Top 5 站点完整行:")
        for x in per_site_complete[:5]:
            print(f"  {x['site_no']}: {x['complete_rows']}/{x['rows']} ({x['complete_ratio']:.2%})")

    if args.report_out.strip():
        out = Path(args.report_out.strip())
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已写入: {out.resolve()}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Summarize per-model JSON outputs from run_turbidity_exog_model_suite.py into CSV + markdown conclusions.

Reads every *.json in --suite-dir except suite_manifest.json.

Example::

    .venv/bin/python models/summarize_turbidity_exog_suite.py \\
      --suite-dir reports/turbidity_exog_suite/run_20260513 \\
      --csv-out reports/turbidity_exog_suite/run_20260513/comparison_holdout.csv \\
      --md-out reports/turbidity_exog_suite/run_20260513/report_conclusions.md
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any


def _f(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)) and (math.isnan(x) if isinstance(x, float) else False):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _row_from_report(j: dict[str, Any]) -> dict[str, Any]:
    model = str(j.get("model", ""))
    hs = j.get("holdout_split") or {}
    ho = (j.get("summary_by_eval_window") or {}).get("holdout") or {}
    m = ho.get("model") or {}
    bp = (ho.get("baselines") or {}).get("persistence") or {}
    bs = (ho.get("baselines") or {}).get("seasonal_lag_24h") or {}

    return {
        "model": model,
        "features_csv": j.get("features_csv"),
        "step": j.get("step"),
        "horizons": ",".join(str(h) for h in (j.get("horizons") or [])),
        "series_hours": j.get("series_hours"),
        "split_index": hs.get("split_index"),
        "split_time_utc": hs.get("split_time_utc"),
        "holdout_hours": hs.get("holdout_hours"),
        # Primary reporting slice (holdout): Tier A / Tier B / h1-12
        "tier_a_smape_pct_model": _f(m.get("tier_a_mean_smape_pct")),
        "tier_a_mae_model": _f(m.get("tier_a_mean_mae")),
        "tier_b_smape_pct_model": _f(m.get("tier_b_mean_smape_pct")),
        "tier_b_mae_model": _f(m.get("tier_b_mean_mae")),
        "h1_12_smape_pct_model": _f(m.get("h1_12_mean_smape_pct")),
        "h1_12_mae_model": _f(m.get("h1_12_mean_mae")),
        "tier_a_smape_pct_persistence": _f(bp.get("tier_a_mean_smape_pct")),
        "tier_a_mae_persistence": _f(bp.get("tier_a_mean_mae")),
        "tier_a_smape_pct_seasonal_lag24": _f(bs.get("tier_a_mean_smape_pct")),
        "tier_a_mae_seasonal_lag24": _f(bs.get("tier_a_mean_mae")),
    }
    strata = j.get("summary_strata_holdout") or {}
    st = (strata.get("strata") or {}).get("high_turbidity_at_T") or {}
    st_m = st.get("model") or {}
    row["tier_a_smape_high_turbidity_stratum"] = _f(st_m.get("tier_a_mean_smape_pct"))
    row["tier_a_smape_heavy_precip_stratum"] = _f(
        ((strata.get("strata") or {}).get("heavy_precip_6h_at_T") or {}).get("model") or {}).get(
            "tier_a_mean_smape_pct"
        )
    )


def _sort_key(r: dict[str, Any]) -> tuple[float, str]:
    v = r.get("tier_a_smape_pct_model")
    if v is None:
        return (1e9, str(r.get("model", "")))
    return (float(v), str(r.get("model", "")))


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.4f}%"


def _fmt_num(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.6f}"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize turbidity exog suite JSON reports.")
    p.add_argument("--suite-dir", type=Path, required=True, help="Directory containing per-model *.json")
    p.add_argument("--csv-out", type=Path, required=True)
    p.add_argument("--md-out", type=Path, required=True)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    d = args.suite_dir
    if not d.is_dir():
        print(f"Not a directory: {d}", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    for path in sorted(d.glob("*.json")):
        if path.name == "suite_manifest.json":
            continue
        try:
            j = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"Skip unreadable JSON {path}: {e}", file=sys.stderr)
            continue
        if not isinstance(j, dict) or "model" not in j:
            continue
        rows.append(_row_from_report(j))

    if not rows:
        print("No model JSON files found.", file=sys.stderr)
        return 3

    rows.sort(key=_sort_key)

    fieldnames = list(rows[0].keys())
    args.csv_out.parent.mkdir(parents=True, exist_ok=True)
    with args.csv_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})

    # Markdown conclusions (Simplified Chinese for reporting)
    best = rows[0]
    bm = _f(best.get("tier_a_smape_pct_model"))
    pers_best = _f(best.get("tier_a_smape_pct_persistence"))
    seas_best = _f(best.get("tier_a_smape_pct_seasonal_lag24"))
    beats_p = bm is not None and pers_best is not None and bm < pers_best
    beats_s = bm is not None and seas_best is not None and bm < seas_best

    lines: list[str] = []
    lines.append("# 浊度 (63680) 模型对比 — 报告草稿")
    lines.append("")
    lines.append(
        "评估口径对齐 `plan/evaluation_contract.md`：walk-forward、horizons 按套件参数、`split_index` 划分 tuning/holdout。"
        "**主要结论依据：** holdout 分段 cutoffs + **Tier A（h=1..6）** 平均 sMAPE / MAE；Tier B 与 h1–12 作辅助。"
    )
    st = best.get("step")
    if st is not None and int(st) != 1:
        lines.append("")
        lines.append(
            f"> **说明：** 本套件使用 **`step={st}`**（cutoffs  subsampling）。"
            "按合同的正式报表通常要求 **`step=1`**，除非明确标注为探索性运行。"
        )
    lines.append("")
    lines.append("## Holdout 汇总（按 Tier A 模型 sMAPE 升序）")
    lines.append("")
    lines.append("| 名次 | 模型 | Tier A sMAPE(模型) | Tier A MAE | Tier B sMAPE | Persistence Tier A sMAPE | Seasonal 24h Tier A sMAPE |")
    lines.append("|------|-------|----------------------|------------|--------------|---------------------------|----------------------------|")
    for i, r in enumerate(rows, start=1):
        lines.append(
            f"| {i} | `{r['model']}` | {_fmt_pct(_f(r['tier_a_smape_pct_model']))} | {_fmt_num(_f(r['tier_a_mae_model']))} | "
            f"{_fmt_pct(_f(r['tier_b_smape_pct_model']))} | {_fmt_pct(_f(r['tier_a_smape_pct_persistence']))} | "
            f"{_fmt_pct(_f(r['tier_a_smape_pct_seasonal_lag24']))} |"
        )
    lines.append("")
    lines.append("## 结论要点（草稿）")
    lines.append("")
    lines.append(f"1. **Tier A holdout 上 sMAPE 最低的模型：** `{best.get('model')}` "
        f"（{_fmt_pct(bm)}），step={best.get('step')}，其余旋钮见 CSV / manifest。"
    )
    lines.append(
        f"2. **与合同基线对比（与该模型相同的 holdout cutoffs，Tier A）：** "
        f"Persistence ≈ {_fmt_pct(pers_best)}，seasonal lag-24 ≈ {_fmt_pct(seas_best)}。"
        f"当前排名第一的模型在 Tier A 平均 sMAPE 上 {'优于' if beats_p else '未优于'} persistence，"
        f"{'优于' if beats_s else '未优于'} seasonal lag-24。"
    )
    lines.append(
        "3. **`recursive_*_exog_hindcast`：** rollout 中降水/气温使用 **历史上真实观测**（oracle weather），"
        "属于 hindcast 上界，**不能**等同上线后「用天气预报」的效果。"
    )
    lines.append(
        "4. **`recursive_ridge_univariate`：** 仅用浊度自回归 Ridge，无 Open-Meteo 外生块；"
        "仅在与其它模型 **数据与 horizons 完全一致** 时公平对比。"
    )
    lines.append("")
    lines.append("## 产出文件")
    lines.append("")
    lines.append(f"- Comparison CSV: `{args.csv_out}`")
    lines.append(f"- Source suite directory: `{d.resolve()}`")
    lines.append("")

    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.csv_out.resolve()}")
    print(f"Wrote {args.md_out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

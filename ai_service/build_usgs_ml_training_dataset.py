#!/usr/bin/env python3
"""
从 IV CSV 生成 USGS-only 训练集（弱监督标签）。

标签策略（v1）：
- 用现有 rule_scoring.evaluate_water_quality_rules 产生 Pollution_Level
- 仅把 USGS 可观测项（00010/00400/00300/00095/63680）作为 observed_fields
- 其余字段使用 DEFAULT_FILLS（来自 usgs_iv_to_predict_payload）
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from rule_scoring import (
    _subscore_conductivity,
    _subscore_do,
    _subscore_ph,
    _subscore_temperature,
    _subscore_turbidity,
    evaluate_water_quality_rules,
)
from usgs_iv_to_predict_payload import DEFAULT_FILLS

CORE = {
    "00010": "Water_Temperature_C",
    "00400": "pH",
    "00300": "Dissolved_Oxygen_mg_L",
    "00095": "Conductivity_uS_cm",
    "63680": "Turbidity_NTU",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build weak-labeled USGS ML dataset")
    p.add_argument(
        "--iv-csv",
        default=str(Path(__file__).resolve().parent / "data" / "usgs_wa_core_iv.csv"),
    )
    p.add_argument(
        "--out-csv",
        default=str(Path(__file__).resolve().parent / "data" / "usgs_ml_training_v1.csv"),
    )
    p.add_argument("--require-complete-core", action="store_true", help="仅保留5核心参数全非空行")
    p.add_argument(
        "--label-policy",
        choices=["rule11_weak", "core_strict_v1"],
        default="core_strict_v1",
        help="标签策略：rule11_weak=沿用11项规则弱监督；core_strict_v1=仅核心USGS参数严格分档",
    )
    return p.parse_args()


def _level_from_core_strict(features: dict[str, float]) -> tuple[str, float]:
    # 仅核心参数评分：DO、浊度更高权重；比 rule11 更严格，拉开类别分布
    s_temp = _subscore_temperature(features["Water_Temperature_C"])
    s_ph = _subscore_ph(features["pH"])
    s_do = _subscore_do(features["Dissolved_Oxygen_mg_L"])
    s_cond = _subscore_conductivity(features["Conductivity_uS_cm"])
    s_turb = _subscore_turbidity(features["Turbidity_NTU"])
    score = (
        0.10 * s_temp
        + 0.20 * s_ph
        + 0.30 * s_do
        + 0.15 * s_cond
        + 0.25 * s_turb
    )
    score = round(float(score), 2)
    if score >= 88:
        return "Excellent", score
    if score >= 72:
        return "Good", score
    if score >= 56:
        return "Moderate", score
    if score >= 40:
        return "Poor", score
    return "Very Poor", score


def main() -> None:
    args = parse_args()
    src = Path(args.iv_csv)
    if not src.is_file():
        raise SystemExit(f"输入文件不存在: {src}")
    df = pd.read_csv(src)
    for c in ("site_no", "datetime", *CORE.keys()):
        if c not in df.columns:
            raise SystemExit(f"缺少列: {c}")

    df["site_no"] = df["site_no"].astype(str).str.strip()
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df = df.dropna(subset=["site_no", "datetime"])

    if args.require_complete_core:
        df = df[df[list(CORE.keys())].notna().all(axis=1)].copy()

    rows = []
    for _, r in df.iterrows():
        features = dict(DEFAULT_FILLS)
        observed = []
        x = {}
        skip = False
        for p, f in CORE.items():
            v = pd.to_numeric(r.get(p), errors="coerce")
            if pd.isna(v):
                if args.require_complete_core:
                    skip = True
                    break
                continue
            fv = float(v)
            features[f] = fv
            observed.append(f)
            x[p] = fv
        if skip:
            continue
        if args.label_policy == "rule11_weak":
            out = evaluate_water_quality_rules(features, observed_fields=observed)
            label = out.get("Pollution_Level")
            score = out.get("score")
        else:
            label, score = _level_from_core_strict(features)
            out = {"observed_count": len(observed), "coverage_ratio": round(len(observed) / 11, 4)}
        rows.append(
            {
                "site_no": str(r["site_no"]),
                "datetime": pd.Timestamp(r["datetime"]).isoformat(),
                "00010": x.get("00010"),
                "00400": x.get("00400"),
                "00300": x.get("00300"),
                "00095": x.get("00095"),
                "63680": x.get("63680"),
                "observed_count": out.get("observed_count"),
                "coverage_ratio": out.get("coverage_ratio"),
                "score": score,
                "Pollution_Level": label,
                "label_source": f"{args.label_policy}",
            }
        )

    out_df = pd.DataFrame(rows).sort_values("datetime")
    out_path = Path(args.out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)
    print(f"rows={len(out_df)} -> {out_path.resolve()}")
    if len(out_df) > 0:
        print(out_df["Pollution_Level"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()

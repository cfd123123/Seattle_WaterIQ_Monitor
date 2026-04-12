"""
从 IV 宽表 CSV 中组装「五核心参数」向量供异常检测。

若某列在 CSV 中不存在、或该站从未观测到非空值，则用 **正常训练子集的中位数** 填补
（与 train_usgs_anomaly_model 写入 pkl 的 imputation_defaults 一致；无则使用内置兜底值）。
模型仍是 5 维 IsolationForest；填补会削弱可解释性，故响应中返回 imputed_params 便于审计。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from usgs_iv_to_predict_payload import load_iv_csv

CORE_PARAMS: tuple[str, ...] = ("00010", "00400", "00300", "00095", "63680")

# 与 data/usgs_ml_training_v2_90d.csv 正常类中位数一致（artifact 不可读时的兜底）
_CORE_IMPUTE_FALLBACK: dict[str, float] = {
    "00010": 6.4,
    "00400": 7.2,
    "00300": 12.0,
    "00095": 78.0,
    "63680": 1.9,
}

_ANOMALY_PKL = Path(__file__).resolve().parent / "usgs_anomaly_iforest_v1.pkl"


def _load_imputation_defaults() -> dict[str, float]:
    if not _ANOMALY_PKL.is_file():
        return dict(_CORE_IMPUTE_FALLBACK)
    try:
        art = joblib.load(_ANOMALY_PKL)
        raw = art.get("imputation_defaults")
        if isinstance(raw, dict):
            out = {}
            for f in CORE_PARAMS:
                if f in raw:
                    out[f] = float(raw[f])
            if len(out) == len(CORE_PARAMS):
                return out
    except Exception:
        pass
    return dict(_CORE_IMPUTE_FALLBACK)


def build_core_snapshot_for_anomaly(csv_path: Path, site_no: str) -> dict[str, Any]:
    """
    按参数分别取该站「时间最新的一条非空观测」；缺列或无时序值则用默认填补。
    """
    sn = str(site_no).strip()
    if not sn:
        raise ValueError("site_no 不能为空")
    path = Path(csv_path)
    if not path.is_file():
        raise ValueError(f"IV CSV 不存在: {path}")
    df = load_iv_csv(path)
    if df.empty or "site_no" not in df.columns:
        raise ValueError("IV CSV 无有效数据")
    sub = df[df["site_no"].astype(str).str.strip() == sn].copy()
    if sub.empty:
        raise ValueError(f"CSV 中无站点 {sn} 的记录")

    defaults = _load_imputation_defaults()
    imputed: list[str] = []
    notes: list[str] = []
    ts_seen: list[pd.Timestamp] = []

    sub_d = sub.dropna(subset=["datetime"]).copy()

    vals: dict[str, float] = {}
    for col in CORE_PARAMS:
        if col not in sub_d.columns:
            vals[col] = defaults[col]
            imputed.append(col)
            notes.append(f"{col}: CSV 无此列，已用正常样本中位数")
            continue
        hit = sub_d.sort_values("datetime", ascending=False)
        hit = hit[hit[col].notna()]
        if hit.empty:
            vals[col] = defaults[col]
            imputed.append(col)
            notes.append(f"{col}: 该站无有效观测，已用正常样本中位数")
            continue
        row = hit.iloc[0]
        vals[col] = float(row[col])
        ts = row["datetime"]
        if isinstance(ts, pd.Timestamp) and pd.notna(ts):
            ts_seen.append(ts)

    sample_dt: str | None = None
    if ts_seen:
        sample_dt = max(ts_seen).isoformat()

    return {
        "site_no": sn,
        "sample_datetime": sample_dt,
        "v_00010": vals["00010"],
        "v_00400": vals["00400"],
        "v_00300": vals["00300"],
        "v_00095": vals["00095"],
        "v_63680": vals["63680"],
        "imputed_params": imputed,
        "imputation_note": "；".join(notes) if notes else None,
    }


def latest_complete_core_snapshot(csv_path: Path, site_no: str) -> dict[str, Any]:
    """兼容旧名：与 build_core_snapshot_for_anomaly 相同（支持缺列填补）。"""
    return build_core_snapshot_for_anomaly(csv_path, site_no)

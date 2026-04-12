"""
可解释的规则评分：将 11 项水质指标映射为 0–100 综合分及 Pollution_Level（与 Java PollutionLevelThresholds 一致）。

口径为演示级综合指数，非任何国标的正式 WQI；后续可接 USGS 参数映射与配置化阈值。
"""

from __future__ import annotations

from typing import Any

RULE_VERSION = "rule-v1-2026-03"

FEATURE_KEYS = [
    "Water_Temperature_C",
    "pH",
    "Dissolved_Oxygen_mg_L",
    "Conductivity_uS_cm",
    "Turbidity_NTU",
    "Nitrate_mg_L",
    "Ammonia_N_mg_L",
    "Total_Phosphorus_mg_L",
    "COD_mg_L",
    "BOD_mg_L",
    "Heavy_Metals_Pb_ug_L",
]

# 权重之和为 1；毒性与溶解氧略高
WEIGHTS: dict[str, float] = {
    "Water_Temperature_C": 0.05,
    "pH": 0.10,
    "Dissolved_Oxygen_mg_L": 0.15,
    "Conductivity_uS_cm": 0.07,
    "Turbidity_NTU": 0.09,
    "Nitrate_mg_L": 0.09,
    "Ammonia_N_mg_L": 0.12,
    "Total_Phosphorus_mg_L": 0.09,
    "COD_mg_L": 0.09,
    "BOD_mg_L": 0.07,
    "Heavy_Metals_Pb_ug_L": 0.08,
}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _lerp(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if x1 == x0:
        return y0
    t = _clamp((x - x0) / (x1 - x0), 0.0, 1.0)
    return y0 + t * (y1 - y0)


def _subscore_temperature(c: float) -> float:
    # 溪流/河流常见舒适段，偏离则扣分
    optimal = 18.0
    d = abs(c - optimal)
    if d <= 3:
        return 100.0
    if d <= 8:
        return _lerp(d, 3, 100, 8, 72)
    if d <= 15:
        return _lerp(d, 8, 72, 15, 35)
    return max(0.0, 35.0 - (d - 15.0) * 2.0)


def _subscore_ph(ph: float) -> float:
    center = 7.2
    d = abs(ph - center)
    if d <= 0.4:
        return 100.0
    if d <= 1.0:
        return _lerp(d, 0.4, 100, 1.0, 85)
    if d <= 2.0:
        return _lerp(d, 1.0, 85, 2.0, 60)
    if d <= 3.0:
        return _lerp(d, 2.0, 60, 3.0, 35)
    return max(0.0, 35.0 - (d - 3.0) * 12.0)


def _subscore_do(do: float) -> float:
    if do >= 9.0:
        return 100.0
    if do >= 7.0:
        return _lerp(do, 7.0, 78.0, 9.0, 100.0)
    if do >= 5.0:
        return _lerp(do, 5.0, 50.0, 7.0, 78.0)
    if do >= 3.0:
        return _lerp(do, 3.0, 28.0, 5.0, 50.0)
    return _lerp(do, 0.0, 5.0, 3.0, 28.0)


def _subscore_conductivity(u: float) -> float:
    # 淡水背景电导率越低越好，高值反映离子/盐度负荷
    if u <= 200:
        return 100.0
    if u <= 500:
        return _lerp(u, 200, 100, 500, 82)
    if u <= 1200:
        return _lerp(u, 500, 82, 1200, 52)
    if u <= 3000:
        return _lerp(u, 1200, 52, 3000, 22)
    return max(0.0, 22.0 - (u - 3000.0) / 500.0)


def _subscore_turbidity(ntu: float) -> float:
    if ntu <= 2:
        return 100.0
    if ntu <= 10:
        return _lerp(ntu, 2, 100, 10, 75)
    if ntu <= 40:
        return _lerp(ntu, 10, 75, 40, 38)
    if ntu <= 100:
        return _lerp(ntu, 40, 38, 100, 12)
    return max(0.0, 12.0 - (ntu - 100.0) / 50.0)


def _subscore_nitrate(mg: float) -> float:
    if mg <= 2:
        return 100.0
    if mg <= 8:
        return _lerp(mg, 2, 100, 8, 72)
    if mg <= 20:
        return _lerp(mg, 8, 72, 20, 38)
    return max(0.0, 38.0 - (mg - 20.0) * 1.5)


def _subscore_ammonia(mg: float) -> float:
    if mg <= 0.15:
        return 100.0
    if mg <= 0.6:
        return _lerp(mg, 0.15, 100, 0.6, 72)
    if mg <= 2.0:
        return _lerp(mg, 0.6, 72, 2.0, 35)
    return max(0.0, 35.0 - (mg - 2.0) * 12.0)


def _subscore_tp(mg: float) -> float:
    if mg <= 0.05:
        return 100.0
    if mg <= 0.15:
        return _lerp(mg, 0.05, 100, 0.15, 78)
    if mg <= 0.45:
        return _lerp(mg, 0.15, 78, 0.45, 42)
    return max(0.0, 42.0 - (mg - 0.45) * 40.0)


def _subscore_cod(mg: float) -> float:
    if mg <= 15:
        return 100.0
    if mg <= 35:
        return _lerp(mg, 15, 100, 35, 58)
    if mg <= 80:
        return _lerp(mg, 35, 58, 80, 25)
    return max(0.0, 25.0 - (mg - 80.0) * 0.2)


def _subscore_bod(mg: float) -> float:
    if mg <= 3:
        return 100.0
    if mg <= 8:
        return _lerp(mg, 3, 100, 8, 62)
    if mg <= 20:
        return _lerp(mg, 8, 62, 20, 30)
    return max(0.0, 30.0 - (mg - 20.0) * 1.0)


def _subscore_pb(ug: float) -> float:
    if ug <= 2:
        return 100.0
    if ug <= 8:
        return _lerp(ug, 2, 100, 8, 72)
    if ug <= 20:
        return _lerp(ug, 8, 72, 20, 38)
    return max(0.0, 38.0 - (ug - 20.0) * 1.8)


_SUBSCORERS: dict[str, Any] = {
    "Water_Temperature_C": _subscore_temperature,
    "pH": _subscore_ph,
    "Dissolved_Oxygen_mg_L": _subscore_do,
    "Conductivity_uS_cm": _subscore_conductivity,
    "Turbidity_NTU": _subscore_turbidity,
    "Nitrate_mg_L": _subscore_nitrate,
    "Ammonia_N_mg_L": _subscore_ammonia,
    "Total_Phosphorus_mg_L": _subscore_tp,
    "COD_mg_L": _subscore_cod,
    "BOD_mg_L": _subscore_bod,
    "Heavy_Metals_Pb_ug_L": _subscore_pb,
}


def _aggregate_to_level(score: float) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 55:
        return "Moderate"
    if score >= 38:
        return "Poor"
    return "Very Poor"


def evaluate_water_quality_rules(
    features: dict[str, float],
    observed_fields: list[str] | None = None,
) -> dict[str, Any]:
    """
    :param features: 键与 FEATURE_KEYS 一致（与 WaterQualityRequest JSON 一致）
    :param observed_fields: 实测指标名子集；None 表示 11 项均视为实测（coverage=1）。
    :return: 含 Pollution_Level、score、rule_version、subscores、覆盖度字段，供 FastAPI JSON 序列化
    """
    n = len(FEATURE_KEYS)
    if observed_fields is None:
        observed_set = set(FEATURE_KEYS)
    else:
        observed_set = {k for k in observed_fields if k in FEATURE_KEYS}
    imputed_fields = [k for k in FEATURE_KEYS if k not in observed_set]
    observed_count = len(observed_set)
    coverage_ratio = round(observed_count / n, 4) if n else 0.0

    sub: dict[str, float] = {}
    total_w = 0.0
    agg = 0.0
    for k in FEATURE_KEYS:
        fn = _SUBSCORERS[k]
        v = float(features[k])
        s = float(fn(v))
        sub[k] = round(s, 2)
        w = WEIGHTS[k]
        agg += s * w
        total_w += w
    if total_w <= 0:
        overall = 0.0
    else:
        overall = agg / total_w
    overall = round(float(overall), 2)
    level = _aggregate_to_level(overall)
    return {
        "Pollution_Level": level,
        "score": overall,
        "rule_version": RULE_VERSION,
        "subscores": sub,
        "observed_count": observed_count,
        "coverage_ratio": coverage_ratio,
        "imputed_fields": imputed_fields,
    }


def _self_test() -> None:
    good = {
        "Water_Temperature_C": 19.0,
        "pH": 7.2,
        "Dissolved_Oxygen_mg_L": 8.5,
        "Conductivity_uS_cm": 250.0,
        "Turbidity_NTU": 2.0,
        "Nitrate_mg_L": 1.0,
        "Ammonia_N_mg_L": 0.05,
        "Total_Phosphorus_mg_L": 0.04,
        "COD_mg_L": 12.0,
        "BOD_mg_L": 2.0,
        "Heavy_Metals_Pb_ug_L": 1.0,
    }
    r1 = evaluate_water_quality_rules(good)
    assert r1["Pollution_Level"] in ("Excellent", "Good"), r1

    bad = {
        "Water_Temperature_C": 30.0,
        "pH": 5.2,
        "Dissolved_Oxygen_mg_L": 2.5,
        "Conductivity_uS_cm": 3500.0,
        "Turbidity_NTU": 80.0,
        "Nitrate_mg_L": 25.0,
        "Ammonia_N_mg_L": 4.0,
        "Total_Phosphorus_mg_L": 0.8,
        "COD_mg_L": 95.0,
        "BOD_mg_L": 22.0,
        "Heavy_Metals_Pb_ug_L": 45.0,
    }
    r2 = evaluate_water_quality_rules(bad)
    assert r2["Pollution_Level"] in ("Poor", "Very Poor"), r2

    assert r1["observed_count"] == 11 and r1["coverage_ratio"] == 1.0 and r1["imputed_fields"] == []

    r_partial = evaluate_water_quality_rules(
        good,
        observed_fields=["Water_Temperature_C", "pH"],
    )
    assert r_partial["observed_count"] == 2
    assert r_partial["coverage_ratio"] == round(2 / 11, 4)
    assert set(r_partial["imputed_fields"]) == set(FEATURE_KEYS) - {
        "Water_Temperature_C",
        "pH",
    }


if __name__ == "__main__":
    _self_test()
    print("rule_scoring self-test ok")

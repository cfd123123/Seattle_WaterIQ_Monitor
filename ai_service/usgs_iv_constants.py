"""
USGS NWIS 瞬时数据（IV）的 parameter_cd 约定：与 fetch 默认参数、CSV 列名、payload 映射单一事实来源。

完整释义见：../monitor_business/docs/usgs-parameter-mapping.md
"""

from __future__ import annotations

# parameter_cd → PredictRequest / WaterQualityRequest 字段（仅水质相关；00060 无对应项，写入 meta）
IV_PARM_TO_FIELD: dict[str, str] = {
    "00010": "Water_Temperature_C",
    "00095": "Conductivity_uS_cm",
    "00300": "Dissolved_Oxygen_mg_L",
    "00400": "pH",
    "63680": "Turbidity_NTU",
}

# 默认拉取的 IV 参数码顺序（与 USGS 常用编号大致分组；00060 仅水文上下文）
DEFAULT_FETCH_PARAMETER_CDS: tuple[str, ...] = (
    "00060",  # Discharge, ft³/s → 仅 usgs_iv_to_predict_payload meta.discharge_ft3s
    "00010",  # Water temperature, °C
    "00095",  # Specific conductance, µS/cm @25°C
    "00300",  # Dissolved oxygen, mg/L
    "00400",  # pH, standard units
    "63680",  # Turbidity, FNU/NWU（演示级映射到 Turbidity_NTU）
)

DEFAULT_FETCH_PARAMETER_CSV: str = ",".join(DEFAULT_FETCH_PARAMETER_CDS)

# 可选：便于日志 / 文档生成
PARM_CD_LEGEND: dict[str, str] = {
    "00060": "Discharge (ft³/s), not mapped to 11-feature DTO",
    "00010": "Water temperature (°C)",
    "00095": "Specific conductance (µS/cm @25°C)",
    "00300": "Dissolved oxygen (mg/L)",
    "00400": "pH (field)",
    "63680": "Turbidity (probe; FNU ~ NTU for demo)",
}

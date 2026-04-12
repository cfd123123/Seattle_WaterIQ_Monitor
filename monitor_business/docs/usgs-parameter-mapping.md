# USGS NWIS 参数码 ↔ 项目水质字段映射

本文档把 **美国国家水质信息系统（NWIS）** 常用的 `parameter_cd` 与 `WaterQualityRequest` / `ai_service` 规则评分使用的 **11 个 JSON 字段** 对齐，便于把 `fetch_usgs_puget_sound.py` 等采集结果接到 `/predict` 与 `/api/check`。

权威码表与完整释义以 USGS 为准：**[Parameter code search (NWIS)](https://nwis.waterdata.usgs.gov/usa/nwis/pmcode)**。下列码为地表水监测中**较常见**取值；具体站点是否发布该码、以及是 **IV（连续瞬时）** 还是 **qwdata（实验室/野外水样）**，需对站点单独核对。

---

## 1. API 内部字段（契约）

与 Java `WaterQualityRequest` / Python `PredictRequest` 一致（单位如下表「项目内约定单位」）。

| JSON 字段 | 项目内约定单位 |
|-----------|----------------|
| `Water_Temperature_C` | °C |
| `pH` | 无量纲（标准单位） |
| `Dissolved_Oxygen_mg_L` | mg/L |
| `Conductivity_uS_cm` | µS/cm（25 °C 可比电导 / 比电导） |
| `Turbidity_NTU` | NTU（或可与 FNU 的工程近似，见下文） |
| `Nitrate_mg_L` | mg/L（以 **N** 计，与 USGS「as N」一致） |
| `Ammonia_N_mg_L` | mg/L（以 **N** 计） |
| `Total_Phosphorus_mg_L` | mg/L（以 **P** 计，总磷） |
| `COD_mg_L` | mg/L |
| `BOD_mg_L` | mg/L |
| `Heavy_Metals_Pb_ug_L` | µg/L（总铅或溶解态，见站点方法码） |

---

## 2. 推荐映射表（.parameter_cd → 内部字段）

| parameter_cd | USGS 含义（简述） | 典型数据服务 | 映射到内部字段 | 单位 / 换算注意 |
|--------------|-------------------|--------------|----------------|-----------------|
| `00010` | 水温 | IV / DV | `Water_Temperature_C` | 一般为 °C；若遇极少数华氏记录需换算 \(C=(F-32)\times5/9\)。 |
| `00400` | pH（现场） | IV / qwdata | `pH` | 无量纲。 |
| `00300` | 溶解氧 | IV / qwdata | `Dissolved_Oxygen_mg_L` | mg/L。 |
| `00095` | 比电导（25 °C） | IV / qwdata | `Conductivity_uS_cm` | µS/cm。 |
| `63680` | 浊度（探头） | IV | `Turbidity_NTU` | 现场常为 **FNU**；与 NTU 在不少量程内可近似等同用于演示，正式协议需查传感器与 QA。 |
| `00061` / `99133` 等 | 其他浊度相关码 | IV | `Turbidity_NTU` | 以站点 `parm_cd` 与备注为准，可能需标注「非 NTU」。 |
| `00618` | 硝酸盐（过滤，以 N 计） | qwdata 为主 | `Nitrate_mg_L` | mg/L as N；与字段语义一致。 |
| `00613` | 硝酸盐（以 NO₃ 计等） | qwdata | — | **不直接等同** `Nitrate_mg_L`（as N）；需按化学计量从 NO₃⁻ 换为 N 或改字段定义。 |
| `00610` | 氨（以 N 计） | qwdata | `Ammonia_N_mg_L` | mg/L as N。 |
| `00665` | 总磷（以 P 计） | qwdata | `Total_Phosphorus_mg_L` | mg/L as P。 |
| （多码，如溶解态/总 recoverable 铅） | 铅 | qwdata | `Heavy_Metals_Pb_ug_L` | µg/L；**具体 `parm_cd` 因方法/过滤态而异**，需在 pmcode 中按站点选定。 |
| `00060` | 流量 | IV / DV | —（可选扩展） | ft³/s；**当前 11 特征无流量**，可用于水文上下文或后续单独「水文特征」API，不强行塞进现有 DTO。 |
| `00065` | 水位（水尺高） | IV / DV | — | ft 或 m，同上。 |

---

## 3. 当前规则管线中「USGS 常缺口」的字段

下列指标在 **公开连续 IV** 里很少齐全，通常出现在 **定期水样 / qwdata** 或根本不由 USGS 单站提供：

| 内部字段 | 说明 |
|----------|------|
| `COD_mg_L` | 化学需氧量：多来自实验室，需 qwdata 或其他机构数据。 |
| `BOD_mg_L` | 五日生化需氧量：同上。 |
| `Nitrate_mg_L`、`Ammonia_N_mg_L`、`Total_Phosphorus_mg_L` | 部分流域有高频探头或高频测点；多数站点为低频水样。 |
| `Heavy_Metals_Pb_ug_L` | 多为低频 qwdata。 |

**工程策略（建议）**：

1. **演示/联调**：缺口字段用 **显式占位**（文档化，如 `null` 不允许则使用「中性默认」并在响应中标记 `imputed_fields`，后续再实现）。  
2. **生产叙事**：区分 **IV 实时通道** 与 **qwdata/实验室通道**，规则引擎可对两类来源采用不同权重或分项缺失降权（后续迭代）。

---

## 4. 与 `fetch_usgs_puget_sound.py` 的对应关系

脚本 **默认** `--parameters` 与 `ai_service/usgs_iv_constants.DEFAULT_FETCH_PARAMETER_CDS` 一致（**单一事实来源**），为：

`00060,00010,00095,00300,00400,63680`

| parameter_cd | 含义（简述） | 与 11 项 DTO |
|--------------|--------------|----------------|
| `00060` | 流量 ft³/s | 仅写入 payload 工具 `meta.discharge_ft3s`，无同名字段 |
| `00010` | 水温 °C | `Water_Temperature_C` |
| `00095` | 比电导 µS/cm @25°C | `Conductivity_uS_cm` |
| `00300` | 溶解氧 mg/L | `Dissolved_Oxygen_mg_L` |
| `00400` | pH | `pH` |
| `63680` | 浊度（探头） | `Turbidity_NTU`（FNU/NTU 演示级处理见 §2） |

各站是否在 IV 中发布上述代号需单独核对；未发布的列在合并后为空白，payload 工具对该项使用占位并列在 `imputed_fields`。  
营养盐、COD、BOD、铅等仍依赖 **qwdata** 或其它数据源（见 §3）。

---

## 5. 工具脚本（IV CSV → `/predict` 请求体）

`ai_service/usgs_iv_to_predict_payload.py`：

- 读 `fetch_usgs_puget_sound.py` 输出的 CSV，按 **`usgs_iv_constants.IV_PARM_TO_FIELD`** 将 `00010`、`00095` 等列写入对应 11 项字段；
- 其余字段用 **中性占位**（`DEFAULT_FILLS`），并在 JSON 中列出 **`imputed_fields`**；
- 可选 `--site <site_no>` 取该站 **最新** 一条；省略则取全表最新一条；
- `--dry-predict` 本地跑 `rule_scoring`；`--compact-payload-only` 只打印 11 项便于 `curl`。

示例：

```bash
cd ai_service
.venv/bin/python fetch_usgs_puget_sound.py --days 7
.venv/bin/python usgs_iv_to_predict_payload.py --csv data/usgs_puget_iv.csv --site 12117000 --dry-predict
```

（`fetch` 省略 `--parameters` 即使用 `DEFAULT_FETCH_PARAMETER_CDS`；若某站点无部分 IV 列，对应项仍走占位。）

---

## 6. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-03-31 | 初版：Puget 试点字段 + 与 `WaterQualityRequest` 对齐。 |
| 2026-03-31 | 增加 `usgs_iv_to_predict_payload.py` 与用法。 |

---

**相关文档**：[ai-rules-forecast-roadmap.md](./ai-rules-forecast-roadmap.md)（Phase C 采集扩展）、`ai_service/fetch_usgs_puget_sound.py`。

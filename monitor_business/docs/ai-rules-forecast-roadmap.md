# AI 服务路线：规则评分 + 短时预测（USGS / 西雅图—华盛顿州）

## 1. 目标与定位

在保留现有 **Spring Boot ↔ Python HTTP** 集成模式的前提下，将 `ai_service` 从「单任务：随机森林分类预测」演进为双线能力：

| 能力 | 作用 | 技术属性 |
|------|------|----------|
| **规则评分（主路径）** | 根据当前观测（或可映射字段）计算可解释的综合结果，并输出业务统一的 `pollution_level`（Excellent / Good / …） | 可审计的规则引擎，非黑盒 ML |
| **短时预测（辅路径 / 简历 ML）** | 对选定指标做 **6–24 小时** 量级的前瞻估计（单步或多步），用于预警提示与展示 | 时序基线：滞后特征回归 / 简单平滑外推等 MVP 即可 |

**原则**：告警与统计的「当前等级」以规则为主；预测为 **增强信息**，不替代规则终裁（避免合规与可解释性争议）。

---

## 2. 数据与采集

### 2.1 数据源

- **USGS 水质/水文公开数据**（西雅图及周边 / 华盛顿州站点，按后续站点清单落实）。
- **采集方式**：Python [`dataretrieval`](https://github.com/USGS-python/dataretrieval)（或等价 USGS API 调用），产出带时间戳的多参数序列。
- **实施范围（已实现第一步）**：`ai_service/fetch_usgs_puget_sound.py` + `ai_service/config/usgs_puget_default_sites.json` 默认覆盖 **普吉特湾 / 大西雅图地表水 IV** 小规模站点清单；**叙事上可称「华盛顿州公开数据」**，工程上先 **小清单验证**，再扩展全州或分区批处理，避免单次请求过大。

### 2.2 字段映射（待落成表）

- 建立 **USGS parameter code → 内部字段名** 对照表（与 `WaterQualityRequest` 或精简后的 DTO 对齐）。
- 文档：[usgs-parameter-mapping.md](./usgs-parameter-mapping.md)（IV/qwdata、单位与缺口策略）。

### 2.3 时间序列就绪要求

- 按站点、按指标整理为规则时间索引（例如 **小时或日** bucket），处理缺失与异常值（前向填充策略、最少历史长度阈值）。
- **冷启动**：历史不足 N 个点时，预测接口返回明确状态（如 `forecast_available: false`），不伪造数值。

---

## 3. 分阶段工作清单

### Phase A：规则评分落地（替换当前 `pkl` 推理）

**范围**

- [x] 在 `ai_service/rule_scoring.py` 中实现 **评分 V1**（分项子分 + 权重 + 综合分 0–100 映射五档等级）。
- [x] `POST /predict` 默认走规则；`USE_LEGACY_MODEL=1` 时加载 `water_model.pkl` / `label_encoder.pkl` 走旧分类（仅返回 `Pollution_Level`）。
- [x] 规则模式响应附加：`score`、`rule_version`、`subscores`；Java `WaterQualityResponse` 增加可选 `score`、`ruleVersion`（`subscores` 由日志 JSON 透传，无需字段亦可）。
- [ ] `GET /health` 已含 `mode`: `rules` | `legacy_model`；按需补充 `ai_service` README 一键启动说明。
- [x] `usgs-parameter-mapping.md`：USGS 参数 → 请求 DTO、IV/qwdata 与缺口说明。

**验收**

- Java `POST /api/check` 全流程仍成功；`pollution_level` 与规则分档一致、可复现。
- [x] Python：`rule_scoring.py` 自带 `__main__` 自检（好/坏样例等级）。

**依赖**

- 规则常量化即可；后续可再做「配置外置 / DB」（已在 `TODO.md` 标为后置项）。

---

### Phase B：短时预测 MVP

**设计定案（与 11 项规则评分解耦）**

- 预测对象按 **站点 + USGS `parameter_cd`（或内部 metric 名）** 各建一条时间序列，**不要求**与 `WaterQualityRequest` 的 11 项对齐。  
- 站点之间可用参数不同属正常：**分开训练或分开推理**；某站某参数无足够历史则 **冷启动**：`forecast_available: false` 或等价字段，**不伪造预测**。  
- 典型 MVP：先只做 **单指标**（如 `00060` 流量或 `63680` 浊度）+ **少数试点站**，再扩展。

**范围**

- [x] 选定 **1 个指标**（例如流量 `00060`、浊度 `63680`）+ 试点站点（与 IV CSV 中 `site_no` 一致）。
- [x] 离线：使用 `fetch_usgs_puget_sound.py` 产出的合并 CSV；引擎内 **1h 重采样** + **滞后 Ridge 递归**（`ai_service/forecast_engine.py`）。
- [x] 新接口：`POST /forecast`（`ai_service/main.py`）  
  请求：`site_no`、`parameter_cd`（5 位）、`horizon_hours`（1–168）、可选 `iv_csv_path`（默认 `data/usgs_puget_iv.csv`）。  
  响应：`forecast_available`、`forecast_value`、`model_version`、`data_points_used`、`reason`（失败时）、`series_last_timestamp`（成功时）。
- [x] Java：`WaterForecastClient` + `ForecastService`（Resilience4j 重试）+ `POST /api/forecast` 代理 Python。
- [x] 前端驾驶舱：`frontend` 增加「短时预测」表单与结果区（`POST /api/forecast`）。

**验收**

- [x] 试点 CSV 存在且该站该参数有足够小时点数时 `forecast_available=true`；不足时 `false` 且带 `reason`。
- [x] 无效 horizon 不 500，结构化 `reason`。

---

### Phase C：采集与流水线整合

**范围**

- [x] 脚本：`ai_service/fetch_usgs_puget_sound.py` — 参数化站点列表（JSON）、起止时间/天数、多 `parameterCd`、输出 CSV。
- [x] 手动刷新：`run_fetch` + FastAPI `POST /refresh/usgs-iv`（`days` 1–90，**覆盖**默认 CSV；可选 **相对旧 CSV 的 (site_no,datetime) 差集** 批量 `/api/check`）；Spring `POST /api/usgs/iv/refresh`；前端按钮。
- [ ] 扩展：`fetch_usgs_wa.py` 或按县/流域分批 — 全州时需分批与参数筛选。
- [ ] （可选）Spring `@Scheduled` 或外部 cron 调脚本 / 写库；或 MVP 仍为手工导入 + `/api/check` 驱动。
- [x] `monitor_station.external_id`：可选 USGS `site_no`；`POST/GET /api/stations`、`GET /api/map/stations` 已暴露；前端站点表单与预测下拉可填入。

**验收**

- 一键命令可拉取可复现的一段 WA 数据并用于 Phase B 训练或演示。

---

### Phase D：前端与可观测性（按需）

**范围**

- [ ] 驾驶舱增加「预测带」或 KPI：未来 24h 风险（若 Java 已暴露字段）。
- [ ] `model_call_log` 或等价表：记录 `rule_version` / `forecast_model_version`（若需简历故事「全链路可追溯」）。

**验收**

- 演示路径：地图选站 → 看到当前等级 + 短时预测提示（可 mock 后替换真数据）。

---

## 4. 接口与契约演进（概要）

| 组件 | 当前 | 目标（概要） |
|------|------|----------------|
| Python `POST /predict` | 返回 `Pollution_Level` | 规则评分，返回等级 + 可选 `score`、`rule_version` |
| Python 新增 | — | `POST /forecast`（短时预测） |
| Java `WaterQualityResponse` | `pollution_level` | 按需扩展 `forecastSummary` 或独立资源 `/api/forecast` |

详细字段在实现 MR 中同步更新 `docs/api.md` 与 OpenAPI。

---

## 5. 风险与对策

- **采样不规则**：重采样 + 最少点数门槛；预测不可用时降级。
- **跨层耦合**：规则与预测模块在 Python 分包（`scoring/` vs `forecast/`），便于单测。
- **简历表述**：写清「可解释规则 + 时序预测增强」，避免将纯规则吹成深度学习。

---

## 6. 建议排期（参考）

| 阶段 | 工作量（粗估） |
|------|----------------|
| Phase A | 0.5–1.5 天 |
| Phase B MVP | 1–3 天 |
| Phase C | 1–2 天 |
| Phase D | 0.5–2 天 |

可根据「先演示后工程化」压缩：先做 **A + B 的 Python 可用演示**，再接线 Java 与入库。

---

## 7. 简历可引用的一句话（中英文）

- **中文**：设计可解释的水质规则评分作为主判定，并基于 USGS 公开时序数据实现短时预测 API，与 Spring Boot 微服务集成，支撑地图驾驶舱与告警闭环。  
- **English**：Delivered explainable rule-based water quality grading as the primary decision path, plus short-horizon time-series forecasting on USGS data via a Python sidecar integrated with Spring Boot for alerting and dashboard workflows.

---

**相关文档**：[`v5-plan.md`](./v5-plan.md)（GIS/表结构/前端阶段）、[`TODO.md`](./TODO.md)（全局待办与延后项）。

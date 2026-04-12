# 按站点：流量 + 浊度预测与异常检测（按需拟合）

本文档固化与产品/实现相关的约定，对应代码：`ai_service/site_param_anomaly_on_demand.py`、`POST /anomaly/site-param-from-iv`、Spring `POST /api/usgs/anomaly/site-param/check`，以及预测接口对 `parameter_cd` 的限制。

## 1. 目标

- **不做水温（00010）预测**；产品侧仅强调 **流量（00060）** 与 **浊度（63680）**。
- **预测**：沿用现有 **单站点 × 单 `parameter_cd`** 的滞后 Ridge（`forecast_engine`），**每次请求用 IV CSV 里该序列当场拟合**，不维护按站长期保存的 pkl。
- **异常检测**：对 **00060 / 63680** 分别、按站点，用 **该站该参数的小时序列** 当场拟合 **单变量 RobustScaler + IsolationForest**，对 **序列最后一个有效小时点** 打分；**不**再依赖全局五维 `usgs_anomaly_iforest_v1.pkl` 做此路径。
- **新站 / 冷启动**：该站在 IV 中 **有效小时点数不足** 时，接口返回 `*_available=false`（或 HTTP 200 + 业务字段）及 **明确 `reason`**，**不进行预测/异常判定**；用户 **刷新 IV、积累窗口数据** 后即可自动可用，**无需**人工「全库重训」。

## 2. 数据与登记流程

1. 用户在界面登记 `monitor_station`，`external_id` = USGS `site_no`。
2. **IV 刷新**（手动或定时）将已登记站点并入 NWIS 拉数列表，合并写入默认 `ai_service/data/usgs_puget_iv.csv`。
3. 某站若 **无该参数列** 或 **重采样后小时序列过短**，则该参数预测/异常均 **不可用**，界面展示原因（如「无序列/列」「历史不足」）。

## 3. 阈值与告警

- **预测告警**：仍仅对 **63680** 使用 `ForecastAlertPolicy` 浊度分档；**00060** 不做污染等级预测告警（水文语义单独扩展时可再议）。
- **站点参数异常告警**：`ANOMALY_ALERT`，`ruleCode` 形如 `SITE_PARAM_IF_00060` / `SITE_PARAM_IF_63680`，按 **站点 + ruleCode** 做 6 小时去重，避免同参重复刷屏。

## 4. 与旧版「五参异常」关系

- `POST /predict-usgs-anomaly` 与 `POST /api/usgs/anomaly/check-from-iv`（五维全局模型）可暂时保留作实验/兼容；**产品主路径**以本文档的 **按站按参按需异常** 为准。

## 5. 参数下限（实现常量，可调）

- 预测：`forecast_engine.MIN_HOURLY_POINTS`（当前 48）。
- 按需单参异常：`site_param_anomaly_on_demand.MIN_HOURLY_POINTS`（当前 72）。

## 6. API 一览

| 说明 | 方法 | 路径 |
|------|------|------|
| 单参异常（Python） | POST | `http://localhost:8000/anomaly/site-param-from-iv` |
| 单参异常（Spring 代理 + 可写告警） | POST | `/api/usgs/anomaly/site-param/check` |
| 短时预测 / 趋势 | POST | `/api/forecast`、`/api/forecast/series`（`parameter_cd` 仅允许 `00060`、`63680`） |
| 自动预测开关 / 摘要 | GET、PUT | `/api/forecast/auto-settings`（`PUT` body：`{ "enabled": true }`） |

## 7. 服务端自动预测（约每 24 小时）

- 表 `auto_forecast_settings`（单行 `id=1`）持久化 `enabled`；前端勾选后 `PUT` 更新。
- `@Scheduled(cron = "${water.auto-forecast.cron}")` 触发批量：对每个 **`externalId` 非空** 的登记站，分别调用 `forecastSeriesWithRetry`（`00060`、`63680`，`horizon_hours=24`，`history_days=10`）。
- 默认 cron `0 0 2 * * ?` = **服务器时区每日 02:00**（「约每 24 小时一次」的工程等价）；可在 `application.properties` 修改。
- 每次跑完写入 `last_run_at` 与 `last_run_summary`（成功/失败计数与部分错误摘要）。

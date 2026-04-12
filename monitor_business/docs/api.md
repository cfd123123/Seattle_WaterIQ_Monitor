# monitor_business API 文档（联调版）

本文用于前后端、测试与运维联调。若与实现冲突，以代码为准。

## 1. 基础信息

- Base URL：`http://localhost:8080`
- Swagger UI：`http://localhost:8080/swagger-ui.html`
- OpenAPI JSON：`http://localhost:8080/v3/api-docs`
- 统一响应：`ApiResponse<T>`
  - `code`：`"0"` 表示成功
  - `message`：提示信息
  - `data`：业务数据
  - `traceId`：链路 ID
  - `timestamp`：服务端时间
- 常用请求头：
  - `Content-Type: application/json`
  - 可选：`X-Trace-Id: your-trace-id`

## 2. 健康与观测

### GET `/actuator/health`
- 说明：健康检查

### GET `/actuator/prometheus`
- 说明：Prometheus 指标抓取

## 3. 检测接口

### POST `/api/check`

- 说明：单次检测，调用 AI 后落库并可能触发告警。
- 重试：当 AI 接口出现瞬时网络异常或返回 `503` 时，服务端会自动重试（间隔 `500ms`，最多重试 `3` 次）。
- 请求体（11 个字段 + `stationCode` 必填；`observed_fields` 可选）：

```json
{
  "Water_Temperature_C": 24.5,
  "pH": 7.1,
  "Dissolved_Oxygen_mg_L": 6.9,
  "Conductivity_uS_cm": 305.0,
  "Turbidity_NTU": 4.0,
  "Nitrate_mg_L": 1.2,
  "Ammonia_N_mg_L": 0.18,
  "Total_Phosphorus_mg_L": 0.06,
  "COD_mg_L": 16.5,
  "BOD_mg_L": 3.1,
  "Heavy_Metals_Pb_ug_L": 4.2,
  "stationCode": "puget_12117000",
  "observed_fields": ["Water_Temperature_C", "pH"]
}
```

`observed_fields`：列明哪些指标为**实测**（与 USGS 等数据源对齐）；省略时规则引擎按 **11 项均实测**（`coverage_ratio`=1）处理。  
当前规则综合分仍按 **11 项数值**加权计算（含占位值）；`coverage_ratio` / `imputed_fields` 仅用于**透明度展示**，后续可迭代为「按实测子集重加权」。

- 成功 `data`（规则模式由 Python 返回；字段可能略多）：

```json
{
  "pollution_level": "Poor",
  "score": 41.2,
  "rule_version": "rule-v1-2026-03",
  "observed_count": 2,
  "coverage_ratio": 0.1818,
  "imputed_fields": ["Dissolved_Oxygen_mg_L", "Conductivity_uS_cm"]
}
```

（`imputed_fields` 完整列表以实际响应为准，示例仅作说明。）

### POST `/api/check/batch`

- 说明：批量检测，单条失败不影响其他条。
- 限制：`items` 至少 1 条，最多 100 条。
- 校验：每条都必须带有效 `stationCode`（已在 `monitor_station.station_code` 登记）；否则该条返回失败。
- 请求体：

```json
{
  "items": [
    {
      "Water_Temperature_C": 24.5,
      "pH": 7.1,
      "Dissolved_Oxygen_mg_L": 6.9,
      "Conductivity_uS_cm": 305.0,
      "Turbidity_NTU": 4.0,
      "Nitrate_mg_L": 1.2,
      "Ammonia_N_mg_L": 0.18,
      "Total_Phosphorus_mg_L": 0.06,
      "COD_mg_L": 16.5,
      "BOD_mg_L": 3.1,
      "Heavy_Metals_Pb_ug_L": 4.2
    }
  ]
}
```

- 成功 `data`：
  - `successCount` / `failCount`
  - `results[]`：每项包含 `index`、`success`、成功时 `data` 或失败时 `errorMessage`

### GET `/api/records`

- 说明：检测记录分页查询
- 查询参数：
  - `page`（默认 0）
  - `size`（默认 20）
- 返回：`PageResponse<WaterQualityRecord>`

### GET `/api/map/stations`

- 说明：地图站点快照（点位 + 最近检测 + 未关闭告警数）
- 返回：`MapStationPointResponse[]`

## 4. 站点接口

### POST `/api/stations`

- 说明：新建站点（`stationCode` 已存在返回 `409`）
- 请求体：

```json
{
  "stationCode": "puget_12117000",
  "stationName": "Puget sample (USGS 12117000)",
  "province": "Washington",
  "city": "Seattle",
  "latitude": 47.6021,
  "longitude": -122.3350,
  "externalId": "12117000"
}
```

`externalId` 可选，如 USGS **8 位 `site_no`**，与 IV 拉数、短时预测一致。  
当填写 `externalId` 时，服务端会通过 AI 侧代理调用 NWIS 站点服务校验是否存在：
- 存在：允许保存
- 不存在：返回 `400`（message 含“站点不存在/未找到”）

### PUT `/api/stations/{stationCode}`

- 说明：更新已存在站点（路径 `stationCode` 为主键；请求体里的 `stationCode` 若填写须一致）
- 不存在：`404`
- 请求体中的 `externalId` 若填写，同样会做 NWIS 存在性校验（失败返回 `400`）

### DELETE `/api/stations/{stationCode}`

- 说明：删除站点主数据
- 不存在：`404`
- 备注：不会级联删除历史检测/告警记录

### GET `/api/stations`

- 说明：站点列表
- 返回：`StationResponse[]`

## 5. 告警接口

### GET `/api/alerts`

- 说明：告警分页查询
- 查询参数（可组合）：
  - `page`、`size`
  - `status`：`NEW` / `ACK` / `CLOSED`
  - `createdFrom`、`createdTo`（ISO DateTime）
  - `severity`：如 `MEDIUM` / `HIGH`
  - `pollutionLevel`：如 `Poor` / `Very Poor`

### POST `/api/alerts/{id}/ack`

- 说明：确认告警
- 请求体（可选）：

```json
{
  "acknowledgedBy": "operator",
  "remark": "已核实"
}
```

### POST `/api/alerts/{id}/close`

- 说明：关闭告警
- 请求体（可选）：

```json
{
  "closedBy": "operator",
  "remark": "现场复核完成"
}
```

## 6. 统计接口

### GET `/api/stats/overview`

- 说明：统计总览
- 无参数
- 返回：总检测/总告警/总AI失败、未关闭告警、今日与近7天汇总

### GET `/api/stats/distribution`

- 说明：分布统计
- 参数：
  - 可不传
  - 若传，`from` 和 `to` 必须同时传（`yyyy-MM-dd`）
- 返回：
  - `pollutionLevelDistribution`
  - `alertSeverityDistribution`
- 约束：查询跨度默认不超过 `water.stats.max-range-days`（默认 365）

### GET `/api/stats/trend`

- 说明：趋势统计
- 参数：
  - `from`（`yyyy-MM-dd`）
  - `to`（`yyyy-MM-dd`）
  - `granularity`（当前仅支持 `day`）
- 返回：`StatsTrendResponse`，每日序列为 **`series`**（每项含 `date`、`checkCount`、`alertCount` 等），**不是** `points`。
- 约束：查询跨度默认不超过 `water.stats.max-range-days`（默认 365）

## 7. USGS IV 与短时预测（Spring 代理，推荐）

### POST `/api/usgs/iv/refresh`

- 说明：触发 AI 服务从 **NWIS** 拉取瞬时数据（IV），合并后 **整文件覆盖** 写入默认 `ai_service/data/usgs_puget_iv.csv`（**不追加**，仅保留最近 `days` 天窗口内数据，避免 CSV 无限增大）。
- 请求体（可选）：
  - `days`：**1–90**，省略时按 **30**。
  - `runChecksAfterRefresh`：`true` 时，在**覆盖写入前**读取旧 IV 文件，对本次合并结果中与旧文件相比 **新增的 `(site_no, datetime)` 行** 各生成一条 11 项请求体，**批量走与 `/api/check` 相同的落库与告警逻辑**（每批最多 100 条，多分块；每条独立事务）。**首次刷新**（无旧文件）时，窗口内**每一行**都会视为新增并各跑一次检测。若 `monitor_station.external_id` 与该 USGS `site_no` 一致，则自动带上 `stationCode`。
- 额外行为（已实现）：
  - 刷新时会把数据库中已登记站点的 `externalId`（去重）作为附加站点列表一并传给 Python，与默认配置站点合并后拉取；
  - 这意味着：新增站点并通过 USGS 校验后，后续刷新无需手改 JSON 也可参与拉取。
- 响应：`ApiResponse<UsgsIvRefreshResultDto>`：含 `incrementalRowsNew`（新增行数）；若勾选批量检测则另含 `checkSyncSuccessCount`、`checkSyncFailCount`。
- 依赖：Python 已安装 `dataretrieval`，且运行环境能访问外网 USGS；Resilience4j 重试实例 `waterAiUsgsIvRefreshRetry`。

### 直连 Python（IV 刷新）

- `POST http://localhost:8000/refresh/usgs-iv`，请求体：`{ "days": 30, "include_latest_check_payloads": false }`；为 `true` 时响应含 `incremental_check_payloads`、`incremental_rows_new`（相对旧文件的差集；供 Java 编排检测）。

### POST `/api/forecast`

- 说明：转发至 AI 服务 `POST /forecast`（`water.ai.base-url`），与直连 Python 语义一致。
- Base URL：`http://localhost:8080`（经 Vite 代理时同 `/api` 前缀）。
- 请求体 JSON 示例（蛇形或 camelCase 均可）：

```json
{
  "site_no": "12117000",
  "parameter_cd": "00060",
  "horizon_hours": 24
}
```

- 可选 `iv_csv_path`：Python 进程可读路径；省略则使用 AI 服务默认 `ai_service/data/usgs_puget_iv.csv`。
- 响应：`ApiResponse<ForecastResponse>`，字段含 `forecast_available`、`forecast_value`、`model_version`、`data_points_used`、`reason` 等。

### 直连 Python（联调备选）

- `POST http://localhost:8000/forecast`，请求体同上；不经 Spring 与重试封装。

## 8. 常见错误码与状态

- `400 Bad Request`
  - 参数缺失/格式不合法
  - `from > to`
  - `granularity` 非 `day`
  - 查询跨度超上限
  - `stationCode` 为空或不存在（未登记）
  - `externalId` 在 USGS/NWIS 中不存在（站点校验失败）
- `503 Service Unavailable`
  - AI 服务不可用（下游不可达）
- `404 / 409`
  - 站点不存在 / 新增站点编码冲突
  - 告警不存在 / 状态冲突（如重复关闭）

## 9. 推荐业务流程（站点登记 → 刷新 → 检测）

1. 调用 `POST /api/stations` 或 `PUT /api/stations/{stationCode}` 保存站点；
2. 若有 `externalId`，系统实时校验 USGS 站点是否存在，不存在直接返回警告（`400`）；
3. 调用 `POST /api/usgs/iv/refresh` 刷新 IV，系统自动合并“默认站点 + 数据库已登记 externalId”进行拉取；
4. 若 `runChecksAfterRefresh=true`，仅对“已登记并能映射到 stationCode”的增量点执行检测并落库，避免孤儿记录。

## 10. 相关文档

- 架构说明：`docs/architecture.md`
- 统计口径：`docs/stats-definition.md`
- 时区说明：`docs/time-and-timezone.md`

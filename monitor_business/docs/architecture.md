# monitor_business 业务架构设计

> **一页总览（架构图，Mermaid）**：[architecture-overview.md](./architecture-overview.md)

## 1. 业务目标与边界

### 1.1 业务目标

- 对水质监测数据进行智能判定，输出污染等级。
- 建立可扩展的 "监测 -> 预警 -> 处置 -> 追踪" 业务闭环。
- 为后续监管、统计分析、趋势预测提供数据基础。

### 1.2 系统边界

- `monitor_business`：
  - 提供业务 API。
  - 完成参数校验、流程编排、规则判断、告警触发、数据持久化。
- `ai_service`（FastAPI，默认 **8000**）：
  - **`POST /predict`**：水质综合判定；默认走 **可解释规则评分**（`rule_scoring`），可选 `USE_LEGACY_MODEL=1` 使用遗留随机森林（`water_model.pkl`）。
  - **`POST /forecast`**：基于本地 **USGS IV 风格 CSV** 的短时数值外推（与 `fetch_usgs_puget_sound.py` 产出对齐；详见 [ai-rules-forecast-roadmap.md](./ai-rules-forecast-roadmap.md)、[usgs-parameter-mapping.md](./usgs-parameter-mapping.md)）。
  - **`GET /health`**：健康检查（返回当前为 `rules` 或 `legacy_model` 模式）。
  - 不承担业务权限、告警状态机、检测/告警持久化（由 Java 侧负责）。

---

## 2. 总体分层架构

### 2.1 接入层（API Layer）

- 对外 REST 由多个 Controller 分工（**已移除**旧的 `/water-quality/*` 与重复 Feign，避免双入口）。
- 当前已实现：
  - **`MonitorController`**：`GET /api/map/stations`（地图站点快照）。
  - **`StationController`**：`POST /api/stations`（幂等 upsert）、`GET /api/stations`。
  - **`ForecastController`**：`POST /api/forecast`（代理 Python `POST /forecast`，带重试配置）。
  - **`StatsController`**、`AlertController`：统计与告警（见第 6 节）。

### 2.2 应用层（Application Layer）

- 用例编排和事务控制。
- 典型职责：
  - 接收 DTO。
  - 参数合法性校验与标准化处理。
  - 调用 AI 客户端。
  - 触发领域规则。
  - 保存记录并构建响应。

### 2.3 领域层（Domain Layer）

- 核心业务模型与规则。
- 领域对象建议：
  - `WaterQualitySample`（采样数据）
  - `PredictionResult`（预测结果）
  - `AlertEvent`（告警事件）
- 领域规则建议：
  - 污染等级映射规则
  - 告警分级规则
  - 重复告警抑制策略

### 2.4 基础设施层（Infrastructure Layer）

- Feign 调用 Python AI 服务。
- 数据持久化（默认 **PostgreSQL**；开发可选 **H2** 文件库）。
- 缓存（Redis）。
- 消息队列（Kafka/RabbitMQ）用于异步告警与通知。
- 日志、监控、链路追踪等可观测组件。

---

## 3. 代码模块设计（包结构建议）

建议在 `src/main/java/com/example/waterbusiness` 下逐步演进为：

- `controller`
  - 接口层，处理请求与返回。
- `application`
  - 应用服务，承接用例流程。
- `domain`
  - `model`：实体和值对象。
  - `service`：领域规则服务。
- `integration`
  - `ai`：Feign Client、AI 适配逻辑。
- `repository`
  - `entity`、`mapper`（或 `jpa`）、`impl`。
- `event`
  - 事件定义与发布/订阅处理。
- `common`
  - 统一返回体、异常体系、枚举、常量、工具类。

---

## 4. 核心业务流程（概念）

当前主线为 **USGS IV / 站点 / 告警 / 预测 / 异步任务**（见各 Controller 与 `database-schema.md`）。历史上曾描述「`POST /api/check` → 写检测事实表」的流程；**`water_quality_record` 已移除**，不再作为默认落库路径。Python **`POST /predict`** 仍可由联调或 IV 刷新可选路径调用，但不强制经已删除的检测分页 API。

---

## 5. 数据架构设计（核心表建议）

**表关系、字段清单与 ER 示意**已单独整理为：[database-schema.md](./database-schema.md)。

### 5.1 检测事实表 `water_quality_record`（已移除）

该表及对应 JPA 实体已从当前代码库删除；**不再**作为「一次检测一行」的主事实表。统计与趋势以 **`usgs_site_param_run`**、**`alert_event`**、**`model_call_log`** 等为准，详见 [database-schema.md](./database-schema.md) 与 [stats-definition.md](./stats-definition.md)。

**站点主数据 `monitor_station`**（已实现）：`station_code` 唯一、经纬度、可选 **`external_id`（USGS `site_no`）** 等；详情与 ER 见 [database-schema.md](./database-schema.md)。

### 5.2 `alert_event`

- 主键 ID
- 告警类型、告警级别
- 当前状态（NEW/ACK/CLOSED）
- 触发规则
- 处理人、处理时间

### 5.3 `rule_config`

- 主键 ID
- 规则名称、规则参数、阈值
- 是否启用
- 版本号

### 5.4 `model_call_log`

- 主键 ID
- 调用时间、耗时、状态码
- 请求摘要、响应摘要
- 错误信息（失败时）

---

## 6. API 设计建议

联调与测试可直接参考独立文档：**[api.md](./api.md)**。

### 6.1 当前对外 API 清单（已实现）

统一使用 **`ApiResponse<T>`** 包装成功响应；请求/响应头支持 **`X-Trace-Id`**（可与网关或客户端对齐）。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/overview` | 统计总览（MVP）：不需要查询参数。`data`：`StatsOverviewResponse`，含总检测/总告警/总 AI 失败、当前未关闭告警，以及今日与最近 7 天的检测/告警/AI 失败汇总。 |
| `GET` | `/api/stats/distribution` | 分布统计（MVP）：可选查询参数 `from`/`to`（`yyyy-MM-dd`，要么都传要么都不传）。`data`：`StatsDistributionResponse`，含污染等级分布（`pollutionLevelDistribution`）与告警严重度分布（`alertSeverityDistribution`）。若传日期，查询跨度默认不超过 **365 天**（`water.stats.max-range-days`）。 |
| `GET` | `/api/stats/trend` | 趋势统计（MVP）：查询参数 `from`/`to`（`yyyy-MM-dd`，含边界）、`granularity`（当前仅支持 `day`）。`data`：`StatsTrendResponse`，含每日 `checkCount`、`alertCount`、`aiFailureCount` 与 `pollutionLevelBreakdown`。查询跨度默认不超过 **365 天**（`water.stats.max-range-days`）。 |
| `GET` | `/api/map/stations` | 地图站点快照：点位、最近检测摘要、未关闭告警数等（`MapStationPointResponse[]`）。 |
| `POST` | `/api/stations` | 新建站点；`stationCode` 重复返回 `409`；`externalId` 非空时会校验 USGS/NWIS 站点存在性。 |
| `PUT` | `/api/stations/{stationCode}` | 更新已存在站点；`externalId` 非空时同样校验 USGS/NWIS。 |
| `DELETE` | `/api/stations/{stationCode}` | 删除站点主数据（不级联删历史检测/告警）。 |
| `GET` | `/api/stations` | 站点列表（`StationResponse[]`）。 |
| `POST` | `/api/usgs/iv/refresh` | 手动从 NWIS 拉取 IV 并按最近 N 天 **覆盖** 写默认 CSV；刷新时会合并“默认清单 + 数据库已登记 externalId”拉取；可选 **`runChecksAfterRefresh`** 对增量点批量走与 `/api/check` 相同的落库与告警（见 [api.md](./api.md)）。 |
| `POST` | `/api/forecast` | 短时预测：请求体含 `siteNo`、`parameterCd`、`horizonHours` 等；Spring 代理 Python `POST /forecast`（IV CSV 路径等约定见 [api.md](./api.md)）。 |
| `GET` | `/api/alerts` | 告警分页。查询参数：`page`、`size`；筛选：**`status`**（`NEW`/`ACK`/`CLOSED`）、**`createdFrom`** / **`createdTo`**（时间语义见 [time-and-timezone.md](./time-and-timezone.md)）、**`severity`**（如 `MEDIUM`/`HIGH`，忽略大小写）、**`pollutionLevel`**（与落库时污染等级文本一致，如 `Poor`/`Very Poor`，忽略大小写）；可多条件组合。默认按 `createdAt` 降序。`data`：**`PageResponse<AlertEvent>`**。 |
| `POST` | `/api/alerts/{id}/ack` | 确认告警，可选 body：`acknowledgedBy`、`remark`。 |
| `POST` | `/api/alerts/{id}/close` | 关闭告警，状态变为 `CLOSED`。可选 body：`closedBy`、`remark`（有原备注时追加 ` \| 关闭备注: …`）。 |

**分页体 `PageResponse`（稳定 JSON）**：`content`、`totalElements`、`totalPages`、`page`（从 0 起）、`size`、`first`、`last`、`numberOfElements`、`empty`。

**说明**：业务侧不再提供 `/water-quality/predict`；**`/api/check`**、**`/api/records`** 等旧版检测分页接口已不在当前控制器中。短时预测走 **`POST /api/forecast`**（Python `POST /forecast`）。离线拉取 IV 数据可使用仓库内 **`ai_service/fetch_usgs_puget_sound.py`**（写入 CSV，不自动写业务库）。

### 6.2 后续接口

- （暂无）

### 6.3 统一响应模型（已实现）

- `code`：业务状态码（成功一般为 `"0"`）
- `message`：提示信息
- `data`：业务数据
- `traceId`：链路追踪 ID（与 `TraceIdFilter` / MDC 一致）
- `timestamp`：服务端时间（ISO-8601）

失败时由全局异常处理返回同类结构，`code` 为业务错误码（如 `VALIDATION_ERROR`、`AI_SERVICE_UNAVAILABLE` 等），HTTP 状态码区分场景（400/503/502 等）。

### 6.4 时间与多时区（决策说明）

业界常用 **UTC + ISO-8601（带 `Z` 或偏移）** 做跨系统对齐；区域型系统也可约定单一业务时区并写进文档。当前实现使用 **`LocalDateTime` + PostgreSQL `timestamp`**，含义与升级路径见专门说明：**[time-and-timezone.md](./time-and-timezone.md)**。

### 6.5 统计口径（V4.4）

`/api/stats/overview`、`/api/stats/distribution`、`/api/stats/trend` 以及 Grafana 统计面板的口径定义见：**[stats-definition.md](./stats-definition.md)**。

---

## 7. 稳定性与容错设计

- Feign 配置超时（connect/read timeout）。
- AI 调用重试策略（有限重试次数）。
- 熔断与降级（推荐 Resilience4j）。
- Python 服务不可用时返回业务友好错误，不直接暴露 500。
- 对重复上报进行幂等去重（按监测点 + 时间窗口）。
- 告警通知采用异步化处理，避免接口阻塞。

---

## 8. 安全与治理设计

- 接口鉴权：JWT/OAuth2（按角色访问）。
- 输入安全：字段白名单、范围校验、请求限流。
- 审计日志：记录规则变更、告警处理等关键操作。
- 配置治理：环境隔离（dev/test/prod），敏感配置外置。

---

## 9. 可观测性设计

- 日志：结构化 JSON 日志，统一携带 traceId。
- 指标：
  - 接口 QPS、P95/P99 延迟
  - AI 调用成功率
  - 告警触发数量
- 链路追踪：Spring -> Feign -> Python 全链路追踪。
- 运行告警：接口 5xx、AI 超时率、失败率阈值报警。

---

## 10. 部署架构建议

### 10.1 短期（当前阶段）

- 单体部署：
  - `monitor_business`：`8080`
  - `ai_service`：`8000`
- 数据库：**PostgreSQL**（本地可用 Docker Compose，见 `monitor_business/docker-compose.yml` 与 `docs/postgresql-setup.md`）；开发可选 **H2 文件库**（`h2` profile）。

### 10.2 中期

- 容器化部署（Docker）。
- 接入网关（Spring Cloud Gateway）。
- 使用 K8s 做弹性扩容。

### 10.3 长期

- 按领域拆分服务：
  - 检测服务
  - 告警服务
  - 报表服务
  - 规则中心

---

## 11. 迭代路线图

### V1（已完成）

- Spring Boot 工程搭建
- Feign 调用 Python `/predict`（联调能力）

### V2（已完成）

- H2 + JPA：本地 profile 可用 H2 Console 查看数据
- 统一响应 `ApiResponse`、全局异常、`TraceIdFilter`
- `WaterQualityService` / `water_quality_record` 主路径已移除；当前以 USGS/站点/告警/预测为主

### V3

- **已完成**：告警中心（分级、状态流转、列表与确认接口）、`alert_event` / `model_call_log` 等（见当前代码）。
- **暂缓（优化阶段再做）**：规则配置化（`rule_config`）、异步通知（消息队列 / `@Async`）——详见 [TODO.md](./TODO.md)「暂不实施」。

### V4（规划中：可观测 + 权限 + 统计）

V4 **主目标**：监控指标、链路追踪、接口鉴权与授权、统计/趋势 API。下列按**工作包**拆分，便于排期、并行与验收。

#### 4.1 监控指标（Metrics）

- 接入 **Micrometer**，指标对外导出（常见：**Prometheus** `/actuator/prometheus` 或同类）。
- **HTTP**：QPS、延迟分位（如 P95/P99）、`4xx`/`5xx` 计数。
- **AI / Feign**：调用次数、成功率、超时与失败（可与现有 `model_call_log` 互补：指标偏实时聚合，库表偏审计）。
- **业务**：如告警新建速率、检测批量成功率等（按需要增量添加）。
- **验收建议**：本地或测试环境能拉取指标并看到核心前缀（如 `http.server.requests`、自定义 `water.*`）。

**当前已落地**：

- 依赖：`spring-boot-starter-actuator`、`micrometer-registry-prometheus`；另加 **`feign-micrometer`** 便于 Feign 出站请求进入 Micrometer（与下方业务 Timer 并存，名称空间不同）。
- 配置：`application.properties` 中 `management.endpoints.web.exposure.include=health,info,prometheus`，`spring.application.name=water-business`，HTTP 服务端 `percentiles-histogram` 已打开；**生产**应对 `/actuator/**` 做网络隔离或接入 Security。
- 自定义指标：`WaterBusinessMetrics`（若已注册：`water.ai.predict`、`water.alerts.created` 等；以实际 `/actuator/prometheus` 为准）。
- **拉取示例**：启动后访问 `GET http://localhost:8080/actuator/prometheus`，检索 `water_`、`http_server_requests`、JVM 等序列。
- **Grafana 大盘**：`observability/grafana/dashboards/water-business-overview.json`（HTTP、业务 `water_*`、JVM、Hikari）；`docker compose up -d grafana` 后于 **Dashboards** 打开 **水质业务 · 监控大盘**，顶部可选 **Application** 变量。

#### 4.2 链路追踪（Tracing）

- 选型并实现 **分布式追踪**（如 **OpenTelemetry** 接入 **Zipkin** / **Jaeger** / **SkyWalking** 等之一）。
- 串联 **Spring MVC → Feign → Python**：同一业务请求共用一个 trace， spans 覆盖 HTTP 出站与（可选）Python 侧 OTLP。
- 与现有 **`TraceIdFilter` / `X-Trace-Id` / MDC** 对齐，避免日志 trace id 与追踪后端不一致。
- **验收建议**：任一带 Feign 出站的请求在追踪 UI 中可见 **Java 侧** MVC + Feign 子跨度；Python 侧 OTLP 为可选增强。

**当前已落地（Tempo + Grafana）**：

- **Java**：`micrometer-tracing-bridge-otel` + `opentelemetry-exporter-otlp`；`management.otlp.tracing.endpoint=http://127.0.0.1:4318/v1/traces`，`management.tracing.sampling.probability=1.0`（开发全采样）；`spring.cloud.openfeign.observation.enabled=true`（Feign 出站观测）。
- **`TraceIdFilter`**：顺序在入口观测之后（`Ordered.HIGHEST_PRECEDENCE + 100`），**优先使用 Micrometer/OTEL 的 trace id** 写入 MDC 与 `X-Trace-Id`；无活跃 span 时回退请求头或 UUID。
- **本地栈**（与 `docker-compose.yml` 同目录）：`docker compose up -d tempo prometheus grafana`。**Tempo** OTLP `4317`/`4318`；**Prometheus** `9090`（默认抓取 Compose 网络内 **`monitor-service:8080/actuator/prometheus`**，见 `observability/prometheus/prometheus.yml`；仅起可观测栈、未起业务容器时需改 targets 或会抓取失败）。**Grafana** `http://localhost:3000`：数据源 **Tempo** → `http://tempo:3200`；**Prometheus** → `http://prometheus:9090`（⚠️ 不能把 Grafana 直接指到 Actuator URL，否则会 404：Grafana 需要 Prometheus 的 `/api/v1/query` API）。
- **配置与文件**：`observability/tempo.yaml`、`observability/prometheus/prometheus.yml`、`observability/grafana/provisioning/datasources/datasources.yaml`；**预置大盘** JSON：`observability/grafana/dashboards/water-business-overview.json`（provisioning：`observability/grafana/provisioning/dashboards/dashboards.yaml`）。Grafana 侧边栏 **Dashboards** 可见 **「水质业务 · 监控大盘」**。
- **使用顺序**：先起 Tempo，再起 **Spring Boot**，再在 Grafana → Explore → Tempo 查 trace；未起 Tempo 时 OTLP 可能打错误日志，应用一般仍可运行。
- **后续**：`ai_service` 增加 OTLP 导出后，可在同一 Trace 中拼接 Python span。

#### 4.3 权限体系（AuthN / AuthZ）

- **鉴权**：**JWT** 或 **OAuth2**（资源服务器模式等），与部署环境一致。
- **授权**：角色或权限点（示例：**只读** vs **告警处理**）；敏感写操作（如 `POST /api/alerts/{id}/ack|close`、若后续有规则管理）与只读查询分离。
- **审计**：与现有 `acknowledgedBy`、`closedBy`、`remark` 等字段衔接；关键写操作可记结构化审计日志（谁、何时、对哪些资源）。
- **配套**：敏感配置外置、环境隔离（见第 8 节）；可选请求限流。
- **验收建议**：无令牌访问写接口被拒绝；只读角色无法 ack/close（若按上述模型落地）。

#### 4.4 统计报表与趋势分析（Stats / Trend）

- 数据源：**`usgs_site_param_run`**、**`alert_event`**、**`model_call_log`**（只读聚合）；与 [stats-definition.md](./stats-definition.md) 一致。
- **能力**：按时间窗口聚合（如按日/周）、**污染等级分布**、**告警量/严重度趋势**、检测量与 AI 失败概览等（具体指标在实现时固化到 OpenAPI/文档）。
- **接口形态**：新增如 **`GET /api/stats/trend`**（或拆为多资源：`/api/stats/overview`、`series` 等），请求参数含时间范围、粒度；响应适合前端图表与运营导出。
- **实现注意**：大数据量时考虑**数据库索引**、分页或预聚合策略；时间与语义延续 [time-and-timezone.md](./time-and-timezone.md) 现状，若日后做 UTC 统一再同步调整（见 [TODO.md](./TODO.md)）。
- **验收建议**：给定时间范围返回稳定 JSON，与数据库抽样一致。

#### 4.5 可选加码（与 V4 穿插，不阻塞 4.1–4.4 主验收）

- 第 7 节中的 **Feign 重试**、**Resilience4j 熔断/降级**、**幂等去重**（按监测点 + 时间窗口）等。
- 与 **Spring Boot Actuator** 健康检查、`/health` 对外策略一并梳理。

#### 与 V3 暂缓项的边界（不列入 V4 必做）

- **`rule_config` / 规则配置化**、**异步通知**（MQ / `@Async`）：仍按 [TODO.md](./TODO.md)「暂不实施」处理，可与 V4 **并行**若资源允许，但不作为 V4 里程碑必选项。
- **时区统一到 UTC**：仍为 **最低优先级**，见 [TODO.md](./TODO.md) 与 [time-and-timezone.md](./time-and-timezone.md)。

### V5

- 多模型路由策略（按区域/场景选择模型）；与当前 **规则优先 + 可选遗留模型** 并存时的版本治理。
- 模型版本治理与灰度发布；**USGS 定时入库、训练数据与 `train_water_model.py --input` 重训** 等见 [v5-plan.md](./v5-plan.md)、[ai-rules-forecast-roadmap.md](./ai-rules-forecast-roadmap.md)。

---

## 12. 当前项目与本设计的对应关系

- 已有：
  - `WaterAIClient`：调用 Python `POST /predict`（规则或遗留模型）
  - `WaterForecastClient` / `ForecastService` / `ForecastController`：`POST /api/forecast` → Python `POST /forecast`
  - `WaterAiMaintenanceClient` / `UsgsIvRefreshService` / `UsgsIvRefreshController`：`POST /api/usgs/iv/refresh` → Python `POST /refresh/usgs-iv`（覆盖写 IV CSV）
  - `MonitorController`：`GET /api/map/stations`
  - `StationController`：`POST /api/stations`、`GET /api/stations`；`MonitorStation` 实体与 `externalId`（USGS）对齐 IV/预测
  - `StatsController`：`GET /api/stats/overview`、`/distribution`、`/trend`
  - `AlertController`：`GET /api/alerts`（筛选）、`POST .../ack`、`POST .../close`
  - `AlertService` 等：告警写入与确认
  - DTO：`ApiResponse`、`AlertAckRequest` 等（与 OpenAPI 一致）
  - 实体/仓储：`AlertEvent`、`ModelCallLog`、`MonitorStation`、`UsgsSiteParamRun`、`AsyncTask` 等及对应 Repository
  - 横切：`TraceIdFilter`、`GlobalExceptionHandler`、`WaterAlertProperties`
  - **V4.1 指标**：Spring Boot Actuator + Prometheus（`/actuator/prometheus`）、`WaterBusinessMetrics`（`water.*` 前缀自定义指标）
  - **V4.2 追踪**：Micrometer OTEL bridge + OTLP → **Grafana Tempo**；**Grafana** 联 Tempo + Compose 内 **Prometheus**（抓取目标见 `observability/prometheus/prometheus.yml`；见 §11 4.2）
- 暂缓优化项（见 [TODO.md](./TODO.md)）：`rule_config`、异步通知等。
- **V4**：见上文 **§11 V4** 工作包（4.1 指标、**4.2 Tempo+Grafana 追踪**、4.4 统计接口已落地；4.3 与 4.5、TODO 边界）。

该文档作为 `monitor_business` 的业务架构基线，可在每次版本迭代后更新。

**待办清单**：见 [TODO.md](./TODO.md)。

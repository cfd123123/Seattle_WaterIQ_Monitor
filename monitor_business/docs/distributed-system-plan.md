# Distributed System Plan (Phased)

This document records the phased plan to evolve the project into a distributed system in a safe, incremental way.

## Goals

- Improve stability under long-running AI and data-refresh jobs.
- Keep read APIs responsive during peak load.
- Add observability and operational readiness before large-scale service splitting.
- Avoid premature microservice complexity.

## Guiding Principles

- Prefer incremental migration over big-bang rewrites.
- Make long-running operations asynchronous first.
- Split services by domain boundaries, not by technology stack alone.
- Ensure idempotency, retryability, and traceability for all background jobs.

## Phase 0 - Baseline and Readiness (1 week)

### Objective

Establish measurable performance and reliability baselines before architecture changes.

### Scope

- Produce current architecture snapshot (frontend, Spring, Python AI, DB).
- Measure baseline metrics (QPS, P95 latency, timeout/error rates).
- Classify endpoints into:
  - synchronous and latency-sensitive
  - asynchronous candidates
  - future split candidates

### Deliverables

- Baseline report with key API metrics.
- Risk register for slow or fragile paths.
- Initial SLO targets.

### Exit Criteria

- Team can identify top latency bottlenecks with evidence.
- SLO targets are agreed and documented.

### Personal Project Baseline Checklist (Lightweight)

Use this lightweight checklist for low-traffic personal projects. It is enough to decide whether async/MQ is justified.

- Record baseline for these 6 APIs:
  - `GET /api/map/stations`
  - `GET /api/stats/trend`
  - `GET /api/stats/overview`
  - `POST /api/forecast/series` (single-station forecast)
  - `POST /api/usgs/iv/refresh` (heavy job)
  - `POST /api/usgs/turbidity-threshold/scan` (heavy job)
- For each API, capture:
  - average latency
  - P95 latency
  - error rate
  - timeout rate (e.g. >10s counted as timeout)
- Set practical thresholds:
  - read APIs: P95 < 500ms (or <1s on local env)
  - light write APIs: P95 < 2s
  - heavy jobs: if sync request often > 5-10s, move to async
- Save one markdown report under `docs/` (date-stamped) for future comparison.

## Phase 1 - Modular Monolith + Async Task Framework (1-2 weeks)

### Objective

Keep deployment simple while eliminating request-thread blocking for heavy tasks.

### Scope

- Introduce task model/table:
  - `id`, `type`, `status`, `progress`, `payload`, `result`, `error`, `retry_count`, timestamps
- Add task APIs:
  - submit task
  - query status/result
  - optional cancel
- Add worker process (same repo, separate runtime).
- Frontend integration for task progress polling.

### Priority Async Jobs

- Batch forecast run.
- IV backfill/refresh.
- Threshold/anomaly full-station scan.

### Deliverables

- Task state machine (`PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `RETRYING`).
- Worker execution loop with retry and timeout policy.
- UI progress/status feedback for users.

### Exit Criteria

- Long jobs no longer block API request threads.
- Users can track and retry failed tasks.

## Phase 2 - Redis for Cache and Coordination (1 week)

### Objective

Improve response speed and prevent duplicate heavy job execution.

### Scope

- **Read cache (this project)**: Redis cache **only** for `GET /api/stats/trend`.  Overview (`/api/stats/overview`), TopN (`/api/stats/station-alert-top`), and other reads stay uncached unless a future phase needs them.
- **Duplicate task submissions**:
  - **Chosen for this repo**: database unique constraint on `(task_type, idempotency_key)` plus optional `Idempotency-Key` header on task POST APIs.
  - **Alternative (not required now)**: Redis-based distributed lock for the same purpose if you later need cross-process coordination without leaning on DB uniqueness.

### Deliverables

- Redis integration for Spring Cache (trend cache name: `statsTrend`).
- **When to invalidate trend cache (plain language)**: cached trend answers the question “what does the chart show **right now**?”. After data-changing jobs succeed (e.g. IV refresh, batch forecast), the app **clears** the `statsTrend` cache so the next `GET /api/stats/trend` recomputes from the DB. Entries also **expire** after a short TTL (see `water.cache.trend-ttl-seconds`). No separate “per-endpoint invalidation matrix” is required beyond this.

### Exit Criteria

- Trend read latency improves under repeat queries (cache hit path).
- Duplicate task submissions with the same idempotency key are suppressed reliably.

## Phase 3 - Message Queue Introduction (1-2 weeks)

### Objective

Queue heavy jobs for burst control, decoupled execution, and robust retries.

### Scope

- Producer in API layer, consumer in worker layer.
- Queue-backed execution for heavy async jobs.
- Retry policy and dead-letter queue (DLQ).
- Persist task state transitions and failure reasons.

### Deliverables

- Queue topology and routing design.
- Retry/backoff and DLQ handling.
- Operational runbook for failed jobs（本仓库：`monitor_business/docs/mq-runbook.md`；架构与实现见同目录 `MQ使用.md`）。

### Exit Criteria

- Traffic spikes do not degrade synchronous API responsiveness.
- Failed messages are observable and recoverable.

## Phase 4 - Service Boundary Split (2-4 weeks)

### Objective

Split components along clear domain boundaries after async foundation is stable.

### Target Services

- `monitor-service` (Spring business APIs).
- `ai-inference-service` (Python model inference, stateless).
- `task-worker` (queue consumers/executors).
- `api-gateway` (routing, auth, rate limiting).

### Data Strategy

- Start with shared Postgres (logical separation/schema discipline).
- Move to service-owned data boundaries when cross-service coupling is reduced.

### Exit Criteria

- Services deploy independently.
- Failures are isolated by boundary.

## Phase 5 - Observability and Reliability Hardening (continuous)

### Objective

Make the distributed system diagnosable and operable.

### Scope

- Metrics: Prometheus + dashboards.
- Logging: structured logs with trace IDs.
- Tracing: OpenTelemetry end-to-end.
- Alerts:
  - queue backlog
  - consumer failure/retry spikes
  - API P95/SLA breach
  - DB pool saturation

### Exit Criteria

- Incident triage is fast and evidence-driven.
- Core alerts are actionable and tested.

## Phase 6 - Container Orchestration and Elasticity (optional/later)

### Objective

Enable standardized deployment and scaling under production load.

### Scope

- Dockerize all components.
- Add Kubernetes manifests/Helm.
- Configure autoscaling (especially workers by queue depth).
- Add progressive delivery and rollback strategy.

### Exit Criteria

- Repeatable deployment process.
- Elastic worker scaling for burst workloads.

## What to Do First (Recommended Sequence)

1. Complete Phase 1 (async task framework in current codebase).
2. Add Phase 2 (Redis cache for trend + DB idempotency; Redis lock remains optional).
3. Introduce Phase 3 (MQ) once backlog and concurrency justify it.
4. Split services in Phase 4 only after operational signals are stable.

## Notes

- This roadmap is iterative and should be revisited after each phase review.
- Architecture decisions should be justified by measured bottlenecks and reliability needs.

**阶段 0：基线与准备（1 周）**

**目标**：先量化现状，避免盲改。  
**交付物**：

- 当前架构图（前端/Java/Python/DB）
- 关键接口基线：QPS、P95、错误率、超时率
- 任务清单分级：同步保留 / 异步候选 / 后续拆分

**要做的事**：

- 加统一请求日志（traceId）
- 给关键 API 打耗时点（尤其预测、IV刷新、扫描）
- 明确 SLO（例如：查询 API P95 < 500ms）

**验收标准**：

- 有可复现的压测和指标报表
- 明确“哪些慢、慢在哪里”

---

## **阶段 1：模块化单体 + 异步任务骨架（1~2 周）**

**目标**：不拆服务，先把“重任务”异步化。  
**交付物**：

- `task` 任务表（`id/type/status/progress/payload/result/error/retryCount`）
- 任务 API：提交、查询状态、取消（可选）
- Worker 进程（可同仓、独立启动）
- 前端任务进度展示（轮询）

**优先异步任务**：

- 批量预测
- IV 回溯刷新
- 阈值/异常全站扫描

**为什么先这样做**：

- 收益大、风险低
- 不引入网络分布式复杂度，但已具备“分布式任务思维”

**验收标准**：

- 前端不再因为长任务卡死/超时
- 任务失败可重试、状态可追踪

---

## **阶段 2：引入 Redis（缓存 + 协调）（1 周）**

**目标**：提升查询性能，避免重复任务。  
**范围（与本仓库实现对齐）**：

- **读缓存**：**仅**对 `GET /api/stats/trend` 使用 Redis（缓存名 `statsTrend`）。  
概览、TopN 等接口**本阶段不做** Redis 缓存，除非后续真有瓶颈再加。
- **防重复提交（本仓库采用）**：任务提交接口支持 `**Idempotency-Key` 请求头** + 数据库 `**(task_type, idempotency_key)` 唯一约束**，重复相同 key 时返回已有任务、不重复入队。
- **备选方案（未采用）**：用 **Redis 分布式锁** 达到类似“同类任务同时只跑一份”的效果；需要跨进程强协调、又不想依赖 DB 唯一键时再考虑。

**「缓存失效」是什么意思（白话）**：

- 缓存里存的是**上一时刻**算好的趋势结果。若后台任务**改写了底层数据**（例如 IV 刷新、批量预测成功），继续用旧缓存就会**图表与数据库不一致**。
- **失效** = **删掉或过期这份缓存**，让下一次 `GET /api/stats/trend` **重新查库计算**，用户看到新数据。  
本仓库：**相关异步任务成功后会清空 `statsTrend` 全缓存**；同时趋势缓存还有 **TTL**（`water.cache.trend-ttl-seconds`），时间到了也会自动过期。

**验收标准**：

- 趋势接口在重复查询下响应更稳、更省 DB（命中缓存时）
- 相同 `Idempotency-Key` 的重复提交不会产生第二个并行任务

---

## **阶段 3：引入 MQ（RabbitMQ/Kafka）（1~2 周）**

**目标**：真正队列化、削峰、解耦。  
**交付物**：

- Producer（API 提交任务到队列）
- Consumer（**独立 Worker 进程**消费任务；与 API 同 JAR、`worker` profile，见 `docs/MQ使用.md`）
- 重试策略 + 死信队列（DLQ）
- 任务状态回写 DB
- 失败任务运维手册（Runbook）：`docs/mq-runbook.md`

**建议优先 RabbitMQ**（实现快、运维成本低）  
Kafka 可在吞吐要求更高时再上。

**验收标准**：

- 高峰期 API 不被重任务拖慢
- 任务失败自动重试且可审计

---

## **阶段 4：服务拆分（2~4 周）**

**目标**：按边界拆，不按技术喜好拆。  
**建议拆分**：

- `monitor-service`（Java，业务主服务）
- `ai-inference-service`（Python，无状态推理）
- `task-worker`（消费队列执行任务）
- `api-gateway`（统一入口，鉴权、限流、路由）

> 当前仓库可运行拆分版本：`docs/phase4-service-split.md`（`docker-compose.phase4.yml` + **Spring Cloud Gateway**）。  
> Java 与前端目录分离见仓库根 `monitor_business/README.md`（`backend/` + `frontend/`）。

**数据库策略**：

- 初期可共享同一 Postgres（逻辑分 schema）
- 后续按服务独立库（避免跨库事务）

**验收标准**：

- 服务故障隔离可验证
- 单服务可独立部署升级

---

## **阶段 5：可观测性与稳定性（持续）**

**目标**：让分布式系统“可运维”。  
**交付物**：

- 指标：Prometheus + Grafana
- 日志：结构化日志（JSON）+ 聚合
- 链路追踪：OpenTelemetry + Jaeger/Tempo
- 告警：任务积压、消费失败率、接口 P95、DB 连接池

**验收标准**：

- 故障可在分钟级定位
- 有明确告警而非用户先反馈

---

## **阶段 6：K8s 部署与弹性（可后置）**

**目标**：标准化部署、弹性扩缩容。  
**交付物**：

- Dockerfile + Helm/Kustomize
- HPA（按 CPU/队列长度扩容 worker）
- 灰度发布/回滚策略

## 你项目的 API + Worker 数据流图”

**什么是“独立 worker 进程”**
  现在你的异步任务是：

- API 服务（Spring）收到请求后
- 在**同一个进程里**开线程去跑任务
“独立 worker 进程”是指：
- API 服务只负责“接单 + 写任务状态”
- 另一个**单独运行的进程**专门“干活”（消费任务、执行预测/刷新）

## **两种模式对比**

### **1) 当前模式（同进程线程池）**

- 优点：实现快、简单
- 缺点：
  - API 进程挂了，任务也受影响
  - 重任务会和 API 抢 CPU/内存
  - 不方便单独扩容“干活能力”

### **2) 独立 worker 进程（推荐后续）**

- 优点：
  - API 和任务执行隔离，互不拖垮
  - 可单独扩 worker 数量
  - 更接近真正分布式架构
- 缺点：部署和运维稍复杂一点

1. Frontend -> POST /api/tasks/iv-refresh
2. API: insert async_task(status=PENDING)
3. Worker: 轮询拿到 PENDING -> 改 RUNNING(progress=10)
4. Worker: 调 Python 刷新、可选阈值扫描
5. Worker: 成功写 SUCCEEDED(result_json)；失败写 FAILED(error)
6. Frontend 轮询 GET /api/tasks/{id} 展示进度/结果
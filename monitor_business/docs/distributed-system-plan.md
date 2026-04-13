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

- Cache hot read endpoints (overview/trend/topN as appropriate).
- Add distributed lock for duplicate submissions.
- Add idempotency keys for task submission.

### Deliverables

- Redis integration for cache and lock primitives.
- Cache invalidation strategy documented per endpoint.

### Exit Criteria

- Hot-path API latency improves and stabilizes.
- Duplicate task submissions are suppressed reliably.

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
- Operational runbook for failed jobs.

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
2. Add Phase 2 (Redis for cache + lock + idempotency).
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

## **阶段 2：引入 Redis（缓存 + 分布式锁）（1 周）**

**目标**：提升查询性能，避免重复任务。  
**交付物**：

- Redis 缓存热点查询（趋势/TopN/概览）
- 分布式锁（防重复提交同类重任务）
- 幂等键（同参数短时间内只受理一次）

**验收标准**：

- 热点接口响应稳定下降
- 重复点击“运行批量”不会生成重复执行

---

## **阶段 3：引入 MQ（RabbitMQ/Kafka）（1~2 周）**

**目标**：真正队列化、削峰、解耦。  
**交付物**：

- Producer（API 提交任务到队列）
- Consumer（Worker 消费任务）
- 重试策略 + 死信队列（DLQ）
- 任务状态回写 DB

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


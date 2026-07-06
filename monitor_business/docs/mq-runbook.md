# 批量预测 MQ — 失败任务运维手册（Runbook）

面向 **RabbitMQ + 独立 Worker + `async_task` 任务表** 的个人/小团队场景：当批量预测消息消费失败、进入 DLQ 或任务长时间卡住时，按本文排查与恢复。

架构背景见 [`MQ使用.md`](./MQ使用.md)。大厂常见做法见文末 **附录**。

---

## 1. 服务与端口速查（本地默认）

| 组件 | 说明 | 默认地址 |
|------|------|----------|
| API（Spring Boot） | 接收 HTTP、写任务、**生产** MQ 消息 | `http://localhost:8080` |
| Worker（Spring Boot，`worker` profile） | **消费** MQ、执行批量预测 | 无业务 HTTP；健康检查 `http://localhost:8088/actuator/health` |
| RabbitMQ | Broker + 管理台 | AMQP `localhost:5672`；管理台 `http://localhost:15672`（guest/guest） |
| PostgreSQL | `async_task` 等 | 见 `application.properties` |

---

## 2. 日常健康检查（上线/值班第一步）

1. **API**：`curl -sf http://localhost:8080/actuator/health`（若未暴露则改用你们环境实际路径）。
2. **Worker**：`curl -sf http://localhost:8088/actuator/health`（仅 `worker` profile 进程）。
3. **RabbitMQ**：管理台 **Overview** 无红色告警；节点存活。
4. **业务队列**：Queues → `water.forecast.batch`  
   - **Ready**：堆积过高说明消费跟不上或 Worker 未启动。  
   - **Unacked**：长时间偏大可能消费卡住或下游 AI 极慢。
5. **DLQ**：Queues → `water.forecast.batch.dlq`  
   - **Ready > 0**：存在**最终失败**消息，需对照下文处理。

---

## 3. 故障现象 → 可能原因 → 处理步骤

### 3.1 用户反馈「批量预测一直 PENDING / 不跑」

| 可能原因 | 核查 | 处理 |
|----------|------|------|
| Worker 未启动 | 无8088 健康或进程不存在 | 按第 4 节启动 Worker |
| RabbitMQ 不可达 | API 日志有连接/投递异常；任务可能 `FAILED` 且提示 MQ | 启动 `docker compose up -d rabbitmq`；修复网络/账号 |
| 消息未进队 | DB 任务 `PENDING`，队列 Ready=0 | 查 API 是否 `publish` 报错；必要时对**同一幂等键**重试提交或人工补发（见 5.2） |

### 3.2 任务已 `FAILED`，管理台 DLQ 有消息

说明：业务重试耗尽后，服务将任务标为 `FAILED` 并**抛错**，消息进入 **`water.forecast.batch.dlq`**（见 `MQ使用.md`）。

1. 在管理台打开 DLQ → **Get messages**，记下 **`taskId`**（JSON 内字段）。
2. 数据库查 `async_task`：`status`、`error_message`、`finished_at`。
3. **根因分类**：  
   - **下游 AI `:8000` 不可用/超时**：先恢复 AI，再决定是否重放（5.2）。  
   - **数据/配置错误**：修数据后重放或让用户重新发起（新 `Idempotency-Key`）。  
   - **代码 Bug**：修版本后部署，再重放。

### 3.3 队列 Ready 很高、Worker CPU 低

| 可能原因 | 处理 |
|----------|------|
| `prefetch`/`concurrency` 过小 | 在确认 AI 扛得住的前提下，略增 `spring.rabbitmq.listener.simple.*`（见 `application.properties`） |
| AI 极慢 | 优先扩容/优化 AI；勿盲目加大并发把 `:8000` 打满 |

### 3.4 任务长期 `RUNNING`（少见）

可能：Worker 崩溃、进程被 kill、JVM OOM。当前实现下，**重复投递**若遇 `RUNNING`/`RETRYING` 会跳过，避免双跑；因此极端情况下可能需人工把任务置为 `FAILED` 或 `CANCELLED` 后由用户重试。

**建议 SQL（示例，生产请走审批/备份）**：

```sql
-- 仅当你确认没有 Worker 在跑该 taskId 时
UPDATE async_task SET status = 'FAILED', current_step = 'stale_running_reset',
  error_message = 'Manually reset stale RUNNING', finished_at = NOW(), updated_at = NOW()
WHERE task_id = '<taskId>' AND status = 'RUNNING';
```

然后按5.2 决定是否重放 MQ消息。

---

## 4. 如何启动「API + Worker」两套进程（独立 Worker）

与「大厂」一致：**同一制品（JAR）、不同进程、不同入口或 profile**。

### 4.1 本地开发（Maven）

**终端 A — API**

```bash
cd monitor_business/backend
mvn -q spring-boot:run
```

**终端 B — Worker**

```bash
cd monitor_business/backend
mvn -q spring-boot:run -Dspring-boot.run.profiles=worker
```

或 **IDE**：运行 `WaterBusinessWorkerApplication` 的 `main`（已内置 `worker` profile + 无 Web）。

### 4.2 本地开发（已打包 JAR）

```bash
cd monitor_business/backend
java -jar target/water-business-0.0.1-SNAPSHOT.jar
java -jar target/water-business-0.0.1-SNAPSHOT.jar --spring.profiles.active=worker
```

### 4.3 依赖顺序

先起 **PostgreSQL**、**RabbitMQ**、**Redis**，再起 **API**，最后起 **Worker**（或 API/Worker 同时起，但 Worker 晚几秒无妨）。

### 4.4 用 Docker Compose 在镜像里跑（推荐与本仓库一致）

在 `monitor_business` 目录：

```bash
docker compose up -d --build postgres redis rabbitmq ai-inference-service monitor-service task-worker api-gateway
```

- **`api-gateway`**：**Spring Cloud Gateway**，对外统一 **`localhost:8080`**（`/api/*` 转发至 monitor）。
- **`monitor-service`**：Spring Boot **API 进程**（经网关对外；直连 **`localhost:18080`**）+ 往 RabbitMQ **发消息**。
- **`task-worker`**：**同一 Java 镜像**，`worker` profile，**消费** MQ、跑批量预测；健康 **`localhost:18088/actuator/health`**。
- **`ai-inference-service`**：Python **FastAPI**（`ai_service` 目录构建），映射 `:8000`；`monitor-service` / `task-worker` 通过 **`WATER_AI_BASE_URL=http://ai-inference-service:8000`** 访问。IV CSV 等在卷 **`ai_service_data`** →容器内 `/app/data` 持久化。
- **`rabbitmq`**：Broker（排队、DLQ）。
- **`redis`**：趋势缓存等。

**AI 仅在本地开发、不进 Docker 时**  

在 `ai_service` 目录执行：

```bash
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

此时若 Java 仍在容器内，需把 compose 里 `WATER_AI_BASE_URL` 改回 `http://host.docker.internal:8000` 并加回 `extra_hosts`（见旧文档或自行改 compose）。

详见 `monitor_business/docker-compose.yml` 顶部注释。

---

## 5. DLQ 消息如何「安全重放」

原则：**先搞清楚失败原因**；重放会导致**再次执行批量预测**（打 AI、写库），生产环境需变更窗口。

### 5.1 仅清理 DLQ（不重跑）

适用于：任务已在 DB `FAILED`，只需清空 DLQ 噪音。

- 管理台 DLQ → **Purge**（或逐条 Ack丢弃）。

### 5.2 需要再跑一遍批量预测

1. 确认 AI、DB、配置已恢复。  
2. **优先**：前端/接口 **重新提交** `POST /api/tasks/forecast-batch-run-now`（**新的** `Idempotency-Key`），得到新 `taskId`。  
3. **仅在必须复用原 taskId 时**：在管理台从 DLQ **re-publish** 到交换机 `water.task.exchange`、路由键 `forecast.batch.run`（与 `application.properties` 一致），并确认 DB 中该任务状态已改回可消费（高级操作，易与幂等/状态机冲突，**个人项目慎用**）。

---

## 6. 配置与日志排查清单

- **MQ 连接**：`spring.rabbitmq.*`、`water.mq.forecast.*`  
- **消费限速**：`spring.rabbitmq.listener.simple.prefetch`、`concurrency`、`max-concurrency`  
- **日志关键词**：`ForecastBatchMessageDeadLetterException`、`taskId`、Rabbit `Channel shutdown`  
- **追踪**：同一 `taskId` 串联 API 日志与 Worker 日志（请求可加 trace id，后续可增强）

---

## 7. 附录：大厂团队通常怎么做（API vs Worker）

- **部署形态**：API 与 Worker **分进程**（甚至分 K8s Deployment），**共用同一 Docker 镜像**，通过 **启动命令** 区分，例如：  
  `java -jar app.jar` 与 `java -jar app.jar --spring.profiles.active=worker`。  
- **扩容**：API 按 HTTP QPS；Worker 按 **队列堆积深度** 水平扩容副本数。  
- **资源隔离**：Worker 限制 CPU/内存，避免批量预测拖垮 API 节点（与你们「无 Web 的 worker」一致）。  
- **失败归宿**：业务状态在 DB，消息层用 **DLQ** 保留「最终未投递成功/消费失败」的可审计副本；重要系统还会对 DLQ 做告警与工单。

本仓库已采用：**独立 Worker 进程（`worker` profile）+ DLQ + DB 任务表**，与上述实践对齐，规模缩小到个人项目可维护的程度。

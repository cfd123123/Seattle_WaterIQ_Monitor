# monitor_business（前后端同仓目录）

本目录按 **前端 / 后端分离** 组织，便于 Phase 4 多服务编排与本地开发。

| 路径 | 说明 |
|------|------|
| `backend/` | Spring Boot（`water-business`）：`pom.xml`、`src/`、后端 `Dockerfile` |
| `frontend/` | Vite + React 管理台 |
| `docs/` | 设计与 API 文档 |
| `docs/主要业务.md` | **业务总览**（中文）：项目定位、核心对象与能力 |
| `api-gateway/` | Phase 4 **Spring Cloud Gateway**（独立小工程，入口 `:8080`） |
| `docker-compose.yml` | 统一编排：基础设施、可观测、`ai-inference-service` / `monitor-service` / `task-worker` / `api-gateway`（与 `docs/phase4-service-split.md` 服务名一致） |
| `observability/` | Prometheus / Grafana / Tempo 等 |

**本地跑后端**（在 `backend` 目录）：

```bash
cd backend
mvn -q spring-boot:run
```

**本地跑前端**（在 `frontend` 目录）：

```bash
cd frontend
npm install
npm run dev
```

Docker 构建上下文已指向 `./backend`，无需在仓库根混放 `pom.xml` 与 `src/`。

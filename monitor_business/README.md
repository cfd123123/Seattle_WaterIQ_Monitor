# monitor_business (frontend + backend in one tree)

This directory follows a **separated frontend / backend** layout for Phase 4 multi-service orchestration and local development.

| Path | Description |
|------|-------------|
| `backend/` | Spring Boot (`water-business`): `pom.xml`, `src/`, backend `Dockerfile` |
| `frontend/` | Vite + React admin console |
| `BUSINESS.md` | **Business overview**: product scope, core entities, and capabilities (tracked in repo) |
| `docs/` | Local design and API documentation (gitignored; not pushed to GitHub) |
| `api-gateway/` | Phase 4 **Spring Cloud Gateway** (small standalone project; entry `:8080`) |
| `docker-compose.yml` | Unified stack: infrastructure, observability, `ai-inference-service` / `monitor-service` / `task-worker` / `api-gateway` |
| `observability/` | Prometheus / Grafana / Tempo, etc. |

**Run backend locally** (from `backend`):

```bash
cd backend
mvn -q spring-boot:run
```

**Run frontend locally** (from `frontend`):

```bash
cd frontend
npm install
npm run dev
```

Docker build context points at `./backend`; no need to mix `pom.xml` and `src/` at the repo root.
